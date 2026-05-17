from pydantic import BaseModel, ConfigDict
from typing import Optional


class RelationshipCreate(BaseModel):
    source_id: int
    target_id: int
    source_topic: Optional[str] = None
    target_topic: Optional[str] = None
    rel_type: str = "related_to"
    label: Optional[str] = None


class RelationshipOut(BaseModel):
    id: int
    source_id: int
    target_id: int
    source_topic: Optional[str]
    target_topic: Optional[str]
    rel_type: str
    label: Optional[str]
    is_ai_generated: bool

    model_config = ConfigDict(from_attributes=True)
