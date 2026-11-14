"""Ροή γεγονότων: ό,τι κάνει ο agent γίνεται γεγονός που βλέπει ζωντανά η κονσόλα.

Κάθε γεγονός γράφεται και σε αρχείο runs/<run_id>.jsonl, ώστε μια εκτέλεση να
μπορεί να ξαναπαιχτεί (replay) αν στο demo πέσει το internet.
"""
import asyncio
import json
import time
from typing import Any

from . import config

_subscribers: set[asyncio.Queue] = set()
_history: list[dict] = []          # όλα τα γεγονότα της τρέχουσας συνεδρίας του server
_MAX_HISTORY = 5000


def emit(run_id: str, type: str, **data: Any) -> dict:
    event = {"run_id": run_id, "type": type, "ts": time.time(), **data}
    _history.append(event)
    if len(_history) > _MAX_HISTORY:
        del _history[: len(_history) - _MAX_HISTORY]
    if not data.get("replay"):
        with open(config.RUNS_DIR / f"{run_id}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False, default=str) + "\n")
    for q in list(_subscribers):
        q.put_nowait(event)
    return event


def history() -> list[dict]:
    return list(_history)


def subscribe() -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)


def load_run(run_id: str) -> list[dict]:
    path = config.RUNS_DIR / f"{run_id}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def replay(run_id: str, speed: float = 1.0, max_gap: float = 2.5) -> str:
    """Ξαναπαίζει μια αποθηκευμένη εκτέλεση με τον αρχικό ρυθμό (με όριο στις παύσεις)."""
    events = load_run(run_id)
    new_id = f"{run_id}-replay-{int(time.time()) % 100000}"
    prev_ts = None
    for ev in events:
        if prev_ts is not None:
            await asyncio.sleep(min(max(ev["ts"] - prev_ts, 0) / speed, max_gap))
        prev_ts = ev["ts"]
        data = {k: v for k, v in ev.items() if k not in ("run_id", "type", "ts")}
        if ev["type"] == "approval_request":
            data["resolved"] = True      # στο replay δεν περιμένουμε έγκριση
        emit(new_id, ev["type"], replay=True, **data)
    return new_id
