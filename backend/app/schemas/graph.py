from pydantic import BaseModel
from typing import Optional


class GraphNode(BaseModel):
    id: int
    title: str
    category: Optional[str]
    tags: list[str]
    importance: float


class GraphLink(BaseModel):
    source: int
    target: int
    source_topic: Optional[str]
    target_topic: Optional[str]
    rel_type: str
    label: Optional[str]


class GraphData(BaseModel):
    nodes: list[GraphNode]
    links: list[GraphLink]