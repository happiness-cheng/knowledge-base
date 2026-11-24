"""索引集合的身份元数据：模型、维度、切分策略与 schema 版本。

这些值只描述“索引是用什么写的”，不证明 ANN 文件或向量值健康；对账报告
必须把 metadata 匹配与向量健康分开表述。
"""

INDEX_SCHEMA_VERSION = 1
EMBEDDING_MODEL = 'BAAI/bge-large-zh-v1.5'
EMBEDDING_DIMENSION = 1024
CHUNK_STRATEGY = 'heading+prepare_chunks(512)'

METADATA_KEYS = (
    'kb_schema_version',
    'embedding_model',
    'embedding_dimension',
    'chunk_strategy',
)


def collection_metadata() -> dict[str, str | int]:
    return {
        'kb_schema_version': INDEX_SCHEMA_VERSION,
        'embedding_model': EMBEDDING_MODEL,
        'embedding_dimension': EMBEDDING_DIMENSION,
        'chunk_strategy': CHUNK_STRATEGY,
    }


def metadata_status(metadata: dict | None) -> dict:
    """只读比较；旧集合缺字段时报告 missing，不自动改写。"""
    expected = collection_metadata()
    actual = metadata if isinstance(metadata, dict) else {}
    missing = [key for key in METADATA_KEYS if key not in actual]
    mismatch = [
        key for key in METADATA_KEYS
        if key in actual and actual[key] != expected[key]
    ]
    if not actual:
        status = 'missing'
    elif missing:
        status = 'missing'
    elif mismatch:
        status = 'mismatch'
    else:
        status = 'match'
    return {
        'status': status,
        'missing': missing,
        'mismatch': mismatch,
        'expected': expected,
        'observed': {key: actual.get(key) for key in METADATA_KEYS},
    }