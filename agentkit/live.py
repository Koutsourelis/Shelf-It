"""Live παρακολούθηση ραφιού: κάθε frame γίνεται εργασίες, χωρίς κλικ.

Η σελίδα /shelf στέλνει ένα frame κάθε LIVE_INTERVAL_SECONDS στο POST /api/shelf/frame. Για κάθε frame:

    1. αποθήκευση στο workspace/live/         (ΟΧΙ στο workspace/photos: εκεί ο watcher ξεκινά πλήρη εκτέλεση)
    2. σχεδόν ίδιο με το προηγούμενο;  → skip, χωρίς κλήση στο μοντέλο
    3. vision.read_photo                → ανάγνωση (Άτομο Α)
    4. occluded;                        → skip, δεν μετράει στην επιβεβαίωση
    5. findings(): διαφορές από το πλανόγραμμα, καθαρός κώδικας
    6. ίδια ευρήματα σε LIVE_CONFIRM_FRAMES συνεχόμενα frames και διαφορετικά από την τελευταία φορά
         → tasks.sync(): νέες εργασίες, αυτόματη παραγγελία, εργασίες που λύθηκαν κλείνουν
         → ειδοποίηση στον υπάλληλο (Telegram), και εκτέλεση του agent για εξήγηση αν LIVE_START_AGENT=1

Η γρήγορη διαδρομή (βήματα 5 και 6) είναι όλη σε κώδικα και τελειώνει σε κλάσματα του δευτερολέπτου μετά την
ανάγνωση. Ο agent δεν χρειάζεται για να βγει η εργασία ή η παραγγελία· τρέχει δίπλα, για το «show the work».
"""
import asyncio
import io
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any

from . import config, events, tasks
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
        self.prev_thumb: Any = None                  # μικρογραφία του τελευταίου frame που διαβάστηκε
        self.recent: deque = deque(maxlen=max(config.LIVE_CONFIRM_FRAMES, 1))   # υπογραφές ευρημάτων
        self.reported_sig: tuple | None = None       # για ποια ευρήματα έγινε τελευταία φορά sync
        self.last: dict | None = None                # τελευταία απάντηση προς τη σελίδα
        self.agent_run: str | None = None
        self.frames = self.model_calls = 0
        self.busy = False
        tasks.reset()


STATE = LiveState()


# --- 2. ίδιο frame; -----------------------------------------------------------

def _thumb(data: bytes):
    from PIL import Image, ImageOps
    with Image.open(io.BytesIO(data)) as im:
        return ImageOps.exif_transpose(im).convert("L").resize((64, 48))


def _diff(a, b) -> float:
    pa, pb = list(a.tobytes()), list(b.tobytes())
    return sum(abs(x - y) for x, y in zip(pa, pb)) / len(pa)


# --- 5. ευρήματα ----------------------------------------------------------------

def _plan() -> list:
    from .tools.data import run_sql
    _, plan = run_sql("select pl.shelf, pl.level, pl.position, pl.sku, p.name, pl.facings "
                      "from planogram pl join products p using (sku) order by pl.shelf, pl.position")
    return plan


