"""Which shelf is in the picture. The catalogue follows the photo; it is not fixed at start-up.

A shelf set is a folder with catalog.csv, planogram.csv and backroom.csv: `data/shelf` (coffee) and every folder
under `data/shelf/sets/` (trad, drinks, ...). SHELF_SET in .env only says which one is active when the server
starts. When the camera shows a shelf whose products are not in the active catalogue, `guess()` looks for the set
whose brands are on the labels the model read, and `activate()` switches to it: catalogue, planogram, backroom,
sales and the database behind the tools. Adding a shelf is adding a folder; no code changes.

If no set fits, the shelf stays "outside the catalogue" and is read without one (agentkit/live.py).
"""
import csv
from collections import Counter
from functools import lru_cache
from pathlib import Path

from . import config, off

SETS_DIR = config.DATA_DIR / "shelf" / "sets"
MIN_HITS = 3          # labels that carry a brand of the set
MIN_SHARE = 0.4       # ... and their share of everything read from the photo


def names() -> list[str]:
    """'' is the base set (data/shelf); the rest are the folders of data/shelf/sets that hold a catalogue."""
    extra = sorted(d.name for d in SETS_DIR.iterdir() if (d / "catalog.csv").is_file()) if SETS_DIR.is_dir() else []
    return [""] + extra


def folder(name: str) -> Path:
    return SETS_DIR / name if name else config.DATA_DIR / "shelf"


def db_path(name: str) -> Path:
    return config.DATA_DIR / (f"demo_{name}.duckdb" if name else "demo.duckdb")


@lru_cache(maxsize=None)
def _catalog(name: str) -> tuple[tuple[str, str], ...]:
    with open(folder(name) / "catalog.csv", encoding="utf-8-sig", newline="") as f:
        return tuple((r.get("brand") or "", r.get("category") or "") for r in csv.DictReader(f) if any(r.values()))


def brands(name: str) -> frozenset[str]:
    """The brands of a set as off.norm() writes them: 'Βεργίνα' and 'VERGINA' are both 'vergina'."""
    return frozenset(b for b in (off.norm(brand) for brand, _ in _catalog(name)) if len(b) >= 3)


def title(name: str) -> str:
    """What the set sells, from its own catalogue: the two most common categories."""
    top = Counter(c for _, c in _catalog(name) if c).most_common(2)
    return " · ".join(c for c, _ in top) or (name or "ράφι")


def _has(text: str, brand: str) -> bool:
    return f" {brand} " in f" {text} "


def guess(labels: list[str], active: str | None = None) -> str | None:
    """The set whose brands appear on most of the labels read from a photo, or None when no set fits.

    `labels` is what the model read (brand and label of each group). The active set is skipped: its catalogue was
    already tried. A set wins only with at least MIN_HITS labels and MIN_SHARE of all of them.
    """
    texts = [t for t in (off.norm(l) for l in labels) if t]
    if not texts:
        return None
    active = config.SHELF_SET if active is None else active
    best, best_hits = None, 0
    for name in names():
        if name == active:
            continue
        hits = sum(1 for t in texts if any(_has(t, b) for b in brands(name)))
        if hits > best_hits:
            best, best_hits = name, hits
    if best is None or best_hits < MIN_HITS or best_hits / len(texts) < MIN_SHARE:
        return None
    return best


def activate(name: str) -> dict:
    """Makes `name` the active set: paths, database (built from the CSVs the first time) and vision cache."""
    from . import demo_data
    from .tools import data as data_tools
    from .vision import assessment
    if name not in names():
        raise ValueError(f"Δεν υπάρχει σετ ραφιού «{name}»")
    with data_tools._lock:                          # no query may run while the connection changes file
        if data_tools._con is not None:
            data_tools._con.close()
            data_tools._con = None
        config.SHELF_SET = name
        config.SHELF_DIR = folder(name)
        config.DB_PATH = db_path(name)
        demo_data.SHELF_DIR = config.SHELF_DIR
        demo_data.PHOTOS_DIR = config.SHELF_DIR / "photos"
        if config.VISION_REFERENCE:                 # the reference photo shows the other shelf
            config.VISION_REFERENCE = ""
        assessment._cache.clear()
    if not config.DB_PATH.exists():
        demo_data.build()
    return {"shelf_set": name or "shelf", "title": title(name)}
