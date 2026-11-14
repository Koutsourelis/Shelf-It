"""Πακέτο τεκμηρίων ανά προϊόν: ό,τι επιτρέπεται να πει το μοντέλο για ένα προϊόν, με την πηγή του.

Το πακέτο έχει δύο μέρη:
- Στοιχεία του καταστήματος: τιμή και κόστος από τον κατάλογο (με την πηγή τους), περιθώριο από κώδικα.
- Εξωτερικά τεκμήρια για την κατηγορία του προϊόντος: ισχυρισμοί από σελίδες του διαδικτύου, ο καθένας με
  URL, ημερομηνία, γεωγραφία και το αυτούσιο απόσπασμα που τον στηρίζει.

Κανόνες που εφαρμόζει ο κώδικας, όχι το μοντέλο:
- Ισχυρισμός μένει μόνο αν το απόσπασμά του υπάρχει αυτούσιο στο κείμενο της πηγής.
- Αριθμός μένει μόνο αν υπάρχει μέσα στο απόσπασμα ΚΑΙ η πηγή έχει ημερομηνία. Αλλιώς ο ισχυρισμός μένει χωρίς αριθμό.
- Με λιγότερες από EVIDENCE_MIN_SOURCES πηγές το πακέτο βγαίνει «insufficient» και το λέει ρητά.

Οι πηγές αποθηκεύονται στο data/evidence/, ώστε το demo να δουλεύει και χωρίς δίκτυο.
Μορφή του πακέτου: planning/EVIDENCE.md.
"""
import asyncio
import csv
import hashlib
import json
import re
from datetime import date, datetime
from urllib.parse import urlparse

import httpx

from .. import config
from ..llm.structured import structured
from . import tool
from .data import run_sql
from .web import _UA, html_to_text

CACHE_DIR = config.DATA_DIR / "evidence"
SOURCES_CSV = config.DATA_DIR / "shelf" / "sources.csv"
MAX_SOURCES = 6
MAX_LISTED_QUERIES = 3
GENERIC_QUERIES = 2
PAGE_CHARS = 5000

CLAIMS_SCHEMA = {
    "type": "object",
    "properties": {"claims": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "source": {"type": "integer", "description": "Ο αριθμός της πηγής, όπως δίνεται"},
                "claim": {"type": "string", "description": "Ο ισχυρισμός σε μία πρόταση, στα ελληνικά"},
                "quote": {"type": "string", "description": "Το αυτούσιο απόσπασμα της πηγής που τον στηρίζει, αντιγραμμένο χωρίς αλλαγές"},
                "value": {"anyOf": [{"type": "number"}, {"type": "null"}],
                          "description": "Ο αριθμός του ισχυρισμού αν υπάρχει μέσα στο απόσπασμα, αλλιώς null"},
                "unit": {"anyOf": [{"type": "string"}, {"type": "null"}], "description": "π.χ. %, €, εκατ. €"},
                "published": {"anyOf": [{"type": "string"}, {"type": "null"}],
                              "description": "Ημερομηνία δημοσίευσης YYYY-MM-DD αν αναγράφεται στην πηγή, αλλιώς null"},
                "region": {"anyOf": [{"type": "string"}, {"type": "null"}],
                           "description": "Η γεωγραφία που αφορά ο ισχυρισμός αν αναγράφεται, αλλιώς null"},
            },
            "required": ["source", "claim", "quote", "value", "unit", "published", "region"],
            "additionalProperties": False,
        },
    }},
    "required": ["claims"],
    "additionalProperties": False,
}
CLAIMS_SYSTEM = (
    "Εξάγεις τεκμήρια από κείμενα σελίδων για μια κατηγορία προϊόντων λιανικής. Γράφεις μόνο ό,τι αναγράφεται ρητά "
    "στην πηγή. Κάθε ισχυρισμός συνοδεύεται από το αυτούσιο απόσπασμα που τον στηρίζει. Δεν υπολογίζεις, δεν "
    "συμπεραίνεις και δεν συνδυάζεις πηγές. Αν μια πηγή δεν λέει κάτι χρήσιμο για ζήτηση, πωλήσεις, τιμές ή "
    "προτιμήσεις καταναλωτών στην κατηγορία, δεν βγάζεις τίποτα από αυτήν. Λίγα και σίγουρα, όχι πολλά.")


