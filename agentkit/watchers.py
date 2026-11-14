"""Προληπτική λειτουργία: έλεγχοι που τρέχουν μόνοι τους και ξεκινούν τον agent όταν κάτι αλλάξει.

Κάθε watcher είναι μια φθηνή συνάρτηση (χωρίς μοντέλο) που επιστρέφει None ή (κλειδί, στόχος).
Το κλειδί εμποδίζει να ξεκινήσει δεύτερη εκτέλεση για το ίδιο συμβάν.

Ο μόνος watcher σήμερα: νέα φωτογραφία στο workspace/photos. Ό,τι ρίξει αρχείο εκεί (η σελίδα
/capture από το κινητό, μια σταθερή κάμερα, ένα script) ξεκινά τον έλεγχο του ραφιού.
"""
import asyncio

from . import config, events

PHOTO_DIR = config.WORKSPACE / "photos"
PHOTO_TYPES = {".jpg", ".jpeg", ".png", ".webp"}

_seen: set[str] = set()
_baseline_done = False


def photo_goal(name: str) -> str:
    return f"Νέα φωτογραφία ραφιού: workspace/photos/{name}. Έλεγξε το ράφι και κάνε ό,τι χρειάζεται."


def mark_seen(name: str) -> None:
    """Η φωτογραφία έχει ήδη αναλάβει εκτέλεση (π.χ. από το upload), να μην την ξαναπιάσει ο watcher."""
    _seen.add(f"photo:{name}")


def new_photo():
    """Η πιο πρόσφατη φωτογραφία που δεν έχει ελεγχθεί. Όσες υπήρχαν πριν ξεκινήσει ο server αγνοούνται."""
    global _baseline_done
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    photos = sorted((p for p in PHOTO_DIR.iterdir() if p.suffix.lower() in PHOTO_TYPES), key=lambda p: p.stat().st_mtime)
    if not _baseline_done:
        _baseline_done = True
        _seen.update(f"photo:{p.name}" for p in photos)
        return None
    fresh = [p for p in photos if f"photo:{p.name}" not in _seen]
    if not fresh:
        return None
    _seen.update(f"photo:{p.name}" for p in fresh[:-1])      # αν ήρθαν πολλές μαζί, ελέγχεται η τελευταία
    return f"photo:{fresh[-1].name}", photo_goal(fresh[-1].name)


# (συνάρτηση ελέγχου, σενάριο που θα αναλάβει)
WATCHERS = [(new_photo, "shelf")]


async def check_once(notifier_factory=None) -> list[str]:
    """Τρέχει όλους τους ελέγχους μία φορά. Επιστρέφει τα run_id που ξεκίνησαν."""
    from .agent import start_run
    started = []
    for fn, scenario in WATCHERS:
        try:
            hit = await asyncio.to_thread(fn)
        except Exception as e:
            events.emit("system", "log", text=f"Ο έλεγχος {fn.__name__} απέτυχε: {e}")
            continue
        if not hit or hit[0] in _seen:
            continue
        _seen.add(hit[0])
        notifier = notifier_factory() if notifier_factory else None
        if notifier:
            await notifier("notify", "Εντόπισα κάτι και το αναλαμβάνω:\n" + hit[1])
        started.append(start_run(hit[1], scenario, source="watcher", notifier=notifier))
    return started


def reset() -> None:
    global _baseline_done
    _seen.clear()
    _baseline_done = False


async def loop(notifier_factory=None) -> None:
    while True:
        await asyncio.sleep(config.WATCH_INTERVAL_SECONDS)
        if config.WATCHERS_ENABLED:
            await check_once(notifier_factory)
