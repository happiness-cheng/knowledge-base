import logging
import os
from pathlib import Path
from threading import Lock
from chromadb.errors import NotFoundError
from app.env_sanitize import sanitize_no_proxy  # noqa: F401  必须最先执行（净化 NO_PROXY）
from app.models.node import KnowledgeNode
from app.database import SessionLocal
from app.utils.markdown_cleaner import split_by_headings, _get_tokenizer
from app.utils.time_meta import note_date_of
from app.services.index_jobs import enqueue, fingerprint
from app.services.evidence_freshness import current_evidence
from app.services.embedding_input import count_tokens, prepare_chunks
from app.services.index_store import create_index_client
from app.config import settings

# Setup paths
CHROMA_DB_DIR = Path(os.environ.get("KB_CHROMA_DIR", str(Path(__file__).parent.parent.parent / "chroma_db")))
# HTTP模式由独立Chroma服务拥有持久索引；不创建本地备用目录。
chroma_client = create_index_client(CHROMA_DB_DIR, url=settings.kb_chroma_url,
                                    production=settings.app_env == 'production')

# ---------------------------------------------------------------------------
# 集合名后缀：让"生产集合"可被外部指定，而不是写死在代码里
# ---------------------------------------------------------------------------
# 为什么要有这个开关（而不是直接把下面的字符串改掉）：
#   1. 回滚成本 = 一条命令。删掉环境变量重启，立刻回到旧集合，代码零改动。
#   2. 旧集合原样留存、只读，直到新集合被验证通过为止——这是迁移的底线。
#   3. 评测集合用 "_eval" 后缀，与生产集合彻底分家（评测语料不得被用户检索到）。
# 注意：本值在"模块导入时"读取一次（见下方 _SUFFIX）。运行中改环境变量不生效，
#       必须重启进程——这是刻意的，避免同一进程中途换集合造成半新半旧。
KB_CHROMA_SUFFIX_ENV = "KB_CHROMA_SUFFIX"
_SUFFIX = os.environ.get(KB_CHROMA_SUFFIX_ENV, "")

# 每个 node 最多返回几块（见 retrieve_relevant_nodes 的实测说明）
#   1 = 旧行为（只留向量分最高的那块）：答案段进上下文 0.818
#   2 = 0.977（修好 7/44，零退化）        ← 默认
#   3 = 1.000（修好 8/44，零退化），代价是 prompt 更长
# 想回退旧行为：把这里改成 1，或调用时显式传 chunks_per_node=1
MAX_CHUNKS_PER_NODE = 2

# Lazy-load embedding model
_embedding_model = None
_embedding_model_lock = Lock()

def _get_model():
    global _embedding_model
    if _embedding_model is None:
        with _embedding_model_lock:
            if _embedding_model is None:
                # 并发首次检索只加载一份大模型；缓存缺失仍按离线策略失败。
                from sentence_transformers import SentenceTransformer
                _embedding_model = SentenceTransformer('BAAI/bge-large-zh-v1.5')
    return _embedding_model


def get_collection_name(user_id: int, suffix: str | None = None) -> str:
    """集合名的唯一出口（健康检查/对账脚本必须调它，不要手写字符串）。

    误写错集合名的后果：检索到别的集合的数据（09-26 实测：生产集合里混了 287 条
    评测块，真实笔记反而查不到），且不会报任何错——所以集合名必须只在一个地方拼。
    """
    if suffix is None:
        suffix = _SUFFIX
    return f"user_{user_id}_nodes{suffix}"


def _get_user_collection(user_id: int, suffix: str | None = None):
    """获取用户专属的向量集合

    suffix=None 时用模块级 _SUFFIX（生产默认行为，向后兼容旧调用）；
    显式传 "" 用于测试/影子脚本，指向旧集合且不受环境变量影响。
    """
    return chroma_client.get_or_create_collection(name=get_collection_name(user_id, suffix))


