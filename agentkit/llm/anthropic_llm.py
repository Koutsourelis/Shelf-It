"""Claude μέσω του επίσημου Anthropic SDK."""
import anthropic

from .. import config
from .base import Conversation, ToolCall, ToolResult, Turn

# Ο client διαβάζει μόνος του το ANTHROPIC_API_KEY από το περιβάλλον / .env.
_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic()
    return _client


class AnthropicConversation(Conversation):
    def __init__(self, system, tools):
        super().__init__(system, tools)
        self.model = config.ANTHROPIC_MODEL
        self.messages: list[dict] = []

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def add_tool_results(self, results: list[ToolResult]) -> None:
        # Όλα τα αποτελέσματα πάνε σε ΕΝΑ μήνυμα χρήστη.
        self.messages.append({
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": r.id, "content": r.content, "is_error": r.is_error}
                for r in results
            ],
        })

    async def step(self) -> Turn:
        client = _get_client()
        while True:
            response = await client.messages.create(
                model=self.model,
                max_tokens=16000,
                system=self.system,
                tools=self.tools,
                messages=self.messages,
                cache_control={"type": "ephemeral"},   # φθηνότερα επαναλαμβανόμενα βήματα
            )
            # Κρατάμε ολόκληρο το content (και τα thinking blocks), όχι μόνο το κείμενο.
            self.messages.append({"role": "assistant", "content": response.content})
            if response.stop_reason == "pause_turn":
                continue
            break

        turn = Turn(
            input_tokens=response.usage.input_tokens
            + (response.usage.cache_read_input_tokens or 0)
            + (response.usage.cache_creation_input_tokens or 0),
            output_tokens=response.usage.output_tokens,
        )
        if response.stop_reason == "refusal":
            turn.stop = "refusal"
            turn.text = "Το μοντέλο αρνήθηκε να συνεχίσει αυτό το αίτημα."
            return turn
        for block in response.content:
            if block.type == "text":
                turn.text += block.text
            elif block.type == "tool_use":
                turn.tool_calls.append(ToolCall(id=block.id, name=block.name, input=dict(block.input)))
        if response.stop_reason == "max_tokens":
            turn.stop = "max_tokens"
        elif turn.tool_calls:
            turn.stop = "tools"
        return turn
