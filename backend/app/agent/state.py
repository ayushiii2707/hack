"""Lightweight agent state.

The database stays authoritative – this only carries what the conversation
turn needs. Chat history is persisted as JSON on the Session row.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

MAX_HISTORY_MESSAGES = 20


@dataclass
class ChatTurn:
    role: str  # "user" | "assistant"
    content: str


@dataclass
class AgentState:
    session_id: str
    cart_id: str
    current_state: str
    history: list[ChatTurn] = field(default_factory=list)

    @staticmethod
    def load_history(raw: str | None) -> list[ChatTurn]:
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return []
        return [
            ChatTurn(role=str(m.get("role", "user")), content=str(m.get("content", "")))
            for m in data
            if m.get("content")
        ][-MAX_HISTORY_MESSAGES:]

    @staticmethod
    def dump_history(history: list[ChatTurn]) -> str:
        trimmed = history[-MAX_HISTORY_MESSAGES:]
        return json.dumps([{"role": t.role, "content": t.content} for t in trimmed])
