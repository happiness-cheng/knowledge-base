"""Initial knowledge-base schema.

Revision ID: 20260712_01
Revises:
Create Date: 2026-07-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260712_01"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=50), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("ai_api_key", sa.String(length=500), nullable=True),
        sa.Column("ai_base_url", sa.String(length=500), nullable=True),
        sa.Column("ai_model_name", sa.String(length=100), nullable=True),
        sa.Column("is_admin", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_id", "users", ["id"], unique=False)
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("file_type", sa.String(length=10), nullable=False),
        sa.Column("file_path", sa.String(length=1000), nullable=True),
        sa.Column("imported_at", sa.DateTime(), nullable=False),
        sa.Column("node_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sources_user_id", "sources", ["user_id"], unique=False)

    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=False),
        sa.Column("is_ai_generated", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_tag_user_name"),
    )
    op.create_index("ix_tags_user_id", "tags", ["user_id"], unique=False)
    op.create_index("ix_tags_name", "tags", ["name"], unique=False)

    op.create_table(
        "knowledge_nodes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("importance", sa.Float(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("ai_analyzed", sa.Boolean(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_knowledge_nodes_user_id", "knowledge_nodes", ["user_id"], unique=False)
    op.create_index("ix_knowledge_nodes_title", "knowledge_nodes", ["title"], unique=False)
    op.create_index("ix_knowledge_nodes_category", "knowledge_nodes", ["category"], unique=False)

    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_conversations_id", "conversations", ["id"], unique=False)
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"], unique=False)

    op.create_table(
        "relationships",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("source_topic", sa.String(length=200), nullable=True),
        sa.Column("target_topic", sa.String(length=200), nullable=True),
        sa.Column("rel_type", sa.String(length=50), nullable=False),
        sa.Column("strength", sa.Float(), nullable=False),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("is_ai_generated", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["knowledge_nodes.id"]),
        sa.ForeignKeyConstraint(["target_id"], ["knowledge_nodes.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_relationships_user_id", "relationships", ["user_id"], unique=False)
    op.create_index("ix_relationships_source_id", "relationships", ["source_id"], unique=False)
    op.create_index("ix_relationships_target_id", "relationships", ["target_id"], unique=False)

    op.create_table(
        "node_tags",
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["node_id"], ["knowledge_nodes.id"]),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"]),
        sa.PrimaryKeyConstraint("node_id", "tag_id"),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("conversation_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("is_ai_search", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_messages_id", "messages", ["id"], unique=False)

    op.create_table(
        "message_sources",
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["node_id"], ["knowledge_nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("message_id", "node_id"),
    )


def downgrade() -> None:
    op.drop_table("message_sources")
    op.drop_table("messages")
    op.drop_table("node_tags")
    op.drop_table("relationships")
    op.drop_table("conversations")
    op.drop_table("knowledge_nodes")
    op.drop_table("tags")
    op.drop_table("sources")
    op.drop_table("users")
