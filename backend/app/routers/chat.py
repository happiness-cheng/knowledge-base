from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app.models.chat import Conversation, Message
from app.models.node import KnowledgeNode
from app.services.agent_service import run_agent
from app.services.rag_service import add_node_to_index
from pydantic import BaseModel
from datetime import datetime, timezone
import hashlib

router = APIRouter(prefix="/chat", tags=["chat"])

# Schemas
class MessageCreate(BaseModel):
    content: str
    ai_search: bool = False

class AgentStep(BaseModel):
    type: str  # "tool_call", "tool_result", "final_answer"
    content: str = ""
    tool_name: str = ""
    tool_input: dict = {}
    tool_use_id: str = ""

class MessageResponse(BaseModel):
    id: int
    conversation_id: int
    role: str
    content: str
    created_at: datetime
    source_node_ids: List[int] = []
    is_from_kb: bool = True
    found_in_kb: bool = True
    agent_steps: List[AgentStep] = []

    class Config:
        from_attributes = True

class ConversationCreate(BaseModel):
    title: str = "New Conversation"

class ConversationResponse(BaseModel):
    id: int
    title: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class ConversationDetailResponse(ConversationResponse):
    messages: List[MessageResponse] = []

class SaveToKBRequest(BaseModel):
    title: str
    content: str
    question: str


def _safe_add_to_index(node_id: int, content: str, title: str):
    try:
        add_node_to_index(node_id, content, title)
    except Exception:
        pass


@router.post("/conversations", response_model=ConversationResponse)
def create_conversation(conv: ConversationCreate, db: Session = Depends(get_db)):
    db_conv = Conversation(title=conv.title)
    db.add(db_conv)
    db.commit()
    db.refresh(db_conv)
    return db_conv


@router.get("/conversations", response_model=List[ConversationResponse])
def list_conversations(db: Session = Depends(get_db)):
    return db.query(Conversation).order_by(Conversation.updated_at.desc()).all()


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation(conversation_id: int, db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    result = ConversationDetailResponse.model_validate(conv)
    for i, msg in enumerate(conv.messages):
        result.messages[i].source_node_ids = [s.id for s in msg.sources]
        is_ai = bool(getattr(msg, 'is_ai_search', 0))
        result.messages[i].is_from_kb = not is_ai
        # For historical messages: if it's KB mode and has sources, it was found
        result.messages[i].found_in_kb = not is_ai and len(msg.sources) > 0

    return result


@router.post("/conversations/{conversation_id}/messages", response_model=MessageResponse)
def send_message(conversation_id: int, msg_in: MessageCreate, background: BackgroundTasks, db: Session = Depends(get_db)):
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # 1. Save user message
    user_msg = Message(conversation_id=conversation_id, role="user", content=msg_in.content)
    db.add(user_msg)
    db.commit()

    # Update conversation updated_at
    conv.updated_at = datetime.now(timezone.utc)
    db.refresh(conv)
    # Auto-title if it's the first message
    if conv.title == "New Conversation" and len(conv.messages) == 1:
        conv.title = msg_in.content[:50] + "..." if len(msg_in.content) > 50 else msg_in.content

    db.commit()

    # 2. Generate AI response via Agent
    result = run_agent(db, conv, msg_in.content, ai_search=msg_in.ai_search)
    ai_content = result["content"]
    source_ids = result["source_ids"]
    is_from_kb = result.get("is_from_kb", True)
    found_in_kb = result.get("found_in_kb", True)
    agent_steps = result.get("steps", [])

    # 3. Save AI message
    ai_msg = Message(
        conversation_id=conversation_id,
        role="assistant",
        content=ai_content,
        is_ai_search=1 if msg_in.ai_search else 0,
    )

    # 4. Link sources
    if source_ids:
        nodes = db.query(KnowledgeNode).filter(KnowledgeNode.id.in_(source_ids)).all()
        ai_msg.sources = nodes

    db.add(ai_msg)
    db.commit()
    db.refresh(ai_msg)

    # Prepare response
    resp = MessageResponse.model_validate(ai_msg)
    resp.source_node_ids = source_ids
    resp.is_from_kb = is_from_kb
    resp.found_in_kb = found_in_kb
    resp.agent_steps = [AgentStep(**step) for step in agent_steps]

    return resp


@router.post("/save-to-kb")
def save_to_kb(body: SaveToKBRequest, background: BackgroundTasks, db: Session = Depends(get_db)):
    """Save AI-generated knowledge as a new node in the knowledge base."""
    content_hash = hashlib.sha256(body.content.encode()).hexdigest()

    # Format the content nicely
    full_content = f"# {body.title}\n\n**Question:** {body.question}\n\n## Answer\n\n{body.content}"

    node = KnowledgeNode(
        title=body.title,
        content=full_content,
        category="AI搜索",
        content_hash=content_hash,
    )
    db.add(node)
    db.commit()
    db.refresh(node)

    # Index and analyze in background
    background.add_task(_safe_add_to_index, node.id, node.content, node.title)

    return {"ok": True, "node_id": node.id, "title": node.title}
