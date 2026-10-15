import sys
import os
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from app import env_sanitize  # noqa: F401  必须最先导入：净化 NO_PROXY，否则 httpx 建 client 即崩
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.config import settings
from app.database import get_db
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from app.models.index_job import IndexJob

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

# 限流器
limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])

# 导入所有模型
from app.models import user, node, tag, relationship, source, chat  # noqa: E402, F401
from app.routers import nodes, tags, relationships, import_files, graph, ai, chat as chat_router, auth  # noqa: E402
from app.routers import index_jobs  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 仅验证运行时配置；schema DDL 由部署入口的 `alembic upgrade head` 负责
    settings.validate_runtime()
    try:
        yield
    finally:
        from app.services.tool_executor import close_tool_executor
        close_tool_executor()


app = FastAPI(title="Knowledge Base", lifespan=lifespan)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": f"请求过于频繁，请稍后再试"})

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Cache-Control"],
    allow_credentials=True,
)

# 注册路由
for router in [auth.router, nodes.router, tags.router, relationships.router,
               import_files.router, graph.router, ai.router, chat_router.router, index_jobs.router]:
    app.include_router(router, prefix="/api")


@app.get("/api/health")
@limiter.limit("30/minute")
def health(request: Request):
    return {"status": "ok", "version": "1.0.0"}


@app.get("/api/ready")
def ready(db: Session = Depends(get_db)):
    from app.services.rag_service import chroma_client
    checks = {"sql": "ok", "index": "ok"}
    try:
        db.execute(text("SELECT 1"))
        db.execute(select(IndexJob).limit(1))
        db.execute(select(node.KnowledgeNode).limit(1))
        db.execute(select(user.User).limit(1))
    except Exception:
        db.rollback()
        checks["sql"] = "unavailable"
    try:
        chroma_client.heartbeat()
    except Exception:
        checks["index"] = "unavailable"
    available = all(value == "ok" for value in checks.values())
    return JSONResponse(status_code=200 if available else 503,
                        content={"status": "ready" if available else "not_ready", "checks": checks})


def resolve_frontend_dist():
    custom_dist = os.environ.get("KB_FRONTEND_DIST")
    if custom_dist:
        return Path(custom_dist)
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        if (exe_dir / "frontend" / "dist").exists():
            return exe_dir / "frontend" / "dist"
        return Path(sys._MEIPASS) / "frontend" / "dist"
    return Path(__file__).parent.parent.parent / "frontend" / "dist"


DIST_DIR = resolve_frontend_dist()


@app.get("/{full_path:path}")
async def serve_frontend(request: Request, full_path: str):
    if full_path == "api" or full_path.startswith("api/"):
        raise HTTPException(404, "API route not found")
    if not DIST_DIR.exists():
        return {"error": "Frontend not built. Run: cd frontend && npx vite build"}
    root = DIST_DIR.resolve()
    file_path = (root / full_path.replace("\\", "/")).resolve()
    if not file_path.is_relative_to(root):
        raise HTTPException(404, "File not found")
    if file_path.is_file():
        return FileResponse(file_path)
    index = (root / "index.html").resolve()
    if not index.is_relative_to(root) or not index.is_file():
        raise HTTPException(404, "Frontend entry not found")
    return FileResponse(index)