def findings(reading: dict, plan: list) -> list[dict]:
    """Ευρήματα ανά κωδικό, ταξινομημένα κατά προτεραιότητα. Καθαρός κώδικας, χωρίς μοντέλο."""
    seen: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    boxes: dict[str, list] = defaultdict(list)
    for it in reading["items"]:
        if it["sku"]:
            seen[it["sku"]][it["shelf"]] += it["facings"]
            if it["box_2d"]:
                boxes[it["sku"]].append(it["box_2d"])
    planned = {r[3] for r in plan}
    out = []
    for shelf, level, _pos, sku, _name, facings in plan:
        here = seen[sku].get(shelf, 0)
        elsewhere = sorted(s for s in seen[sku] if s != shelf)
        if here == 0 and elsewhere:
            out.append({"type": "misplaced", "sku": sku, "shelf": shelf, "level": level, "found_on": elsewhere,
                        "boxes": boxes[sku]})
        elif here == 0:
            # Για την εικόνα της εργασίας: τα κενά που είδε το μοντέλο στο ίδιο ράφι.
            holes = [g["box_2d"] for g in reading.get("gaps") or [] if g["shelf"] == shelf]
            out.append({"type": "missing", "sku": sku, "shelf": shelf, "level": level, "need": facings, "boxes": holes})
        elif here < facings:
            out.append({"type": "low", "sku": sku, "shelf": shelf, "level": level, "need": facings - here,
                        "boxes": boxes[sku]})
    for it in reading["items"]:
        if not it["sku"] or it["sku"] not in planned:
            out.append({"type": "unknown", "sku": it["sku"], "shelf": it["shelf"], "label": it["label"],
                        "boxes": [it["box_2d"]] if it["box_2d"] else []})
    for v in reading.get("visual_issues") or []:
        out.append({"type": "visual", "sku": None, "shelf": v["shelf"], "label": v["type"], "detail": v["detail"],
                    "boxes": []})
    # Τα κενά δεν γίνονται χωριστή εργασία (καλύπτονται από τα «λείπει»), αλλά ζωγραφίζονται στη σελίδα.
    out.sort(key=lambda f: (PRIORITY[f["type"]], f["shelf"]))
    for i, f in enumerate(out, 1):
        f["priority"] = i
    return out


def _signature(found: list[dict]) -> tuple:
    """Τι μετράει για «άλλαξε κάτι;». Οι προσόψεις μπαίνουν, τα κουτιά όχι (αλλάζουν λίγο σε κάθε frame)."""
    return tuple(sorted((f["type"], f["sku"] or f.get("label", ""), f["shelf"], f.get("need", 0)) for f in found))


# --- 6. εργασίες, ειδοποίηση, agent ------------------------------------------------

def _notify_text(changed: dict) -> str:
    lines = []
    for t in changed["new"]:
        order = t.get("order") or {}
        lines.append(f"{t['priority']}. {t['text']}" + (f" · παραγγελία {order['order_no']}" if order.get("order_no") else ""))
        if t.get("needs_approval"):
            lines.append("   ⚠ θέλει έγκριση στην οθόνη του ραφιού: " + t["needs_approval"]["why"])
    for t in changed["resolved"]:
        lines.append(f"✓ Έγινε: {t['text']}")
    open_now = tasks.open_tasks()
    head = f"Ράφι: {len(open_now)} εργασίες" if open_now else "Ράφι σωστό ✓"
    return head + ("\n" + "\n".join(lines) if lines else "")


async def _notify(text: str) -> None:
    from . import telegram
    notifier = telegram.default_notifier()
    if not notifier:
        return
    try:
        await notifier("notify", text)
    except Exception as e:
        events.emit("system", "log", text=f"Telegram: {e}")


async def _act(frame: Path, found: list[dict], sig: tuple) -> dict:
    """Η γρήγορη διαδρομή: εργασίες και παραγγελίες σε κώδικα. Ο agent είναι προαιρετικός."""
    from . import agent
    changed = await asyncio.to_thread(tasks.sync, found, frame)
    STATE.reported_sig = sig
    if changed["new"] or changed["resolved"]:
        await _notify(_notify_text(changed))
    events.emit("system", "live_report", frame=frame.name, open=len(tasks.open_tasks()),
                new=len(changed["new"]), resolved=len(changed["resolved"]))

    if changed["new"] and config.LIVE_START_AGENT:
        running = STATE.agent_run and agent.RUNS.get(STATE.agent_run, {}).get("status") == "running"
        if not running:
            rel = frame.relative_to(config.ROOT).as_posix()
            listing = "\n".join(f"- {t['text']}" for t in changed["new"])
            STATE.agent_run = agent.start_run(
                f"Η κάμερα του ραφιού βρήκε νέα ευρήματα στη φωτογραφία {rel}. Ο κώδικας έχει ήδη στείλει στον "
                f"υπάλληλο αυτές τις εργασίες και έχει κάνει τις παραγγελίες:\n{listing}", "live", source="camera",
                notifier=None)
    return changed


# --- είσοδος ------------------------------------------------------------------

