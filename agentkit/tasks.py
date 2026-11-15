"""Εργασίες ραφιού: από το εύρημα της κάμερας ως το «έγινε», χωρίς κλικ.

Κάθε εύρημα γίνεται εργασία με σταθερή ταυτότητα (τύπος + κωδικός + ράφι), ώστε το ίδιο πρόβλημα να μη
δημιουργεί δεύτερη εργασία σε κάθε frame:

    ανοιχτή ──(ο υπάλληλος πατά «το κάνω»)──► σε εξέλιξη ──┐
       └──────────────────────────────────────────────────►├──► έκλεισε (η κάμερα δεν το βλέπει πια)
                                                           └──► ακυρώθηκε (άλλαξε το εύρημα)

Η κάμερα κλείνει τις εργασίες, όχι ο άνθρωπος. Το «το κάνω» είναι μόνο ένδειξη ότι κάποιος το ανέλαβε.

Αυτόματη παραγγελία: όταν λείπει απόθεμα από την αποθήκη του καταστήματος, η παραγγελία καταχωρείται
μόνη της αν μένει κάτω από τα όρια του .env (AUTO_ORDER_MAX_EUR, AUTO_ORDER_MAX_CASES). Πάνω από τα
όρια φτιάχνεται εργασία έγκρισης για τον υπεύθυνο. Κάθε παραγγελία γράφεται στο ιστορικό.
"""
import math
import time
from pathlib import Path

from . import config, events

DEFAULT_DEPTH = 3                      # πόσα τεμάχια πίσω από μία πρόσοψη, όταν δεν το ξέρουμε
TASKS: dict[str, dict] = {}            # task_id -> εργασία (in-memory, όπως όλη η κατάσταση του demo)
HISTORY: list[dict] = []               # χρονολόγιο για την οθόνη: τι είδε και τι έκανε ο agent
PROPOSALS: list[dict] = []             # προτάσεις διάταξης που αποφάσισε ο agent (εργαλείο propose_move)
MAX_PROPOSALS = 3
OPEN = ("open", "in_progress")
VERB = {"restock": "Φέρε", "relocate": "Μετακίνησε", "remove": "Βγάλε", "tidy": "Τακτοποίησε"}
# εύρημα του live.findings() -> τύπος εργασίας
KIND = {"missing": "restock", "low": "restock", "gap": "restock", "misplaced": "relocate", "unknown": "remove",
        "visual": "tidy"}


def _now() -> float:
    return time.time()


def log(kind: str, text: str, **data) -> dict:
    """Μία γραμμή στο χρονολόγιο. Φαίνεται στην οθόνη του ραφιού και στο /dev."""
    entry = {"ts": _now(), "kind": kind, "text": text, **data}
    HISTORY.append(entry)
    del HISTORY[:-200]
    events.emit("system", "shelf_log", **entry)
    return entry


def reset() -> None:
    TASKS.clear()
    HISTORY.clear()
    PROPOSALS.clear()


# --- Προτάσεις διάταξης (τις αποφασίζει ο agent, τους αριθμούς τους βγάζει ο κώδικας) ---

def cancel_open() -> int:
    """Η κάμερα δείχνει άλλο ράφι: οι ανοιχτές εργασίες του προηγούμενου ακυρώνονται, δεν «έγιναν»."""
    n = 0
    for task in TASKS.values():
        if task["status"] in OPEN:
            task.update(status="cancelled", done=_now(), needs_approval=None)
            n += 1
    PROPOSALS.clear()
    return n


def clear_proposals() -> None:
    PROPOSALS.clear()


def add_proposal(proposal: dict) -> dict:
    """Καταχωρεί πρόταση του agent για την οθόνη. Ίδια πρόταση δεύτερη φορά αντικαθιστά την πρώτη."""
    p = {"id": f"{proposal['kind']}:{proposal['a']['sku']}:{proposal['b']['sku']}", "ts": _now(), **proposal}
    PROPOSALS[:] = [x for x in PROPOSALS if x["id"] != p["id"]][-(MAX_PROPOSALS - 1):] + [p]
    log("proposal", f"Πρόταση διάταξης: {p['text']}", proposal=p["id"])
    return p


