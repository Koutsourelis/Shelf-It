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

from . import config, events, identity, shelfsets, tasks
from .vision import assess_photo
from .vision.assessment import unknown_ratio

LIVE_DIR = config.WORKSPACE / "live"
KEEP_FRAMES = 200                       # τα παλιότερα frames σβήνονται
MAX_MOVES = 6                           # βέλη αλλαγής ραφιού στην οθόνη: οι σημαντικότερες, όχι όλες
LABEL = {"missing": "Λείπει", "low": "Λίγες προσόψεις", "misplaced": "Λάθος ράφι", "unknown": "Εκτός πλανογράμματος",
         "gap": "Κενό", "visual": "Παρουσίαση"}
PRIORITY = {"missing": 1, "low": 2, "gap": 3, "misplaced": 4, "unknown": 5, "visual": 6}


class LiveState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.prev_thumb: Any = None                  # μικρογραφία του τελευταίου frame που διαβάστηκε
        self.recent: deque = deque(maxlen=max(config.LIVE_CONFIRM_FRAMES, 1))   # υπογραφές ευρημάτων
        self.reported_sig: tuple | None = None       # για ποια ευρήματα έγινε τελευταία φορά sync
        self.last: dict | None = None                # τελευταία απάντηση προς τη σελίδα
        self.verdict: dict | None = None             # εκτίμηση του μοντέλου για το τελευταίο frame
        self.agent_run: str | None = None
        self.shelf: str | None = None                # ποιο ράφι έδειχνε το τελευταίο frame (σετ ή «?» = εκτός καταλόγου)
        self.frames = self.model_calls = 0
        self.busy = False
        self.preview_jpeg: bytes | None = None       # ελαφρύ live frame κινητού (/cam -> /shelf mirror, RAM-only)
        self.preview_ts: float = 0.0
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


# --- 5. εκτίμηση ραφιού από το μοντέλο -------------------------------------------

