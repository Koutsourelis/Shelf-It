from .. import config
from .base import Conversation, ToolCall, ToolResult, Turn

__all__ = ["Conversation", "ToolCall", "ToolResult", "Turn", "new_conversation"]


def new_conversation(system: str, tools: list[dict], mock_script=None) -> Conversation:
    provider = config.LLM_PROVIDER
    if provider == "anthropic":
        from .anthropic_llm import AnthropicConversation
        return AnthropicConversation(system, tools)
    if provider == "openai_compat":
        from .openai_llm import OpenAICompatConversation
        return OpenAICompatConversation(system, tools)
    if provider == "mock":
        from .mock_llm import MockConversation
        return MockConversation(system, tools, mock_script)
    raise ValueError(f"Άγνωστο LLM_PROVIDER: {provider!r} (anthropic | openai_compat | mock)")
