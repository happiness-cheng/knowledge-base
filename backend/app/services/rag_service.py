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
collection_name = "knowledge_nodes"
collection = chroma_client.get_or_create_collection(name=collection_name)

# Lazy-load embedding model (only load when first needed)
_embedding_model = None

def _get_model():
    global _embedding_model
    if _embedding_model is None:
        import os
        os.environ["HF_HUB_OFFLINE"] = "1"
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
    return _embedding_model


def get_embedding(text: str) -> list[float]:
    """Generate vector embedding for a given text."""
    model = _get_model()
    embeddings = model.encode(text)
    return embeddings.tolist()

def add_node_to_index(node_id: int, content: str, title: str = ""):
    """Add or update a node in the vector database."""
    if not content:
        return

    embedding = get_embedding(content)
    collection.upsert(
        ids=[str(node_id)],
        embeddings=[embedding],
        documents=[content],
        metadatas=[{"title": title, "node_id": node_id}]
    )

def remove_node_from_index(node_id: int):
    """Remove a node from the vector database."""
    try:
        collection.delete(ids=[str(node_id)])
    except Exception as e:
        print(f"Error deleting from chroma: {e}")

def retrieve_relevant_nodes(query: str, top_k: int = 3) -> list[dict]:
    """Retrieve top-k most relevant nodes for a given query."""
    query_embedding = get_embedding(query)

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k
    )

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

def reindex_all_nodes():
    """Rebuild the vector index from the database."""
    db = SessionLocal()
    try:
        nodes = db.query(KnowledgeNode).all()
        for node in nodes:
            add_node_to_index(node.id, node.content, node.title)
    finally:
        db.close()