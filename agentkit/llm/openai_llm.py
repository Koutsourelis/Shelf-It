"""Οποιοσδήποτε πάροχος με API τύπου OpenAI (OpenAI, Gemini, Groq, OpenRouter, Mistral...).

Ρυθμίζεται με OPENAI_COMPAT_BASE_URL / _API_KEY / _MODEL στο .env.
"""
import json

from openai import AsyncOpenAI

from .. import config
from .base import Conversation, ToolCall, ToolResult, Turn

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=config.OPENAI_COMPAT_API_KEY or None,
            base_url=config.OPENAI_COMPAT_BASE_URL or None,
        )
    return _client


class OpenAICompatConversation(Conversation):
    def __init__(self, system, tools):
        super().__init__(system, tools)
        self.model = config.OPENAI_COMPAT_MODEL
        self.messages: list[dict] = [{"role": "system", "content": system}]
        self.oa_tools = [
            {"type": "function",
             "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
            for t in tools
        ]

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_tool_results(self, results: list[ToolResult]) -> None:
        for r in results:
            content = ("ERROR: " + r.content) if r.is_error else r.content
            self.messages.append({"role": "tool", "tool_call_id": r.id, "content": content})

    async def step(self) -> Turn:
        response = await _get_client().chat.completions.create(
            model=self.model,
            messages=self.messages,
            tools=self.oa_tools or None,
        )
        choice = response.choices[0]
        msg = choice.message
        self.messages.append(msg.model_dump(exclude_none=True))

        turn = Turn(text=msg.content or "")
        if response.usage:
            turn.input_tokens = response.usage.prompt_tokens or 0
            turn.output_tokens = response.usage.completion_tokens or 0
        for call in msg.tool_calls or []:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw": call.function.arguments}
            turn.tool_calls.append(ToolCall(id=call.id, name=call.function.name, input=args))
        if choice.finish_reason == "length":
            turn.stop = "max_tokens"
        elif turn.tool_calls:
            turn.stop = "tools"
        return turn
