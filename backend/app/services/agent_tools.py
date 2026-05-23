"""Agent 工具注册表 — 6 个工具定义 + 处理函数，供 Agent 循环调用"""

import json
import logging
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_
from app.database import nocase
from app.services.rag_service import retrieve_relevant_nodes
from app.models.node import KnowledgeNode
from app.models.tag import Tag
from app.models.relationship import Relationship

logger = logging.getLogger(__name__)


# ============================================================
# 工具 schema（Anthropic API 格式）
# ============================================================

TOOL_DEFINITIONS = [
    {
        "name": "search_knowledge_base",
        "description": "Search the knowledge base using semantic vector search. Returns relevant nodes with titles, content snippets, and node IDs. Use this first when answering questions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "top_k": {"type": "integer", "description": "Number of results (1-10, default 5)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_node_details",
        "description": "Get full details of a specific knowledge node by ID, including content, tags, category, and summary.",
        "input_schema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "integer", "description": "The node ID"},
            },
            "required": ["node_id"],
        },
    },
    {
        "name": "query_graph",
        "description": "Explore the knowledge graph around a node. Returns connected nodes and relationships within N hops.",
        "input_schema": {
            "type": "object",
            "properties": {
                "node_id": {"type": "integer", "description": "Center node ID"},
                "hops": {"type": "integer", "description": "Number of hops to explore (1-3, default 1)"},
            },
            "required": ["node_id"],
        },
    },
    {
        "name": "list_nodes",
        "description": "List and filter knowledge nodes by tag, category, or search text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Search text"},
                "tag": {"type": "string", "description": "Filter by tag name"},
                "category": {"type": "string", "description": "Filter by category"},
                "limit": {"type": "integer", "description": "Max results (default 20)"},
            },
        },
    },
    {
        "name": "analyze_relationships",
        "description": "Analyze relationships between knowledge nodes using AI. Returns discovered relationships with types and strengths.",
        "input_schema": {
            "type": "object",
            "properties": {
                "node_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "List of node IDs to analyze (2-20 nodes)",
                },
            },
            "required": ["node_ids"],
        },
    },
    {
        "name": "web_search",
        "description": "Search the web for information not found in the knowledge base. Use this ONLY when the knowledge base search returns no relevant results or the topic is not covered.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "description": "Max results (1-10, default 5)"},
            },
            "required": ["query"],
        },
    },
]


# ============================================================
# 工具处理函数
# ============================================================

def _handle_search(input_dict: dict, db: Session, **kwargs) -> str:
    """语义向量搜索知识库"""
    query = input_dict.get("query", "")
    top_k = min(input_dict.get("top_k", 5), 10)
    if not query:
        return json.dumps({"error": "query is required"})

    user_id = kwargs.get("user_id", 1)
    results = retrieve_relevant_nodes(query, top_k=top_k, user_id=user_id)
    # 截断内容避免撑爆上下文
    trimmed = []
    for r in results:
        content = r.get("content", "")
        if len(content) > 500:
            content = content[:500] + "..."
        trimmed.append({
            "node_id": r["node_id"],
            "title": r.get("title", ""),
            "content": content,
            "distance": r.get("distance"),
        })
    return json.dumps(trimmed, ensure_ascii=False)


def _handle_node_details(input_dict: dict, db: Session, **kwargs) -> str:
    """获取节点详情"""
    node_id = input_dict.get("node_id")
    if not node_id:
        return json.dumps({"error": "node_id is required"})

    user_id = kwargs.get("user_id", 1)
    node = db.query(KnowledgeNode).filter(KnowledgeNode.id == node_id, KnowledgeNode.user_id == user_id).first()
    if not node:
        return json.dumps({"error": f"Node {node_id} not found"})

    # 查关系
    rels = db.query(Relationship).filter(
        (Relationship.source_id == node_id) | (Relationship.target_id == node_id)
    ).all()
    relationships = []
    for r in rels:
        other_id = r.target_id if r.source_id == node_id else r.source_id
        other = db.query(KnowledgeNode).filter(KnowledgeNode.id == other_id).first()
        relationships.append({
            "rel_id": r.id,
            "direction": "outgoing" if r.source_id == node_id else "incoming",
            "other_node_id": other_id,
            "other_title": other.title if other else "?",
            "rel_type": r.rel_type,
            "label": r.label,
        })

    return json.dumps({
        "id": node.id,
        "title": node.title,
        "content": node.content,
        "summary": node.summary,
        "category": node.category,
        "tags": [t.name for t in node.tags],
        "importance": node.importance,
        "ai_analyzed": node.ai_analyzed,
        "relationships": relationships,
    }, ensure_ascii=False)


