"""Conversational agent endpoint (session-scoped).

    POST /agent/chat  { message }  ->  { message, state, actions, tool_calls }

The session comes from the bearer token, never the request body.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.agent.agent import run_agent
from app.api.deps import require_session
from app.database.database import get_db
from app.models.session import Session as ShopSession
from app.schemas.agent import AgentChatIn, AgentChatOut

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/chat", response_model=AgentChatOut, summary="Talk to Checkout Copilot")
def chat(
    body: AgentChatIn,
    session: ShopSession = Depends(require_session),
    db: Session = Depends(get_db),
):
    result = run_agent(db, session_id=session.id, message=body.message)
    return AgentChatOut.from_response(result)
