"""RAGFlow 派生索引的绑定关系：SQL 是笔记真值，RAGFlow 是可重建的检索层。"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base


class RagflowDataset(Base):
    __tablename__ = "ragflow_datasets"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    embedding_model: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(),
    )


class RagflowDocument(Base):
    __tablename__ = "ragflow_documents"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    node_id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[str] = mapped_column(String(64), index=True)
    source_fingerprint: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16), default="pending")
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=func.now(), onupdate=func.now(),
    )