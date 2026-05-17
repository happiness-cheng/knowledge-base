from sqlalchemy import String, Boolean
from sqlalchemy.orm import relationship, Mapped, mapped_column
from app.database import Base
from app.models.node import node_tags


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    color: Mapped[str] = mapped_column(String(7), default="#6366f1")
    is_ai_generated: Mapped[bool] = mapped_column(default=False)

    nodes = relationship("KnowledgeNode", secondary=node_tags, back_populates="tags")