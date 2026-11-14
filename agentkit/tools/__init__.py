"""Μητρώο εργαλείων.

Νέο εργαλείο = μία συνάρτηση με το @tool. Παράδειγμα:

    @tool("say_hi", "Χαιρετάει κάποιον.", {"name": {"type": "string", "description": "Όνομα"}})
    async def say_hi(ctx, name: str) -> str:
        return f"Γεια σου {name}"

Το `ctx` (RunContext) δίνει πρόσβαση στην εκτέλεση: ctx.emit(...) για γεγονότα στην
κονσόλα, ctx.notify(...) για μήνυμα στον χρήστη, ctx.artifact(path) για παραγόμενα αρχεία.
Με needs_approval=True ο agent σταματά και περιμένει έγκριση ανθρώπου πριν εκτελέσει. Αντί για True δέχεται και
συνάρτηση f(ορίσματα) -> bool, για έγκριση μόνο πάνω από ένα όριο (π.χ. order_from_warehouse).
"""
from dataclasses import dataclass
from typing import Any, Awaitable, Callable


@dataclass
class Tool:
    name: str
    description: str
    properties: dict[str, Any]
    required: list[str]
    fn: Callable[..., Awaitable[str]]
    needs_approval: bool | Callable[[dict], bool] = False

    def approval_needed(self, args: dict) -> bool:
        return bool(self.needs_approval(args)) if callable(self.needs_approval) else bool(self.needs_approval)

    def schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {"type": "object", "properties": self.properties, "required": self.required},
        }


REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, properties: dict | None = None,
         required: list[str] | None = None, needs_approval: bool | Callable[[dict], bool] = False):
    props = properties or {}

    def deco(fn):
        REGISTRY[name] = Tool(
            name=name, description=description, properties=props,
            required=list(props.keys()) if required is None else required,
            fn=fn, needs_approval=needs_approval,
        )
        return fn

    return deco


def load_all() -> None:
    """Φορτώνει όλα τα αρχεία εργαλείων ώστε να γραφτούν στο μητρώο."""
    from . import browser, core, data, evidence, mail, shelf, verify, web  # noqa: F401
    from . import talker  # noqa: F401  (make_shelf_talker; not in any scenario yet, see tools/talker.py)
