"""Names and identity for what the camera sees: connects the shelf reading with Open Food Facts (agentkit/off.py).

Every group of products in a reading gets a `name` the shelf screen can show, a `brand`, and, when Open Food
Facts knows the product, an `off` record (barcode, pack size, page):

- products of the department catalogue take their name from the catalogue and their identity from the saved
  lookup next to it (`off_products.json`, written by scripts/fetch_off.py). No network.
- products outside the catalogue (a new photo, another department) keep the label the model read. They are looked
  up in Open Food Facts in the background, a few per scan to respect the service's limit, and every answer is saved
  in `workspace/off_seen.json`, in the same shape as `off_products.json`. The next scan reads it from there.

Identity only. Sales and cost do not exist in Open Food Facts, so nothing here feeds a number into a decision.
"""
import asyncio
import json
import threading
from datetime import datetime, timezone

from . import config, events, off

SEEN_PATH = config.WORKSPACE / "off_seen.json"
LOOKUPS_PER_SCAN = 3        # each lookup is up to three searches; the service allows about ten a minute
PAUSE_SECONDS = 7.0

_lock = threading.Lock()
_task: asyncio.Task | None = None


def key(brand: str, label: str) -> str:
    """One product read from a photo → the key of its saved lookup. The brand is not repeated if the label has it."""
    brand, label = off.norm(brand), off.norm(label)
    return label if not brand or label.startswith(brand) else f"{brand} {label}".strip()


def display_name(name: str, brand: str = "") -> str:
    """'Μπίρα Lager κουτί 500ml' is six different products on a drinks shelf: the brand goes in front."""
    name, brand = (name or "").strip(), (brand or "").strip()
    return name if not brand or off.norm(brand) in off.norm(name) else f"{brand} {name}"


def load_seen() -> dict:
    """{key: off.identify() result} for products outside the catalogue that the camera has seen."""
    try:
        return json.loads(SEEN_PATH.read_text(encoding="utf-8")).get("products", {})
    except (OSError, ValueError):
        return {}


def _save_seen(products: dict) -> None:
    doc = {"source": off.LICENSE, "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "products": dict(sorted(products.items()))}
    tmp = SEEN_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(SEEN_PATH)


def public(res: dict | None) -> dict | None:
    """The part of a lookup the screen shows. 'weak' guesses and misses are not shown as an identity."""
    m = (res or {}).get("match")
    if not m or res.get("status") not in ("matched", "similar"):
        return None
    return {"status": res["status"], "barcode": m.get("barcode", ""), "name": m.get("name", ""),
            "brand": m.get("brand", ""), "quantity": m.get("quantity", ""), "url": m.get("url", ""),
            "image": m.get("image", "")}


def _catalog() -> dict[str, tuple[str, str]]:
    from .tools.data import run_sql
    _, rows = run_sql("select sku, name, brand from products")
    return {r[0]: (r[1], r[2] or "") for r in rows}


def annotate(shelves: list[dict]) -> list[dict]:
    """Adds `name`, `brand` and `off` to every item of a reading, in place. Safe to call again: it only reads."""
    catalog, cached, seen = _catalog(), off.load_cache(), load_seen()
    for sh in shelves:
        for it in sh.get("items") or []:
            sku = it.get("sku")
            if sku in catalog:
                name, brand = catalog[sku]
                it["name"], it["brand"] = display_name(name, brand), brand or it.get("brand") or ""
                it["off"] = public(cached.get(sku))
            else:
                it["name"] = it.get("label") or it.get("brand") or ""
                it["brand"] = it.get("brand") or ""
                it["off"] = public(seen.get(key(it["brand"], it.get("label") or "")))
    return shelves


def for_sku(sku: str) -> dict | None:
    """The saved Open Food Facts identity of a catalogue code, for proposals and tasks."""
    return public(off.load_cache().get(sku))


def pending(shelves: list[dict]) -> list[tuple[str, str, str]]:
    """(key, label, brand) of products outside the catalogue with a readable brand and no saved lookup yet."""
    seen, out, have = load_seen(), [], set()
    for it in (i for sh in shelves for i in sh.get("items") or []):
        if it.get("sku") or not (it.get("brand") or "").strip():
            continue
        k = key(it["brand"], it.get("label") or "")
        if k and k not in seen and k not in have:
            have.add(k)
            out.append((k, it.get("label") or it["brand"], it["brand"]))
    return out


def same_pack(label: str, res: dict) -> bool:
    """The pack size read from the label agrees with the Open Food Facts record (±5%)."""
    m = res.get("match") or {}
    want, have = off._grams(label), off._grams(m.get("quantity", "")) or off._grams(m.get("name", ""))
    return bool(want and have and abs(want - have) <= 0.05 * want)


async def _lookup(todo: list[tuple[str, str, str]]) -> None:
    found = 0
    for i, (k, label, brand) in enumerate(todo):
        if i:
            await asyncio.sleep(PAUSE_SECONDS)
        try:
            res = await off.identify(label, brand)
        except Exception as e:            # the service is outside our control; the shelf screen never waits for it
            events.emit("system", "log", text=f"Open Food Facts: {type(e).__name__}: {e}")
            return
        # A label read from a photo has no category to check against, so the brand alone can pick another variant
        # (a weiss for a lager). Without the same pack size the hit is reported as comparable, not as the product.
        if res.get("status") == "matched" and not same_pack(label, res):
            res = {**res, "status": "similar"}
        with _lock:
            seen = load_seen()
            seen[k] = {"query": {"name": label, "brand": brand, "category": ""}, **res}
            _save_seen(seen)
        found += res.get("status") == "matched"
    if todo:
        # live_report makes the shelf screen re-read /api/live/status, where annotate() picks up the new file
        events.emit("system", "live_report", source="open_food_facts", looked_up=len(todo), matched=found)


def lookup_in_background(shelves: list[dict]) -> int:
    """Starts the lookups of this scan, unless the previous batch is still running. Returns how many started."""
    global _task
    if not config.OFF_LIVE_LOOKUP or (_task and not _task.done()):
        return 0
    todo = pending(shelves)[:LOOKUPS_PER_SCAN]
    if todo:
        _task = asyncio.create_task(_lookup(todo))
    return len(todo)