def _get_existing_user_collection(user_id: int):
    """检索只读取集合，创建集合属于索引writer的职责。"""
    try:
        return chroma_client.get_collection(name=get_collection_name(user_id))
    except NotFoundError:
        return None


# bge 查询指令前缀（M5-03：bge 系列检索时 query 必须加指令，否则检索质量明显下降）
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："


def get_embedding(text: str) -> list[float]:
    """文本 → 向量。**必须归一化**（写入与查询共用此函数，保证两侧同尺度）。

    为什么必须归一化（2026-10-07 实测，不是理论洁癖）：
      ChromaDB 默认用 L2² 距离，展开为  L2² = ||v||² − 2⟨v,q⟩ + ||q||²。
      · 若所有文档向量模长相同 → 排名只取决于 ⟨v,q⟩，与模长无关（实测 top-10 28/28 一致）
      · 若**混存两种模长**（老数据 norm=1、新写入 norm≈18.13）→ ||v||² 这一项参与排序，
        语义退居次席。实测：与"全部归一化"的 top-10 **0/28 一致，逐位置重合率 51.1%**
      ——即混入一条未归一化向量，检索结果就开始崩。

    历史坑（09-16/09-26 两次误判的来源）：本项目所有 eval 脚本都写了
    `normalize_embeddings=True`（见 eval/run_kb_eval.py:130,136），而生产这里没写。
    于是"评测的余弦"和"生产的距离"从不是同一把尺子，且生产写入会污染库内尺度。
    """
    model = _get_model()
    if count_tokens(model.tokenizer, text) > model.max_seq_length:
        raise ValueError('complete embedding input exceeds model token budget')
    embeddings = model.encode(text, normalize_embeddings=True)
    return embeddings.tolist()


def get_query_embedding(query: str) -> list[float]:
    """查询向量：bge 需加检索指令前缀；文档向量不加（用 get_embedding）"""
    return get_embedding(QUERY_PREFIX + query)


def _chunk_id(node_id: int, chunk_index: int) -> str:
    return f"{node_id}:{chunk_index}"


def add_node_to_index(node_id: int, content: str, title: str = "", user_id: int = 1):
    """父子切割（T2）：内容按 token 封顶切块，每块一个向量，metadata 记 parent node_id + chunk_index。
    短内容（≤480 token）仍是 1 块。成功返回后清理旧尾块；空正文清理本节点。

    写入与清理不是原子操作：失败向调用者抛出，同一输入串行重放可收敛。
    同一节点的并发版本更新仍需上层协调，不能据此保证多 worker 安全。
    """
    collection = _get_user_collection(user_id)
    chunks = split_by_headings(content) if content else []
    prepared = prepare_chunks(chunks, title, _get_tokenizer() if chunks else None)
    ids, embeddings, documents, metadatas = [], [], [], []
    for i, chunk in enumerate(prepared):
        ids.append(_chunk_id(node_id, i))
        embeddings.append(get_embedding(chunk.embedding_text))
        documents.append(chunk.content)
        metadatas.append({"title": title, "node_id": node_id, "chunk_index": i, "heading": chunk.heading,
                          "source_fingerprint": fingerprint(title, content),
                          "embedding_tokens": chunk.token_count,
                          "embedding_header_shortened": chunk.header_shortened})
    # 全部向量准备好后才写入；向量生成失败时保留原索引。
    if ids:
        collection.upsert(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)

    # 新块写入成功后再清理，兼容没有 node_id 元数据的旧版单 ID。
    existing_ids = set(collection.get(where={"node_id": node_id}, include=[])["ids"])
    existing_ids.update(collection.get(ids=[str(node_id)], include=[])["ids"])
    stale_ids = existing_ids.difference(ids)
    if stale_ids:
        collection.delete(ids=sorted(stale_ids))


