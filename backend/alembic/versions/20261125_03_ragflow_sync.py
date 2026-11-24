"""RAGFlow 数据集/文档绑定。

Revision ID: 20261125_03
Revises: 20261014_02
"""
from alembic import op
import sqlalchemy as sa

revision = "20261125_03"
down_revision = "20261014_02"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ragflow_datasets",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("dataset_id", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("embedding_model", sa.String(255)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
        sa.UniqueConstraint("dataset_id"),
    )
    op.create_index("ix_ragflow_datasets_dataset_id", "ragflow_datasets", ["dataset_id"])
    op.create_table(
        "ragflow_documents",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("document_id", sa.String(64), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("last_error", sa.Text()),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "node_id"),
    )
    op.create_index("ix_ragflow_documents_document_id", "ragflow_documents", ["document_id"])
    op.create_index("ix_ragflow_documents_state", "ragflow_documents", ["state"])


def downgrade():
    op.drop_index("ix_ragflow_documents_state", table_name="ragflow_documents")
    op.drop_index("ix_ragflow_documents_document_id", table_name="ragflow_documents")
    op.drop_table("ragflow_documents")
    op.drop_index("ix_ragflow_datasets_dataset_id", table_name="ragflow_datasets")
    op.drop_table("ragflow_datasets")