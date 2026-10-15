from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Literal, Optional
from app.database import get_db
from app.models.chat import Conversation, Message
from app.models.node import KnowledgeNode
from app.models.user import User
from app.auth import get_current_user
from app.services.agent_service import run_agent
from app.services.claude_client import get_client_for_user
from app.services.index_jobs import enqueue, fingerprint
from pydantic import BaseModel, Field, model_validator
from datetime import datetime, timezone
import hashlib

router = APIRouter(prefix="/chat", tags=["chat"])


class MessageCreate(BaseModel):
    content: str
    ai_search: bool = False
    kb_only: bool = False
    backend: Literal["custom", "langchain"] = "custom"
    retrieval_mode: Literal["current", "dense", "bm25", "hybrid"] = "current"
    rerank: bool = False
    rewrite: bool = False
    rewrite_bindings: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_answer_mode(self):
        if self.kb_only and self.ai_search:
            raise ValueError("kb_only and ai_search cannot both be enabled")
        if self.backend == "langchain" and not self.kb_only:
            raise ValueError("langchain backend requires kb_only")
        if self.backend != "langchain" and (self.retrieval_mode != "current" or self.rerank or self.rewrite):
            raise ValueError("retrieval candidates require langchain backend")
        if self.rerank and self.retrieval_mode == "current":
            raise ValueError("rerank requires an explicit retrieval candidate")
        if self.rewrite_bindings and not self.rewrite:
            raise ValueError("rewrite bindings require enabled rewrite")
        return self

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
    # 仅当前严格请求返回；没有数据库迁移，历史记录不推断此状态。
    answer_status: Optional[Literal["supported", "not_found", "error"]] = None
    # 候选诊断仅随当前响应返回；没有新增持久化字段。
    retrieval_trace: Optional[dict] = None
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


def run_langchain_candidate(db, question, **kwargs):
    # 候选只从明确的严格请求进入，复用当前用户的已选客户端。
    from app.services.langchain_rag import run_langchain_rag

    return run_langchain_rag(db, question, **kwargs)


def make_retrieval_candidate(db, **kwargs):
    from app.services.retrieval_pipeline import make_candidate_retrieval

    return make_candidate_retrieval(db, **kwargs)


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

    selected_client = get_client_for_user(current_user)
    if msg_in.backend == "langchain":
        candidate = None
        options = {}
        if msg_in.retrieval_mode != "current":
            candidate = make_retrieval_candidate(
                db, user_id=current_user.id, mode=msg_in.retrieval_mode, rerank=msg_in.rerank,
            )
            options['retrieval'] = candidate
        if msg_in.rewrite:
            history = db.query(Message).filter(
                Message.conversation_id == conversation_id, Message.role == 'user',
                Message.id < user_msg.id,
            ).order_by(Message.id.desc()).limit(2).all() if msg_in.rewrite_bindings else []
            options.update(
                rewrite_enabled=True, rewrite_bindings=msg_in.rewrite_bindings,
                rewrite_history=tuple({'role': 'user', 'content': entry.content} for entry in reversed(history)),
            )
        result = run_langchain_candidate(
            db, msg_in.content, user_id=current_user.id, ai_client=selected_client,
            **options,
        )
        if candidate is not None:
            result['retrieval_trace'] = getattr(candidate, 'history', candidate.trace)
    else:
        result = run_agent(
            db,
            conv,
            msg_in.content,
            ai_search=msg_in.ai_search,
            user_id=current_user.id,
            ai_client=selected_client,
            kb_only=msg_in.kb_only,
        )
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
    resp.answer_status = result.get("answer_status")
    resp.retrieval_trace = {'branches': result['retrieval_trace']} if isinstance(
        result.get('retrieval_trace'), list,
    ) else result.get('retrieval_trace')
    return resp


@router.post("/save-to-kb")
def save_to_kb(body: SaveToKBRequest, background: BackgroundTasks,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    content_hash = hashlib.sha256(body.content.encode()).hexdigest()
    full_content = f"# {body.title}\n\n**Question:** {body.question}\n\n## Answer\n\n{body.content}"
    node = KnowledgeNode(title=body.title, content=full_content, category="AI搜索",
        content_hash=content_hash, user_id=current_user.id)
    db.add(node)
    db.flush()
    enqueue(db, current_user.id, node.id, "upsert", fingerprint(node.title, node.content))
    db.commit()
    db.refresh(node)
    return {"ok": True, "node_id": node.id, "title": node.title}
