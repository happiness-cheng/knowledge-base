from sqlalchemy import Column, Integer, String, Text, ForeignKey, Table, DateTime
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func
from datetime import datetime
from typing import Optional
from app.database import Base

node_tags = Table(
    "node_tags",
    Base.metadata,
    Column("node_id", Integer, ForeignKey("knowledge_nodes.id"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id"), primary_key=True),
)


class KnowledgeNode(Base):
    __tablename__ = "knowledge_nodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(500), index=True)
    content: Mapped[str] = mapped_column(Text)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    category: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    importance: Mapped[float] = mapped_column(default=0.5)
    source_id: Mapped[Optional[int]] = mapped_column(ForeignKey("sources.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=func.now(), onupdate=func.now())
    ai_analyzed: Mapped[bool] = mapped_column(default=False)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64))

    source = relationship("Source", back_populates="nodes")
    tags = relationship("Tag", secondary=node_tags, back_populates="nodes")
    outgoing = relationship("Relationship", foreign_keys="Relationship.source_id", back_populates="source_node")
    incoming = relationship("Relationship", foreign_keys="Relationship.target_id", back_populates="target_node")
