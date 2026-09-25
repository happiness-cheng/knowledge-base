import os
from pathlib import Path
from chromadb import PersistentClient
from app.models.node import KnowledgeNode
from app.database import SessionLocal
from app.utils.markdown_cleaner import split_by_headings

# Setup paths
CHROMA_DB_DIR = Path(__file__).parent.parent.parent / "chroma_db"
CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)

# Initialize ChromaDB
chroma_client = PersistentClient(path=str(CHROMA_DB_DIR))

# Lazy-load embedding model
_embedding_model = None

def _get_model():
    global _embedding_model
    if _embedding_model is None:
        import os
        os.environ["HF_HUB_OFFLINE"] = "1"
        from sentence_transformers import SentenceTransformer
        # bge-large-zh-v1.5：中文语义（M5-03），1024 维；
        # 换模型必须全量重嵌入（新旧向量不在同一空间）
        _embedding_model = SentenceTransformer('BAAI/bge-large-zh-v1.5')
    return _embedding_model


def _get_user_collection(user_id: int):
    """获取用户专属的向量集合"""
    return chroma_client.get_or_create_collection(name=f"user_{user_id}_nodes")


# bge 查询指令前缀（M5-03：bge 系列检索时 query 必须加指令，否则检索质量明显下降）
QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："


def get_embedding(text: str) -> list[float]:
    model = _get_model()
    embeddings = model.encode(text)
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


def retrieve_relevant_nodes(query: str, top_k: int = 3, user_id: int = 1) -> list[dict]:
    """检索：多取 chunk（同 node 可能多块），按 node_id 去重后返回 top_k 个不同 node（取各自最相关块）"""
    collection = _get_user_collection(user_id)
    query_embedding = get_query_embedding(query)
    # 多取 3 倍，去重后仍有足够不同 node
    results = collection.query(query_embeddings=[query_embedding], n_results=top_k * 3)
    retrieved = {}
    if results and results['ids'] and len(results['ids']) > 0:
        for i in range(len(results['ids'][0])):
            id_str = results['ids'][0][i]
            document = results['documents'][0][i]
            metadata = results['metadatas'][0][i]
            distance = results['distances'][0][i] if 'distances' in results and results['distances'] else None
            node_id = int(metadata.get("node_id", id_str.split(':')[0]))
            # 去重：每个 node 只保留最相关（最先出现）的块
            if node_id not in retrieved:
                retrieved[node_id] = {
                    "node_id": node_id,
                    "title": metadata.get("title", ""),
                    "content": document,
                    "chunk_index": metadata.get("chunk_index"),
                    "heading": metadata.get("heading", ""),
                    "distance": distance,
                }
    return list(retrieved.values())[:top_k]


def reindex_all_nodes(user_id: int = 1):
    db = SessionLocal()
    try:
        nodes = db.query(KnowledgeNode).filter(KnowledgeNode.user_id == user_id).all()
        for node in nodes:
            add_node_to_index(node.id, node.content, node.title, user_id)
    finally:
        db.close()
