from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from app.database import get_db
from app.models.chat import Conversation, Message
from app.models.node import KnowledgeNode
from app.models.user import User
from app.auth import get_current_user
from app.services.agent_service import run_agent
from app.services.rag_service import add_node_to_index
from pydantic import BaseModel
from datetime import datetime, timezone
import hashlib

router = APIRouter(prefix="/chat", tags=["chat"])


class MessageCreate(BaseModel):
    content: str
    ai_search: bool = False

class AgentStep(BaseModel):
    type: str
    content: str = ""
    tool_name: str = ""
    tool_input: dict = {}
    tool_use_id: str = ""

class WebSource(BaseModel):
    title: str = ""
    url: str = ""

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
    web_sources: List[WebSource] = []
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


def _safe_add_to_index(node_id: int, content: str, title: str, user_id: int):
    try:
        add_node_to_index(node_id, content, title, user_id)
    except Exception:
        pass


@router.post("/conversations", response_model=ConversationResponse)
def create_conversation(conv: ConversationCreate, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)):
    db_conv = Conversation(title=conv.title, user_id=current_user.id)
    db.add(db_conv)
    db.commit()
    db.refresh(db_conv)
    return db_conv


@router.get("/conversations", response_model=List[ConversationResponse])
def list_conversations(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return db.query(Conversation).filter(Conversation.user_id == current_user.id).order_by(Conversation.updated_at.desc()).all()


@router.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
def get_conversation(conversation_id: int, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)):
    conv = db.query(Conversation).filter(
        Conversation.id == conversation_id, Conversation.user_id == current_user.id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    result = ConversationDetailResponse.model_validate(conv)
    for i, msg in enumerate(conv.messages):
        result.messages[i].source_node_ids = [s.id for s in msg.sources]
        is_ai = bool(getattr(msg, 'is_ai_search', 0))
        result.messages[i].is_from_kb = not is_ai
        result.messages[i].found_in_kb = not is_ai and len(msg.sources) > 0
    return result


@router.post("/conversations/{conversation_id}/messages", response_model=MessageResponse)
def send_message(conversation_id: int, msg_in: MessageCreate, background: BackgroundTasks,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    conv = db.query(Conversation).filter(
        Conversation.id == conversation_id, Conversation.user_id == current_user.id).first()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    user_msg = Message(conversation_id=conversation_id, role="user", content=msg_in.content)
    db.add(user_msg)
    db.commit()
    conv.updated_at = datetime.now(timezone.utc)
    db.refresh(conv)
    if conv.title == "New Conversation" and len(conv.messages) == 1:
        conv.title = msg_in.content[:50] + "..." if len(msg_in.content) > 50 else msg_in.content
    db.commit()

    result = run_agent(db, conv, msg_in.content, ai_search=msg_in.ai_search, user_id=current_user.id)
    ai_content = result["content"]
    source_ids = result["source_ids"]
    is_from_kb = result.get("is_from_kb", True)
    found_in_kb = result.get("found_in_kb", True)
    agent_steps = result.get("steps", [])
    web_sources = result.get("web_sources", [])

    ai_msg = Message(conversation_id=conversation_id, role="assistant", content=ai_content,
        is_ai_search=1 if msg_in.ai_search else 0)
    if source_ids:
        nodes = db.query(KnowledgeNode).filter(
            KnowledgeNode.id.in_(source_ids), KnowledgeNode.user_id == current_user.id).all()
        ai_msg.sources = nodes
    db.add(ai_msg)
    db.commit()
    db.refresh(ai_msg)

    resp = MessageResponse.model_validate(ai_msg)
    resp.source_node_ids = source_ids
    resp.is_from_kb = is_from_kb
    resp.found_in_kb = found_in_kb
    resp.agent_steps = [AgentStep(**step) for step in agent_steps]
    resp.web_sources = [WebSource(**ws) for ws in web_sources]
    return resp


@router.post("/save-to-kb")
def save_to_kb(body: SaveToKBRequest, background: BackgroundTasks,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    content_hash = hashlib.sha256(body.content.encode()).hexdigest()
    full_content = f"# {body.title}\n\n**Question:** {body.question}\n\n## Answer\n\n{body.content}"
    node = KnowledgeNode(title=body.title, content=full_content, category="AI搜索",
        content_hash=content_hash, user_id=current_user.id)
    db.add(node)
    db.commit()
    db.refresh(node)
    background.add_task(_safe_add_to_index, node.id, node.content, node.title, current_user.id)
    return {"ok": True, "node_id": node.id, "title": node.title}
