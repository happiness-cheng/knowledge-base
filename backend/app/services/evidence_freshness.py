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
