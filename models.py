from typing import Optional
from pydantic import BaseModel, Field

TITLE_MAX_LEN = 200
CONTENT_MAX_LEN = 2000


class NodeCreate(BaseModel):
    topic_id: int = Field(..., ge=1)
    parent_id: Optional[int] = None
    content: str = Field(..., min_length=1, max_length=CONTENT_MAX_LEN)
