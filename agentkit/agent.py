"""Ο βρόχος του agent: στόχος → πλάνο → εργαλεία → αποτέλεσμα.

Κάθε βήμα γίνεται γεγονός (events.emit) που βλέπει ζωντανά η κονσόλα.
"""
import asyncio
import json
import time
import traceback
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from . import config, events
from .llm import ToolCall, ToolResult, new_conversation
from . import scenarios
from .scenarios import Scenario
from .tools import REGISTRY, load_all

load_all()

RUNS: dict[str, dict] = {}                         # run_id -> σύνοψη εκτέλεσης
_approvals: dict[str, asyncio.Future] = {}         # approval_id -> απάντηση (True/False)
_tasks: dict[str, asyncio.Task] = {}

Notifier = Callable[[str, str], Awaitable[None]]   # (είδος, κείμενο)


@dataclass
class RunContext:
    run_id: str
    scenario: Scenario
    notifier: Notifier | None = None
    artifacts: list[str] = field(default_factory=list)
    trail: list[dict] = field(default_factory=list)

    def emit(self, type: str, **data) -> None:
        events.emit(self.run_id, type, **data)

    async def notify(self, text: str, kind: str = "notify") -> None:
        self.emit("notify", text=text)
        if self.notifier:
            try:
                await self.notifier(kind, text)
            except Exception as e:
                self.emit("log", text=f"Αποτυχία ειδοποίησης: {e}")

    def artifact(self, path: Path) -> None:
        rel = Path(path).resolve().relative_to(config.WORKSPACE.resolve()).as_posix()
        if rel not in self.artifacts:
            self.artifacts.append(rel)
        self.emit("artifact", file=rel)

    def audit(self, kind: str, **data) -> None:
        """Ίχνος ελέγχου: από πού ήρθε κάθε αριθμός (εξαγωγή από έγγραφο ή υπολογισμός με κώδικα)."""
        self.trail.append({"kind": kind, **data})
        self.emit("audit", kind=kind, **data)

    def save_audit(self) -> None:
        if not self.trail:
            return
        path = config.WORKSPACE / f"audit_{self.run_id}.json"
        path.write_text(json.dumps(self.trail, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        self.artifact(path)

    async def ask_approval(self, title: str, details: dict) -> bool:
        if config.AUTO_APPROVE:
            self.emit("approval_request", id="auto", title=title, details=details, resolved=True, approved=True)
            return True
        approval_id = uuid.uuid4().hex[:8]
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        _approvals[approval_id] = fut
        self.emit("approval_request", id=approval_id, title=title, details=details)
        if self.notifier:
            await self.notifier("approval:" + approval_id, f"Χρειάζεται έγκριση: {title}\n{_short(details)}")
        try:
            approved = await asyncio.wait_for(fut, timeout=600)
        except asyncio.TimeoutError:
            approved = False
        finally:
            _approvals.pop(approval_id, None)
        self.emit("approval_result", id=approval_id, approved=approved)
        return approved


def resolve_approval(approval_id: str, approved: bool) -> bool:
    fut = _approvals.get(approval_id)
    if fut is None or fut.done():
        return False
    fut.set_result(approved)
    return True


def _short(obj, limit: int = 600) -> str:
    text = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


async def _call_tool(ctx: RunContext, call: ToolCall) -> ToolResult:
    tool = REGISTRY.get(call.name)
    if tool is None or call.name not in ctx.scenario.tools:
        return ToolResult(call.id, f"Άγνωστο εργαλείο: {call.name}", is_error=True)
    ctx.emit("tool_call", id=call.id, name=call.name, input=call.input)
    started = time.time()
    try:
        if tool.approval_needed(call.input) and not await ctx.ask_approval(f"{call.name}", call.input):
            result = ToolResult(call.id, "Ο χρήστης ΔΕΝ ενέκρινε αυτή την ενέργεια. Μην την επαναλάβεις· "
                                         "συνέχισε χωρίς αυτήν ή ρώτα τι να αλλάξεις.", is_error=True)
        else:
            out = await asyncio.wait_for(tool.fn(ctx, **call.input), timeout=120)
            result = ToolResult(call.id, str(out))
    except Exception as e:
        # Το σφάλμα επιστρέφει στο μοντέλο ώστε να δοκιμάσει αλλιώς, δεν ρίχνει την εκτέλεση.
        result = ToolResult(call.id, f"{type(e).__name__}: {e}", is_error=True)
    ctx.emit("tool_result", id=call.id, name=call.name, output=_short(result.content, 4000),
             is_error=result.is_error, seconds=round(time.time() - started, 2))
    return result


async def run_agent(goal: str, scenario_name: str | None = None, source: str = "console",
                    notifier: Notifier | None = None, run_id: str | None = None) -> str:
    scenario = scenarios.get(scenario_name)
    run_id = run_id or time.strftime("%H%M%S") + "-" + uuid.uuid4().hex[:4]
    ctx = RunContext(run_id=run_id, scenario=scenario, notifier=notifier)
    RUNS[run_id] = {"run_id": run_id, "goal": goal, "scenario": scenario.name, "source": source,
                    "status": "running", "started": time.time()}

    tools = [REGISTRY[name].schema() for name in scenario.tools if name in REGISTRY]
    conv = new_conversation(scenario.system_prompt(), tools, mock_script=scenario.mock_script)
    ctx.emit("run_start", goal=goal, scenario=scenario.name, scenario_title=scenario.title,
             source=source, model=conv.model)

    final, status = "", "done"
    tokens_in = tokens_out = 0
    try:
        conv.add_user(goal)
        for step in range(1, config.MAX_STEPS + 1):
            turn = await conv.step()
            tokens_in += turn.input_tokens
            tokens_out += turn.output_tokens
            ctx.emit("usage", input_tokens=tokens_in, output_tokens=tokens_out, steps=step)
            if turn.text.strip() and turn.tool_calls:
                ctx.emit("thought", text=turn.text.strip())
            if not turn.tool_calls:
                final = turn.text.strip() or "(χωρίς τελικό κείμενο)"
                if turn.stop in ("refusal", "max_tokens"):
                    status = turn.stop
                break
            # Τα εργαλεία ενός βήματος τρέχουν με τη σειρά (ο browser και οι εγκρίσεις δεν θέλουν παραλληλία).
            results = [await _call_tool(ctx, call) for call in turn.tool_calls]
            conv.add_tool_results(results)
        else:
            status = "max_steps"
            final = f"Σταμάτησα στα {config.MAX_STEPS} βήματα χωρίς να ολοκληρώσω."
    except asyncio.CancelledError:
        status, final = "cancelled", "Η εκτέλεση ακυρώθηκε."
    except Exception as e:
        status, final = "error", f"Σφάλμα: {type(e).__name__}: {e}"
        ctx.emit("log", text=traceback.format_exc()[-1500:])
    finally:
        from .tools import browser
        await browser.close_run(run_id)
        ctx.save_audit()

    RUNS[run_id].update(status=status, final=final, finished=time.time(), artifacts=ctx.artifacts)
    ctx.emit("run_end", status=status, final=final, artifacts=ctx.artifacts,
             seconds=round(time.time() - RUNS[run_id]["started"], 1))
    if notifier:
        try:
            await notifier("final", final)
        except Exception:
            pass
    return final


def start_run(goal: str, scenario_name: str | None = None, source: str = "console",
              notifier: Notifier | None = None) -> str:
    """Ξεκινά εκτέλεση στο παρασκήνιο και επιστρέφει αμέσως το run_id."""
    run_id = time.strftime("%H%M%S") + "-" + uuid.uuid4().hex[:4]
    task = asyncio.create_task(run_agent(goal, scenario_name, source, notifier, run_id))
    _tasks[run_id] = task
    task.add_done_callback(lambda _t: _tasks.pop(run_id, None))
    return run_id


def cancel_run(run_id: str) -> bool:
    task = _tasks.get(run_id)
    if task is None:
        return False
    task.cancel()
    return True
