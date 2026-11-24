"""RAGFlow 检索适配：把 chunk 映射回 SQL 节点，并在进入模型前再次校验。"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from app.models.node import KnowledgeNode
from app.models.ragflow import RagflowDataset, RagflowDocument
from app.services.index_jobs import fingerprint
from app.services.ragflow_client import RagflowClient


def retrieve_for_user(
    db: Session,
    *,
    user_id: int,
    query: str,
    top_k: int = 3,
    client: RagflowClient,
    trace: Callable[[dict], None] | None = None,
    keywords_similarity_weight: float = 0.7,
    similarity_threshold: float = 0.2,
) -> list[dict]:
    if type(user_id) is not int or user_id <= 0:
        raise ValueError("user_id must be a positive integer")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be nonempty")
    if type(top_k) is not int or top_k <= 0:
        raise ValueError("top_k must be a positive integer")
    if not 0.0 <= keywords_similarity_weight <= 1.0:
        raise ValueError("keywords_similarity_weight must be in [0, 1]")
    if not 0.0 <= similarity_threshold <= 1.0:
        raise ValueError("similarity_threshold must be in [0, 1]")

    dataset = db.get(RagflowDataset, user_id)
    if dataset is None:
        if trace is not None:
            trace({"backend": "ragflow", "dataset": None, "candidate_chunks": 0,
                   "unmapped_chunks": 0, "stale_chunks": 0, "selected": []})
        return []

    page_size = min(max(top_k * 4, 10), 100)
    chunks = client.retrieve(
        query, [dataset.dataset_id], page_size=page_size,
        similarity_threshold=similarity_threshold,
        keywords_similarity_weight=keywords_similarity_weight,
    )
    document_ids = {
        str(chunk.get("document_id")) for chunk in chunks
        if isinstance(chunk.get("document_id"), str) and chunk.get("document_id")
    }
    rows = (
        db.query(RagflowDocument)
        .filter(RagflowDocument.user_id == user_id,
                RagflowDocument.document_id.in_(document_ids))
        .all()
    ) if document_ids else []
    by_document = {row.document_id: row for row in rows}
    node_ids = {row.node_id for row in rows}
    nodes = (
        db.query(KnowledgeNode)
        .populate_existing()
        .filter(KnowledgeNode.user_id == user_id, KnowledgeNode.id.in_(node_ids))
        .all()
    ) if node_ids else []
    current = {node.id: node for node in nodes}

    selected: list[dict] = []
    counts: dict[int, int] = {}
    unmapped = stale = 0
    seen: set[tuple[int, str]] = set()
    for chunk in chunks:
        document_id = chunk.get("document_id")
        mapping = by_document.get(document_id) if isinstance(document_id, str) else None
        if mapping is None:
            unmapped += 1
            continue
        node = current.get(mapping.node_id)
        content = chunk.get("content")
        if (node is None or not isinstance(content, str) or not content.strip()
                or not node.content.strip()):
            stale += 1
            continue
        # RAGFlow 的 document_id 不代表内容版本；必须用 fingerprint 再核验。
        if mapping.source_fingerprint != fingerprint(node.title, node.content):
            stale += 1
            continue
        if counts.get(node.id, 0) >= 2:
            continue
        identity = (node.id, content)
        if identity in seen:
            continue
        seen.add(identity)
        similarity = chunk.get("similarity")
        score = float(similarity) if isinstance(similarity, (int, float)) else None
        distance = None if score is None else max(0.0, 1.0 - min(max(score, 0.0), 1.0))
        selected.append({
            "node_id": node.id,
            "title": node.title,
            "content": content,
            "chunk_id": str(chunk.get("id") or ""),
            "heading": "",
            "distance": distance,
            "score": score,
            "source_fingerprint": mapping.source_fingerprint,
            "evidence_verified": True,
        })
        counts[node.id] = counts.get(node.id, 0) + 1
        if len(selected) >= top_k * 2:
            break

    if trace is not None:
        trace({
            "backend": "ragflow",
            "dataset": dataset.dataset_id,
            "candidate_chunks": len(chunks),
            "unmapped_chunks": unmapped,
            "stale_chunks": stale,
            "selected": [
                {"node_id": item["node_id"], "chunk_id": item["chunk_id"],
                 "score": item["score"]}
                for item in selected
            ],
        })
    return selected