"""Open Food Facts: who a product on the shelf really is.

Open Food Facts (https://world.openfoodfacts.org) is an open, crowd-sourced database of packaged food, under the
Open Database License (ODbL). We use it for product *identity* only: barcode, product name, brand, pack size,
category and a front image. It has no sales and no purchase cost; those stay synthetic and are declared so.

Two public endpoints, no API key:
  - search:  https://search.openfoodfacts.org/search?q=...        (Search-a-licious, full text)
  - barcode: https://world.openfoodfacts.org/api/v2/product/{code}.json

Rules of the service: send a User-Agent that names the app, and keep to about 10 searches and 100 product reads a
minute. `scripts/fetch_off.py` looks up the whole catalogue once and saves the result next to the catalogue
(`off_products.json`), so the demo runs offline and never depends on the service being up.
"""
import json
import re
import unicodedata

import httpx

from . import config

SEARCH_URL = "https://search.openfoodfacts.org/search"
PRODUCT_URL = "https://world.openfoodfacts.org/api/v2/product/{code}.json"
PAGE_URL = "https://world.openfoodfacts.org/product/{code}"
USER_AGENT = "ShelfAgent-GenAI-Hackathon/0.1 (+https://github.com/Koutsourelis/Gen-AI-Hackathon-Agent)"
FIELDS = ("code,product_name,product_name_el,product_name_en,brands,quantity,categories_tags,countries_tags,"
          "image_front_small_url")
LICENSE = "Open Food Facts, ODbL 1.0"

MATCH = 0.6          # score from which a candidate counts as the product (brand must match too)

# The catalogue's category (column `category`) → Open Food Facts category tag. Used both to search and to score.
CATEGORY_TAGS = {
    "Ελαιόλαδο": "olive-oils", "Ελιές": "olives", "Ταχίνι": "tahini", "Μέλι": "honeys", "Ζυμαρικά": "pastas",
    "Δημητριακά": "cereals-and-their-products", "Μπαχαρικά": "spices", "Αλλαντικά": "sausages",
    "Καφές": "coffees", "Κακάο": "cocoa-and-its-products", "Τσάι": "teas",
}

_GREEK = str.maketrans({
    "α": "a", "β": "v", "γ": "g", "δ": "d", "ε": "e", "ζ": "z", "η": "i", "θ": "th", "ι": "i", "κ": "k",
    "λ": "l", "μ": "m", "ν": "n", "ξ": "x", "ο": "o", "π": "p", "ρ": "r", "σ": "s", "ς": "s", "τ": "t",
    "υ": "y", "φ": "f", "χ": "ch", "ψ": "ps", "ω": "o",
})


def norm(text: str) -> str:
    """Lower case, no accents, Greek written in Latin letters: 'Αγρινό' and 'AGRINO' both become 'agrino'."""
    text = unicodedata.normalize("NFD", (text or "").lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", text.translate(_GREEK)).strip()


def _tokens(text: str) -> set[str]:
    return {t for t in norm(text).split() if len(t) > 1}


# Words of our Greek catalogue names (after norm()) → how Open Food Facts usually writes them, mostly in English.
# Without this 'Πράσινες ελιές' cannot tell green olives from Kalamata olives.
SYNONYMS = {
    "prasines": {"green"}, "kalamon": {"kalamata", "kalamta"}, "elies": {"olives"}, "elaiolado": {"olive", "oil"},
    "partheno": {"virgin"}, "exairetiko": {"extra"}, "tachini": {"tahini"}, "meli": {"honey"}, "thymarisio": {"thyme"},
    "kritharaki": {"kritharaki", "orzo", "risoni"}, "chylopites": {"hilopites", "chilopites"},
    "pligouri": {"bulgur", "pligouri"}, "fylla": {"leaves"}, "dafnis": {"bay", "laurel"},
    "loukanika": {"sausages", "sausage"}, "choriatika": {"village", "country"},
}


def _grams(text: str) -> float | None:
    """Pack size in grams or millilitres: '500g' → 500, '1L' → 1000, '1 kg' → 1000, 'x20' → None."""
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(kg|g|gr|ml|l|lt)\b", (text or "").lower())
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    return value * 1000 if m.group(2) in ("kg", "l", "lt") else value


def record(hit: dict) -> dict:
    """One Open Food Facts product in the shape the rest of the code uses."""
    brands = hit.get("brands") or []
    if isinstance(brands, str):
        brands = [b.strip() for b in brands.split(",") if b.strip()]
    code = str(hit.get("code") or "")
    return {
        "barcode": code,
        "name": hit.get("product_name_el") or hit.get("product_name") or hit.get("product_name_en") or "",
        "brand": ", ".join(brands),
        "quantity": hit.get("quantity") or "",
        "categories": [c.split(":", 1)[-1] for c in (hit.get("categories_tags") or [])],
        "countries": [c.split(":", 1)[-1] for c in (hit.get("countries_tags") or [])],
        "image": hit.get("image_front_small_url") or "",
        "url": PAGE_URL.format(code=code) if code else "",
    }


def brand_matches(candidate: dict, brand: str) -> bool:
    """Every word of our brand appears in one of the candidate's brands: 'Delphi' fits 'Delphi', 'Cretan Gold'
    does not fit 'Cretan'."""
    want = set(norm(brand).split())
    return bool(want) and any(want <= set(norm(b).split()) for b in candidate.get("brand", "").split(","))


def category_matches(candidate: dict, category: str) -> bool:
    tag = CATEGORY_TAGS.get(category)
    return bool(tag) and any(c == tag or c.endswith("-" + tag) for c in candidate.get("categories", []))


def is_greek(candidate: dict) -> bool:
    """Sold in Greece, or a Greek GS1 barcode (prefix 520)."""
    return "greece" in candidate.get("countries", []) or candidate.get("barcode", "").startswith("520")


def name_overlap(candidate: dict, name: str) -> float:
    """Share of the words of our name (not the pack size) found in the candidate's name or categories, 0 to 1.
    A Greek word also counts when its usual English form (SYNONYMS) is there."""
    want = {t for t in _tokens(name) if not re.fullmatch(r"\d+[a-z]*", t)}     # words, not '500g' or '1l'
    if not want:
        return 0.0
    have = _tokens(candidate.get("name", "")) | _tokens(" ".join(candidate.get("categories", [])))
    return sum(1 for t in want if t in have or SYNONYMS.get(t, set()) & have) / len(want)


def score(candidate: dict, name: str, brand: str = "", category: str = "") -> float:
    """How well an Open Food Facts record fits a catalogue row, 0 to 1.

    brand 0.4 · category 0.25 · words of the name 0.15 · pack size 0.1 · Greek product 0.1. Simple on purpose: the
    score is shown next to the match, and anything under MATCH is reported as weak, for a person to confirm.
    """
    s = 0.4 * brand_matches(candidate, brand) + 0.25 * category_matches(candidate, category)
    s += 0.15 * name_overlap(candidate, name)
    g, cg = _grams(name), _grams(candidate.get("quantity", "")) or _grams(candidate.get("name", ""))
    if g and cg and abs(g - cg) <= 0.05 * g:
        s += 0.1
    s += 0.1 * is_greek(candidate)
    return round(s, 2)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=20, headers={"User-Agent": USER_AGENT}, follow_redirects=True)


