from sqlalchemy import String, ForeignKey, DateTime
from sqlalchemy.orm import relationship as rel, Mapped, mapped_column
from sqlalchemy.sql import func
from datetime import datetime
from typing import Optional
from app.database import Base


class Relationship(Base):
    __tablename__ = "relationships"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("knowledge_nodes.id"), index=True)
    target_id: Mapped[int] = mapped_column(ForeignKey("knowledge_nodes.id"), index=True)
    source_topic: Mapped[Optional[str]] = mapped_column(String(200))
    target_topic: Mapped[Optional[str]] = mapped_column(String(200))
    rel_type: Mapped[str] = mapped_column(String(50), default="related_to")
    strength: Mapped[float] = mapped_column(default=0.5)  # kept for DB compat
    label: Mapped[Optional[str]] = mapped_column(String(200))
    is_ai_generated: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())

    source_node = rel("KnowledgeNode", foreign_keys=[source_id], back_populates="outgoing")
    target_node = rel("KnowledgeNode", foreign_keys=[target_id], back_populates="incoming")