def remove_node_from_index(node_id: int, user_id: int = 1):
    collection = _get_user_collection(user_id)
    existing = collection.get(where={"node_id": node_id})
    if existing and existing['ids']:
        collection.delete(ids=existing['ids'])
    collection.delete(ids=[str(node_id)])


def retrieve_relevant_nodes(query: str, top_k: int = 3, user_id: int = 1,
                            chunks_per_node: int = MAX_CHUNKS_PER_NODE) -> list[dict]:
    """检索：返回 top_k 个 node，每个 node 最多 chunks_per_node 块。

    ## 为什么需要 chunks_per_node（2026-10-07 实测）
    原规则是"每个 node 只保留向量分最高的那一块"（见 git 历史的 `if node_id not in
    retrieved`）。实测后果：44 条评测的 8 条失败里 **7 条是"答案块被同 node 的第 1 块
    挤掉"**，不是排序算法问题。典型：「select 和 epoll 的区别」gold 在 node13 第 1 块，
    返回的却是第 0 块。

    对照实测（同一批 44 条 query / 同模型 / 同向量池）：
        chunks_per_node=1（原行为）  答案段进上下文 0.818
        chunks_per_node=2            0.977（修好 7 条，0 条退化）  延迟 +10ms
        chunks_per_node=3            1.000（修好 8 条，0 条退化）  延迟 +6ms
    延迟几乎不变，因为多返回的块**不需要重新检索**，只是不再丢弃。

    作为对照，上 Cross-Encoder 重排（`bge-reranker-v2-m3`）只能到 0.955，且
    单 query 延迟 +19.7 秒（CPU 上 568M 模型对 480 token 块做 12 次前向）。
    即"改去重规则"以零新增依赖换到更高精度 ⇒ 本项目不需要重排。

    ⚠️ 代价：每个 node 多返回一块 ⇒ 进 prompt 的 token 增加。按 480 token/块、
    2 块/node × 3 node 估算最坏约 2880 token。这是**用上下文换精度**的显式取舍，
    所以做成可配置参数而非写死。
    """
    collection = _get_existing_user_collection(user_id)
    if collection is None or collection.count() == 0:
        return []
    query_embedding = get_query_embedding(query)
    # 多取：既要有足够不同 node，也要让同一 node 的第 2/3 块有机会浮上来
    n_fetch = max(top_k * 3, top_k * chunks_per_node * 3)
    results = collection.query(query_embeddings=[query_embedding], n_results=n_fetch)

    # 当前 SQL 所有权和正文真值必须在检索结果进入模型前核验；SQL 故障不静默放行。
    from app.database import SessionLocal as current_sessions
    with current_sessions() as db:
        current_nodes = {node.id: node for node in db.query(KnowledgeNode).filter(
            KnowledgeNode.user_id == user_id).all()}

    grouped: dict[int, list[dict]] = {}
    order: list[int] = []          # node 首次出现的顺序，保证返回顺序稳定
    if results and results['ids'] and len(results['ids'][0]) > 0:
        for i in range(len(results['ids'][0])):
            id_str = results['ids'][0][i]
            document = results['documents'][0][i]
            metadata = results['metadatas'][0][i]
            distance = (results['distances'][0][i]
                        if 'distances' in results and results['distances'] else None)
            node_id = int(metadata.get("node_id", id_str.split(':')[0]))
            node = current_nodes.get(node_id)
            if node is None or not current_evidence({"content": document, **metadata}, node):
                continue
            if len(grouped.get(node_id, [])) >= chunks_per_node:
                continue           # 该 node 已取够
            if node_id not in grouped:
                grouped[node_id] = []
                order.append(node_id)
            grouped[node_id].append({
                "node_id": node_id,
                "title": node.title,
                "content": document,
                "chunk_index": metadata.get("chunk_index"),
                "heading": metadata.get("heading", ""),
                "distance": distance,
                "source_fingerprint": metadata.get("source_fingerprint"),
            })
            # 已收集够 top_k 个 node 且每个都达到 chunks_per_node → 提前结束
            if len(order) >= top_k and all(
                    len(grouped[n]) >= chunks_per_node for n in order[:top_k]):
                break

    out: list[dict] = []
    for node_id in order[:top_k]:
        out.extend(grouped[node_id])
    return _attach_note_dates(out, user_id)