# --- Αναζήτηση --------------------------------------------------------------------------------

def _harvest(node, out: list[dict]) -> None:
    """Μαζεύει αποτελέσματα από JSON άγνωστης μορφής: κάθε αντικείμενο που έχει διεύθυνση και τίτλο."""
    if isinstance(node, list):
        for item in node:
            _harvest(item, out)
    elif isinstance(node, dict):
        url = next((node[k] for k in ("url", "link", "href") if isinstance(node.get(k), str)), None)
        title = next((node[k] for k in ("title", "name", "headline") if isinstance(node.get(k), str)), None)
        if url and title and url.startswith("http"):
            out.append({
                "title": title, "url": url,
                "snippet": next((node[k] for k in ("snippet", "description", "body", "content", "text")
                                 if isinstance(node.get(k), str)), ""),
                "published": next((node[k] for k in ("date", "published", "publishedDate", "published_at", "published_date")
                                   if isinstance(node.get(k), str)), None)})
        else:
            for value in node.values():
                _harvest(value, out)


async def treg_call(tool_id: str, body: dict, log: list | None = None):
    """Μία κλήση σε εργαλείο του treg (POST με σώμα JSON). Γράφει στο `log` το εργαλείο, το κόστος και το αποτέλεσμα.

    Το κόστος έρχεται στο header X-Treg-Cost-Micro (εκατομμυριοστά του δολαρίου). Το token δεν γράφεται πουθενά.
    """
    headers = {"X-Treg-Token": config.TREG_TOKEN, "content-type": "application/json"}
    if config.TREG_ORG:
        headers["X-Treg-Org"] = config.TREG_ORG
    entry = {"tool": tool_id, "cost_usd": None, "ok": False, "error": None}
    if log is not None:
        log.append(entry)
    try:
        async with httpx.AsyncClient(timeout=40, headers=headers) as client:
            r = await client.post(f"https://treg.to/call/{tool_id}", json=body)
        micro = r.headers.get("X-Treg-Cost-Micro")
        entry["cost_usd"] = round(int(micro) / 1_000_000, 6) if micro and micro.isdigit() else None
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        data = r.json()
    except Exception as e:
        entry["error"] = f"{type(e).__name__}: {str(e)[:200]}"
        raise
    entry["ok"] = True
    return data


async def _search_treg(query: str, log: list | None = None) -> list[dict]:
    """Ειδήσεις πρώτα (έχουν ημερομηνία), μετά γενική αναζήτηση. Αν αποτύχει το ένα, μένει το άλλο."""
    out: list[dict] = []
    for tool_id in (config.TREG_NEWS_TOOL, config.TREG_SEARCH_TOOL):
        if not tool_id:
            continue
        try:
            _harvest(await treg_call(tool_id, {config.TREG_QUERY_PARAM: query}, log), out)
        except Exception:
            continue
    return out


def _search_ddg(query: str) -> list[dict]:
    from ddgs import DDGS
    out = []
    try:                                   # οι ειδήσεις έχουν ημερομηνία, γι' αυτό πάνε πρώτες
        for r in DDGS().news(query, max_results=6):
            out.append({"title": r.get("title"), "url": r.get("url"), "snippet": r.get("body") or "",
                        "published": r.get("date")})
    except Exception:
        pass
    try:
        for r in DDGS().text(query, max_results=6):
            out.append({"title": r.get("title"), "url": r.get("href"), "snippet": r.get("body") or "", "published": None})
    except Exception:
        if not out:
            raise
    return [r for r in out if r["url"] and r["title"]]


async def search(query: str, log: list | None = None) -> tuple[str, list[dict]]:
    """Επιστρέφει (πάροχος, αποτελέσματα). Με token treg δοκιμάζει πρώτα εκεί, αλλιώς DuckDuckGo."""
    if config.TREG_TOKEN:
        results = await _search_treg(query, log)
        if results:
            return "treg", results
    try:
        return "duckduckgo", await asyncio.to_thread(_search_ddg, query)
    except Exception:
        return "none", []