def update_proposal_feedback(recommendation_id: str, **fields) -> dict | None:
    """Ενημερώνει την κατάσταση μιας πρότασης στη μνήμη (π.χ. decision, talker_file) και ειδοποιεί την οθόνη."""
    for p in PROPOSALS:
        if p.get("recommendation_id") == recommendation_id:
            p.update(fields)
            if "decision" in fields:
                labels = {"accepted": "Εγκρίθηκε", "rejected": "Απορρίφθηκε", "corrected": "Επιβεβαιώθηκε"}
                log("proposal", f"{labels.get(fields['decision'], fields['decision'])}: {p['text']}", proposal=p["id"])
            elif "talker_file" in fields:
                log("proposal", f"Εκτυπώσιμο ταμπελάκι έτοιμο για {p.get('featured_name') or p['id']}", proposal=p["id"])
            return p
    return None


# --- Υπολογισμοί σε κώδικα (ποτέ από το μοντέλο) ---------------------------------

def _stock() -> dict[str, dict]:
    """Ανά κωδικό: όνομα, τεμάχια ανά κιβώτιο, απόθεμα αποθήκης, κόστος, βάθος αν το ξέρουμε.

    Το βάθος δεν είναι «θέση»: είναι πόσα τεμάχια χωράνε πίσω από μία πρόσοψη, για να βγουν τα τεμάχια.
    Αν το πλανόγραμμα δεν έχει τον κωδικό, παίρνουμε DEFAULT_DEPTH.
    """
    from .tools.data import run_sql
    from .identity import display_name
    _, rows = run_sql("""
        select p.sku, p.name, p.case_size, coalesce(b.on_hand, 0), p.unit_cost,
               (select pl.depth from planogram pl where pl.sku = p.sku limit 1), p.brand
        from products p left join backroom b using (sku) order by p.sku""")
    return {r[0]: {"name": display_name(r[1], r[6]), "case_size": r[2], "on_hand": r[3], "unit_cost": r[4],
                   "depth": r[5] or DEFAULT_DEPTH} for r in rows}


def plan_units(finding: dict, stock: dict) -> dict:
    """Πόσα τεμάχια θέλει η θέση, πόσα δίνει η αποθήκη, πόσα κιβώτια πρέπει να παραγγελθούν."""
    info = stock.get(finding["sku"]) or {}
    facings = finding.get("need", 0)
    depth = info.get("depth", 1) or 1
    units = facings * depth
    from_backroom = min(units, info.get("on_hand", 0))
    to_order = units - from_backroom
    case_size = info.get("case_size", 1) or 1
    cases = math.ceil(to_order / case_size) if to_order else 0
    # η αποθήκη πουλάει ολόκληρα κιβώτια: η αξία είναι κιβώτια × τεμάχια ανά κιβώτιο × κόστος (όπως στο portal)
    return {"units": units, "from_backroom": from_backroom, "to_order": to_order, "cases": cases,
            "order_eur": round(cases * case_size * (info.get("unit_cost") or 0), 2)}


# --- Κείμενο της εργασίας ----------------------------------------------------------

def _text(finding: dict, numbers: dict | None, stock: dict) -> str:
    name = (stock.get(finding["sku"]) or {}).get("name") or finding.get("label") or finding["sku"] or ""
    shelf = finding["shelf"]
    level = {"top": "πάνω", "eye": "ύψος ματιών", "bottom": "κάτω"}.get(finding.get("level") or "", "")
    if finding["type"] == "gap":
        where = f" ({level})" if level else ""
        n = finding.get("need") or 1
        room = f"χωράει {n} τεμάχιο" if n == 1 else f"χωράνε {n} τεμάχια"
        return (f"Γέμισε το ράφι {shelf}{where}: κενό στο {name}, {room}" if name
                else f"Γέμισε το ράφι {shelf}{where}: υπάρχει κενό, {room}")
    if finding["type"] in ("missing", "low"):
        where = f" ({level})" if level else ""
        n = numbers or {}
        if n.get("from_backroom"):
            rest = f" · τα άλλα {n['to_order']} δεν υπάρχουν στην αποθήκη" if n.get("to_order") else ""
            return f"Φέρε από την αποθήκη: {name}, {n['from_backroom']} τεμάχια, ράφι {shelf}{where}{rest}"
        if n.get("to_order"):
            return f"Λείπει {name} από το ράφι {shelf}{where} · δεν υπάρχει στην αποθήκη"
        if not numbers and finding.get("need"):
            few = "πρόσοψη" if finding["need"] == 1 else "προσόψεις"
            return f"Γέμισε το ράφι {shelf}{where}: {name}, λείπουν {finding['need']} {few}"
        return f"Φέρε από την αποθήκη: {name}, ράφι {shelf}{where}"
    if finding["type"] == "misplaced":
        to_level = {"top": "πάνω", "eye": "ύψος ματιών", "bottom": "κάτω"}.get(finding.get("to_level") or "", "")
        why = f" — {finding['why']}" if finding.get("why") else ""
        return f"Μετακίνησε: {name} από {level or 'εδώ'} σε {to_level or 'άλλο επίπεδο'}{why}"
    if finding["type"] == "unknown":
        return f"Βγάλε από το ράφι: {finding.get('label') or name} (δεν ανήκει στο τμήμα)"
    return f"Τακτοποίησε στο ράφι {shelf}: {finding.get('detail') or finding.get('msg', '')}"