def to_findings(verdict: dict, planned: dict[str, int] | None = None) -> list[dict]:
    """Εκτίμηση του μοντέλου → ευρήματα για τις εργασίες. Καμία σύγκριση με θέσεις.

    Τα επίπεδα γίνονται «ράφι 1/2/3» μόνο για το κείμενο της εργασίας· ο κώδικας δεν ελέγχει αν το προϊόν
    είναι «στη σωστή θέση», γιατί τέτοια θέση δεν υπάρχει. Ελέγχει ό,τι λέει το μοντέλο (λείπει, σε λάθος επίπεδο,
    ξένο, κενό, παρουσίαση) και μία ποσότητα: `planned` είναι οι προσόψεις που έχει κάθε κωδικός όταν το ράφι
    είναι γεμάτο (πλανόγραμμα). Λιγότερες στη φωτογραφία = το ράφι δεν είναι γεμάτο = εργασία γεμίσματος.
    Για προϊόν χωρίς κωδικό το «γεμάτο» είναι ό,τι βλέπει το μοντέλο ως κενό δίπλα του (target_facings).
    """
    from .vision.assessment import LEVEL_TO_SHELF
    planned = planned or {}
    full = lambda sku: (planned.get(sku) or {}).get("facings")           # προσόψεις με το ράφι γεμάτο
    out = []
    removed = {f["label"] for f in verdict.get("foreign") or []}
    groups: dict[str, dict] = {}                 # ίδιος κωδικός σε δύο σημεία μετράει μία φορά
    for sh in verdict["shelves"]:
      for item in sh["items"]:
        key = item.get("sku") or item.get("label")
        if not key or (not item.get("sku") and item["label"] in removed):
            continue
        g = groups.setdefault(key, {"item": item, "level": sh["level"], "seen": 0, "target": 0, "boxes": [],
                                    "shelf": sh.get("shelf") or LEVEL_TO_SHELF[sh["level"]]})
        g["seen"] += item["facings"]
        g["target"] = max(g["target"], item.get("target_facings") or 0)
        if item.get("box_2d"):
            g["boxes"].append(item["box_2d"])
    gap_skus = {g.get("sku") for g in verdict.get("gaps") or [] if g.get("sku")}
    for key, g in groups.items():
        sku = g["item"].get("sku")
        target = full(sku) or g["target"]
        if not target or g["seen"] >= target:
            continue
        # Μία πρόσοψη διαφορά από το πλανόγραμμα είναι μέσα στο λάθος μέτρησης της κάμερας σε πυκνό ράφι. Μετράει
        # μόνο όταν και το μοντέλο βλέπει άδειο χώρο δίπλα στην ομάδα· από δύο και πάνω μετράει πάντα.
        if full(sku) and target - g["seen"] == 1 and g["target"] <= g["seen"] and sku not in gap_skus:
            continue
        out.append({"type": "low", "sku": sku, "label": g["item"]["label"], "level": g["level"], "shelf": g["shelf"],
                    "need": target - g["seen"], "seen": g["seen"], "target": target, "boxes": g["boxes"]})
    for m in verdict["missing"]:
        home = planned.get(m.get("sku"))                 # η σανίδα όπου μπαίνει ο κωδικός που λείπει
        level, shelf = (home["level"], home["shelf"]) if home else ("eye", 2)
        spot = [g["box_2d"] for g in verdict.get("gaps") or []       # το άδειο σημείο του, αν το έδειξε το μοντέλο
                if m.get("sku") and g.get("sku") == m["sku"] and g.get("box_2d")]
        out.append({"type": "missing", "sku": m.get("sku"), "label": m["product"], "level": level,
                    "shelf": shelf, "need": full(m.get("sku")) or m.get("target_facings") or 1, "boxes": spot,
                    "why": m.get("why", "")})
    # Κενά του ραφιού. Όσα εξηγούνται ήδη (ο κωδικός τους λείπει ή έχει λίγες προσόψεις) δεν γίνονται δεύτερη εργασία.
    restock = {f["sku"] or f["label"] for f in out}
    any_missing = bool(verdict["missing"])
    gaps: dict[tuple, dict] = {}
    for gap in verdict.get("gaps") or []:
        key = gap.get("sku") or gap.get("product") or ""
        if key in restock or (any_missing and not key):
            continue
        # Ο κωδικός δίπλα στο κενό έχει όλες τις προσόψεις του πλανογράμματος: ο χώρος είναι περίσσευμα του ραφιού,
        # όχι έλλειψη. Χωρίς αυτό το σωστά γεμάτο ράφι του καφέ, που έχει ελεύθερη άκρη, δεν θα έβγαινε ποτέ «σωστό».
        if gap.get("sku") in planned:
            continue
        f = gaps.setdefault((key, gap.get("shelf") or gap["level"]), {
            "type": "gap", "sku": gap.get("sku"), "label": gap.get("product") or "", "level": gap["level"],
            "shelf": gap.get("shelf") or LEVEL_TO_SHELF[gap["level"]], "need": 0, "boxes": []})
        f["need"] += gap.get("units") or 1
        if gap.get("box_2d"):
            f["boxes"].append(gap["box_2d"])
    out += gaps.values()
    for m in verdict["misplaced"]:
        out.append({"type": "misplaced", "sku": m.get("sku"), "label": m["product"], "level": m["from_level"],
                    "shelf": LEVEL_TO_SHELF[m["from_level"]], "to_level": m["to_level"],
                    "boxes": [m["box_2d"]] if m.get("box_2d") else [], "why": m.get("why", "")})
    for f in verdict["foreign"]:
        out.append({"type": "unknown", "sku": None, "label": f["label"], "level": f["level"],
                    "shelf": LEVEL_TO_SHELF[f["level"]], "boxes": [f["box_2d"]] if f.get("box_2d") else []})
    covered = {f["sku"] for f in out if f["sku"]}          # κωδικοί που έχουν ήδη εργασία
    for v in verdict["visual_issues"]:
        if any(sku and sku in v["detail"] for sku in covered):
            continue        # π.χ. «ο C02 έχει 1 πρόσοψη» — έχει ήδη εργασία αναπλήρωσης, όχι δεύτερη
        out.append({"type": "visual", "sku": None, "label": v["type"], "level": v["level"],
                    "shelf": LEVEL_TO_SHELF[v["level"]], "detail": v["detail"], "boxes": []})
    out.sort(key=lambda f: (PRIORITY[f["type"]], f["shelf"]))
    for i, f in enumerate(out, 1):
        f["priority"] = i
    return out


