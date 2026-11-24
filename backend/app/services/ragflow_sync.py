"""RAGFlow 派生索引同步：上传、解析状态、删除与数据集绑定。

SQL 仍保存笔记真值；RAGFlow 只是可重建的检索层。每次写入都带
`source_fingerprint`，检索/对账时可以拒绝旧文档，而不是相信“同一 document_id
就一定是新内容”。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.node import KnowledgeNode
from app.models.ragflow import RagflowDataset, RagflowDocument
from app.services.index_jobs import fingerprint
from app.services.ragflow_client import RagflowAPIError, RagflowClient, RagflowError

STATE_PENDING = "pending"
STATE_UPLOADED = "uploaded"
STATE_PARSING = "parsing"
STATE_READY = "ready"
STATE_FAILED = "failed"
STATE_MISSING = "missing"

_READY_STATES = {STATE_PARSING, STATE_READY}
_DONE_RUN = {"DONE"}
_FAILED_RUN = {"FAIL"}
_ACTIVE_RUN = {"UNSTART", "RUNNING", "SCHEDULE"}


@dataclass(frozen=True)
class SyncResult:
    node_id: int
    document_id: str
    state: str
    changed: bool


def dataset_name(user_id: int, prefix: str = "kb_user") -> str:
    if type(user_id) is not int or user_id <= 0:
        raise ValueError("user_id must be a positive integer")
    prefix = (prefix or "kb_user").strip()
    if not prefix or len(prefix) > 48:
        raise ValueError("invalid RAGFlow dataset prefix")
    return f"{prefix}_{user_id}"


def _dataset_row(db: Session, user_id: int, client: RagflowClient,
                 prefix: str, embedding_model: str = "") -> RagflowDataset:
    row = db.get(RagflowDataset, user_id)
    if row is not None:
        return row
    name = dataset_name(user_id, prefix)
    dataset = client.ensure_dataset(name, embedding_model=embedding_model)
    dataset_id = dataset.get("id")
    if not isinstance(dataset_id, str) or not dataset_id:
        raise RagflowError("RAGFlow dataset has no id")
    row = RagflowDataset(
        user_id=user_id,
        dataset_id=dataset_id,
        name=str(dataset.get("name") or name),
        embedding_model=str(dataset.get("embedding_model") or embedding_model or "") or None,
    )
    db.add(row)
    db.flush()
    return row


def sync_node(db: Session, node: KnowledgeNode, client: RagflowClient, *,
              prefix: str = "kb_user", embedding_model: str = "") -> SyncResult:
    """把一条笔记同步为一个 RAGFlow 文档并触发解析。

    已同步且 fingerprint 未变时直接返回；内容变化时删除旧文档再上传，避免
    RAGFlow 侧保留旧 chunk。RAGFlow 没有“替换文件内容”的 API，删除+重传是
    明确且可重放的路径。
    """
    if node.user_id is None or node.id is None:
        raise ValueError("node must be persisted")
    current = fingerprint(node.title, node.content)
    existing = db.get(RagflowDocument, (node.user_id, node.id))
    if (existing is not None and existing.source_fingerprint == current
            and existing.state in _READY_STATES):
        return SyncResult(node.id, existing.document_id, existing.state, False)

    dataset = _dataset_row(db, node.user_id, client, prefix, embedding_model)
    if existing is not None and existing.document_id:
        try:
            client.delete_documents(dataset.dataset_id, [existing.document_id])
        except RagflowAPIError as exc:
            # 旧文档可能已在 RAGFlow 侧被删除；404/102 可继续，权限/网络错误
            # 必须上抛，不能静默当成“已删除”。
            if exc.code not in (102, 404):
                raise

    filename = f"node-{node.id}.md"
    body = f"# {node.title}\n\n{node.content}".encode("utf-8")
    document = client.upload_document(dataset.dataset_id, filename, body)
    document_id = document.get("id")
    if not isinstance(document_id, str) or not document_id:
        raise RagflowError("RAGFlow upload returned no document id")

    row = existing or RagflowDocument(
        user_id=node.user_id, node_id=node.id, document_id=document_id,
        source_fingerprint=current, state=STATE_UPLOADED,
    )
    row.document_id = document_id
    row.source_fingerprint = current
    row.state = STATE_UPLOADED
    row.last_error = None
    if existing is None:
        db.add(row)
    db.flush()

    try:
        client.update_document_metadata(dataset.dataset_id, document_id, {
            "node_id": str(node.id),
            "source_fingerprint": current,
            "title": node.title[:500],
        })
        client.parse_documents(dataset.dataset_id, [document_id])
    except Exception as exc:
        row.state = STATE_FAILED
        row.last_error = type(exc).__name__
        db.flush()
        raise
    row.state = STATE_PARSING
    db.flush()
    return SyncResult(node.id, document_id, row.state, True)


def delete_node(db: Session, user_id: int, node_id: int,
                client: RagflowClient) -> bool:
    row = db.get(RagflowDocument, (user_id, node_id))
    if row is None:
        return False
    dataset = db.get(RagflowDataset, user_id)
    if dataset is not None and row.document_id:
        try:
            client.delete_documents(dataset.dataset_id, [row.document_id])
        except RagflowAPIError as exc:
            if exc.code not in (102, 404):
                raise
    db.delete(row)
    db.flush()
    return True


def refresh_states(db: Session, user_id: int, client: RagflowClient) -> dict[str, int]:
    """按 RAGFlow 的 run 状态更新本地映射；不改 SQL 笔记正文。"""
    dataset = db.get(RagflowDataset, user_id)
    if dataset is None:
        return {"updated": 0, "missing": 0}
    docs = client.list_documents(dataset.dataset_id, page_size=100)
    by_id = {str(item.get("id")): item for item in docs if item.get("id")}
    rows = db.query(RagflowDocument).filter(RagflowDocument.user_id == user_id).all()
    updated = missing = 0
    for row in rows:
        item = by_id.get(row.document_id)
        if item is None:
            if row.state != STATE_MISSING:
                row.state = STATE_MISSING
                row.last_error = "document_missing"
                updated += 1
            missing += 1
            continue
        run = str(item.get("run") or "").upper()
        new_state = row.state
        if run in _DONE_RUN:
            new_state = STATE_READY
        elif run in _FAILED_RUN:
            new_state = STATE_FAILED
        elif run in _ACTIVE_RUN:
            new_state = STATE_PARSING
        if new_state != row.state:
            row.state = new_state
            row.last_error = None if new_state != STATE_FAILED else "parse_failed"
            updated += 1
    db.flush()
    return {"updated": updated, "missing": missing}