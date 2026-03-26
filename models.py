from typing import Optional
from pydantic import BaseModel


class NodeCreate(BaseModel):
    topic_id: int
    parent_id: Optional[int] = None
    content: str