def regroup(verdict: dict, planned: dict[str, dict]) -> None:
    """Ξαναχωρίζει την ανάγνωση σε πραγματικά ράφια και δίνει όνομα στα ανώνυμα κενά. Αλλάζει το verdict επί τόπου.

    Το μοντέλο ξέρει τρία επίπεδα (top / eye / bottom). Σε ράφι με πέντε σανίδες βάζει τρεις από αυτές στο «eye», και
    τότε το «ράφι 2» της εργασίας και το «από πού» του βέλους βγαίνουν λάθος. Το πλανόγραμμα λέει σε ποια σανίδα
    ανήκει κάθε κωδικός· από τα κουτιά των κωδικών που διαβάστηκαν βγαίνει το ύψος κάθε σανίδας στη φωτογραφία, και
    κάθε ομάδα (με ή χωρίς κωδικό) πηγαίνει στη σανίδα που είναι πιο κοντά της. Δεν ελέγχεται αν ο κωδικός είναι
    στη «σωστή» σανίδα: αυτό το κρίνουν το μοντέλο και οι κανόνες.

    Κενό χωρίς προϊόν παίρνει το προϊόν της διπλανής ομάδας στην ίδια σανίδα.
    """
    from statistics import median
    items = [i for sh in verdict["shelves"] for i in sh["items"]]
    centre = lambda box: (box[0] + box[2]) / 2
    ys: dict[int, list[float]] = defaultdict(list)
    for it in items:
        if it.get("sku") in planned and it.get("box_2d"):
            ys[planned[it["sku"]]["shelf"]].append(centre(it["box_2d"]))
    rows = {shelf: median(v) for shelf, v in ys.items()}
    level_of = {p["shelf"]: p["level"] for p in planned.values()}
    if len(rows) >= 2:
        nearest = lambda box: min(rows, key=lambda shelf: abs(rows[shelf] - centre(box)))
        by_shelf: dict[int, list[dict]] = defaultdict(list)
        loose = []                                    # ομάδες χωρίς κουτί: μένουν στο επίπεδο που είπε το μοντέλο
        for sh in verdict["shelves"]:
            for it in sh["items"]:
                if it.get("box_2d"):
                    by_shelf[nearest(it["box_2d"])].append(it)
                elif it.get("sku") in planned:
                    by_shelf[planned[it["sku"]]["shelf"]].append(it)
                else:
                    loose.append((sh["level"], it))
        shelves = [{"level": level_of[n], "shelf": n,
                    "items": sorted(by_shelf[n], key=lambda i: (i.get("box_2d") or [0, 1000])[1])} for n in sorted(by_shelf)]
        for level, it in loose:
            target = next((sh for sh in shelves if sh["level"] == level), None)
            if target is None:
                shelves.append(target := {"level": level, "items": []})
            target["items"].append(it)
        verdict["shelves"] = shelves
        for gap in verdict.get("gaps") or []:
            if gap.get("box_2d"):
                gap["shelf"] = nearest(gap["box_2d"])
                gap["level"] = level_of[gap["shelf"]]
    # Ανώνυμο κενό: ανήκει στη διπλανή ομάδα της ίδιας σανίδας. Αν η μία γειτόνισσα έχει λιγότερες προσόψεις από το
    # πλανόγραμμα και η άλλη όχι, είναι δικό της.
    seen: dict[str, int] = defaultdict(int)
    for it in items:
        if it.get("sku"):
            seen[it["sku"]] += it["facings"]
    short = lambda it: it.get("sku") in planned and seen[it["sku"]] < planned[it["sku"]]["facings"]
    for gap in verdict.get("gaps") or []:
        box = gap.get("box_2d")
        if gap.get("sku") or gap.get("product") or not box:
            continue
        same_row = [i for i in items if i.get("box_2d") and i["box_2d"][0] <= centre(box) <= i["box_2d"][2]]
        if not same_row:
            continue
        distance = lambda i: max(i["box_2d"][1] - box[3], box[1] - i["box_2d"][3], 0)
        near = sorted(same_row, key=distance)[:2]
        owner = next((i for i in near if short(i)), near[0])
        gap["sku"], gap["product"] = owner.get("sku"), owner.get("label") or ""


