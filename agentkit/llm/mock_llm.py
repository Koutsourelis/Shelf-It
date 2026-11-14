"""Ψεύτικο μοντέλο: παίζει ένα έτοιμο σενάριο βημάτων χωρίς κλειδί API και χωρίς internet.

Χρησιμεύει για δοκιμές, για ανάπτυξη της κονσόλας χωρίς κόστος και ως έσχατη
εφεδρεία στο demo. Κάθε σενάριο δίνει τα βήματά του ως λίστα (κείμενο, [(εργαλείο, ορίσματα)]).
"""
import asyncio

from .base import Conversation, ToolCall, ToolResult, Turn


class MockConversation(Conversation):
    model = "mock"

    def __init__(self, system, tools, script=None):
        super().__init__(system, tools)
        self.script = list(script or [("Δεν υπάρχει έτοιμο σενάριο για το ψεύτικο μοντέλο.", [])])
        self.i = 0

    def add_user(self, text: str) -> None:
        pass

    def add_tool_results(self, results: list[ToolResult]) -> None:
        pass

    async def step(self) -> Turn:
        await asyncio.sleep(0.6)     # για να φαίνεται φυσικό στην κονσόλα
        if self.i >= len(self.script):
            return Turn(text="Ολοκληρώθηκε.")
        text, calls = self.script[self.i]
        self.i += 1
        turn = Turn(text=text, input_tokens=0, output_tokens=0)
        for n, (name, args) in enumerate(calls):
            turn.tool_calls.append(ToolCall(id=f"mock-{self.i}-{n}", name=name, input=args))
        turn.stop = "tools" if calls else "end"
        return turn
