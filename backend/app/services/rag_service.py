import os
from pathlib import Path
from chromadb import PersistentClient
from app.models.node import KnowledgeNode
from app.database import SessionLocal

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
        _embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
    return _embedding_model


def _get_user_collection(user_id: int):
    """获取用户专属的向量集合"""
    return chroma_client.get_or_create_collection(name=f"user_{user_id}_nodes")


def get_embedding(text: str) -> list[float]:
    model = _get_model()
    embeddings = model.encode(text)
    return embeddings.tolist()


def add_node_to_index(node_id: int, content: str, title: str = "", user_id: int = 1):
    if not content:
        return
    collection = _get_user_collection(user_id)
    embedding = get_embedding(content)
    collection.upsert(
        ids=[str(node_id)],
        embeddings=[embedding],
        documents=[content],
        metadatas=[{"title": title, "node_id": node_id}]
    )


def remove_node_from_index(node_id: int, user_id: int = 1):
    collection = _get_user_collection(user_id)
    try:
        collection.delete(ids=[str(node_id)])
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Error deleting from chroma: %s", e)


def retrieve_relevant_nodes(query: str, top_k: int = 3, user_id: int = 1) -> list[dict]:
    collection = _get_user_collection(user_id)
    query_embedding = get_embedding(query)
    results = collection.query(query_embeddings=[query_embedding], n_results=top_k)
    retrieved_nodes = []
    if results and results['ids'] and len(results['ids']) > 0:
        for i in range(len(results['ids'][0])):
            node_id_str = results['ids'][0][i]
            document = results['documents'][0][i]
            metadata = results['metadatas'][0][i]
            distance = results['distances'][0][i] if 'distances' in results and results['distances'] else None
            retrieved_nodes.append({
                "node_id": int(metadata.get("node_id", node_id_str)),
                "title": metadata.get("title", ""),
                "content": document,
                "distance": distance
            })
    return retrieved_nodes


def reindex_all_nodes(user_id: int = 1):
    db = SessionLocal()
    try:
        nodes = db.query(KnowledgeNode).filter(KnowledgeNode.user_id == user_id).all()
        for node in nodes:
            add_node_to_index(node.id, node.content, node.title, user_id)
    finally:
        db.close()
