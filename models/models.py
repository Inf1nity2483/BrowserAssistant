from typing import Optional
from pydantic import BaseModel

class NextAction(BaseModel):
    function: str
    args: dict
    reason: str

class MissingData(BaseModel):
    field: str
    question: str

class AssistantResponse(BaseModel):
    action_sequence: Optional[list[NextAction]] = None
    status: str
    current_goal: str
    missing_data: Optional[list[MissingData]] = None