def _planned() -> dict[str, dict]:
    """Ανά κωδικό, από το πλανόγραμμα του ενεργού σετ: προσόψεις με το ράφι γεμάτο και σε ποιο ράφι μπαίνει.

    Χρησιμοποιείται για ποσότητες («λείπουν 2 προσόψεις») και για να ξέρει ο υπάλληλος πού να το πάει. Η θέση
    μέσα στο ράφι δεν συγκρίνεται με τη φωτογραφία.
    """
    from .tools.data import run_sql
    _, rows = run_sql("select sku, sum(facings), min(shelf), min(level) from planogram group by 1")
    return {r[0]: {"facings": int(r[1]), "shelf": int(r[2]), "level": r[3]} for r in rows}


def layout_moves(verdict: dict) -> list[dict]:
    """Ποια προϊόντα πρέπει να αλλάξουν ράφι και γιατί. Η οθόνη ζωγραφίζει ένα βέλος για το καθένα.

    Στο ράφι του τμήματος το επίπεδο-στόχος και ο λόγος βγαίνουν από τις πωλήσεις με κώδικα (rules.target_layout,
    Κ4 και Κ7), άρα ο λόγος έχει αριθμό. Σε ράφι εκτός καταλόγου δεν υπάρχουν πωλήσεις: το επίπεδο και ο λόγος είναι
    κρίση του μοντέλου με τους κανόνες κατηγορίας, χωρίς αριθμούς, και σημειώνονται ως τέτοια (source = model).
    """
    from .vision.assessment import LEVEL_TO_SHELF
    target = {i["sku"]: (lay["level"], i) for lay in verdict.get("suggested_layout") or []
              for i in lay.get("items") or []}
    tasked = {m.get("sku") or m.get("product") for m in verdict.get("misplaced") or []}   # έχουν ήδη εργασία
    out, seen = [], set()
    for level, item in ((sh["level"], i) for sh in verdict["shelves"] for i in sh["items"]):
        if (item.get("sku") or item.get("label")) in tasked:
            continue
        if item.get("sku") in target:
            to_level, info = target[item["sku"]]
            why, source = info["why"], "rules"
            # Πρώτα οι προορισμοί (Κ7, οι πιο πολλές πωλήσεις), μετά ό,τι ανεβαίνει στο ύψος των ματιών με το
            # μεγαλύτερο περιθώριο ανά πρόσοψη, τελευταίοι όσοι απλώς τους κάνουν χώρο.
            rank = {"destination": (0, -info.get("units_day", 0)), "heavy": (1, -info.get("margin_per_facing", 0)),
                    "eye": (2, -info.get("margin_per_facing", 0))
                    }.get(info.get("role"), (3, info.get("margin_per_facing", 0)))
        elif not item.get("sku") and item.get("move_why"):
            to_level, why, source, rank = item.get("best_level") or level, item["move_why"], "model", (1, 0)
        else:
            continue
        if to_level != level and (item.get("sku") or item.get("label")) not in seen:
            seen.add(item.get("sku") or item.get("label"))
            out.append({"sku": item.get("sku"), "name": item.get("name") or item.get("label") or "",
                        "label": item.get("label") or "", "from_level": level, "to_level": to_level,
                        "to_shelf": LEVEL_TO_SHELF[to_level], "why": why, "source": source,
                        "box": item.get("box_2d"), "rank": rank})
    out.sort(key=lambda m: m.pop("rank"))
    return out


def _signature(found: list[dict]) -> tuple:
    """Τι μετράει για «άλλαξε κάτι;». Τα κουτιά όχι (αλλάζουν λίγο σε κάθε frame)."""
    return tuple(sorted((f["type"], f["sku"] or f.get("label", ""), f["shelf"], f.get("need", 0)) for f in found))


# --- 3. ποιο ράφι είναι αυτό -------------------------------------------------------

