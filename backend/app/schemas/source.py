from pydantic import BaseModel, ConfigDict
from datetime import datetime


class SourceOut(BaseModel):
    id: int
    filename: str
    file_type: str
    imported_at: datetime
    node_count: int

    model_config = ConfigDict(from_attributes=True)
