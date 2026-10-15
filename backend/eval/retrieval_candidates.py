"""离线检索候选：真实 tokenizer 预算、授权过滤、BM25、RRF 与可关精排。"""

import importlib.util
import math
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from pathlib import Path


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


@dataclass(frozen=True)
class CandidateChunk:
    chunk_id: str
    node_id: int
    user_id: int
    title: str
    heading: str
    content: str
    token_count: int

    @property
    def embedding_text(self) -> str:
        return '\n'.join(value for value in (self.title, self.heading, self.content) if value)


@dataclass(frozen=True)
class RankedChunk:
    chunk: CandidateChunk
    score: float
    source: str


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


def _authorized_unique(ranked: list[RankedChunk], user_id: int) -> list[RankedChunk]:
    seen = set()
    result = []
    for item in ranked:
        if item.chunk.user_id == user_id and item.chunk.chunk_id not in seen:
            seen.add(item.chunk.chunk_id)
            result.append(item)
    return result


def dense_rank(query_vector, chunks: list[CandidateChunk], embeddings, *, user_id: int, limit: int) -> list[RankedChunk]:
    import numpy as np

    authorized = [index for index, chunk in enumerate(chunks) if chunk.user_id == user_id]
    if not authorized or limit < 1:
        return []
    # 先过滤行，再计算内积；归一化由固定 embedding 编码器完成。
    vectors = np.asarray(embeddings)[authorized]
    scores = vectors @ np.asarray(query_vector)
    ranked = [RankedChunk(chunks[index], float(score), 'dense') for index, score in zip(authorized, scores)]
    return _authorized_unique(sorted(ranked, key=lambda item: (-item.score, item.chunk.chunk_id)), user_id)[:limit]


class BM25Retriever:
    def __init__(self, chunks: list[CandidateChunk], *, user_id: int, tokenize: Callable | None = None):
        from rank_bm25 import BM25Okapi

        if tokenize is None:
            import jieba

            tokenize = lambda text: [token.strip().lower() for token in jieba.lcut(text) if token.strip()]
        self.tokenize = tokenize
        self.chunks = list({chunk.chunk_id: chunk for chunk in chunks if chunk.user_id == user_id}.values())
        self.model = BM25Okapi([self.tokenize(chunk.embedding_text) for chunk in self.chunks]) if self.chunks else None

    def rank(self, query: str, limit: int) -> list[RankedChunk]:
        tokens = self.tokenize(query)
        if not tokens or self.model is None or limit < 1:
            return []
        scores = self.model.get_scores(tokens)
        ranked = [RankedChunk(chunk, float(score), 'bm25') for chunk, score in zip(self.chunks, scores)]
        return sorted(ranked, key=lambda item: (-item.score, item.chunk.chunk_id))[:limit]


def reciprocal_rank_fusion(rankings: list[list[RankedChunk]], *, user_id: int,
                           k: int = 60, limit: int = 20) -> list[RankedChunk]:
    if k < 1:
        raise ValueError('RRF k must be positive')
    scores = {}
    chunks = {}
    for ranked in rankings:
        for rank, item in enumerate(_authorized_unique(ranked, user_id), start=1):
            identity = item.chunk.chunk_id
            chunks[identity] = item.chunk
            scores[identity] = scores.get(identity, 0.) + 1 / (k + rank)
    fused = [RankedChunk(chunks[identity], score, 'rrf') for identity, score in scores.items()]
    return sorted(fused, key=lambda item: (-item.score, item.chunk.chunk_id))[:limit]


def pack_context(ranked: list[RankedChunk], tokenizer, *, user_id: int,
                 token_budget: int) -> tuple[list[RankedChunk], dict]:
    if token_budget < 1:
        raise ValueError('context token budget must be positive')
    authorized = _authorized_unique(ranked, user_id)
    selected = []
    texts = []
    count = 0
    skipped = 0
    for item in authorized:
        candidate_texts = texts + [item.chunk.embedding_text]
        candidate_count = len(tokenizer('\n\n'.join(candidate_texts), add_special_tokens=True)['input_ids'])
        if candidate_count > token_budget:
            skipped += 1
            continue
        selected.append(item)
        texts = candidate_texts
        count = candidate_count
    return selected, {'context_tokens': count, 'context_budget': token_budget,
                      'skipped_budget': skipped,
                      'unauthorized_filtered': sum(item.chunk.user_id != user_id for item in ranked)}


def rerank_candidates(query: str, ranked: list[RankedChunk], predict: Callable, *, user_id: int,
                      pool_size: int, tokenizer=None, max_length: int | None = None,
                      enabled: bool = True) -> tuple[list[RankedChunk], dict]:
    if pool_size < 1:
        raise ValueError('reranker pool must be positive')
    candidates = _authorized_unique(ranked, user_id)[:pool_size]
    trace = {'status': 'disabled' if not enabled else 'ok', 'pairs': 0, 'pair_truncated': 0}
    if not enabled:
        return candidates, trace
    pairs = [(query, item.chunk.embedding_text) for item in candidates]
    trace['pairs'] = len(pairs)
    if tokenizer is not None and max_length is not None:
        trace['pair_truncated'] = sum(
            len(tokenizer(question, content, add_special_tokens=True, truncation=False)['input_ids']) > max_length
            for question, content in pairs
        )
    if not pairs:
        return candidates, trace
    try:
        scores = list(predict(pairs))
        if len(scores) != len(candidates) or any(not math.isfinite(float(score)) for score in scores):
            raise ValueError('invalid reranker scores')
        result = [RankedChunk(item.chunk, float(score), 'reranker') for item, score in zip(candidates, scores)]
        return sorted(result, key=lambda item: (-item.score, item.chunk.chunk_id)), trace
    except Exception as exc:  # noqa: BLE001 -- 第三方模型失败按契约显式降级，保留错误类别。
        trace.update(status='degraded', error_type=type(exc).__name__)
        return candidates, trace
