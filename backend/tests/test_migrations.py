"""Alembic baseline and legacy-schema safety tests."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from app.database import Base
from app.models import chat, node, relationship, source, tag, user  # noqa: F401
from app.schema_validation import SchemaCompatibilityError, validate_existing_schema


def alembic_config(database_url):
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["database_url"] = database_url
    return config


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


def test_upgrade_creates_schema_and_records_head(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'fresh.db'}"

    command.upgrade(alembic_config(database_url), "head")

    engine = create_engine(database_url)
    tables = set(inspect(engine).get_table_names())
    assert {
        "users",
        "knowledge_nodes",
        "tags",
        "relationships",
        "sources",
        "conversations",
        "messages",
        "node_tags",
        "message_sources",
    } <= tables
    with engine.connect() as connection:
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "20260712_01"
        )


def test_stamp_preserves_existing_data(tmp_path):
    database_url = f"sqlite:///{tmp_path / 'legacy.db'}"
    engine = create_engine(database_url)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (username, hashed_password, is_admin) "
                "VALUES ('existing', 'hash', 0)"
            )
        )

    validate_existing_schema(engine)
    command.stamp(alembic_config(database_url), "20260712_01")

    with engine.connect() as connection:
        assert connection.execute(text("SELECT username FROM users")).scalar_one() == "existing"
        assert (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            == "20260712_01"
        )
