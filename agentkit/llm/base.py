"""Κοινή διεπαφή για όλους τους παρόχους μοντέλου.

Ο agent μιλάει μόνο με αυτή τη διεπαφή. Κάθε πάροχος κρατάει το ιστορικό της
συνομιλίας στη δική του μορφή, οπότε η αλλαγή παρόχου είναι μία ρύθμιση στο .env.
"""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class ToolResult:
    id: str
    content: str
    is_error: bool = False


@dataclass
class Turn:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop: str = "end"            # end | tools | max_tokens | refusal
    input_tokens: int = 0
    output_tokens: int = 0


class Conversation:
    """Μία συνομιλία με το μοντέλο. `tools` = λίστα {name, description, input_schema}."""

    model: str = ""

    def __init__(self, system: str, tools: list[dict[str, Any]]):
        self.system = system
        self.tools = tools

    def add_user(self, text: str) -> None:
        raise NotImplementedError

    def add_tool_results(self, results: list[ToolResult]) -> None:
        raise NotImplementedError

    async def step(self) -> Turn:
        raise NotImplementedError
