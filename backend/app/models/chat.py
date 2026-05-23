from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text, Table
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.database import Base

# Association table for Message <-> KnowledgeNode
message_sources = Table(
    'message_sources',
    Base.metadata,
    Column('message_id', Integer, ForeignKey('messages.id', ondelete='CASCADE'), primary_key=True),
    Column('node_id', Integer, ForeignKey('knowledge_nodes.id', ondelete='CASCADE'), primary_key=True)
)

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255), default="New Conversation")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    messages = relationship("Message", back_populates="conversation", cascade="all, delete-orphan")


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False)
    role = Column(String(50), nullable=False) # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_ai_search = Column(Integer, default=0)  # 0=from KB, 1=AI search

    conversation = relationship("Conversation", back_populates="messages")
    sources = relationship("KnowledgeNode", secondary=message_sources, backref="mentioned_in_messages")