def _read_labels(verdict: dict) -> list[str]:
    """Ό,τι διάβασε το μοντέλο και δεν είναι στον ενεργό κατάλογο: μάρκα και ετικέτα κάθε ομάδας."""
    items = [i for sh in verdict["shelves"] for i in sh["items"] if not i.get("sku")]
    return [f"{i.get('brand') or ''} {i.get('label') or ''}" for i in items] + [f["label"] for f in verdict["foreign"]]


async def _assess(frame: Path) -> dict:
    """Διαβάζει το frame με τον κατάλογο του ραφιού που δείχνει η φωτογραφία, όχι με αυτόν που έτυχε να είναι ενεργός.

    1. Ανάγνωση με το ενεργό σετ. Αν τα περισσότερα προϊόντα είναι γνωστά, τέλος.
    2. Αλλιώς ψάχνουμε ποιο σετ έχει τις μάρκες που διάβασε το μοντέλο (shelfsets.guess). Αν βρεθεί, γίνεται ενεργό
       (κατάλογος, πλανόγραμμα, αποθήκη, πωλήσεις) και το frame διαβάζεται ξανά με αυτό.
    3. Αν κανένα σετ δεν ταιριάζει, το ράφι διαβάζεται ξανά χωρίς κατάλογο: ονόματα, κενά και διάταξη, χωρίς
       παραγγελίες.
    """
    verdict = await assess_photo(frame)
    STATE.model_calls += 1
    if config.vision_provider() == "mock" or unknown_ratio(verdict) < config.LIVE_UNKNOWN_RATIO:
        return verdict
    other = shelfsets.guess(_read_labels(verdict))
    if other is not None and agent_status() != "running":       # ο agent δουλεύει πάνω στη βάση του τωρινού σετ
        await asyncio.to_thread(shelfsets.activate, other)
        verdict = await assess_photo(frame)
        STATE.model_calls += 1
        if unknown_ratio(verdict) < config.LIVE_UNKNOWN_RATIO:
            return verdict
    # Κανένα σετ δεν έχει αυτά τα προϊόντα: το ράφι διαβάζεται ξανά χωρίς κατάλογο. Η πρώτη ανάγνωση δεν αρκεί: με
    # κατάλογο μπροστά του το μοντέλο γράφει μόνο λίγες από τις ομάδες που δεν του ταιριάζουν (5 από ~40 σε δοκιμή).
    verdict = await assess_photo(frame, catalog=[])
    verdict["unknown_shelf"] = True
    STATE.model_calls += 1
    return verdict


def _shelf_changed(verdict: dict, before: str) -> None:
    """Άλλο ράφι από το προηγούμενο frame: οι εργασίες του παλιού ακυρώνονται και η επιβεβαίωση ξεκινά από την αρχή.

    `before` είναι το σετ που ήταν ενεργό πριν διαβαστεί το frame: με αυτό συγκρίνεται η πρώτη φωτογραφία.
    """
    shelf = "?" if verdict.get("unknown_shelf") else config.SHELF_SET
    if shelf != (before if STATE.shelf is None else STATE.shelf):
        cancelled = tasks.cancel_open()
        STATE.recent.clear()
        STATE.reported_sig = None
        what = ("ράφι εκτός καταλόγου· το διαβάζω από τις ετικέτες, χωρίς παραγγελίες" if shelf == "?"
                else f"{shelfsets.title(shelf)}· άλλαξα κατάλογο, πλανόγραμμα και αποθήκη")
        tasks.log("setup", f"Άλλο ράφι στη φωτογραφία: {what}"
                           + (f" ({cancelled} εργασίες του προηγούμενου ραφιού ακυρώθηκαν)" if cancelled else ""))
    STATE.shelf = shelf


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
    from . import agent, telegram
    changed = await asyncio.to_thread(tasks.sync, found, frame)
    STATE.reported_sig = sig
    if changed["new"] or changed["resolved"]:
        try:
            await telegram.notify_shelf_change(changed, frame)
        except Exception as e:
            events.emit("system", "log", text=f"Telegram: {e}")
    events.emit("system", "live_report", frame=frame.name, open=len(tasks.open_tasks()),
                new=len(changed["new"]), resolved=len(changed["resolved"]))

    # Σε ράφι εκτός καταλόγου ο agent δεν ξεκινά: τα εργαλεία του μετρούν με πωλήσεις και πλανόγραμμα του τμήματος
    # και θα πρότειναν αλλαγές σε κωδικούς που δεν είναι στη φωτογραφία.
    if changed["new"] and config.LIVE_START_AGENT and not (STATE.verdict or {}).get("unknown_shelf"):
        if agent_status() != "running":
            rel = frame.relative_to(config.ROOT).as_posix()
            listing = "\n".join(f"- {t['text']}" for t in changed["new"])
            STATE.agent_run = agent.start_run(
                f"Η κάμερα του ραφιού βρήκε νέα ευρήματα στη φωτογραφία {rel}. Ο κώδικας έχει ήδη στείλει στον "
                f"υπάλληλο αυτές τις εργασίες και έχει κάνει τις παραγγελίες:\n{listing}", "live", source="camera",
                notifier=_agent_to_timeline)
    return changed