async def search(query: str, size: int = 20) -> list[dict]:
    """Full-text search. Accepts the service's query syntax, e.g. 'misko AND categories_tags:"en:pastas"'."""
    async with _client() as c:
        r = await c.get(SEARCH_URL, params={"q": query, "page_size": size, "fields": FIELDS, "langs": "el,en"})
        r.raise_for_status()
        return [record(h) for h in r.json().get("hits", [])]


async def by_barcode(code: str) -> dict | None:
    async with _client() as c:
        r = await c.get(PRODUCT_URL.format(code=code), params={"fields": FIELDS})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        data = r.json()
        return record({**data.get("product", {}), "code": data.get("code", code)}) if data.get("status") == 1 else None


def queries(name: str, brand: str = "", category: str = "") -> list[str]:
    """Searches to try, most precise first: brand within the category, brand and name, then the category in Greece
    (which finds a comparable Greek product when the brand is not in the database)."""
    tag = CATEGORY_TAGS.get(category)
    out = []
    if brand and tag:
        out.append(f'{norm(brand)} AND categories_tags:"en:{tag}"')
    if brand:
        out.append(f"{brand} {name}")
    if tag:
        out.append(f'categories_tags:"en:{tag}" AND countries_tags:"en:greece"')
    return out or [name]


def verdict(candidate: dict, name: str, brand: str, category: str) -> str:
    """'matched': same brand, same kind of product, score ≥ MATCH. 'similar': other brand, but same category and
    at least half the words of the name (a comparable product). 'weak': anything else, a guess for a person to check."""
    s = score(candidate, name, brand, category)
    if s >= MATCH and brand_matches(candidate, brand) and (category_matches(candidate, category) or not category):
        return "matched"
    if category_matches(candidate, category) and name_overlap(candidate, name) >= 0.5:
        return "similar"
    return "weak"


async def identify(name: str, brand: str = "", category: str = "", barcode: str = "") -> dict:
    """Find a catalogue row in Open Food Facts.

    With a barcode: exact lookup. Without: the searches of queries(), stopping at the first that gives a match; the
    best scoring hit wins. Returns status 'matched', 'similar', 'weak' (see verdict()) or 'not_found', with up to
    three runner-up candidates.
    """
    if barcode:
        hit = await by_barcode(barcode)
        if hit:
            return {"status": "matched", "score": 1.0, "how": "barcode", "match": hit, "candidates": []}
    seen: dict[str, dict] = {}
    rank = lambda h: score(h, name, brand, category)  # noqa: E731
    for query in queries(name, brand, category):
        for hit in await search(query):
            if hit["barcode"]:
                seen.setdefault(hit["barcode"], hit)
        best = max(seen.values(), key=rank, default=None)
        if best and verdict(best, name, brand, category) == "matched":
            break
    ranked = sorted(seen.values(), key=rank, reverse=True)
    if not ranked:
        return {"status": "not_found", "score": 0.0, "how": "search", "match": None, "candidates": []}
    best = ranked[0]
    return {"status": verdict(best, name, brand, category), "score": rank(best), "how": "search", "match": best,
            "candidates": [{**h, "score": rank(h)} for h in ranked[1:4]]}


# --- the saved lookups of the active shelf set ---------------------------------------------------------------

def cache_path():
    return config.SHELF_DIR / "off_products.json"


def load_cache() -> dict:
    """{sku: identify() result} saved by scripts/fetch_off.py; empty if the set has not been looked up yet."""
    p = cache_path()
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8")).get("products", {})