def _took(seconds: float) -> str:
    return f"σε {seconds:.0f} δευτ." if seconds < 90 else f"σε {seconds / 60:.0f} λεπτά"


def _task_id(finding: dict) -> str:
    return f"{finding['type']}:{finding.get('sku') or finding.get('label', '')}:{finding['shelf']}"


# --- Αυτόματη παραγγελία -----------------------------------------------------------

def _auto_order(task: dict) -> None:
    """Παραγγελία χωρίς έγκριση μέσα στα όρια· αλλιώς εργασία έγκρισης για τον υπεύθυνο."""
    from . import portal
    n = task["numbers"]
    if not n["cases"]:
        return
    sku, cases, eur = task["sku"], n["cases"], n["order_eur"]
    within = (config.AUTO_ORDER and cases <= config.AUTO_ORDER_MAX_CASES and eur <= config.AUTO_ORDER_MAX_EUR)
    if not within:
        task["needs_approval"] = {"sku": sku, "cases": cases, "eur": eur,
                                  "why": f"πάνω από το όριο ({config.AUTO_ORDER_MAX_CASES} κιβ. / "
                                         f"{config.AUTO_ORDER_MAX_EUR:.0f} €)"}
        log("approval", f"Θέλει έγκριση: παραγγελία {sku} × {cases} κιβ. ({eur:.2f} €)", task=task["id"])
        return
    order = portal.place_order({sku: cases})
    task["order"] = {"order_no": order["order_no"], "cases": cases, "eur": order["total"]}
    log("order", f"Παρήγγειλα αυτόματα {sku} × {cases} κιβ. ({order['total']:.2f} €) · {order['order_no']}",
        task=task["id"], order_no=order["order_no"])


def approve_order(task_id: str, approved: bool) -> dict | None:
    """Ο υπεύθυνος απαντά σε εργασία που περίμενε έγκριση (πάνω από τα όρια)."""
    task = TASKS.get(task_id)
    if not task or not task.get("needs_approval"):
        return None
    pending = task.pop("needs_approval")
    if not approved:
        log("approval", f"Απορρίφθηκε η παραγγελία {pending['sku']} × {pending['cases']} κιβ.", task=task_id)
        task["order"] = {"rejected": True, **pending}
        return task
    from . import portal
    order = portal.place_order({pending["sku"]: pending["cases"]})
    task["order"] = {"order_no": order["order_no"], "cases": pending["cases"], "eur": order["total"]}
    log("order", f"Εγκρίθηκε: {pending['sku']} × {pending['cases']} κιβ. ({order['total']:.2f} €) · "
                 f"{order['order_no']}", task=task_id, order_no=order["order_no"])
    return task


# --- Εικόνα της εργασίας ------------------------------------------------------------

def _crop(frame: Path, boxes: list, task_id: str) -> str | None:
    """Κόβει το κομμάτι του ραφιού που αφορά την εργασία και σημειώνει το σημείο με κόκκινο."""
    if not boxes:
        return None
    try:
        from PIL import Image, ImageDraw, ImageOps
        with Image.open(frame) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
        w, h = im.size
        pad = 0.06
        ys = [b[0] for b in boxes] + [b[2] for b in boxes]
        xs = [b[1] for b in boxes] + [b[3] for b in boxes]
        y0, y1 = min(ys) / 1000 - pad, max(ys) / 1000 + pad
        x0, x1 = min(xs) / 1000 - pad, max(xs) / 1000 + pad
        box = (max(x0, 0) * w, max(y0, 0) * h, min(x1, 1) * w, min(y1, 1) * h)
        crop = im.crop((int(box[0]), int(box[1]), int(box[2]), int(box[3])))
        draw = ImageDraw.Draw(crop)
        line = max(3, round(min(crop.size) / 60))
        for b in boxes:
            draw.rectangle([b[1] * w / 1000 - box[0], b[0] * h / 1000 - box[1],
                            b[3] * w / 1000 - box[0], b[2] * h / 1000 - box[1]], outline=(207, 34, 46), width=line)
        out_dir = config.WORKSPACE / "tasks"
        out_dir.mkdir(parents=True, exist_ok=True)
        name = f"task_{task_id.replace(':', '_')}_{int(_now())}.jpg"
        crop.save(out_dir / name, quality=85)
        return f"tasks/{name}"
    except Exception as e:                                  # η εικόνα είναι βοήθημα, δεν ρίχνει τη ροή
        events.emit("system", "log", text=f"Crop εργασίας: {type(e).__name__}: {e}")
        return None


