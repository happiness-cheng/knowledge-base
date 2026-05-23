from sqlalchemy import String, Boolean, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship, Mapped, mapped_column
from typing import Optional
from app.database import Base
from app.models.node import node_tags


class Tag(Base):
    __tablename__ = "tags"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_tag_user_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(100), index=True)
    color: Mapped[str] = mapped_column(String(7), default="#6366f1")
    is_ai_generated: Mapped[bool] = mapped_column(default=False)

    nodes = relationship("KnowledgeNode", secondary=node_tags, back_populates="tags")