def _handle_query_graph(input_dict: dict, db: Session, **kwargs) -> str:
    """BFS 探索子图"""
    node_id = input_dict.get("node_id")
    hops = min(input_dict.get("hops", 1), 3)
    user_id = kwargs.get("user_id", 1)
    if not node_id:
        return json.dumps({"error": "node_id is required"})

    node_ids = {node_id}
    all_rels = []
    for _ in range(hops):
        rels = db.query(Relationship).filter(
            Relationship.user_id == user_id,
            (Relationship.source_id.in_(node_ids)) | (Relationship.target_id.in_(node_ids))
        ).all()
        for r in rels:
            node_ids.add(r.source_id)
            node_ids.add(r.target_id)
            all_rels.append(r)

    nodes = db.query(KnowledgeNode).filter(
        KnowledgeNode.id.in_(node_ids), KnowledgeNode.user_id == user_id).all()
    return json.dumps({
        "nodes": [{"id": n.id, "title": n.title, "category": n.category} for n in nodes],
        "links": [
            {"source": r.source_id, "target": r.target_id, "rel_type": r.rel_type, "label": r.label}
            for r in all_rels
        ],
    }, ensure_ascii=False)


def _handle_list_nodes(input_dict: dict, db: Session, **kwargs) -> str:
    """筛选节点列表"""
    user_id = kwargs.get("user_id", 1)
    q = db.query(KnowledgeNode).options(joinedload(KnowledgeNode.tags))
    q = q.filter(KnowledgeNode.user_id == user_id)

    tag = input_dict.get("tag")
    category = input_dict.get("category")
    search = input_dict.get("search")
    limit = min(input_dict.get("limit", 20), 20)

    if tag:
        q = q.join(KnowledgeNode.tags).filter(Tag.name == tag, Tag.user_id == user_id)
    if category:
        q = q.filter(KnowledgeNode.category == category)
    if search:
        tag_subq = db.query(KnowledgeNode.id).join(KnowledgeNode.tags).filter(
            nocase(Tag.name).contains(search)
        ).subquery()
        q = q.filter(
            or_(
                nocase(KnowledgeNode.title).contains(search),
                nocase(KnowledgeNode.content).contains(search),
                nocase(KnowledgeNode.summary).contains(search),
                KnowledgeNode.id.in_(tag_subq),
            )
        )

    nodes = q.order_by(KnowledgeNode.updated_at.desc()).limit(limit).all()
    return json.dumps([
        {"id": n.id, "title": n.title, "category": n.category,
         "tags": [t.name for t in n.tags], "importance": n.importance}
        for n in nodes
    ], ensure_ascii=False)


def _handle_analyze_relationships(input_dict: dict, db: Session, **kwargs) -> str:
    """AI 分析节点间关系"""
    node_ids = input_dict.get("node_ids", [])
    if len(node_ids) < 2:
        return json.dumps({"error": "Need at least 2 node IDs"})

    user_id = kwargs.get("user_id", 1)
    nodes = db.query(KnowledgeNode).filter(KnowledgeNode.id.in_(node_ids), KnowledgeNode.user_id == user_id).all()
    if len(nodes) < 2:
        return json.dumps({"error": "Not enough valid nodes found"})

    from app.services.relationship_finder import find_relationships_batch
    suggestions = find_relationships_batch(nodes)
    return json.dumps(suggestions[:20], ensure_ascii=False)


def _handle_web_search(input_dict: dict, db: Session, **kwargs) -> str:
    """DuckDuckGo 联网搜索"""
    query = input_dict.get("query", "")
    max_results = min(input_dict.get("max_results", 5), 10)
    if not query:
        return json.dumps({"error": "query is required"})

    try:
        from ddgs import DDGS
        results = DDGS().text(query, max_results=max_results)
        formatted = []
        for r in results:
            formatted.append({
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            })
        return json.dumps(formatted, ensure_ascii=False)
    except Exception as e:
        logger.warning("Web search failed: %s", e)
        return json.dumps({"error": f"Search failed: {str(e)}"})


# ============================================================
# 统一执行入口
# ============================================================

TOOL_HANDLERS = {
    "search_knowledge_base": _handle_search,
    "get_node_details": _handle_node_details,
    "query_graph": _handle_query_graph,
    "list_nodes": _handle_list_nodes,
    "analyze_relationships": _handle_analyze_relationships,
    "web_search": _handle_web_search,
}


def execute_tool(name: str, input_dict: dict, db: Session, user_id: int = 1) -> str:
    """执行工具，返回 JSON 字符串结果"""
    handler = TOOL_HANDLERS.get(name)
    if not handler:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        return handler(input_dict, db, user_id=user_id)
    except Exception as e:
        return json.dumps({"error": str(e)})
