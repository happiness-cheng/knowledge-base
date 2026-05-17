from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
import logging
from app.database import get_db
from app.models.node import KnowledgeNode

logger = logging.getLogger(__name__)
from app.models.tag import Tag
from app.models.relationship import Relationship
from app.schemas.node import NodeCreate, NodeUpdate, NodeDetail, NodeSummary
from app.services.rag_service import add_node_to_index, remove_node_from_index
import hashlib

router = APIRouter(prefix="/nodes", tags=["nodes"])


def _safe_add_to_index(node_id: int, content: str, title: str):
    try:
        add_node_to_index(node_id, content, title)
    except Exception:
        logger.warning("Failed to add node %s to index", node_id, exc_info=True)


def _safe_remove_from_index(node_id: int):
    try:
        remove_node_from_index(node_id)
    except Exception:
        logger.warning("Failed to remove node %s from index", node_id, exc_info=True)


def _node_to_detail(node):
    """Convert ORM node to API response schema."""
    return NodeDetail(
        id=node.id, title=node.title, content=node.content, summary=node.summary,
        category=node.category, tags=[t.name for t in node.tags],
        importance=node.importance, source_id=node.source_id,
        created_at=node.created_at, updated_at=node.updated_at,
        ai_analyzed=node.ai_analyzed,
    )


def _safe_auto_analyze(node_id: int):
    """Background task: analyze new node and find relationships with existing nodes."""
    from app.database import SessionLocal
    from app.models.node import KnowledgeNode
    from app.models.tag import Tag
    from app.models.relationship import Relationship

    db = SessionLocal()
    try:
        node = db.query(KnowledgeNode).filter(KnowledgeNode.id == node_id).first()
        if not node:
            return

        # 1. Analyze the node
        from app.services.knowledge_extractor import extract_knowledge
        result = extract_knowledge(node.title, node.content)

        node.summary = result.get("summary")
        if not node.category:
            node.category = result.get("category")
        node.importance = result.get("importance", 0.5)
        node.ai_analyzed = True

        for tag_name in result.get("tags", []):
            existing = db.query(Tag).filter(Tag.name == tag_name).first()
            if not existing:
                existing = Tag(name=tag_name, is_ai_generated=True)
                db.add(existing)
            if existing not in node.tags:
                node.tags.append(existing)

        db.commit()

        # 2. Find relationships with existing analyzed nodes
        other_nodes = db.query(KnowledgeNode).filter(
            KnowledgeNode.ai_analyzed == True,
            KnowledgeNode.id != node_id,
        ).all()

        if len(other_nodes) >= 1:
            from app.services.relationship_finder import find_relationships_batch
            all_nodes = [node] + other_nodes
            suggestions = find_relationships_batch(all_nodes)

            for s in suggestions:
                src = db.query(KnowledgeNode).filter(KnowledgeNode.title == s["source_title"]).first()
                tgt = db.query(KnowledgeNode).filter(KnowledgeNode.title == s["target_title"]).first()
                if src and tgt:
                    existing = db.query(Relationship).filter(
                        Relationship.source_id == src.id,
                        Relationship.target_id == tgt.id,
                    ).first()
                    if not existing:
                        rel = Relationship(
                            source_id=src.id,
                            target_id=tgt.id,
                            rel_type=s.get("rel_type", "related_to"),
                            strength=s.get("strength", 0.5),
                            label=s.get("label"),
                            is_ai_generated=True,
                        )
                        db.add(rel)
            db.commit()

    except Exception:
        logger.warning("Auto-analyze failed for node %s", node_id, exc_info=True)
    finally:
        db.close()


