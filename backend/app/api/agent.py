"""Conversational agent endpoint.

    POST /agent/chat  { session_id, message }  ->  { message, state, actions, tool_calls }
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agent.agent import run_agent
from app.database.database import get_db
from app.schemas.agent import AgentChatIn, AgentChatOut

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/chat", response_model=AgentChatOut, summary="Talk to Checkout Copilot")
def chat(body: AgentChatIn, db: Session = Depends(get_db)):
    result = run_agent(db, session_id=body.session_id, message=body.message)
    return AgentChatOut.from_response(result)
