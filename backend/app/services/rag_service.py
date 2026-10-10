import os
from pathlib import Path
from chromadb import PersistentClient
from app.env_sanitize import sanitize_no_proxy  # noqa: F401  必须最先执行（净化 NO_PROXY）
from app.models.node import KnowledgeNode
from app.database import SessionLocal
from app.utils.markdown_cleaner import split_by_headings

# Setup paths
CHROMA_DB_DIR = Path(__file__).parent.parent.parent / "chroma_db"
CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)

# Initialize ChromaDB
chroma_client = PersistentClient(path=str(CHROMA_DB_DIR))

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

def _get_model():
    global _embedding_model
    if _embedding_model is None:
        # 离线开关已由 app.env_sanitize 在导入期设好（那里才能早于 huggingface_hub 缓存常量）
        from sentence_transformers import SentenceTransformer
        # bge-large-zh-v1.5：中文语义（M5-03），1024 维；
        # 换模型必须全量重嵌入（新旧向量不在同一空间）
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
    embeddings = model.encode(text, normalize_embeddings=True)
    return embeddings.tolist()


def get_query_embedding(query: str) -> list[float]:
    """查询向量：bge 需加检索指令前缀；文档向量不加（用 get_embedding）"""
    return get_embedding(QUERY_PREFIX + query)


def _chunk_id(node_id: int, chunk_index: int) -> str:
    return f"{node_id}:{chunk_index}"


def add_node_to_index(node_id: int, content: str, title: str = "", user_id: int = 1):
    """父子切割（T2）：内容按 token 封顶切块，每块一个向量，metadata 记 parent node_id + chunk_index。
    短内容（≤480 token）仍是 1 块，行为等价旧版。"""
    if not content:
        return
    collection = _get_user_collection(user_id)
    chunks = split_by_headings(content)
    ids, embeddings, documents, metadatas = [], [], [], []
    for i, (heading, chunk_content) in enumerate(chunks):
        # 标题+小节标题拼进正文再编码（M5-02 contextual chunk headers）
        embed_text = f"{title}\n{heading}\n{chunk_content}" if title else f"{heading}\n{chunk_content}"
        ids.append(_chunk_id(node_id, i))
        embeddings.append(get_embedding(embed_text))
        documents.append(chunk_content)
        metadatas.append({"title": title, "node_id": node_id, "chunk_index": i, "heading": heading})
    collection.upsert(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)


def remove_node_from_index(node_id: int, user_id: int = 1):
    collection = _get_user_collection(user_id)
    try:
        # 删除该 node 的所有 chunk（按 metadata node_id 过滤，覆盖旧版单 id 和新版多 chunk）
        existing = collection.get(where={"node_id": node_id})
        if existing and existing['ids']:
            collection.delete(ids=existing['ids'])
        # 兜底：旧版 id = str(node_id) 也可能残留
        collection.delete(ids=[str(node_id)])
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Error deleting from chroma: %s", e)


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
    collection = _get_user_collection(user_id)
    query_embedding = get_query_embedding(query)
    # 多取：既要有足够不同 node，也要让同一 node 的第 2/3 块有机会浮上来
    n_fetch = max(top_k * 3, top_k * chunks_per_node * 3)
    results = collection.query(query_embeddings=[query_embedding], n_results=n_fetch)

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
            if len(grouped.get(node_id, [])) >= chunks_per_node:
                continue           # 该 node 已取够
            if node_id not in grouped:
                grouped[node_id] = []
                order.append(node_id)
            grouped[node_id].append({
                "node_id": node_id,
                "title": metadata.get("title", ""),
                "content": document,
                "chunk_index": metadata.get("chunk_index"),
                "heading": metadata.get("heading", ""),
                "distance": distance,
            })
            # 已收集够 top_k 个 node 且每个都达到 chunks_per_node → 提前结束
            if len(order) >= top_k and all(
                    len(grouped[n]) >= chunks_per_node for n in order[:top_k]):
                break

    out: list[dict] = []
    for node_id in order[:top_k]:
        out.extend(grouped[node_id])
    return out


def reindex_all_nodes(user_id: int = 1):
    db = SessionLocal()
    try:
        nodes = db.query(KnowledgeNode).filter(KnowledgeNode.user_id == user_id).all()
        for node in nodes:
            add_node_to_index(node.id, node.content, node.title, user_id)
    finally:
        db.close()