# --- Συγχρονισμός με ό,τι βλέπει η κάμερα -------------------------------------------

def sync(findings: list[dict], frame: Path, auto_order: bool = True) -> dict:
    """Ευρήματα του frame → εργασίες. Νέες δημιουργούνται, λυμένες κλείνουν. Επιστρέφει τι άλλαξε."""
    stock = _stock()
    seen, new = set(), []
    for finding in findings:
        task_id = _task_id(finding)
        seen.add(task_id)
        existing = TASKS.get(task_id)
        # Χωρίς κωδικό καταλόγου δεν ξέρουμε απόθεμα ούτε κιβώτιο: η εργασία βγαίνει, παραγγελία ποτέ.
        numbers = (plan_units(finding, stock) if finding["type"] in ("missing", "low") and finding.get("sku") in stock
                   else None)
        if existing and existing["status"] in OPEN:
            existing["last_seen"] = _now()
            existing["priority"] = finding["priority"]
            continue
        task = {
            "id": task_id, "kind": KIND[finding["type"]], "finding": finding["type"],
            "sku": finding.get("sku"), "shelf": finding["shelf"], "priority": finding["priority"],
            "text": _text(finding, numbers, stock), "numbers": numbers,
            "status": "open", "created": _now(), "last_seen": _now(), "done": None,
            "image": _crop(frame, finding.get("boxes") or [], task_id), "order": None, "needs_approval": None,
        }
        TASKS[task_id] = task
        log("task", task["text"], task=task_id, task_kind=task["kind"])
        if auto_order and numbers and numbers["to_order"]:
            _auto_order(task)
        new.append(task)

    resolved = []
    for task in TASKS.values():
        if task["status"] in OPEN and task["id"] not in seen:
            task["status"] = "done"
            task["done"] = _now()
            took = max(task["done"] - task["created"], 0)
            task["took_seconds"] = round(took)
            resolved.append(task)
            log("done", f"Έγινε: {task['text']} ({_took(took)})", task=task["id"])
    return {"new": new, "resolved": resolved}


def claim(task_id: str, who: str = "") -> dict | None:
    """Ο υπάλληλος δηλώνει ότι το αναλαμβάνει. Το κλείσιμο το κάνει πάντα η κάμερα."""
    task = TASKS.get(task_id)
    if not task or task["status"] != "open":
        return None
    task.update(status="in_progress", claimed_by=who or "υπάλληλος", claimed=_now())
    log("claim", f"Ανέλαβε: {task['text']}", task=task_id)
    return task


def open_tasks() -> list[dict]:
    return sorted((t for t in TASKS.values() if t["status"] in OPEN), key=lambda t: (t["priority"], t["created"]))


def recent_done(limit: int = 5) -> list[dict]:
    return sorted((t for t in TASKS.values() if t["status"] == "done"),
                  key=lambda t: t["done"] or 0, reverse=True)[:limit]


def stale(minutes: int | None = None) -> list[dict]:
    """Εργασίες που μένουν ανοιχτές πολλή ώρα: αξίζει υπενθύμιση."""
    limit = (minutes if minutes is not None else config.TASK_REMINDER_MINUTES) * 60
    if not limit:
        return []
    now = _now()
    return [t for t in open_tasks() if now - (t.get("reminded") or t["created"]) > limit]


def mark_reminded(tasks: list[dict]) -> None:
    for t in tasks:
        t["reminded"] = _now()


def summary() -> dict:
    tasks = open_tasks()
    orders = [t["order"] for t in TASKS.values() if t.get("order") and t["order"].get("order_no")]
    return {"shelf_ok": not tasks, "open": len(tasks), "tasks": tasks, "done": recent_done(),
            "pending_approval": [t for t in TASKS.values() if t.get("needs_approval")],
            "orders": orders, "proposals": list(PROPOSALS), "history": HISTORY[-40:]}
