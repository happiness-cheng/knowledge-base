"""公开文档导读的独立索引输入；不导入应用、数据库或模型。"""
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlparse


def load_documents(rows: list[dict]) -> list[dict]:
    if not rows:
        raise ValueError('empty corpus')
    documents, ids = [], set()
    for row in rows:
        node_id = row.get('node_id')
        if type(node_id) is not int or node_id <= 0 or node_id in ids:
            raise ValueError('invalid or duplicate node id')
        for field in ('title', 'content', 'source_url', 'source_section',
                      'source_version', 'checked_at', 'content_kind'):
            if not isinstance(row.get(field), str) or not row[field].strip():
                raise ValueError(f'missing {field}')
        url = urlparse(row['source_url'])
        # 来源只接受经过维护者选择的五个官方站点，避免误收本地路径或内网站点。
        if url.scheme != 'https' or url.hostname not in {
            'aws.amazon.com', 'docs.nvidia.com', 'docs.python.org',
            'docs.pytorch.org', 'kubernetes.io',
        } or url.username or url.password:
            raise ValueError('source must be an approved official HTTPS URL')
        if row['content_kind'] != 'editorial_summary':
            raise ValueError('this adapter only accepts explicitly labelled editorial summaries')
        ids.add(node_id)
        documents.append(dict(row, content_sha256=sha256(row['content'].encode()).hexdigest()))
    return documents


def prepare_chunks(documents, splitter, count_tokens, max_input_tokens: int) -> list[dict]:
    chunks = []
    for doc in documents:
        sections = splitter(doc['content'])
        if not sections:
            raise ValueError('document produced no chunks')
        for index, (heading, body) in enumerate(sections):
            if not body.strip():
                raise ValueError('empty chunk')
            text = f"{doc['title']}\n{heading}\n{body}"
            tokens = count_tokens(text)
            if tokens > max_input_tokens:
                raise ValueError(f"embedding input exceeds budget: {doc['node_id']}:{index}")
            metadata = {key: doc[key] for key in (
                'node_id', 'title', 'source_url', 'source_section', 'source_version',
                'checked_at', 'content_kind', 'content_sha256')}
            metadata.update(heading=heading, chunk_index=index)
            chunks.append({'id': f"{doc['node_id']}:{index}", 'document': body,
                           'embedding_text': text, 'input_tokens': tokens, 'metadata': metadata})
    return chunks


def reserve_output(root: Path, name: str) -> Path:
    # 拒绝覆盖已有目录；失败或重跑必须使用新的运行名，保留原始证据。
    root = root.resolve(strict=True)
    target = (root / name).resolve()
    if not name or target.parent != root:
        raise ValueError('output must be a new direct child directory')
    target.mkdir(exist_ok=False)
    return target