def _save(data: bytes) -> Path:
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = LIVE_DIR / f"frame_{time.strftime('%H%M%S')}_{STATE.frames:04d}.jpg"
    path.write_bytes(data)
    old = sorted(LIVE_DIR.glob("frame_*.jpg"))
    for p in old[:-KEEP_FRAMES]:
        p.unlink(missing_ok=True)
    return path


async def process_frame(data: bytes, force: bool = False, single: bool = False) -> dict:
    """Ένα frame από τη σελίδα του ραφιού. Επιστρέφει ό,τι χρειάζεται η σελίδα για να ζωγραφίσει.

    single: σκόπιμη φωτογραφία από το κινητό (/capture). Διαβάζεται πάντα και μετράει ως επιβεβαιωμένη μόνη της.
    """
    if STATE.busy:
        return {**status(), "status": "busy", "detail": "Το προηγούμενο frame διαβάζεται ακόμη"}
    STATE.busy = True
    try:
        STATE.frames += 1
        thumb = await asyncio.to_thread(_thumb, data)
        if not (force or single) and STATE.prev_thumb is not None and STATE.last:
            d = _diff(thumb, STATE.prev_thumb)
            if d < config.LIVE_DIFF_THRESHOLD:
                return {**status(), "status": "unchanged", "diff": round(d, 1)}
        frame = await asyncio.to_thread(_save, data)
        t0 = time.time()
        reading = await read_photo(frame)
        STATE.model_calls += 1
        seconds = round(time.time() - t0, 1)
        if reading["occluded"]:
            events.emit("system", "live_frame", frame=frame.name, status="occluded", seconds=seconds)
            return {**status(), "status": "occluded", "seconds": seconds,
                    "detail": "Κάτι κρύβει το ράφι· το frame δεν μετράει"}
        STATE.prev_thumb = thumb
        found = findings(reading, await asyncio.to_thread(_plan))
        sig = _signature(found)
        STATE.recent.extend([sig] * (STATE.recent.maxlen if single else 1))
        confirmed = len(STATE.recent) == STATE.recent.maxlen and len(set(STATE.recent)) == 1
        acted = False
        if confirmed and sig != STATE.reported_sig:
            await _act(frame, found, sig)
            acted = True
        STATE.last = {
            "status": "acted" if acted else ("confirmed" if confirmed else "pending"),
            "frame": frame.name, "seconds": seconds, "findings": found,
            "items": reading["items"], "gaps": reading["gaps"],
            "confirm": f"{sum(1 for s in STATE.recent if s == sig)}/{STATE.recent.maxlen}",
        }
        events.emit("system", "live_frame", frame=frame.name, status=STATE.last["status"],
                    findings=len(found), seconds=seconds)
        return status()
    finally:
        STATE.busy = False


def status() -> dict:
    """Όλη η κατάσταση που χρειάζονται οι σελίδες, και όταν δεν έχει έρθει ακόμη frame."""
    return {"interval": config.LIVE_INTERVAL_SECONDS, "confirm_frames": config.LIVE_CONFIRM_FRAMES,
            "provider": config.vision_provider(), "model": config.vision_model(),
            "auto_order": config.AUTO_ORDER, "max_cases": config.AUTO_ORDER_MAX_CASES,
            "max_eur": config.AUTO_ORDER_MAX_EUR, "frames": STATE.frames, "model_calls": STATE.model_calls,
            "agent_run": STATE.agent_run,
            **(STATE.last or {"status": "idle", "findings": [], "items": [], "gaps": []}), **tasks.summary()}


async def reminder_loop() -> None:
    """Εργασίες που μένουν ανοιχτές πολλή ώρα: μία υπενθύμιση ανά TASK_REMINDER_MINUTES."""
    while True:
        await asyncio.sleep(60)
        try:
            late = tasks.stale()
            if late:
                tasks.mark_reminded(late)
                await _notify("Υπενθύμιση, εκκρεμούν:\n" + "\n".join(f"· {t['text']}" for t in late))
        except Exception as e:
            events.emit("system", "log", text=f"Υπενθύμιση: {type(e).__name__}: {e}")
