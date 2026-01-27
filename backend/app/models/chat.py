from typing import Optional
from pydantic import BaseModel

class ChatRequest(BaseModel):
    message: str

class ChatResponse(BaseModel):
    response: str
    code: str
    image: Optional[str] = None
