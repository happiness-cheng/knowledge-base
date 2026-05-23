import sys
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.config import settings
from app.database import engine, Base

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


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
               import_files.router, graph.router, ai.router, chat_router.router]:
    app.include_router(router, prefix="/api")


@app.get("/api/health")
@limiter.limit("30/minute")
def health(request: Request):
    return {"status": "ok", "version": "1.0.0"}


# Resolve frontend dist directory
if getattr(sys, "frozen", False):
    exe_dir = Path(sys.executable).parent
    import os
    custom_dist = os.environ.get("KB_FRONTEND_DIST")
    if custom_dist and Path(custom_dist).exists():
        DIST_DIR = Path(custom_dist)
    elif (exe_dir / "frontend" / "dist").exists():
        DIST_DIR = exe_dir / "frontend" / "dist"
    else:
        DIST_DIR = Path(sys._MEIPASS) / "frontend" / "dist"
else:
    DIST_DIR = Path(__file__).parent.parent.parent / "frontend" / "dist"


@app.get("/{full_path:path}")
async def serve_frontend(request: Request, full_path: str):
    if not DIST_DIR.exists():
        return {"error": "Frontend not built. Run: cd frontend && npx vite build"}
    file_path = DIST_DIR / full_path
    if file_path.is_file():
        return FileResponse(file_path)
    return FileResponse(DIST_DIR / "index.html")