# --- Τάση αναζητήσεων (Google Trends μέσω treg) -------------------------------------------------

def _series(node, best: list | None = None) -> list[tuple[str, float]]:
    """Η μεγαλύτερη χρονοσειρά (ημερομηνία, τιμή) μέσα σε JSON άγνωστης μορφής."""
    best = [] if best is None else best
    if isinstance(node, list):
        points = []
        for item in node:
            if not isinstance(item, dict):
                continue
            day = next((_iso(item[k]) for k in ("date_from", "date", "time", "timestamp")
                        if item.get(k) is not None and _iso(item[k])), None)
            raw = next((item[k] for k in ("value", "values", "interest", "extracted_value") if k in item), None)
            if isinstance(raw, list) and raw:
                raw = raw[0].get("extracted_value", raw[0].get("value")) if isinstance(raw[0], dict) else raw[0]
            if day and isinstance(raw, (int, float)) and not isinstance(raw, bool):
                points.append((day, float(raw)))
        if len(points) > len(best):
            best[:] = points
        for item in node:
            _series(item, best)
    elif isinstance(node, dict):
        for value in node.values():
            _series(value, best)
    return best


def trend_change(points: list[tuple[str, float]]) -> dict | None:
    """Μεταβολή του δείκτη: μέσος όρος του τελευταίου τετάρτου των σημείων έναντι του πρώτου. Κώδικας, όχι μοντέλο."""
    points = sorted(points)
    if len(points) < 8:
        return None
    k = max(len(points) // 4, 2)
    first = sum(v for _, v in points[:k]) / k
    last = sum(v for _, v in points[-k:]) / k
    if first <= 0:
        return None
    return {"change_pct": round(100 * (last - first) / first, 1), "first_avg": round(first, 1), "last_avg": round(last, 1),
            "from": points[0][0], "to": points[-1][0], "points": len(points)}


async def search_trend(keyword: str, log: list | None = None) -> dict:
    """Δείκτης ενδιαφέροντος αναζήτησης για μια λέξη. Αν δεν διαβάζεται χρονοσειρά, επιστρέφει μόνο τον λόγο."""
    base = {"keyword": keyword, "source": "Google Trends μέσω treg", "tool": config.TREG_TRENDS_TOOL}
    if not (config.TREG_TOKEN and config.TREG_TRENDS_TOOL):
        return {**base, "change": None, "note": "Δεν έχει ρυθμιστεί token ή εργαλείο τάσεων."}
    try:
        body = {"keywords": keyword, **json.loads(config.TREG_TRENDS_EXTRA or "{}")}
        change = trend_change(_series(await treg_call(config.TREG_TRENDS_TOOL, body, log)))
    except Exception as e:
        return {**base, "change": None, "note": f"Η κλήση απέτυχε: {str(e)[:160]}"}
    return {**base, "change": change, "note": None if change else "Η απάντηση δεν είχε χρονοσειρά που να διαβάζεται."}


async def _page_text(url: str) -> str:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15, headers=_UA) as client:
            r = await client.get(url)
        if r.status_code < 400 and "html" in r.headers.get("content-type", ""):
            return html_to_text(r.text, PAGE_CHARS)
    except Exception:
        pass
    return ""


# --- Έλεγχοι με κώδικα ------------------------------------------------------------------------

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _iso(value) -> str | None:
    """Ημερομηνία σε μορφή YYYY-MM-DD, ή None αν δεν διαβάζεται ή είναι στο μέλλον."""
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        try:
            d = date.fromisoformat(str(value)[:10])
        except (TypeError, ValueError):
            return None
    return d.isoformat() if d <= date.today() else None


def _number_in(value: float, quote: str) -> bool:
    forms = {f"{value:g}", f"{value:g}".replace(".", ",")}
    if float(value).is_integer():
        forms.add(str(int(value)))
    return any(re.search(rf"(?<![\d.,]){re.escape(f)}(?![\d])", quote) for f in forms)


