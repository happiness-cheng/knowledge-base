"""事务索引任务。

Revision ID: 20261014_02
Revises: 20260712_01
"""
from alembic import op
import sqlalchemy as sa

revision = "20261014_02"
down_revision = "20260712_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "index_jobs",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.Integer(), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("operation", sa.String(10), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("lease_token", sa.String(32)),
        sa.Column("lease_until", sa.DateTime()),
        sa.Column("last_error_type", sa.String(80)),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "node_id"),
    )
    op.create_index("ix_index_jobs_state", "index_jobs", ["state"])


def downgrade():
    op.drop_index("ix_index_jobs_state", table_name="index_jobs")
    op.drop_table("index_jobs")
