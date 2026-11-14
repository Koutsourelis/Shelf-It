# Shelf data

Three small CSV files describe the shelf the agent looks after. Edit them by hand; no code changes needed.
After every edit run `python scripts/make_demo_data.py` to rebuild the database.

| File | One row is | Columns |
|---|---|---|
| `catalog.csv` | a product | `sku`, `name`, `brand`, `unit_cost`, `unit_price`, `daily_units` (average units sold per day, used to generate sales), `case_size` (units per case when ordering) |
| `planogram.csv` | a slot on the shelf | `shelf` (1 = top), `level` (`top` / `eye` / `bottom`), `position` (1 = leftmost), `sku`, `facings` (units side by side in the front row), `depth` (units behind each facing) |
| `backroom.csv` | stock in the backroom | `sku`, `on_hand` |

`photos/` holds shelf photos. A file `<photo>.reading.json` next to a photo is what the offline mock model
"sees" in it, so the whole flow can be tested with no API key.

**Everything here is a placeholder.** Product names and brands are invented, sales are generated. Replace the
catalogue and planogram with the real products on the demo shelf, and the sample photos with real ones.
Never use an employer's planograms, sales or store photos.
