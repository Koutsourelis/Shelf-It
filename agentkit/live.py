"""Live παρακολούθηση ραφιού. Κάτοχος: Άτομο Β (ενσωμάτωση).

Η σελίδα /live στέλνει ένα frame κάθε LIVE_INTERVAL_SECONDS στο POST /api/shelf/frame. Για κάθε frame:

    1. αποθήκευση στο workspace/live/         (ΟΧΙ στο workspace/photos: εκεί ο watcher ξεκινά πλήρη εκτέλεση)
    2. σχεδόν ίδιο με το προηγούμενο;  → skip, χωρίς κλήση στο μοντέλο
    3. vision.read_photo                → ανάγνωση (Άτομο Α)
    4. occluded;                        → skip, δεν μετράει στην επιβεβαίωση
    5. findings(): διαφορές από το πλανόγραμμα, καθαρός κώδικας
    6. ίδια ευρήματα σε LIVE_CONFIRM_FRAMES συνεχόμενα frames και διαφορετικά από την τελευταία αναφορά
         → αναφορά στον αποθηκάριο (κονσόλα + Telegram) και, αν LIVE_START_AGENT, εκτέλεση του agent
           για αναπλήρωση/παραγγελία πάνω στο ίδιο frame (το read_photo το έχει σε cache, άρα όχι 2η κλήση).

Τα findings εδώ είναι ελαφριά έκδοση του check_planogram, χωρίς βάση και χωρίς ζωγραφική, ώστε το live loop να μη
συγκρούεται με εκτέλεση του agent που γράφει στους πίνακες shelf_*.
"""
import asyncio
import io
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from . import config, events
from .vision import read_photo

LIVE_DIR = config.WORKSPACE / "live"
KEEP_FRAMES = 200                       # τα παλιότερα frames σβήνονται
LABEL = {"missing": "Λείπει", "low": "Λίγες προσόψεις", "misplaced": "Λάθος ράφι", "unknown": "Εκτός πλανογράμματος",
         "gap": "Κενό", "visual": "Παρουσίαση"}
PRIORITY = {"missing": 1, "misplaced": 2, "low": 3, "gap": 4, "unknown": 5, "visual": 6}


class LiveState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.prev_thumb: Any = None                       # μικρογραφία του τελευταίου frame που διαβάστηκε
        self.recent: deque = deque(maxlen=max(config.LIVE_CONFIRM_FRAMES, 1))   # υπογραφές ευρημάτων
        self.reported_sig: tuple | None = None       # τι αναφέρθηκε τελευταία φορά
        self.last: dict | None = None                # τελευταία απάντηση προς τη σελίδα
        self.agent_run: str | None = None
        self.frames = self.model_calls = 0
        self.busy = False


STATE = LiveState()


# --- 2. ίδιο frame; -----------------------------------------------------------

def _thumb(data: bytes):
    from PIL import Image, ImageOps
    with Image.open(io.BytesIO(data)) as im:
        return ImageOps.exif_transpose(im).convert("L").resize((64, 48))


def _diff(a, b) -> float:
    pa, pb = a.getdata(), b.getdata()
    return sum(abs(x - y) for x, y in zip(pa, pb)) / len(pa)


# --- 5. ευρήματα ----------------------------------------------------------------

def _plan() -> tuple[list, dict]:
    from .tools.data import run_sql
    _, plan = run_sql("select pl.shelf, pl.level, pl.position, pl.sku, p.name, pl.facings "
                      "from planogram pl join products p using (sku) order by pl.shelf, pl.position")
    _, names = run_sql("select sku, name from products")
    return plan, dict(names)


def findings(reading: dict, plan: list, names: dict) -> list[dict]:
    """Ευρήματα ανά κωδικό, ταξινομημένα κατά προτεραιότητα. Κάθε εύρημα έχει και έτοιμο μήνυμα για τον αποθηκάριο."""
    seen: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    boxes: dict[str, list] = defaultdict(list)
    for it in reading["items"]:
        if it["sku"]:
            seen[it["sku"]][it["shelf"]] += it["facings"]
            if it["box_2d"]:
                boxes[it["sku"]].append(it["box_2d"])
    planned = {r[3] for r in plan}
    out = []
    for shelf, level, _pos, sku, name, facings in plan:
        here = seen[sku].get(shelf, 0)
        elsewhere = sorted(s for s in seen[sku] if s != shelf)
        if here == 0 and elsewhere:
            out.append({"type": "misplaced", "sku": sku, "shelf": shelf, "found_on": elsewhere, "boxes": boxes[sku],
                        "msg": f"Μετακίνησε {name} ({sku}) από το ράφι {', '.join(map(str, elsewhere))} στο ράφι {shelf}"})
        elif here == 0:
            out.append({"type": "missing", "sku": sku, "shelf": shelf, "need": facings, "boxes": [],
                        "msg": f"Λείπει {name} ({sku}) από το ράφι {shelf}"
                               + (" (ύψος ματιών)" if level == "eye" else "") + f": φέρε {facings} προσόψεις"})
        elif here < facings:
            out.append({"type": "low", "sku": sku, "shelf": shelf, "need": facings - here, "boxes": boxes[sku],
                        "msg": f"Συμπλήρωσε {name} ({sku}) στο ράφι {shelf}: {here} από {facings} προσόψεις"})
    for it in reading["items"]:
        if not it["sku"] or it["sku"] not in planned:
            out.append({"type": "unknown", "sku": it["sku"], "shelf": it["shelf"],
                        "boxes": [it["box_2d"]] if it["box_2d"] else [],
                        "msg": f"Βγάλε «{it['label']}» από το ράφι {it['shelf']}: δεν ανήκει στο πλανόγραμμα"})
    for v in reading.get("visual_issues") or []:
        out.append({"type": "visual", "sku": None, "shelf": v["shelf"], "boxes": [],
                    "msg": f"Ράφι {v['shelf']}: {v['detail']}"})
    # Τα κενά δεν γίνονται χωριστή εργασία (καλύπτονται από τα «λείπει»), αλλά ζωγραφίζονται στη σελίδα.
    out.sort(key=lambda f: (PRIORITY[f["type"]], f["shelf"]))
    for i, f in enumerate(out, 1):
        f["priority"] = i
    return out


