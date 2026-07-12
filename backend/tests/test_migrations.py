"""Alembic baseline and legacy-schema safety tests."""

import pytest
from sqlalchemy import create_engine, inspect, text

from app.database import Base
from app.models import chat, node, relationship, source, tag, user  # noqa: F401
from app.schema_validation import SchemaCompatibilityError, validate_existing_schema


def test_validator_accepts_schema_created_from_current_metadata(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    Base.metadata.create_all(engine)

    validate_existing_schema(engine)


def test_validator_reports_missing_table_without_writing_version_table(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'incomplete.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY)"))

    with pytest.raises(SchemaCompatibilityError, match="knowledge_nodes"):
        validate_existing_schema(engine)

    assert "alembic_version" not in inspect(engine).get_table_names()
