"""离线切片与生产排序核心的兼容出口。

排序/融合/预算/精排的实现在 `app.services.retrieval_core`，生产与离线实验共用；
本模块只保留离线切片实验需要的 `ChunkConfig` 与 `chunk_documents`，并 re-export
核心类型，避免既有 eval 脚本和测试被迫改 import。
"""

import importlib.util
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from pathlib import Path

from app.services.retrieval_core import (
    BM25Retriever,
    CandidateChunk,
    RankedChunk,
    dense_rank,
    pack_context,
    reciprocal_rank_fusion,
    rerank_candidates,
)

__all__ = [
    'BM25Retriever', 'CandidateChunk', 'ChunkConfig', 'RankedChunk',
    'chunk_documents', 'dense_rank', 'pack_context',
    'reciprocal_rank_fusion', 'rerank_candidates',
]


@dataclass(frozen=True)
class ChunkConfig:
    strategy: str = 'heading'
    body_tokens: int = 384
    overlap_tokens: int = 0
    model_limit: int = 512

    def __post_init__(self):
        if self.strategy not in ('fixed', 'heading') or self.body_tokens < 1 or self.model_limit < 1:
            raise ValueError('invalid chunk configuration')
        if not 0 <= self.overlap_tokens < self.body_tokens:
            raise ValueError('overlap must be smaller than body token budget')


@lru_cache(maxsize=1)
def _heading_splitter():
    # 复用既有缩进标题规则，单独加载纯 utils，避免导入 app 的配置与模型。
    path = Path(__file__).resolve().parents[1] / 'app/utils/markdown_cleaner.py'
    spec = importlib.util.spec_from_file_location('core_rag_heading_rules', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # 既有二次切片带字符回退；这里仅取其标题划分，随后统一用传入 tokenizer 切片。
    def entire_section(content):
        return [content]
    module._split_long_section = entire_section
    return module.split_by_headings


def chunk_documents(documents: list[dict], tokenizer, config: ChunkConfig) -> list[CandidateChunk]:
    chunks = []
    for document in documents:
        sections = (_heading_splitter()(document['content']) if config.strategy == 'heading'
                    else [('', document['content'])])
        for section_index, (heading, body) in enumerate(sections):
            if not body.strip():
                continue
            prefix = '\n'.join(value for value in (document['title'], heading) if value)
            prefix_tokens = len(tokenizer(prefix + '\n', add_special_tokens=True)['input_ids'])
            available = min(config.body_tokens, config.model_limit - prefix_tokens)
            if available <= config.overlap_tokens:
                raise ValueError('title/heading prefix leaves insufficient token budget')
            encoded = tokenizer(body, add_special_tokens=False, return_offsets_mapping=True)
            offsets = encoded['offset_mapping']
            start = 0
            while start < len(offsets):
                end = min(start + available, len(offsets))
                while end > start:
                    content = body[offsets[start][0]:offsets[end - 1][1]]
                    complete = '\n'.join(value for value in (document['title'], heading, content) if value)
                    count = len(tokenizer(complete, add_special_tokens=True)['input_ids'])
                    if count <= config.model_limit:
                        break
                    end -= 1
                if end <= start or (end < len(offsets) and end - start <= config.overlap_tokens):
                    raise ValueError('prefix/overlap prevents bounded chunk progress')
                identity = f"{document['node_id']}:{document['user_id']}:{section_index}:{start}:{config}:{complete}"
                chunks.append(CandidateChunk(
                    sha256(identity.encode('utf-8')).hexdigest(), document['node_id'], document['user_id'],
                    document['title'], heading, content, count,
                ))
                if end == len(offsets):
                    break
                start = end - config.overlap_tokens
    return chunks