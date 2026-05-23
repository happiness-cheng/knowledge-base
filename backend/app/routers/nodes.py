from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, case, func
import logging
import hashlib
from app.database import get_db, nocase
from app.models.node import KnowledgeNode
from app.models.tag import Tag
from app.models.relationship import Relationship
from app.models.user import User
from app.auth import get_current_user
from app.schemas.node import NodeCreate, NodeUpdate, NodeDetail, NodeSummary
from app.services.rag_service import add_node_to_index, remove_node_from_index

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/nodes", tags=["nodes"])


def _safe_add_to_index(node_id: int, content: str, title: str, user_id: int):
    try:
        add_node_to_index(node_id, content, title, user_id)
    except Exception:
        logger.warning("Failed to add node %s to index", node_id, exc_info=True)


def _safe_remove_from_index(node_id: int, user_id: int):
    try:
        remove_node_from_index(node_id, user_id)
    except Exception:
        logger.warning("Failed to remove node %s from index", node_id, exc_info=True)


@router.get("", response_model=list[NodeSummary])
def list_nodes(
    tag: str = Query(None),
    category: str = Query(None),
    search: str = Query(None),
    limit: int = Query(200, le=500),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    q = db.query(KnowledgeNode).options(joinedload(KnowledgeNode.tags))
    q = q.filter(KnowledgeNode.user_id == current_user.id)
    if tag:
        q = q.join(KnowledgeNode.tags).filter(Tag.name == tag, Tag.user_id == current_user.id)
    if category:
        q = q.filter(KnowledgeNode.category == category)
    if search:
        tag_subq = db.query(KnowledgeNode.id).join(KnowledgeNode.tags).filter(
            nocase(Tag.name).contains(search), Tag.user_id == current_user.id
        ).subquery()
        title_match = nocase(KnowledgeNode.title).contains(search)
        content_match = nocase(KnowledgeNode.content).contains(search)
        summary_match = nocase(KnowledgeNode.summary).contains(search)
        tag_match = KnowledgeNode.id.in_(tag_subq)
        q = q.filter(or_(title_match, content_match, summary_match, tag_match))

        search_lower = search.lower()
        content_count = func.length(KnowledgeNode.content) - func.length(
            func.replace(func.lower(KnowledgeNode.content), search_lower, '')
        )
        relevance = case((title_match, 100), else_=0) + case((tag_match, 50), else_=0) + case((summary_match, 30), else_=0) + content_count
        nodes = q.order_by(relevance.desc()).offset(offset).limit(limit).all()
    else:
        nodes = q.order_by(KnowledgeNode.updated_at.desc()).offset(offset).limit(limit).all()
    return [NodeSummary(id=n.id, title=n.title, category=n.category, tags=[t.name for t in n.tags], importance=n.importance) for n in nodes]


@router.get("/{node_id}", response_model=NodeDetail)
def get_node(node_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    node = db.query(KnowledgeNode).filter(KnowledgeNode.id == node_id, KnowledgeNode.user_id == current_user.id).first()
    if not node:
        raise HTTPException(404, "Node not found")
    return NodeDetail(id=node.id, title=node.title, content=node.content, summary=node.summary,
        category=node.category, tags=[t.name for t in node.tags], importance=node.importance,
        source_id=node.source_id, created_at=node.created_at, updated_at=node.updated_at, ai_analyzed=node.ai_analyzed)


@router.post("", response_model=NodeDetail)
def create_node(body: NodeCreate, background: BackgroundTasks,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    content_hash = hashlib.sha256(body.content.encode()).hexdigest()
    node = KnowledgeNode(user_id=current_user.id, title=body.title, content=body.content,
        category=body.category, content_hash=content_hash)
    for tag_name in body.tags:
        tag = db.query(Tag).filter(Tag.name == tag_name, Tag.user_id == current_user.id).first()
        if not tag:
            tag = Tag(name=tag_name, user_id=current_user.id)
            db.add(tag)
        node.tags.append(tag)
    db.add(node)
    db.commit()
    db.refresh(node)
    background.add_task(_safe_add_to_index, node.id, node.content, node.title, current_user.id)
    return NodeDetail(id=node.id, title=node.title, content=node.content, summary=node.summary,
        category=node.category, tags=[t.name for t in node.tags], importance=node.importance,
        source_id=node.source_id, created_at=node.created_at, updated_at=node.updated_at, ai_analyzed=node.ai_analyzed)


@router.put("/{node_id}", response_model=NodeDetail)
def update_node(node_id: int, body: NodeUpdate, background: BackgroundTasks,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    node = db.query(KnowledgeNode).filter(KnowledgeNode.id == node_id, KnowledgeNode.user_id == current_user.id).first()
    if not node:
        raise HTTPException(404, "Node not found")
    if body.title is not None:
        node.title = body.title
    if body.content is not None:
        node.content = body.content
        node.content_hash = hashlib.sha256(body.content.encode()).hexdigest()
        node.ai_analyzed = False
    if body.category is not None:
        node.category = body.category
    if body.tags is not None:
        node.tags.clear()
        for tag_name in body.tags:
            tag = db.query(Tag).filter(Tag.name == tag_name, Tag.user_id == current_user.id).first()
            if not tag:
                tag = Tag(name=tag_name, user_id=current_user.id)
                db.add(tag)
            node.tags.append(tag)
    db.commit()
    db.refresh(node)
    background.add_task(_safe_add_to_index, node.id, node.content, node.title, current_user.id)
    return NodeDetail(id=node.id, title=node.title, content=node.content, summary=node.summary,
        category=node.category, tags=[t.name for t in node.tags], importance=node.importance,
        source_id=node.source_id, created_at=node.created_at, updated_at=node.updated_at, ai_analyzed=node.ai_analyzed)


@router.delete("/{node_id}")
def delete_node(node_id: int, background: BackgroundTasks,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    node = db.query(KnowledgeNode).filter(KnowledgeNode.id == node_id, KnowledgeNode.user_id == current_user.id).first()
    if not node:
        raise HTTPException(404, "Node not found")
    db.query(Relationship).filter(
        Relationship.user_id == current_user.id,
        (Relationship.source_id == node_id) | (Relationship.target_id == node_id)
    ).delete(synchronize_session=False)
    node.tags.clear()
    db.delete(node)
    db.commit()
    background.add_task(_safe_remove_from_index, node_id, current_user.id)
    return {"ok": True}


@router.get("/{node_id}/subtopics")
def get_node_subtopics(node_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    node = db.query(KnowledgeNode).filter(KnowledgeNode.id == node_id, KnowledgeNode.user_id == current_user.id).first()
    if not node:
        raise HTTPException(404, "Node not found")
    import re
    headings = re.findall(r'^[ \t]*##[ \t]+(.+)$', node.content, re.MULTILINE)
    if not headings:
        headings = re.findall(r'^[ \t]*\d+[\.\、]\s*(.+)$', node.content, re.MULTILINE)
    if not headings:
        headings = re.findall(r'^[ \t]*[-*]\s+\*\*(.+?)\*\*', node.content, re.MULTILINE)
    topics = []
    for h in headings:
        h = re.sub(r'^\d+[\.\、]\s*', '', h)
        h = h.strip().rstrip('：:').strip()
        if h and h not in topics and len(h) < 80:
            topics.append(h)
    return {"node_id": node_id, "subtopics": topics}


@router.get("/{node_id}/suggested-links")
def get_suggested_links(node_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    node = db.query(KnowledgeNode).filter(KnowledgeNode.id == node_id, KnowledgeNode.user_id == current_user.id).first()
    if not node:
        raise HTTPException(404, "Node not found")
    from app.services.auto_linker import detect_links_for_node
    existing_rels = db.query(Relationship).filter(
        Relationship.user_id == current_user.id,
        (Relationship.source_id == node_id) | (Relationship.target_id == node_id)
    ).all()
    existing_ids = {r.source_id for r in existing_rels} | {r.target_id for r in existing_rels}
    existing_ids.discard(node_id)
    all_other = db.query(KnowledgeNode).filter(
        KnowledgeNode.user_id == current_user.id, KnowledgeNode.id != node_id
    ).all()
    candidates = [{"id": n.id, "title": n.title, "content": n.summary or n.content[:500]}
        for n in all_other if n.id not in existing_ids]
    suggestions = detect_links_for_node(node_id, node.title, node.content, candidates)
    return {"node_id": node_id, "suggestions": suggestions}
