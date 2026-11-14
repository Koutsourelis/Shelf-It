"""Κλήση του μοντέλου όρασης. Κάτοχος: Άτομο Α.

read_photo(path) → dict που ακολουθεί το READING_SCHEMA, πάντα καθαρισμένο (normalize), ώστε ο υπόλοιπος
κώδικας να μη χρειάζεται ελέγχους.

- Πάροχος: ό,τι ορίζει το .env (LLM_PROVIDER). Για Gemini: openai_compat με το base url της Google.
- Cache ανά αρχείο: αν το live loop διάβασε ένα frame και μετά ο agent ζητήσει το ίδιο, δεν γίνεται 2η κλήση.
- mock: διαβάζει το <photo>.reading.json δίπλα στη φωτογραφία, αλλιώς την «ψεύτικη κατάσταση» του ραφιού
  (set_mock_reading), ώστε το live loop να δοκιμάζεται χωρίς κλειδί.

TODO(Α):
- native Gemini client με response_schema, αν το eval δείξει λάθη τύπων από το openai_compat
- media resolution / μέγεθος εικόνας (MAX_IMAGE_SIDE στο llm/structured.py)
"""
import asyncio
import json
from collections import OrderedDict
from pathlib import Path

from .. import config
from ..demo_data import PHOTOS_DIR
from ..llm.structured import structured
from . import prompts
from .schema import READING_SCHEMA

_cache: "OrderedDict[tuple, dict]" = OrderedDict()
_CACHE_SIZE = 32
_mock_name = "sample_before"


def set_mock_reading(name: str) -> None:
    """Για mock: τι «βλέπει» το μοντέλο σε frames χωρίς .reading.json (π.χ. 'sample_before', 'sample_after')."""
    global _mock_name
    if not (PHOTOS_DIR / f"{name}.reading.json").exists():
        raise FileNotFoundError(f"Δεν υπάρχει data/shelf/photos/{name}.reading.json")
    _mock_name = name


def mock_reading() -> str:
    return _mock_name


def _box(value) -> list[int] | None:
    try:
        ymin, xmin, ymax, xmax = (max(0, min(1000, int(v))) for v in value)
    except (TypeError, ValueError):
        return None
    return [ymin, xmin, ymax, xmax] if ymax > ymin and xmax > xmin else None


def _int(v, default=0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def normalize(raw: dict, known_skus: set[str]) -> dict:
    """Καθαρίζει την έξοδο του μοντέλου: άγνωστοι κωδικοί → null, κουτιά σε 0-1000, αριθμοί ≥ 0."""
    items = []
    for it in raw.get("items") or []:
        if not isinstance(it, dict):
            continue
        sku = it.get("sku") if it.get("sku") in known_skus else None
        items.append({"sku": sku, "label": str(it.get("label") or ""), "shelf": _int(it.get("shelf")),
                      "position": _int(it.get("position")), "facings": max(_int(it.get("facings")), 0),
                      "box_2d": _box(it.get("box_2d"))})
    gaps = [{"shelf": _int(g.get("shelf")), "box_2d": b} for g in raw.get("gaps") or []
            if isinstance(g, dict) and (b := _box(g.get("box_2d")))]
    issues = [{"shelf": _int(v.get("shelf")), "type": str(v.get("type") or "other"), "detail": str(v.get("detail") or "")}
              for v in raw.get("visual_issues") or [] if isinstance(v, dict)]
    return {"occluded": bool(raw.get("occluded")), "items": items, "gaps": gaps, "visual_issues": issues}


def _catalog() -> list[tuple[str, str, str]]:
    from ..tools.data import run_sql
    _, rows = run_sql("select sku, name, brand from products order by sku")
    return rows


def _reference() -> Path | None:
    if not config.VISION_REFERENCE:
        return None
    p = (config.ROOT / config.VISION_REFERENCE).resolve()
    return p if p.is_file() else None


async def _call_model(path: Path, catalog: list, ref: Path | None) -> dict:
    images = [ref, path] if ref else [path]
    last = None
    for attempt in range(2):                       # μία επανάληψη σε timeout ή χαλασμένο JSON
        try:
            return await asyncio.wait_for(
                structured(prompts.SYSTEM, prompts.user_prompt(catalog, ref is not None), READING_SCHEMA, images=images),
                timeout=config.VISION_TIMEOUT_SECONDS)
        except (asyncio.TimeoutError, ValueError, json.JSONDecodeError) as e:
            last = e
    raise RuntimeError(f"Το μοντέλο όρασης απέτυχε δύο φορές: {type(last).__name__}: {last}")


async def read_photo(path: Path) -> dict:
    path = Path(path)
    catalog = await asyncio.to_thread(_catalog)
    known = {c[0] for c in catalog}

    if config.LLM_PROVIDER == "mock":
        side = path.with_suffix(".reading.json")
        if not side.exists():
            side = PHOTOS_DIR / f"{_mock_name}.reading.json"
        return normalize(json.loads(side.read_text(encoding="utf-8")), known)

    ref = _reference()
    key = (str(path.resolve()), path.stat().st_mtime_ns, config.OPENAI_COMPAT_MODEL or config.ANTHROPIC_MODEL,
           prompts.PROMPT_VERSION, str(ref))
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    reading = normalize(await _call_model(path, catalog, ref), known)
    _cache[key] = reading
    if len(_cache) > _CACHE_SIZE:
        _cache.popitem(last=False)
    return reading
