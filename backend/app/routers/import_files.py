from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile, File, HTTPException
from sqlalchemy.orm import Session
import logging
from app.database import get_db
from app.models.node import KnowledgeNode
from app.models.source import Source
from app.services.file_importer import import_file
from app.utils.markdown_cleaner import clean_markdown, split_by_headings
from app.services.rag_service import add_node_to_index
import hashlib

router = APIRouter(prefix="/import", tags=["import"])
logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
MAX_BATCH_FILES = 20


def _safe_add_to_index(node_id: int, content: str, title: str):
    try:
        add_node_to_index(node_id, content, title)
    except Exception:
        logger.warning("Failed to add node %s to index", node_id, exc_info=True)


@router.post("/file")
async def import_single_file(file: UploadFile = File(...), background: BackgroundTasks = None, db: Session = Depends(get_db)):
    ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename else ""
    if ext not in ("md", "txt", "docx"):
        raise HTTPException(400, "Unsupported file type. Use .md, .txt, or .docx")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(413, f"File too large. Maximum size is {MAX_FILE_SIZE // (1024*1024)}MB")

    sections = import_file(content, ext)
    source = Source(filename=file.filename, file_type=ext, node_count=len(sections))
    db.add(source)
    db.flush()
    node_ids = []
    for title, text in sections:
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        node = KnowledgeNode(title=title, content=text, source_id=source.id, content_hash=content_hash)
        db.add(node)
        db.flush()
        node_ids.append(node.id)
        if background:
            background.add_task(_safe_add_to_index, node.id, text, title)
    db.commit()
    return {"source_id": source.id, "node_count": len(node_ids), "node_ids": node_ids}


@router.post("/batch")
async def import_batch_files(files: list[UploadFile] = File(...), background: BackgroundTasks = None, db: Session = Depends(get_db)):
    if len(files) > MAX_BATCH_FILES:
        raise HTTPException(400, f"Too many files. Maximum is {MAX_BATCH_FILES}")
    results = []
    for file in files:
        ext = file.filename.rsplit(".", 1)[-1].lower() if file.filename else ""
        if ext not in ("md", "txt", "docx"):
            continue
        content = await file.read()
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(413, f"File '{file.filename}' too large. Maximum is {MAX_FILE_SIZE // (1024*1024)}MB")
        sections = import_file(content, ext)
        source = Source(filename=file.filename, file_type=ext, node_count=len(sections))
        db.add(source)
        db.flush()
        node_ids = []
        for title, text in sections:
            content_hash = hashlib.sha256(text.encode()).hexdigest()
            node = KnowledgeNode(title=title, content=text, source_id=source.id, content_hash=content_hash)
            db.add(node)
            db.flush()
            node_ids.append(node.id)
            if background:
                background.add_task(_safe_add_to_index, node.id, text, title)
        results.append({"filename": file.filename, "source_id": source.id, "node_count": len(node_ids)})
    db.commit()
    return {"imported": results}


@router.post("/text")
async def import_text(body: dict, background: BackgroundTasks = None, db: Session = Depends(get_db)):
    content = body.get("content", "")
    title = body.get("title", "Pasted Note")
    # 输入长度限制，防止过大请求耗尽内存
    if len(title) > 500:
        raise HTTPException(400, "Title too long (max 500 characters)")
    if len(content) > 1_000_000:  # 1MB
        raise HTTPException(413, "Content too large (max 1MB)")
    if not content.strip():
        raise HTTPException(400, "Content cannot be empty")
    if title != "Pasted Note":
        sections = [(title, content)]
    else:
        sections = split_by_headings(content)
    source = Source(filename=title, file_type="text", node_count=len(sections))
    db.add(source)
    db.flush()
    node_ids = []
    for section_title, text in sections:
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        node = KnowledgeNode(title=section_title, content=text, source_id=source.id, content_hash=content_hash)
        db.add(node)
        db.flush()
        node_ids.append(node.id)
        if background:
            background.add_task(_safe_add_to_index, node.id, text, section_title)
    db.commit()
    return {"source_id": source.id, "node_count": len(node_ids), "node_ids": node_ids}