@router.get("", response_model=list[NodeSummary])
def list_nodes(
    tag: str = Query(None),
    category: str = Query(None),
    search: str = Query(None),
    limit: int = Query(200, le=500),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    q = db.query(KnowledgeNode).options(joinedload(KnowledgeNode.tags))
    if tag:
        q = q.join(KnowledgeNode.tags).filter(Tag.name == tag)
    if category:
        q = q.filter(KnowledgeNode.category == category)
    if search:
        # Search across title, content, summary, and tags (case-insensitive via NOCASE collation)
        tag_subq = db.query(KnowledgeNode.id).join(KnowledgeNode.tags).filter(
            Tag.name.collate("NOCASE").contains(search)
        ).subquery()
        q = q.filter(
            or_(
                KnowledgeNode.title.collate("NOCASE").contains(search),
                KnowledgeNode.content.collate("NOCASE").contains(search),
                KnowledgeNode.summary.collate("NOCASE").contains(search),
                KnowledgeNode.id.in_(tag_subq),
            )
        )
    nodes = q.order_by(KnowledgeNode.updated_at.desc()).offset(offset).limit(limit).all()
    result = []
    for n in nodes:
        result.append(NodeSummary(
            id=n.id,
            title=n.title,
            category=n.category,
            tags=[t.name for t in n.tags],
            importance=n.importance,
        ))
    return result


@router.get("/{node_id}", response_model=NodeDetail)
def get_node(node_id: int, db: Session = Depends(get_db)):
    node = db.query(KnowledgeNode).filter(KnowledgeNode.id == node_id).first()
    if not node:
        raise HTTPException(404, "Node not found")
    return NodeDetail(
        id=node.id,
        title=node.title,
        content=node.content,
        summary=node.summary,
        category=node.category,
        tags=[t.name for t in node.tags],
        importance=node.importance,
        source_id=node.source_id,
        created_at=node.created_at,
        updated_at=node.updated_at,
        ai_analyzed=node.ai_analyzed,
    )


@router.post("", response_model=NodeDetail)
def create_node(body: NodeCreate, background: BackgroundTasks, db: Session = Depends(get_db)):
    content_hash = hashlib.sha256(body.content.encode()).hexdigest()
    node = KnowledgeNode(
        title=body.title,
        content=body.content,
        category=body.category,
        content_hash=content_hash,
    )
    for tag_name in body.tags:
        tag = db.query(Tag).filter(Tag.name == tag_name).first()
        if not tag:
            tag = Tag(name=tag_name)
            db.add(tag)
        node.tags.append(tag)
    db.add(node)
    db.commit()
    db.refresh(node)
    background.add_task(_safe_add_to_index, node.id, node.content, node.title)
    background.add_task(_safe_auto_analyze, node.id)
    return NodeDetail(
        id=node.id,
        title=node.title,
        content=node.content,
        summary=node.summary,
        category=node.category,
        tags=[t.name for t in node.tags],
        importance=node.importance,
        source_id=node.source_id,
        created_at=node.created_at,
        updated_at=node.updated_at,
        ai_analyzed=node.ai_analyzed,
    )


@router.put("/{node_id}", response_model=NodeDetail)
def update_node(node_id: int, body: NodeUpdate, background: BackgroundTasks, db: Session = Depends(get_db)):
    node = db.query(KnowledgeNode).filter(KnowledgeNode.id == node_id).first()
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
            tag = db.query(Tag).filter(Tag.name == tag_name).first()
            if not tag:
                tag = Tag(name=tag_name)
                db.add(tag)
            node.tags.append(tag)
    db.commit()
    db.refresh(node)
    background.add_task(_safe_add_to_index, node.id, node.content, node.title)
    return NodeDetail(
        id=node.id,
        title=node.title,
        content=node.content,
        summary=node.summary,
        category=node.category,
        tags=[t.name for t in node.tags],
        importance=node.importance,
        source_id=node.source_id,
        created_at=node.created_at,
        updated_at=node.updated_at,
        ai_analyzed=node.ai_analyzed,
    )


@router.delete("/{node_id}")
def delete_node(node_id: int, background: BackgroundTasks, db: Session = Depends(get_db)):
    node = db.query(KnowledgeNode).filter(KnowledgeNode.id == node_id).first()
    if not node:
        raise HTTPException(404, "Node not found")
    # Clean up relationships and tags, then delete node — single transaction
    db.query(Relationship).filter(
        (Relationship.source_id == node_id) | (Relationship.target_id == node_id)
    ).delete(synchronize_session=False)
    node.tags.clear()
    db.delete(node)
    db.commit()
    background.add_task(_safe_remove_from_index, node_id)
    return {"ok": True}


@router.get("/{node_id}/subtopics")
def get_node_subtopics(node_id: int, db: Session = Depends(get_db)):
    node = db.query(KnowledgeNode).filter(KnowledgeNode.id == node_id).first()
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
def get_suggested_links(node_id: int, db: Session = Depends(get_db)):
    """Get keyword-based suggested links for a node (zero LLM cost)."""
    node = db.query(KnowledgeNode).filter(KnowledgeNode.id == node_id).first()
    if not node:
        raise HTTPException(404, "Node not found")

    from app.services.auto_linker import detect_links_for_node
    from app.models.relationship import Relationship

    # Get existing relationships to filter out already-linked nodes
    existing_rels = db.query(Relationship).filter(
        (Relationship.source_id == node_id) | (Relationship.target_id == node_id)
    ).all()
    existing_ids = set()
    for r in existing_rels:
        existing_ids.add(r.source_id)
        existing_ids.add(r.target_id)
    existing_ids.discard(node_id)

    # Get all other nodes as candidates
    all_other = db.query(KnowledgeNode).filter(KnowledgeNode.id != node_id).all()
    candidates = [
        {"id": n.id, "title": n.title, "content": n.summary or n.content[:500]}
        for n in all_other if n.id not in existing_ids
    ]

    suggestions = detect_links_for_node(node_id, node.title, node.content, candidates)
    return {"node_id": node_id, "suggestions": suggestions}
