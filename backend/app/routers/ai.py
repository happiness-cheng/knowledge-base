from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.node import KnowledgeNode
from app.models.tag import Tag
from app.models.relationship import Relationship
from app.services.claude_client import claude_client, AIClient
from app.services.knowledge_extractor import extract_knowledge
from app.services.relationship_finder import find_relationships_batch
from app.config import settings
import json
import os

router = APIRouter(prefix="/ai", tags=["ai"])


@router.get("/settings")
def get_settings():
    from app.services.claude_client import claude_client
    return {
        "ai_base_url": settings.ai_base_url,
        "ai_model_name": settings.ai_model_name,
        "has_api_key": claude_client.client is not None,
        "model": claude_client.model,
        "source": getattr(claude_client, "source", "unknown"),
    }


@router.post("/settings")
def save_settings(data: dict):
    api_key = data.get("ai_api_key", "").strip()
    base_url = data.get("ai_base_url", "").strip()
    model_name = data.get("ai_model_name", "").strip()

    if not base_url:
        base_url = settings.ai_base_url
    if not model_name:
        model_name = settings.ai_model_name

    # Update in-memory settings
    if api_key:
        settings.ai_api_key = api_key
    settings.ai_base_url = base_url
    settings.ai_model_name = model_name

    # Re-init the AI client with current key + new URL
    final_key = settings.ai_api_key
    import app.services.claude_client as cc
    if final_key and final_key != "your_api_key_here":
        cc.claude_client = AIClient()

    # Save to .env file
    env_path = os.path.join(os.path.dirname(__file__), "..", "..", ".env")
    env_path = os.path.abspath(env_path)

    keys_to_set = {"AI_BASE_URL": base_url, "AI_MODEL_NAME": model_name}
    if api_key:
        keys_to_set["AI_API_KEY"] = api_key

    lines = []
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0]
            if key in keys_to_set:
                new_lines.append(f"{key}={keys_to_set.pop(key)}\n")
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)
    for k, v in keys_to_set.items():
        new_lines.append(f"{k}={v}\n")
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    return {"ok": True, "has_api_key": bool(api_key)}


@router.post("/analyze-node/{node_id}")
def analyze_node(node_id: int, db: Session = Depends(get_db)):
    node = db.query(KnowledgeNode).filter(KnowledgeNode.id == node_id).first()
    if not node:
        raise HTTPException(404, "Node not found")

    result = extract_knowledge(node.title, node.content)

    node.summary = result.get("summary")
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
    db.refresh(node)
    return {
        "id": node.id,
        "title": node.title,
        "summary": node.summary,
        "category": node.category,
        "importance": node.importance,
        "tags": [t.name for t in node.tags],
    }


@router.post("/find-relationships")
def ai_find_relationships(node_ids: list[int] | None = None, db: Session = Depends(get_db)):
    if node_ids:
        nodes = db.query(KnowledgeNode).filter(KnowledgeNode.id.in_(node_ids)).all()
    else:
        nodes = db.query(KnowledgeNode).filter(KnowledgeNode.ai_analyzed == True).all()

    if len(nodes) < 2:
        return {"suggestions": []}

    suggestions = find_relationships_batch(nodes)

    created = []
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
                db.flush()
                created.append({
                    "id": rel.id,
                    "source_title": s["source_title"],
                    "target_title": s["target_title"],
                    "rel_type": rel.rel_type,
                    "strength": rel.strength,
                    "label": rel.label,
                })
    db.commit()
    return {"created": created, "count": len(created)}


@router.post("/analyze-all")
def analyze_all(db: Session = Depends(get_db)):
    nodes = db.query(KnowledgeNode).filter(KnowledgeNode.ai_analyzed == False).all()
    analyzed = 0
    for node in nodes:
        try:
            result = extract_knowledge(node.title, node.content)
            node.summary = result.get("summary")
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
            analyzed += 1
        except Exception:
            continue
    db.commit()
    return {"analyzed": analyzed, "total": len(nodes)}


@router.post("/extract-subtopics/{node_id}")
def extract_subtopics(node_id: int, db: Session = Depends(get_db)):
    node = db.query(KnowledgeNode).filter(KnowledgeNode.id == node_id).first()
    if not node:
        raise HTTPException(404, "Node not found")

    # Extract sub-topics from ALL markdown headings in the content
    # Allow optional leading whitespace (content may be indented)
    import re
    headings = re.findall(r'^[ \t]*##[ \t]+(.+)$', node.content, re.MULTILINE)
    if not headings:
        # Fallback: match numbered headings like "1. Collector" or "8. 跨模块知识网络"
        headings = re.findall(r'^\s*\d+[\.\、]\s*(.+)$', node.content, re.MULTILINE)
    if not headings:
        headings = re.findall(r'^\s*[-*]\s+\*\*(.+?)\*\*', node.content, re.MULTILINE)
    sub_topics = []
    for h in headings:
        # Strip numbering prefix like "3. ", "8. ", "12. "
        h = re.sub(r'^\d+[\.\、]\s*', '', h)
        h = h.strip().rstrip('：:').strip()
        if h and h not in sub_topics and len(h) < 80:
            sub_topics.append(h)

    # Find relations between sub-topics using keyword overlap
    relations = []
    if len(sub_topics) >= 2:
        import jieba
        # Extract keywords from each sub-topic
        def extract_keywords(text):
            # Remove numbering prefix like "8. " or "3. "
            text = re.sub(r'^\d+[\.\、]\s*', '', text)
            words = set(jieba.cut_for_search(text))
            # Filter short/stop words
            return set(w for w in words if len(w) > 1 and w not in {
                '什么', '怎么', '为什么', '哪些', '如何', '分别', '区别', '常见',
                '哪些', '有什么', '是什么', '一下', '哪些', '通常', '情况'
            })

        kw_list = [extract_keywords(t) for t in sub_topics]
        for i in range(len(sub_topics)):
            for j in range(i + 1, len(sub_topics)):
                # Check keyword overlap
                overlap = kw_list[i] & kw_list[j]
                if len(overlap) >= 1:
                    relations.append([i, j])

    return {"node_id": node_id, "sub_topics": sub_topics, "relations": relations}