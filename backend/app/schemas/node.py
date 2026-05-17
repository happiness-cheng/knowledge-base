from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Optional


class NodeCreate(BaseModel):
    title: str
    content: str
    tags: list[str] = []
    category: Optional[str] = None


class NodeUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    tags: Optional[list[str]] = None
    category: Optional[str] = None


class NodeSummary(BaseModel):
    id: int
    title: str
    category: Optional[str]
    tags: list[str]
    importance: float

    model_config = ConfigDict(from_attributes=True)


class NodeDetail(BaseModel):
    id: int
    title: str
    content: str
    summary: Optional[str]
    category: Optional[str]
    tags: list[str]
    importance: float
    source_id: Optional[int]
    created_at: datetime
    updated_at: datetime
    ai_analyzed: bool

    model_config = ConfigDict(from_attributes=True)
