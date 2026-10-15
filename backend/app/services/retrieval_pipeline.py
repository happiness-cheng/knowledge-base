"""现有用户索引上的检索候选：先核验SQL，再排名与有界证据组织。"""

from functools import lru_cache

from app.models.node import KnowledgeNode
from app.services.evidence_freshness import current_evidence
from eval.retrieval_candidates import (
    BM25Retriever,
    CandidateChunk,
    dense_rank,
    pack_context,
    reciprocal_rank_fusion,
    rerank_candidates,
)


@lru_cache(maxsize=1)
def _reranker():
    from sentence_transformers import CrossEncoder

    return CrossEncoder('BAAI/bge-reranker-v2-m3', local_files_only=True,
                        device='cpu', max_length=512)


@lru_cache(maxsize=1)
def _tokenizer():
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained('BAAI/bge-large-zh-v1.5', local_files_only=True)


class SnapshotRetrievalCandidate:
    def __init__(self, db, *, user_id, mode, collection, tokenizer, query_encoder,
                 reranker, rerank, pool_size, context_tokens, max_chunks):
        self.db, self.user_id, self.mode = db, user_id, mode
        self.collection, self.tokenizer = collection, tokenizer
        self.query_encoder, self.reranker = query_encoder, reranker
        self.rerank = rerank or reranker is not None
        self.pool_size, self.context_tokens, self.max_chunks = pool_size, context_tokens, max_chunks
        self.trace = {}
        self.history = []

    def __call__(self, query, *, user_id, top_k):
        if user_id != self.user_id:
            raise ValueError('candidate user cannot be rebound')
        if not isinstance(query, str) or not query.strip() or type(top_k) is not int or top_k < 1:
            raise ValueError('invalid retrieval input')
        owned = {node.id: node for node in self.db.query(KnowledgeNode).populate_existing().filter(
            KnowledgeNode.user_id == self.user_id,
        ).all() if node.content and node.content.strip()}
        self.trace = {'mode': self.mode, 'ownership_rejected': 0, 'stale_rejected': 0,
                      'oversized_rejected': 0, 'candidate_count': 0}
        if not owned:
            return []
        from app.services import rag_service

        collection = self.collection if self.collection is not None else rag_service._get_existing_user_collection(self.user_id)
        if collection is None:
            raise ValueError('index collection not available')
        snapshot = collection.get(limit=self.max_chunks + 1,
                                  include=['documents', 'metadatas', 'embeddings'])
        identities = snapshot['ids']
        if len(identities) > self.max_chunks:
            raise ValueError('candidate snapshot exceeds bounded size')
        tokenizer = self.tokenizer or _tokenizer()
        chunks, embeddings = [], []
        for index, identity in enumerate(identities):
            metadata = snapshot['metadatas'][index] or {}
            node_id = metadata.get('node_id')
            node = owned.get(node_id) if type(node_id) is int else None
            if node is None:
                self.trace['ownership_rejected'] += 1
                continue
            content = snapshot['documents'][index]
            if not current_evidence({**metadata, 'content': content}, node):
                self.trace['stale_rejected'] += 1
                continue
            heading = str(metadata.get('heading', ''))
            complete = '\n'.join(value for value in (node.title, heading, content) if value)
            token_count = len(tokenizer(complete, add_special_tokens=True)['input_ids'])
            if token_count > 512:
                self.trace['oversized_rejected'] += 1
                continue
            chunks.append(CandidateChunk(str(identity), node_id, self.user_id,
                                         node.title, heading, content, token_count))
            raw_vectors = snapshot.get('embeddings')
            embeddings.append(raw_vectors[index] if raw_vectors is not None else None)
        if not chunks:
            if self.trace['stale_rejected'] or self.trace['oversized_rejected']:
                raise ValueError('index has no usable current evidence')
            return []
        dense, sparse = [], []
        if self.mode in {'dense', 'hybrid'}:
            query_tokens = len(tokenizer(rag_service.QUERY_PREFIX + query,
                                        add_special_tokens=True)['input_ids'])
            if query_tokens > 512:
                raise ValueError('embedding query exceeds model token budget')
            self.trace['embedding_query_tokens'] = query_tokens
            encoder = self.query_encoder or rag_service.get_query_embedding
            dense = dense_rank(encoder(query), chunks, embeddings,
                               user_id=self.user_id, limit=self.pool_size)
        if self.mode in {'bm25', 'hybrid'}:
            sparse = BM25Retriever(chunks, user_id=self.user_id).rank(query, self.pool_size)
        ranked = (reciprocal_rank_fusion([dense, sparse], user_id=self.user_id, limit=self.pool_size)
                  if self.mode == 'hybrid' else dense if self.mode == 'dense' else sparse)
        self.trace['candidate_count'] = len(ranked)
        if self.rerank:
            predict = self.reranker or (lambda pairs: _reranker().predict(pairs))
            ranked, self.trace['rerank'] = rerank_candidates(
                query, ranked, predict, user_id=self.user_id, pool_size=self.pool_size,
            )
            # 没有用实际精排tokenizer测量时，不能把未知截断数写成0。
            self.trace['rerank']['pair_truncated'] = None
        else:
            self.trace['rerank'] = {'status': 'disabled', 'pairs': 0}
        # top_k控制父文档数量，完整块按同一证据预算打包；不截断块正文。
        parent_ids = list(dict.fromkeys(item.chunk.node_id for item in ranked))[:top_k]
        eligible = [item for item in ranked if item.chunk.node_id in parent_ids]
        packed, budget = pack_context(eligible, tokenizer, user_id=self.user_id,
                                      token_budget=self.context_tokens)
        self.trace['evidence_budget_bge'] = budget
        self.trace['selected_chunk_ids'] = [item.chunk.chunk_id for item in packed]
        self.history.append(dict(self.trace))
        if not packed:
            raise ValueError('evidence context budget contains no complete chunk')
        return [{'node_id': item.chunk.node_id, 'title': item.chunk.title,
                 'content': item.chunk.content, 'chunk_id': item.chunk.chunk_id,
                 'score': item.score, 'rank_source': item.source} for item in packed]


def make_candidate_retrieval(db, *, user_id, mode='hybrid', collection=None, tokenizer=None,
                             query_encoder=None, reranker=None, rerank=False,
                             pool_size=20, context_tokens=1536, max_chunks=5000):
    if type(user_id) is not int or user_id < 1 or mode not in {'dense', 'bm25', 'hybrid'}:
        raise ValueError('invalid candidate user or mode')
    if any(type(value) is not int or value < 1 for value in (pool_size, context_tokens, max_chunks)):
        raise ValueError('candidate budgets must be positive integers')
    return SnapshotRetrievalCandidate(
        db, user_id=user_id, mode=mode, collection=collection, tokenizer=tokenizer,
        query_encoder=query_encoder, reranker=reranker, rerank=rerank,
        pool_size=pool_size, context_tokens=context_tokens, max_chunks=max_chunks,
    )
