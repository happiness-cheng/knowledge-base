"""RAGFlow 派生索引对账：SQL 真值 vs 本地 document 映射。

只读取 SQL 与 `ragflow_documents`，不调用 RAGFlow；因此可在 RAGFlow 离线时
发现缺失/旧版本/孤儿映射。修复只登记现有 `index_jobs`，不直接写远端。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.node import KnowledgeNode
from app.models.ragflow import RagflowDataset, RagflowDocument
from app.services.index_jobs import enqueue, fingerprint


def reconcile_user_ragflow(db: Session, user_id: int) -> dict:
    nodes = {
        node.id: node for node in db.query(KnowledgeNode)
        .populate_existing()
        .filter(KnowledgeNode.user_id == user_id)
        .all()
    }
    rows = db.query(RagflowDocument).filter(
        RagflowDocument.user_id == user_id,
    ).all()
    by_node = {row.node_id: row for row in rows}
    dataset = db.get(RagflowDataset, user_id)

    missing = sorted(
        node_id for node_id in nodes
        if node_id not in by_node and nodes[node_id].content.strip()
    )
    orphan = sorted(row.node_id for row in rows if row.node_id not in nodes)
    stale = sorted(
        row.node_id for row in rows
        if row.node_id in nodes
        and row.source_fingerprint != fingerprint(
            nodes[row.node_id].title, nodes[row.node_id].content,
        )
    )
    empty_content = sorted(
        node_id for node_id, node in nodes.items() if not node.content.strip()
    )
    failed = sorted(
        row.node_id for row in rows if row.state in {"failed", "missing"}
    )
    parsing = sorted(
        row.node_id for row in rows if row.state in {"pending", "uploaded", "parsing"}
    )

    errors = []
    if missing:
        errors.append(f"missing_documents:{len(missing)}")
    if orphan:
        errors.append(f"orphan_documents:{len(orphan)}")
    if stale:
        errors.append(f"stale_documents:{len(stale)}")
    if failed:
        errors.append(f"failed_documents:{len(failed)}")
    if dataset is None and nodes:
        errors.append("dataset_missing")

    if missing or orphan or stale or failed:
        health = "unhealthy"
    elif dataset is None or empty_content or parsing:
        health = "needs_verification"
    else:
        health = "healthy"

    upsert = sorted(set(missing) | set(stale) | set(failed))
    return {
        "backend": "ragflow",
        "user_id": user_id,
        "dataset_id": dataset.dataset_id if dataset else None,
        "canonical_nodes": len(nodes),
        "mapped_documents": len(rows),
        "missing_node_ids": missing,
        "orphan_node_ids": orphan,
        "stale_node_ids": stale,
        "empty_content_node_ids": empty_content,
        "failed_node_ids": failed,
        "parsing_node_ids": parsing,
        "errors": errors,
        "health": health,
        "repair_actions": {
            "upsert_node_ids": upsert,
            "delete_node_ids": orphan,
            "manual_node_ids": empty_content,
        },
    }


def apply_user_ragflow_repair(db: Session, report: dict) -> dict:
    if report.get("backend") != "ragflow":
        raise ValueError("report is not a RAGFlow reconciliation report")
    user_id = report["user_id"]
    enqueued = {"upsert": 0, "delete": 0}
    for node_id in report["repair_actions"]["upsert_node_ids"]:
        node = db.query(KnowledgeNode).filter_by(
            id=node_id, user_id=user_id,
        ).first()
        if node is None:
            continue
        enqueue(db, user_id, node.id, "upsert", fingerprint(node.title, node.content))
        enqueued["upsert"] += 1
    for node_id in report["repair_actions"]["delete_node_ids"]:
        enqueue(db, user_id, node_id, "delete", fingerprint("", ""))
        enqueued["delete"] += 1
    return enqueued