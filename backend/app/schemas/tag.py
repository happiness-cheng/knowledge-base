from pydantic import BaseModel, ConfigDict


class TagCreate(BaseModel):
    name: str
    color: str = "#6366f1"


class TagOut(BaseModel):
    id: int
    name: str
    color: str
    is_ai_generated: bool
    node_count: int = 0

    model_config = ConfigDict(from_attributes=True)
