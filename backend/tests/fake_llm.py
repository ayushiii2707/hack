"""A minimal fake chat model that emits scripted tool calls, for agent tests.

No network. Drives langchain's create_agent loop deterministically.
"""
from __future__ import annotations

from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class FakeToolCallingModel(BaseChatModel):
    """Returns ``script[i]`` on the i-th call; last entry repeats."""

    script: list[AIMessage]
    calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-tool-calling"

    def bind_tools(self, tools: Any, **kwargs: Any) -> "FakeToolCallingModel":  # noqa: D401
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        idx = min(self.calls, len(self.script) - 1)
        msg = self.script[idx]
        self.calls += 1
        return ChatResult(generations=[ChatGeneration(message=msg)])


def tool_call(name: str, args: dict, call_id: str = "call_1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def final(text: str) -> AIMessage:
    return AIMessage(content=text)