def _attach_note_dates(items: list[dict], user_id: int) -> list[dict]:
    """给检索结果补上"笔记日期"，并整体附上"库内最新数据日期"。

    ## 为什么需要（2026-10-10 实测，M5-35 数据新鲜度）
    实测负例「今天上证指数收盘多少」被答成「今天收盘 4166.29」——那个数字来自一条
    **2026-05-20** 的交易日志。这类**时效性幻觉**的特征是：faithfulness 满分、引用正确、
    数字真实，**但对用户完全错误**（把 5 个月前的数据当"今天"）。

    根因是**信息缺失**而非阈值：余弦只测"语义是否相邻"，测不出"时间是否匹配"；
    而检索结果里既没有笔记日期，也没有"库里最新到什么时候"。
    正例最高余弦 0.671 与负例最高余弦 0.675 几乎相等，正说明余弦分不开这两者。

    ## 实现取舍
    · 一次 SQL 批量取（`id.in_()`），不做 N+1 查询
    · 日期来源优先标题/正文里的日期（事件发生时间），退回 `created_at`（入库时间），
      并用 `date_source` 标明 —— **不能把入库时间当事件时间用**
    · 失败时**静默降级**为空日期，不让检索整体失败（这类元数据是增强而非必需）
    """
    if not items:
        return items
    node_ids = list({it['node_id'] for it in items})
    meta: dict[int, tuple[str, str]] = {}
    latest = ''
    _log = logging.getLogger(__name__)
    _db = SessionLocal()
    try:
        rows = (_db.query(KnowledgeNode.id, KnowledgeNode.title, KnowledgeNode.content,
                          KnowledgeNode.created_at)
                .filter(KnowledgeNode.id.in_(node_ids), KnowledgeNode.user_id == user_id).all())
        for nid, title, content, created in rows:
            meta[nid] = note_date_of(title, content, created)

        # ⚠️ kb_latest_date 必须是**全库**最新日期，不能只算本批结果里的最大值。
        # 实测踩过：同一份库，query 不同会得到 2026-05-11 / 2026-05-21 两个值 ——
        # 那样模型会误以为"库只到 5 月 11 日"，从而错误判定"今天的数据没有"。
        # 这也是"数据新鲜度"的语义：它描述**整个知识库的覆盖范围**。
        try:
            all_rows = (_db.query(KnowledgeNode.title, KnowledgeNode.content,
                                  KnowledgeNode.created_at)
                        .filter(KnowledgeNode.user_id == user_id).all())
        except Exception as e:
            # 日期增强可留空；不能因用户过滤失败而读取其他用户的覆盖范围。
            _log.warning("scoped latest note date unavailable: %s", type(e).__name__)
            _db.rollback()
            all_rows = []
        latest = max((note_date_of(t, c, cr)[0] for t, c, cr in all_rows), default='')
    except Exception as e:
        # 元数据是增强项：失败降级为"无日期"，但不能让检索整体失败
        _log.warning("attach note dates failed: %s", e)
    finally:
        _db.close()

    for it in items:
        it['note_date'], it['date_source'] = meta.get(it['node_id'], ('', 'unknown'))
        it['kb_latest_date'] = latest
    return items


def reindex_all_nodes(user_id: int = 1):
    db = SessionLocal()
    try:
        nodes = db.query(KnowledgeNode).filter(KnowledgeNode.user_id == user_id).all()
        for node in nodes:
            enqueue(db, user_id, node.id, "upsert", fingerprint(node.title, node.content))
        db.commit()
    finally:
        db.close()