def _signature(found: list[dict]) -> tuple:
    """Τι μετράει για «άλλαξε κάτι;». Οι προσόψεις μπαίνουν, τα κουτιά όχι (αλλάζουν λίγο σε κάθε frame)."""
    return tuple(sorted((f["type"], f["sku"] or "", f["shelf"], f.get("need", 0)) for f in found))


# --- 6. αναφορά ----------------------------------------------------------------

def report_text(found: list[dict], resolved: int) -> str:
    if not found:
        return "Το ράφι είναι σωστό. Όλα τα προϊόντα στη θέση τους." + (f" (διορθώθηκαν {resolved})" if resolved else "")
    lines = [f"Εργασίες για το ράφι ({len(found)}):"] + [f"{f['priority']}. {f['msg']}" for f in found]
    return "\n".join(lines)


async def _report(frame: Path, found: list[dict], sig: tuple) -> None:
    from . import agent, telegram
    resolved = len(set(STATE.reported_sig or ()) - set(sig))
    text = report_text(found, resolved)
    events.emit("system", "live_report", frame=frame.name, findings=found, text=text)
    events.emit("system", "demo", text=text.splitlines()[0])        # η κονσόλα δείχνει toast
    notifier = telegram.default_notifier()
    if notifier:
        try:
            await notifier("notify", text)
        except Exception as e:
            events.emit("system", "log", text=f"Telegram: {e}")
    STATE.reported_sig = sig
    if found and config.LIVE_START_AGENT:
        running = STATE.agent_run and agent.RUNS.get(STATE.agent_run, {}).get("status") == "running"
        if not running:
            rel = frame.relative_to(config.ROOT).as_posix()
            STATE.agent_run = agent.start_run(
                f"Η κάμερα του ραφιού βρήκε νέα ευρήματα στη φωτογραφία {rel}. Έλεγξε το ράφι και κάνε ό,τι χρειάζεται.",
                "shelf", source="camera", notifier=notifier)


# --- είσοδος ------------------------------------------------------------------

def _save(data: bytes) -> Path:
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = LIVE_DIR / f"frame_{time.strftime('%H%M%S')}_{STATE.frames:04d}.jpg"
    path.write_bytes(data)
    old = sorted(LIVE_DIR.glob("frame_*.jpg"))
    for p in old[:-KEEP_FRAMES]:
        p.unlink(missing_ok=True)
    return path


async def process_frame(data: bytes, force: bool = False) -> dict:
    """Ένα frame από τη σελίδα /live. Επιστρέφει ό,τι χρειάζεται η σελίδα για να ζωγραφίσει."""
    if STATE.busy:
        return {"status": "busy", "detail": "Το προηγούμενο frame διαβάζεται ακόμη"}
    STATE.busy = True
    try:
        STATE.frames += 1
        thumb = await asyncio.to_thread(_thumb, data)
        if not force and STATE.prev_thumb is not None and STATE.last:
            d = _diff(thumb, STATE.prev_thumb)
            if d < config.LIVE_DIFF_THRESHOLD:
                return {**STATE.last, "status": "unchanged", "diff": round(d, 1)}
        frame = await asyncio.to_thread(_save, data)
        t0 = time.time()
        reading = await read_photo(frame)
        STATE.model_calls += 1
        seconds = round(time.time() - t0, 1)
        if reading["occluded"]:
            events.emit("system", "live_frame", frame=frame.name, status="occluded", seconds=seconds)
            return {"status": "occluded", "frame": frame.name, "seconds": seconds,
                    "detail": "Κάτι κρύβει το ράφι· το frame δεν μετράει"}
        STATE.prev_thumb = thumb
        plan, names = await asyncio.to_thread(_plan)
        found = findings(reading, plan, names)
        sig = _signature(found)
        STATE.recent.append(sig)
        confirmed = len(STATE.recent) == STATE.recent.maxlen and len(set(STATE.recent)) == 1
        reported = False
        if confirmed and sig != STATE.reported_sig:
            await _report(frame, found, sig)
            reported = True
        STATE.last = {
            "status": "reported" if reported else ("confirmed" if confirmed else "pending"),
            "frame": frame.name, "seconds": seconds, "shelf_ok": not found,
            "findings": found, "items": reading["items"], "gaps": reading["gaps"],
            "confirm": f"{sum(1 for s in STATE.recent if s == sig)}/{STATE.recent.maxlen}",
            "agent_run": STATE.agent_run,
        }
        events.emit("system", "live_frame", frame=frame.name, status=STATE.last["status"],
                    findings=len(found), seconds=seconds)
        return STATE.last
    finally:
        STATE.busy = False


def status() -> dict:
    return {"interval": config.LIVE_INTERVAL_SECONDS, "confirm_frames": config.LIVE_CONFIRM_FRAMES,
            "provider": config.LLM_PROVIDER, "frames": STATE.frames, "model_calls": STATE.model_calls,
            "last": STATE.last}
