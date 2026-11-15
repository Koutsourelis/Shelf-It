"""Set daily_units in catalog.csv from ELSTAT household purchases (agentkit/market.py).

    SHELF_SET=trad python scripts/calibrate_sales.py            # writes catalog.csv
    SHELF_SET=trad python scripts/calibrate_sales.py --dry-run  # only prints

Needs <shelf set>/market.json. Adds or updates the column sales_source, so every number says where it comes from.
Run scripts/make_demo_data.py afterwards to rebuild the 28 days of sales.
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentkit import config, market  # noqa: E402


def main(dry_run: bool) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    model = market.load_model()
    if not model:
        print(f"Δεν υπάρχει {config.SHELF_DIR / 'market.json'}: τίποτα να υπολογιστεί.")
        return 1
    path = config.SHELF_DIR / "catalog.csv"
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields, catalog = list(reader.fieldnames), [r for r in reader if any(r.values())]
    result = {e["sku"]: e for e in market.plan(catalog, model, market.load_hbs())}
    for row in catalog:
        e = result[row["sku"]]
        print(f"{row['sku']:4} {row['daily_units']:>5} → {e['daily_units']:>5}  {row['name'][:32]:32}  "
              f"{e['expression'] or e['sales_source']}")
        row["daily_units"] = f"{e['daily_units']:g}"
        row["sales_source"] = e["sales_source"]
    if "sales_source" not in fields:
        fields.append("sales_source")
    if dry_run:
        print("\n--dry-run: το catalog.csv δεν άλλαξε.")
        return 0
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(catalog)
    print(f"\nΓράφτηκε {path.relative_to(config.ROOT)}. Τώρα: python scripts/make_demo_data.py")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    sys.exit(main(ap.parse_args().dry_run))