def verify_claims(claims: list, sources: list[dict]) -> tuple[list[dict], int]:
    """Κρατά μόνο ό,τι στηρίζεται στο κείμενο της πηγής. Επιστρέφει (τεκμήρια, πόσα απορρίφθηκαν)."""
    kept, dropped = [], 0
    for c in claims or []:
        try:
            src = sources[int(c.get("source")) - 1]
        except (TypeError, ValueError, IndexError):
            dropped += 1
            continue
        quote = str(c.get("quote") or "").strip()
        if len(quote) < 15 or _norm(quote) not in _norm(src["text"]):
            dropped += 1
            continue
        published = _iso(src.get("published")) or _iso(c.get("published"))
        value, note = c.get("value"), None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if not _number_in(value, quote):
                value, note = None, "ο αριθμός δεν υπάρχει στο απόσπασμα"
            elif not published:
                value, note = None, "η πηγή δεν έχει ημερομηνία"
        else:
            value = None
        kept.append({"claim": str(c.get("claim") or "").strip(), "value": value,
                     "unit": c.get("unit") if value is not None else None, "quote": quote, "url": src["url"],
                     "title": src["title"], "listed_source": src.get("listed_source"), "published": published, "region": c.get("region"), "note": note})
    return kept, dropped


# --- Πηγές ανά κατηγορία (data/shelf/sources.csv) -------------------------------------------------

