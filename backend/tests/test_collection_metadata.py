"""Collection 身份元数据：新集合写入，旧集合只报告不静默改写。"""

from app.services import rag_service
from app.services.index_metadata import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL,
    collection_metadata,
    metadata_status,
)


def test_new_collection_writes_model_identity_metadata():
    collection = rag_service._get_user_collection(9876, suffix="_metadata_new")
    status = metadata_status(collection.metadata)
    assert status["status"] == "match"
    assert collection.metadata["embedding_model"] == EMBEDDING_MODEL
    assert collection.metadata["embedding_dimension"] == EMBEDDING_DIMENSION
    assert collection.metadata["kb_schema_version"] == collection_metadata()["kb_schema_version"]


def test_legacy_collection_without_metadata_is_reported_not_rewritten():
    name = rag_service.get_collection_name(9877, "_metadata_legacy")
    legacy = rag_service.chroma_client.create_collection(name=name)
    assert legacy.metadata is None

    reopened = rag_service._get_user_collection(9877, suffix="_metadata_legacy")
    assert reopened.metadata is None
    status = metadata_status(reopened.metadata)
    assert status["status"] == "missing"
    assert "embedding_model" in status["missing"]