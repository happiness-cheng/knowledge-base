"""检索候选的核心实现：生产与离线实验共用，不依赖索引/数据库/配置。

这里的函数只做排序、融合、预算打包和精排降级，不读取 SQL、不创建 Chroma
客户端，也不 import `eval`。这样 `app.services.retrieval_pipeline` 不需要反向
依赖评测包，离线实验也可以复用同一份实现，避免两套排序逻辑漂移。
"""

import math
from collections.abc import Callable
from dataclasses import dataclass


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


def _authorized_unique(ranked: list[RankedChunk], user_id: int) -> list[RankedChunk]:
    seen = set()
    result = []
    for item in ranked:
        if item.chunk.user_id == user_id and item.chunk.chunk_id not in seen:
            seen.add(item.chunk.chunk_id)
            result.append(item)
    return result


def dense_rank(query_vector, chunks: list[CandidateChunk], embeddings, *, user_id: int,
               limit: int) -> list[RankedChunk]:
    import numpy as np

    authorized = [index for index, chunk in enumerate(chunks) if chunk.user_id == user_id]
    if not authorized or limit < 1:
        return []
    # 先过滤行，再计算内积；归一化由固定 embedding 编码器完成。
    vectors = np.asarray(embeddings)[authorized]
    scores = vectors @ np.asarray(query_vector)
    ranked = [RankedChunk(chunks[index], float(score), 'dense')
              for index, score in zip(authorized, scores, strict=True)]
    return _authorized_unique(
        sorted(ranked, key=lambda item: (-item.score, item.chunk.chunk_id)), user_id,
    )[:limit]


class BM25Retriever:
    def __init__(self, chunks: list[CandidateChunk], *, user_id: int,
                 tokenize: Callable | None = None):
        from rank_bm25 import BM25Okapi

        if tokenize is None:
            import jieba

            def tokenize(text):
                return [
                    token.strip().lower() for token in jieba.lcut(text)
                    if token.strip()
                ]
        self.tokenize = tokenize
        self.chunks = list({
            chunk.chunk_id: chunk for chunk in chunks if chunk.user_id == user_id
        }.values())
        self.model = BM25Okapi([
            self.tokenize(chunk.embedding_text) for chunk in self.chunks
        ]) if self.chunks else None

    def rank(self, query: str, limit: int) -> list[RankedChunk]:
        tokens = self.tokenize(query)
        if not tokens or self.model is None or limit < 1:
            return []
        scores = self.model.get_scores(tokens)
        ranked = [RankedChunk(chunk, float(score), 'bm25')
                  for chunk, score in zip(self.chunks, scores, strict=True)]
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
    fused = [RankedChunk(chunks[identity], score, 'rrf')
             for identity, score in scores.items()]
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
        candidate_count = len(tokenizer(
            '\n\n'.join(candidate_texts), add_special_tokens=True,
        )['input_ids'])
        if candidate_count > token_budget:
            skipped += 1
            continue
        selected.append(item)
        texts = candidate_texts
        count = candidate_count
    return selected, {
        'context_tokens': count, 'context_budget': token_budget,
        'skipped_budget': skipped,
        'unauthorized_filtered': sum(item.chunk.user_id != user_id for item in ranked),
    }


def rerank_candidates(query: str, ranked: list[RankedChunk], predict: Callable, *,
                      user_id: int, pool_size: int, tokenizer=None,
                      max_length: int | None = None,
                      enabled: bool = True) -> tuple[list[RankedChunk], dict]:
    if pool_size < 1:
        raise ValueError('reranker pool must be positive')
    candidates = _authorized_unique(ranked, user_id)[:pool_size]
    trace = {'status': 'disabled' if not enabled else 'ok', 'pairs': 0,
             'pair_truncated': 0}
    if not enabled:
        return candidates, trace
    pairs = [(query, item.chunk.embedding_text) for item in candidates]
    trace['pairs'] = len(pairs)
    if tokenizer is not None and max_length is not None:
        trace['pair_truncated'] = sum(
            len(tokenizer(question, content, add_special_tokens=True,
                          truncation=False)['input_ids']) > max_length
            for question, content in pairs
        )
    if not pairs:
        return candidates, trace
    try:
        scores = list(predict(pairs))
        if len(scores) != len(candidates) or any(
            not math.isfinite(float(score)) for score in scores
        ):
            raise ValueError('invalid reranker scores')
        result = [RankedChunk(item.chunk, float(score), 'reranker')
                  for item, score in zip(candidates, scores, strict=True)]
        return sorted(
            result, key=lambda item: (-item.score, item.chunk.chunk_id),
        ), trace
    except Exception as exc:  # noqa: BLE001 -- 第三方模型失败按契约显式降级。
        trace.update(status='degraded', error_type=type(exc).__name__)
        return candidates, trace