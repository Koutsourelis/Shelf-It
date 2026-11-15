"""Look up every product of the active shelf set in Open Food Facts and save the result.

    python scripts/fetch_off.py                 # data/shelf (coffee set)
    SHELF_SET=trad python scripts/fetch_off.py  # the real-photo set

Writes off_products.json next to catalog.csv: barcode, name, brand, pack size, category and image for each sku,
the match score, and runner-up candidates when the match is weak. The demo reads that file, so it runs offline.

A wrong match is fixed by putting the right barcode in the optional `barcode` column of catalog.csv and running
the script again: a barcode is an exact lookup. Waits 7 seconds between products to stay under the service's limit
of about 10 searches a minute.
"""
import argparse
import asyncio
import csv
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentkit import config, off  # noqa: E402


async def main(pause: float) -> int:
    with open(config.SHELF_DIR / "catalog.csv", encoding="utf-8-sig", newline="") as f:
        catalog = [r for r in csv.DictReader(f) if any(r.values())]
    products, counts = {}, {"matched": 0, "similar": 0, "weak": 0, "not_found": 0, "error": 0}
    for i, row in enumerate(catalog):
        if i:
            time.sleep(pause)
        try:
            res = await off.identify(row["name"], row.get("brand", ""), row.get("category", ""),
                                     (row.get("barcode") or "").strip())
        except Exception as e:  # the service can be down; the row is reported and skipped
            res = {"status": "error", "error": f"{type(e).__name__}: {e}", "match": None, "candidates": []}
        products[row["sku"]] = {"query": {k: row.get(k, "") for k in ("name", "brand", "category")}, **res}
        counts[res["status"]] += 1
        m = res.get("match") or {}
        print(f"{row['sku']:4} {res['status']:9} {res.get('score', 0):.2f}  {row['brand']} {row['name']}  →  "
              f"{m.get('barcode', '-')} {m.get('brand', '')} | {m.get('name', '')} {m.get('quantity', '')}"
              + (f"  ({res['error']})" if res.get("error") else ""))
    out = off.cache_path()
    out.write_text(json.dumps({
        "source": off.LICENSE, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "shelf_set": config.SHELF_SET or "shelf", "counts": counts, "products": products,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n{counts} → {out.relative_to(config.ROOT)}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pause", type=float, default=7.0, help="seconds between products (default 7)")
    sys.exit(asyncio.run(main(ap.parse_args().pause)))
