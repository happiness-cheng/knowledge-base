"""SQL 是正文真值；旧索引兼容只接受仍存在的正文片段。"""
import re

from app.services.index_jobs import fingerprint


def current_evidence(row, node) -> bool:
    content = row.get("content")
    if not isinstance(content, str) or not content.strip() or not node.content:
        return False
    expected = row.get("source_fingerprint")
    if expected is not None and expected != fingerprint(node.title, node.content):
        return False
    fragments = row.get("content_fragments", [content])
    if (not isinstance(fragments, list) or not 1 <= len(fragments) <= 10
        or any(not isinstance(item, str) or not item.strip() for item in fragments)
        or content != "\n\n".join(fragments)):
        return False
    # 老索引没有版本指纹，正文仍须逐片核验。标题由 SQL 提供，不信任索引展示值。
    current = re.sub(r"\s+", "", node.content)
    return all(re.sub(r"\s+", "", fragment) in current for fragment in fragments)


def row_is_current(row, node) -> bool:
    """RAGFlow 等适配器可用 fingerprint 预核验，避免标题前缀被字面检查误拒。

    只有行显式带 `evidence_verified=True` 且 fingerprint 与当前 SQL 正文一致时
    才走预核验；其他来源仍走 `current_evidence` 的逐片内容检查。
    """
    if row.get("evidence_verified") is True:
        return row.get("source_fingerprint") == fingerprint(node.title, node.content)
    return current_evidence(row, node)
