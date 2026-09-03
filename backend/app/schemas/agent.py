"""Agent chat API schemas."""
from __future__ import annotations

from pydantic import BaseModel, Field

from app.agent.agent import AgentResponse


class AgentChatIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)


class UIActionOut(BaseModel):
    type: str
    payload: dict = {}


class AgentChatOut(BaseModel):
    message: str
    state: str
    actions: list[UIActionOut]
    tool_calls: list[str]

    @classmethod
    def from_response(cls, r: AgentResponse) -> AgentChatOut:
        return cls(
            message=r.message,
            state=r.state,
            actions=[UIActionOut(type=a.type, payload=a.payload) for a in r.actions],
            tool_calls=r.tool_calls,
        )
