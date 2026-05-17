from sqlalchemy import String, DateTime
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.sql import func
from datetime import datetime
from typing import Optional
from app.database import Base


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(500))
    file_type: Mapped[str] = mapped_column(String(10))
    file_path: Mapped[Optional[str]] = mapped_column(String(1000))
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    node_count: Mapped[int] = mapped_column(default=0)

    nodes = relationship("KnowledgeNode", back_populates="source")