def load_sources(category: str) -> list[dict]:
    """Οι πηγές της λίστας για μια κατηγορία: πρώτα οι δικές της, μετά όσες ισχύουν για όλες («*»)."""
    if not SOURCES_CSV.exists():
        return []
    with SOURCES_CSV.open(encoding="utf-8-sig", newline="") as f:
        rows = [{k: (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]
    wanted = _norm(category)
    return ([r for r in rows if _norm(r["category"]) == wanted and r["domain"]]
            + [r for r in rows if r["category"] == "*" and r["domain"]])


def plan_queries(category: str, audience: str, region: str, sources: list[dict]) -> list[str]:
    """Τα ερωτήματα μιας κατηγορίας: πρώτα όσα στοχεύουν πηγές της λίστας, μετά τα γενικά."""
    year = date.today().year
    listed = []
    for s in sources:
        if s["use"] == "search" and s["query"]:
            q = f"{s['query'].format(category=category, year=year, region=region)} {s['domain']}"
            if q not in listed:
                listed.append(q)
    who = f" {audience}" if audience else ""
    generic = [f"{category} αγορά {region} πωλήσεις τάση {year}",
               f"{category} καταναλωτές{who} {region} προτιμήσεις έρευνα",
               f"{category} κατανάλωση {region} εποχικότητα"]
    return listed[:MAX_LISTED_QUERIES] + generic[:GENERIC_QUERIES if listed else len(generic)]


def listed_source(url: str, sources: list[dict]) -> dict | None:
    """Η πηγή της λίστας στην οποία ανήκει μια διεύθυνση, ή None."""
    host = (urlparse(url).hostname or "").lower()
    return next((s for s in sources if host == s["domain"].lower() or host.endswith("." + s["domain"].lower())), None)


def rank_results(found: list[dict], sources: list[dict]) -> list[dict]:
    """Βάζει μπροστά τα αποτελέσματα από πηγές της λίστας, χωρίς να αλλάζει τη σειρά των υπολοίπων."""
    tagged = [{**r, "listed_source": (listed_source(r["url"], sources) or {}).get("name")} for r in found]
    return sorted(tagged, key=lambda r: r["listed_source"] is None)


# --- Τεκμήρια κατηγορίας (με αποθήκευση) ----------------------------------------------------------

def _cache_path(category: str, region: str, audience: str):
    key = f"{category}|{region}|{audience}".lower()
    return CACHE_DIR / f"{hashlib.md5(key.encode('utf-8')).hexdigest()[:10]}.json"


async def category_evidence(category: str, audience: str = "", refresh: bool = False) -> dict:
    region = config.EVIDENCE_REGION
    path = _cache_path(category, region, audience)
    if path.exists() and not refresh:
        return {**json.loads(path.read_text(encoding="utf-8")), "from_cache": True}
    base = {"category": category, "region": region, "audience": audience, "retrieved_at": date.today().isoformat(),
            "from_cache": False}
    if config.LLM_PROVIDER == "mock":
        return {**base, "provider": "none", "queries": [], "sources": 0, "dropped": 0, "evidence": [],
                "search_trend": None, "treg_calls": [],
                "reason": "Ψεύτικο μοντέλο: δεν έγινε αναζήτηση και δεν υπάρχουν αποθηκευμένες πηγές."}

    listed = load_sources(category)
    queries = plan_queries(category, audience, region, listed)
    calls: list[dict] = []
    trend = await search_trend(category, calls) if config.TREG_TOKEN else None
    provider, found, seen = "none", [], set()
    for q in queries:
        p, results = await search(q, calls)
        provider = p if results else provider
        for r in results:
            if r["url"] not in seen:
                seen.add(r["url"])
                found.append(r)
    found = rank_results(found, listed)[:MAX_SOURCES]
    pages = await asyncio.gather(*(_page_text(r["url"]) for r in found))
    sources = [{**r, "text": f"{r['title']}\n{r['snippet']}\n{page}"} for r, page in zip(found, pages)]
    if not sources:
        return {**base, "provider": provider, "queries": queries, "sources": 0, "dropped": 0, "evidence": [],
                "search_trend": trend, "treg_calls": calls, "reason": "Η αναζήτηση δεν επέστρεψε αποτελέσματα."}

    listing = "\n\n".join(f"ΠΗΓΗ {n}: {s['url']}\nΗμερομηνία από την αναζήτηση: {s.get('published') or 'άγνωστη'}\n{s['text']}"
                          for n, s in enumerate(sources, start=1))
    answer = await structured(
        CLAIMS_SYSTEM,
        f"Κατηγορία: {category}. Γεωγραφία που μας ενδιαφέρει: {region}."
        + (f" Κοινό που μας ενδιαφέρει: {audience}." if audience else "")
        + f"\n\nΒγάλε έως 8 τεκμήρια από τις παρακάτω πηγές.\n\n{listing}", CLAIMS_SCHEMA)
    evidence, dropped = verify_claims(answer.get("claims"), sources)
    result = {**base, "provider": provider, "queries": queries, "sources": len(sources), "dropped": dropped,
              "evidence": evidence, "search_trend": trend, "treg_calls": calls, "reason": None}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({k: v for k, v in result.items() if k != "from_cache"}, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return result


# --- Πακέτο προϊόντος -------------------------------------------------------------------------

async def build_pack(sku: str, audience: str = "", refresh: bool = False) -> dict:
    """Το πλήρες πακέτο για έναν κωδικό. Το χρησιμοποιούν το εργαλείο, το /api/evidence και το script."""
    _, rows = await asyncio.to_thread(
        run_sql, "select sku, name, brand, category, unit_price, price_source, unit_cost, cost_source "
                 "from products where sku = ?", [sku])
    if not rows:
        raise ValueError(f"Άγνωστος κωδικός: {sku}")
    sku, name, brand, category, price, price_source, cost, cost_source = rows[0]
    cat = await category_evidence(category or name, audience, refresh)

    urls = {e["url"] for e in cat["evidence"]}
    numeric = sum(1 for e in cat["evidence"] if e["value"] is not None)
    sufficient = len(urls) >= config.EVIDENCE_MIN_SOURCES
    reason = None if sufficient else (
        cat.get("reason") or f"Βρέθηκαν {len(urls)} πηγές με επαληθευμένο απόσπασμα· χρειάζονται τουλάχιστον "
                             f"{config.EVIDENCE_MIN_SOURCES}.")
    return {
        "sku": sku, "name": name, "brand": brand, "category": category,
        "region": cat["region"], "audience": audience or None,
        "price": {"value": price, "currency": "EUR", "source": price_source or None},
        "cost": {"value": cost, "currency": "EUR", "source": cost_source or None},
        "margin_pct": round(100 * (price - cost) / price, 1) if price else None,
        "status": "sufficient" if sufficient else "insufficient",
        "reason": reason,
        "sources": len(urls), "listed_sources": len({e["url"] for e in cat["evidence"] if e.get("listed_source")}),
        "numeric_evidence": numeric, "dropped_claims": cat.get("dropped", 0),
        "evidence": cat["evidence"],
        "search_trend": cat.get("search_trend"),
        "treg_calls": cat.get("treg_calls") or [],
        "treg_cost_usd": round(sum(c.get("cost_usd") or 0 for c in cat.get("treg_calls") or []), 6),
        "provider": cat.get("provider"), "retrieved_at": cat.get("retrieved_at"), "from_cache": cat["from_cache"],
    }


@tool(
    "product_evidence",
    "Πάρε το πακέτο τεκμηρίων ενός προϊόντος: τιμή, κόστος και περιθώριο με την πηγή τους, και εξωτερικά τεκμήρια "
    "για την κατηγορία του (ζήτηση, τάσεις, προτιμήσεις) με URL, ημερομηνία και αυτούσιο απόσπασμα. Αν το status "
    "είναι «insufficient», πες ρητά ότι δεν βρέθηκαν επαρκή δεδομένα και μη χρησιμοποιήσεις εξωτερικούς ισχυρισμούς. "
    "Αριθμούς τάσης αναφέρεις μόνο όσους έχουν value στο πακέτο, πάντα μαζί με την πηγή και την ημερομηνία τους. "
    "Το search_trend, αν έχει change, είναι η μεταβολή του ενδιαφέροντος αναζήτησης στο Google για την κατηγορία: "
    "ανέφερέ το ως ενδιαφέρον αναζήτησης με την περίοδό του, ποτέ ως πωλήσεις.",
    {"sku": {"type": "string", "description": "Κωδικός προϊόντος, π.χ. C04"},
     "audience": {"type": "string", "description": "Προαιρετικά: το κοινό που μας ενδιαφέρει, π.χ. «φοιτητές»"},
     "refresh": {"type": "boolean", "description": "true = νέα αναζήτηση αντί για τις αποθηκευμένες πηγές"}},
    required=["sku"],
)
async def product_evidence(ctx, sku: str, audience: str = "", refresh: bool = False) -> str:
    pack = await build_pack(sku.strip().upper(), audience.strip(), bool(refresh))
    ctx.audit("compute", label=f"{pack['sku']}: περιθώριο (%)", expression="round(100 * (price - cost) / price, 1)",
              variables={"price": pack["price"]["value"], "cost": pack["cost"]["value"]}, result=pack["margin_pct"])
    ctx.audit("extract", source=f"τεκμήρια κατηγορίας «{pack['category']}» ({pack['provider']})",
              values={"status": pack["status"], "πηγές": pack["sources"], "από τη λίστα πηγών": pack["listed_sources"],
                      "με αριθμό": pack["numeric_evidence"],
                      "απορρίφθηκαν": pack["dropped_claims"]})
    if pack["treg_calls"]:
        ctx.audit("compute", label=f"treg: κόστος {len(pack['treg_calls'])} κλήσεων για «{pack['category']}» ($)",
                  expression="sum(cost_usd of treg calls)",
                  variables={f"{n}. {c['tool']}": c.get("cost_usd") if c.get("ok") else f"απέτυχε: {c.get('error')}"
                             for n, c in enumerate(pack["treg_calls"], start=1)},
                  result=pack["treg_cost_usd"])
    change = (pack.get("search_trend") or {}).get("change")
    if change:
        ctx.audit("compute", label=f"Τάση αναζητήσεων «{pack['search_trend']['keyword']}» (%)",
                  expression="round(100 * (last_avg - first_avg) / first_avg, 1)",
                  variables={k: change[k] for k in ("first_avg", "last_avg", "from", "to", "points")},
                  result=change["change_pct"])
    return json.dumps(pack, ensure_ascii=False, indent=1)
