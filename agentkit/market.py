"""Daily sales of each product, anchored on official Greek household purchases.

No public source in Greece gives sales per product or per brand. ELSTAT's Household Budget Survey does give, per
food item, the average quantity a household buys each month (2025, table 2.00, whole country, all households).
From that the shelf's daily sales of a category follow with three declared assumptions:

    grams_per_day(category) = ELSTAT grams per household per month × households × store_share × shelf_share
                              / days_per_month
    units_per_day(product)  = grams_per_day(category) × weight(product) / Σ weights / grams per pack

households, store_share and shelf_share live in <shelf set>/market.json, each with the reason for its value. The split
inside a category is equal in grams unless catalog.csv has a sales_weight column: that split is what only a retailer's
own sales data can give. scripts/calibrate_sales.py writes the result into catalog.csv (daily_units, sales_source).
"""
import csv
import json
import re

from . import config
from .off import _grams

HBS_FILE = config.DATA_DIR / "shelf" / "elstat_hbs_2025.csv"
HBS_SOURCE = "ΕΛΣΤΑΤ, Έρευνα Οικογενειακών Προϋπολογισμών 2025, πίνακας 2.00"
HBS_URL = "https://www.statistics.gr/en/statistics/-/publication/SFA05/2025"


def load_hbs() -> dict[str, dict]:
    """{coicop: row} of the ELSTAT extract: item, unit, per_household_month (grams)."""
    with open(HBS_FILE, encoding="utf-8", newline="") as f:
        return {r["coicop"]: {**r, "per_household_month": float(r["per_household_month"])} for r in csv.DictReader(f)}


def load_model(shelf_dir=None) -> dict | None:
    p = (shelf_dir or config.SHELF_DIR) / "market.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def pack_grams(name: str, grams_per_ml: float | None = None) -> float | None:
    """Grams in one pack, from the product name ('Ελαιόλαδο 1L' with 0.916 g/ml → 916)."""
    g = _grams(name)
    if g is None:
        return None
    is_volume = bool(re.search(r"\d\s*(ml|l|lt)\b", name.lower()))
    return g * grams_per_ml if (grams_per_ml and is_volume) else g


def category_grams_per_day(cat: dict, model: dict, hbs: dict) -> tuple[float, float]:
    """(grams a day this shelf sells of the category, ELSTAT grams per household per month)."""
    per_hh = sum(hbs[c]["per_household_month"] for c in cat["coicop"])
    grams = per_hh * model["households"] * model["store_share"] * cat["shelf_share"] / model["days_per_month"]
    return grams, per_hh


def plan(catalog: list[dict], model: dict, hbs: dict) -> list[dict]:
    """One entry per catalogue row: daily_units, the expression behind it and its source text.

    Rows whose category has no ELSTAT item (market.json maps it to null or leaves it out) or whose pack size cannot
    be read keep their current daily_units and are marked as an assumption."""
    cats = model.get("categories", {})
    by_cat: dict[str, list[dict]] = {}
    for row in catalog:
        by_cat.setdefault(row.get("category", ""), []).append(row)
    out = []
    for category, rows in by_cat.items():
        cat = cats.get(category)
        sizes = {r["sku"]: pack_grams(r["name"], (cat or {}).get("grams_per_ml")) for r in rows}
        if not cat or any(s is None for s in sizes.values()):
            why = "δεν υπάρχει είδος της ΕΛΣΤΑΤ για την κατηγορία" if not cat else "άγνωστο μέγεθος συσκευασίας"
            out += [{"sku": r["sku"], "daily_units": float(r["daily_units"]), "expression": "",
                     "sales_source": f"υπόθεση ({why})"} for r in rows]
            continue
        grams, per_hh = category_grams_per_day(cat, model, hbs)
        weights = {r["sku"]: float(r.get("sales_weight") or 1) for r in rows}
        total = sum(weights.values())
        for r in rows:
            units = grams * weights[r["sku"]] / total / sizes[r["sku"]]
            expr = (f"{per_hh:g} g/νοικοκυριό/μήνα × {model['households']} νοικοκυριά × {model['store_share']:g} × "
                    f"{cat['shelf_share']:g} / {model['days_per_month']:g} × {weights[r['sku']]:g}/{total:g} "
                    f"/ {sizes[r['sku']]:g} g")
            out.append({"sku": r["sku"], "daily_units": round(units, 1), "expression": expr,
                        "sales_source": f"{HBS_SOURCE} (κωδ. {'+'.join(cat['coicop'])}) × υποθέσεις του market.json"})
    order = {r["sku"]: i for i, r in enumerate(catalog)}
    return sorted(out, key=lambda e: order[e["sku"]])


def unit_cost(price: float, model: dict) -> float | None:
    """Purchase cost from the sector's public gross margin: cost = price × (1 − gross_margin).

    The margin is applied to the shelf price; VAT is not split out in the demo. Same margin for every product, because
    no public source gives it per category. None when market.json has no gross_margin."""
    m = model.get("gross_margin")
    return round(price * (1 - m), 2) if m is not None else None


def cost_source(model: dict) -> str:
    return f"μικτό περιθώριο κλάδου {model['gross_margin'] * 100:.1f}% (ΙΕΛΚΑ, NielsenIQ, ΕΣΕ 2025)· ίδιο σε όλους"
