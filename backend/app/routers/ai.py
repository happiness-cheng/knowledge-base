from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.node import KnowledgeNode
from app.models.tag import Tag
from app.models.relationship import Relationship
from app.models.user import User
from app.auth import get_current_user
from app.services.claude_client import get_client_for_user
from app.services.knowledge_extractor import extract_knowledge
from app.services.relationship_finder import find_relationships_batch
from app.config import settings

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/settings")
def get_settings(current_user: User = Depends(get_current_user)):
    has_key = bool(current_user.ai_api_key)
    return {
        "ai_base_url": current_user.ai_base_url or settings.ai_base_url,
        "ai_model_name": current_user.ai_model_name or settings.ai_model_name,
        "has_api_key": has_key,
        "model": current_user.ai_model_name or settings.ai_model_name,
        "source": "user" if has_key else "deployer",
    }


@router.post("/settings")
def save_settings(data: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    api_key = data.get("ai_api_key", "").strip()
    base_url = data.get("ai_base_url", "").strip()
    model_name = data.get("ai_model_name", "").strip()
    if api_key:
        current_user.ai_api_key = api_key
    if base_url:
        current_user.ai_base_url = base_url
    if model_name:
        current_user.ai_model_name = model_name
    db.commit()
    return {"ok": True, "has_api_key": bool(current_user.ai_api_key)}


@router.post("/analyze-node/{node_id}")
def analyze_node(node_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    node = db.query(KnowledgeNode).filter(KnowledgeNode.id == node_id, KnowledgeNode.user_id == current_user.id).first()
    if not node:
        raise HTTPException(404, "Node not found")
    result = extract_knowledge(node.title, node.content)
    node.summary = result.get("summary")
    node.category = result.get("category")
    node.importance = result.get("importance", 0.5)
    node.ai_analyzed = True
    for tag_name in result.get("tags", []):
        existing = db.query(Tag).filter(Tag.name == tag_name, Tag.user_id == current_user.id).first()
        if not existing:
            existing = Tag(name=tag_name, is_ai_generated=True, user_id=current_user.id)
            db.add(existing)
        if existing not in node.tags:
            node.tags.append(existing)
    db.commit()
    db.refresh(node)
    return {"id": node.id, "title": node.title, "summary": node.summary,
        "category": node.category, "importance": node.importance, "tags": [t.name for t in node.tags]}


@router.post("/find-relationships")
def ai_find_relationships(node_ids: list[int] | None = None,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if node_ids:
        nodes = db.query(KnowledgeNode).filter(
            KnowledgeNode.id.in_(node_ids), KnowledgeNode.user_id == current_user.id).all()
    else:
        nodes = db.query(KnowledgeNode).filter(
            KnowledgeNode.ai_analyzed == True, KnowledgeNode.user_id == current_user.id).all()
    if len(nodes) < 2:
        return {"suggestions": []}
    suggestions = find_relationships_batch(nodes)
    created = []
    for s in suggestions:
        src = db.query(KnowledgeNode).filter(KnowledgeNode.title == s["source_title"], KnowledgeNode.user_id == current_user.id).first()
        tgt = db.query(KnowledgeNode).filter(KnowledgeNode.title == s["target_title"], KnowledgeNode.user_id == current_user.id).first()
        if src and tgt:
            existing = db.query(Relationship).filter(
                Relationship.source_id == src.id, Relationship.target_id == tgt.id).first()
            if not existing:
                rel = Relationship(source_id=src.id, target_id=tgt.id, user_id=current_user.id,
                    rel_type=s.get("rel_type", "related_to"), strength=s.get("strength", 0.5),
                    label=s.get("label"), is_ai_generated=True)
                db.add(rel)
                db.flush()
                created.append({"id": rel.id, "source_title": s["source_title"],
                    "target_title": s["target_title"], "rel_type": rel.rel_type,
                    "strength": rel.strength, "label": rel.label})
    db.commit()
    return {"created": created, "count": len(created)}


@router.post("/analyze-all")
def analyze_all(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    nodes = db.query(KnowledgeNode).filter(
        KnowledgeNode.ai_analyzed == False, KnowledgeNode.user_id == current_user.id).all()
    analyzed = 0
    for node in nodes:
        try:
            result = extract_knowledge(node.title, node.content)
            node.summary = result.get("summary")
            node.category = result.get("category")
            node.importance = result.get("importance", 0.5)
            node.ai_analyzed = True
            for tag_name in result.get("tags", []):
                existing = db.query(Tag).filter(Tag.name == tag_name, Tag.user_id == current_user.id).first()
                if not existing:
                    existing = Tag(name=tag_name, is_ai_generated=True, user_id=current_user.id)
                    db.add(existing)
                if existing not in node.tags:
                    node.tags.append(existing)
            analyzed += 1
        except Exception:
            continue
    db.commit()
    return {"analyzed": analyzed, "total": len(nodes)}


@router.post("/extract-subtopics/{node_id}")
def extract_subtopics(node_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    node = db.query(KnowledgeNode).filter(KnowledgeNode.id == node_id, KnowledgeNode.user_id == current_user.id).first()
    if not node:
        raise HTTPException(404, "Node not found")
    import re
    headings = re.findall(r'^[ \t]*##[ \t]+(.+)$', node.content, re.MULTILINE)
    if not headings:
        headings = re.findall(r'^\s*\d+[\.\、]\s*(.+)$', node.content, re.MULTILINE)
    if not headings:
        headings = re.findall(r'^\s*[-*]\s+\*\*(.+?)\*\*', node.content, re.MULTILINE)
    sub_topics = []
    for h in headings:
        h = re.sub(r'^\d+[\.\、]\s*', '', h)
        h = h.strip().rstrip('：:').strip()
        if h and h not in sub_topics and len(h) < 80:
            sub_topics.append(h)
    relations = []
    if len(sub_topics) >= 2:
        try:
            import jieba
        except ImportError:
            return {"node_id": node_id, "sub_topics": sub_topics, "relations": []}
        def extract_keywords(text):
            text = re.sub(r'^\d+[\.\、]\s*', '', text)
            words = set(jieba.cut_for_search(text))
            return set(w for w in words if len(w) > 1 and w not in {
                '什么', '怎么', '为什么', '哪些', '如何', '分别', '区别', '常见',
                '有什么', '是什么', '一下', '通常', '情况'})
        kw_list = [extract_keywords(t) for t in sub_topics]
        for i in range(len(sub_topics)):
            for j in range(i + 1, len(sub_topics)):
                overlap = kw_list[i] & kw_list[j]
                if len(overlap) >= 1:
                    relations.append([i, j])
    return {"node_id": node_id, "sub_topics": sub_topics, "relations": relations}
