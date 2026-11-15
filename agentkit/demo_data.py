"""Δεδομένα του demo: ένα ράφι καταστήματος, η αποθήκη του και οι πωλήσεις του.

Ο κατάλογος, το πλανόγραμμα και το απόθεμα αποθήκης διαβάζονται από τα CSV του data/shelf/
(αλλάζουν με το χέρι, χωρίς κώδικα). Οι πωλήσεις είναι συνθετικές: παράγονται από τη στήλη
daily_units του καταλόγου. Καμία πραγματική εταιρεία, τιμή ή πώληση.
"""
import csv
import random
from datetime import date, timedelta

import duckdb

from . import config

SHELF_DIR = config.SHELF_DIR          # data/shelf ή data/shelf/sets/<SHELF_SET>
PHOTOS_DIR = SHELF_DIR / "photos"
DAYS = 28
# Οι στήλες του products που φτιάχνει η build(). Αν μια υπάρχουσα βάση δεν τις έχει όλες, είναι παλιά
# και το agentkit/tools/data.py την ξαναχτίζει.
PRODUCT_COLUMNS = {"sku", "name", "brand", "unit_cost", "unit_price", "case_size", "category",
                   "price_source", "cost_source"}


def _rows(name: str) -> list[dict]:
    with open(SHELF_DIR / name, encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f) if any(r.values())]


def build(today: date | None = None, seed: int = 42) -> dict:
    """Ξαναχτίζει ολόκληρη τη βάση από τα CSV. Σβήνει και ό,τι είχε διαβάσει ο agent από φωτογραφίες."""
    rnd = random.Random(seed)
    today = today or date.today()
    config.DATA_DIR.mkdir(exist_ok=True)

    from .tools import data as data_tools
    if data_tools._con is not None:        # κλείνουμε την κοινή σύνδεση πριν ξαναγράψουμε το αρχείο
        data_tools._con.close()
        data_tools._con = None
    if config.DB_PATH.exists():
        config.DB_PATH.unlink()
    con = duckdb.connect(str(config.DB_PATH))

    catalog = _rows("catalog.csv")
    con.execute("create table products(sku varchar, name varchar, brand varchar, unit_cost double, "
                "unit_price double, case_size int, category varchar, price_source varchar, cost_source varchar)")
    con.executemany("insert into products values (?,?,?,?,?,?,?,?,?)",
                    [(p["sku"], p["name"], p["brand"], float(p["unit_cost"]), float(p["unit_price"]),
                      int(p["case_size"]), p.get("category") or "", p.get("price_source") or "",
                      p.get("cost_source") or "") for p in catalog])

    planogram = _rows("planogram.csv")
    con.execute("create table planogram(shelf int, level varchar, position int, sku varchar, facings int, depth int)")
    con.executemany("insert into planogram values (?,?,?,?,?,?)",
                    [(int(r["shelf"]), r["level"], int(r["position"]), r["sku"], int(r["facings"]), int(r["depth"]))
                     for r in planogram])

    con.execute("create table backroom(sku varchar, on_hand int)")
    con.executemany("insert into backroom values (?,?)", [(r["sku"], int(r["on_hand"])) for r in _rows("backroom.csv")])

    # Συνθετικές ημερήσιες πωλήσεις του τμήματος, με εβδομαδιαία εποχικότητα.
    con.execute("create table sales(date date, sku varchar, qty int, revenue double, cost double)")
    sales = []
    for d in range(DAYS, 0, -1):
        day = today - timedelta(days=d)
        weekday = [0.9, 0.9, 1.0, 1.0, 1.25, 1.4, 0.0][day.weekday()]     # Κυριακή κλειστά
        for p in catalog:
            qty = max(0, round(float(p["daily_units"]) * weekday * rnd.uniform(0.8, 1.2)))
            sales.append((day, p["sku"], qty, round(qty * float(p["unit_price"]), 2),
                          round(qty * float(p["unit_cost"]), 2)))
    con.executemany("insert into sales values (?,?,?,?,?)", sales)

    # Πίνακες που γεμίζει ο agent όταν διαβάζει και ελέγχει μια φωτογραφία (agentkit/tools/shelf.py).
    con.execute("create table shelf_observation(photo varchar, shelf int, position int, sku varchar, label varchar, "
                "facings int, ymin int, xmin int, ymax int, xmax int)")
    con.execute("create table shelf_gaps(photo varchar, shelf int, ymin int, xmin int, ymax int, xmax int)")
    con.execute("create table shelf_issues(photo varchar, sku varchar, name varchar, shelf int, status varchar, "
                "planned_facings int, seen_facings int, detail varchar)")
    con.execute("create table replenishment(photo varchar, sku varchar, name varchar, missing_facings int, "
                "units_needed int, from_backroom int, to_order int, order_cases int)")
    con.execute("create table shelf_checks(checked_at timestamp, photo varchar, compliance_pct double, issues int)")
    con.close()
    return {"today": str(today), "products": len(catalog), "planogram_slots": len(planogram), "sales_rows": len(sales)}
