import sys
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from app.config import settings
from app.database import engine, Base
from app.routers import nodes, tags, relationships, import_files, graph, ai, chat

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="Knowledge Base", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in [nodes.router, tags.router, relationships.router, import_files.router, graph.router, ai.router, chat.router]:
    app.include_router(router, prefix="/api")

# Resolve frontend dist directory
if getattr(sys, "frozen", False):
    exe_dir = Path(sys.executable).parent
    # Check env var first, then exe_dir, then _MEIPASS
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