def agent_status() -> str | None:
    """running | done | error | ... για την τελευταία εκτέλεση του agent που ξεκίνησε η κάμερα· None αν δεν έτρεξε."""
    from . import agent
    if STATE.agent_run in agent._tasks:
        return "running"
    return agent.RUNS.get(STATE.agent_run or "", {}).get("status")


async def _agent_to_timeline(kind: str, text: str) -> None:
    """Το τελικό μήνυμα του agent μπαίνει στο χρονολόγιο της οθόνης."""
    if kind == "final" and text:
        tasks.log("agent", text, run=STATE.agent_run)


# --- είσοδος ------------------------------------------------------------------

def _save(data: bytes) -> Path:
    LIVE_DIR.mkdir(parents=True, exist_ok=True)
    path = LIVE_DIR / f"frame_{time.strftime('%H%M%S')}_{STATE.frames:04d}.jpg"
    path.write_bytes(data)
    old = sorted(LIVE_DIR.glob("frame_*.jpg"), key=lambda p: p.stat().st_mtime)
    for p in old[:-KEEP_FRAMES]:
        if p != path:
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
        if single:
            STATE.preview_jpeg = data
            STATE.preview_ts = time.time()
        thumb = await asyncio.to_thread(_thumb, data)
        if config.vision_provider() != "mock":
            px = thumb.tobytes()
            if (sum(px) / len(px)) < 7.0 and max(px) < 22:
                return {**status(), "status": "dark", "detail": "Η κάμερα είναι κλειστή ή πολύ σκοτεινή"}
        if not (force or single) and STATE.prev_thumb is not None and STATE.last:
            d = _diff(thumb, STATE.prev_thumb)
            if d < config.LIVE_DIFF_THRESHOLD:
                return {**status(), "status": "unchanged", "diff": round(d, 1)}
        frame = await asyncio.to_thread(_save, data)
        t0 = time.time()
        active = config.SHELF_SET
        verdict = await _assess(frame)
        seconds = round(time.time() - t0, 1)
        if verdict["occluded"]:
            events.emit("system", "live_frame", frame=frame.name, status="occluded", seconds=seconds)
            return {**status(), "status": "occluded", "seconds": seconds,
                    "detail": "Κάτι κρύβει το ράφι· το frame δεν μετράει"}
        planned = {} if verdict.get("unknown_shelf") else await asyncio.to_thread(_planned)
        regroup(verdict, planned)        # πραγματικές σανίδες και όνομα στα κενά, πριν από οτιδήποτε διαβάσει τα shelves
        if not verdict.get("unknown_shelf"):
            # Η διάταξη που βλέπει ο υπεύθυνος βγαίνει από τις πωλήσεις (Κ4, Κ5, Κ7), όχι από το μοντέλο: ίδια σε
            # κάθε scan και με αριθμούς από SQL. Σε ράφι χωρίς κατάλογο δεν υπάρχουν πωλήσεις· μένει του μοντέλου.
            try:
                from .tools.shelf import stats_layout
                verdict["suggested_layout"] = await asyncio.to_thread(stats_layout) or verdict["suggested_layout"]
            except Exception as e:
                events.emit("system", "log", text=f"Διάταξη από πωλήσεις: {type(e).__name__}: {e}")
        try:        # ο agent που ξεκινά μετά το scan (check_planogram, replenishment_plan) θέλει την ανάγνωση έτοιμη
            from .tools.shelf import record_reading
            await asyncio.to_thread(record_reading, frame.name, verdict)
        except Exception as e:
            events.emit("system", "log", text=f"Καταγραφή ανάγνωσης: {type(e).__name__}: {e}")
        try:        # όνομα και ταυτότητα (Open Food Facts) για κάθε ομάδα, ώστε η οθόνη να δείχνει τι είναι
            await asyncio.to_thread(identity.annotate, verdict["shelves"])
            if verdict.get("unknown_shelf"):
                tasks.clear_proposals()      # οι προτάσεις του agent αφορούσαν το ράφι του τμήματος, όχι αυτό
                identity.lookup_in_background(verdict["shelves"])
        except Exception as e:
            events.emit("system", "log", text=f"Ταυτότητα προϊόντων: {type(e).__name__}: {e}")
        STATE.prev_thumb = thumb
        STATE.verdict = verdict
        _shelf_changed(verdict, active)
        found = to_findings(verdict, planned)
        moves = layout_moves(verdict)
        sig = _signature(found)
        STATE.recent.extend([sig] * ((STATE.recent.maxlen or 1) if single else 1))
        confirmed = len(STATE.recent) == STATE.recent.maxlen and len(set(STATE.recent)) == 1
        acted = False
        if confirmed and sig != STATE.reported_sig:
            await _act(frame, found, sig)
            acted = True
        STATE.last = {
            "status": "acted" if acted else ("confirmed" if confirmed else "pending"),
            "frame": frame.name, "seconds": seconds, "findings": found,
            "shelves": verdict["shelves"], "summary": verdict["summary"],
            "unknown_shelf": bool(verdict.get("unknown_shelf")),
            "shelf_set": config.SHELF_SET or "shelf",
            "shelf_title": "εκτός καταλόγου" if verdict.get("unknown_shelf") else shelfsets.title(config.SHELF_SET),
            "suggested_layout": verdict["suggested_layout"], "shelf_ok": verdict["shelf_ok"],
            "moves": moves[:MAX_MOVES], "moves_more": max(len(moves) - MAX_MOVES, 0),
            "confirm": f"{sum(1 for s in STATE.recent if s == sig)}/{STATE.recent.maxlen}",
        }
        events.emit("system", "live_frame", frame=frame.name, status=STATE.last["status"],
                    findings=len(found), seconds=seconds)
        return status()
    finally:
        STATE.busy = False


