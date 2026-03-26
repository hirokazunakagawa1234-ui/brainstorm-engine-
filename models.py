from typing import Optional
from pydantic import BaseModel, Field

TITLE_MAX_LEN = 200
CONTENT_MAX_LEN = 2000


class NodeCreate(BaseModel):
    topic_id: int
    parent_id: Optional[int] = None
    content: str = Field(..., max_length=CONTENT_MAX_LEN)