def _with_identity(summary: dict) -> dict:
    """Οι προτάσεις διάταξης με την ταυτότητα του κωδικού που προβάλλουν (αποθηκευμένη, χωρίς δίκτυο)."""
    try:
        if STATE.last:      # ό,τι βρήκε στο μεταξύ η αναζήτηση στο παρασκήνιο φαίνεται στο επόμενο poll
            identity.annotate(STATE.last["shelves"])
        summary["proposals"] = [{**p, "off": identity.for_sku(p.get("featured_sku") or "")}
                                for p in summary["proposals"]]
    except Exception as e:
        events.emit("system", "log", text=f"Ταυτότητα προϊόντων: {type(e).__name__}: {e}")
    return summary


def status() -> dict:
    """Όλη η κατάσταση που χρειάζονται οι σελίδες, και όταν δεν έχει έρθει ακόμη frame."""
    return {"interval": config.LIVE_INTERVAL_SECONDS, "confirm_frames": config.LIVE_CONFIRM_FRAMES,
            "provider": config.vision_provider(), "model": config.vision_model(),
            "auto_order": config.AUTO_ORDER, "max_cases": config.AUTO_ORDER_MAX_CASES,
            "max_eur": config.AUTO_ORDER_MAX_EUR, "frames": STATE.frames, "model_calls": STATE.model_calls,
            "agent_run": STATE.agent_run, "agent_status": agent_status(),
            **(STATE.last or {"status": "idle", "findings": [], "shelves": [], "summary": "",
                              "suggested_layout": [], "moves": [], "moves_more": 0, "shelf_ok": True,
                              "shelf_set": config.SHELF_SET or "shelf",
                              "shelf_title": shelfsets.title(config.SHELF_SET)}), **_with_identity(tasks.summary())}


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
