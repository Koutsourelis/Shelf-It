"""Συνθετικά δεδομένα για το demo. Όλα είναι φανταστικά: καμία πραγματική εταιρεία, τιμή ή πελάτης.

Η φανταστική επιχείρηση είναι η «Αγορά Plus», μικρή αλυσίδα χονδρικής με 4 καταστήματα.
Τα ίδια δεδομένα εξυπηρετούν τρία σενάρια: εμπορικός αναλυτής, προμήθειες, τιμολόγια.
"""
import csv
import json
import random
from datetime import date, timedelta

import duckdb

from . import config

SUPPLIERS = [
    (1, "Γαλακτοκομική Ηπείρου ΑΕ", "sales@galaktokomiki-ipeirou.example", 2),
    (2, "Ελαιώνες Μεσσηνίας ΟΕ", "orders@elaiones-messinias.example", 4),
    (3, "Ποτά Αιγαίου ΑΕ", "b2b@pota-aigaiou.example", 3),
    (4, "Αλευρόμυλοι Θεσσαλίας ΑΕ", "sales@alevromyloi-thessalias.example", 5),
    (5, "Καθαριστικά Νότου ΕΠΕ", "info@katharistika-notou.example", 3),
    (6, "Κατεψυγμένα Βορρά ΑΕ", "orders@katepsygmena-vorra.example", 2),
]

# (όνομα, κατηγορία, κύριος προμηθευτής, κόστος, τιμή πώλησης, μέση ημερήσια ποσότητα ανά κατάστημα)
PRODUCTS = [
    ("Φέτα ΠΟΠ 2kg", "Γαλακτοκομικά", 1, 15.80, 19.90, 22),
    ("Γιαούρτι στραγγιστό 1kg", "Γαλακτοκομικά", 1, 2.90, 3.80, 40),
    ("Γάλα φρέσκο 1L", "Γαλακτοκομικά", 1, 0.98, 1.29, 120),
    ("Κασέρι 1kg", "Γαλακτοκομικά", 1, 9.40, 12.20, 18),
    ("Βούτυρο 250g", "Γαλακτοκομικά", 1, 2.10, 2.85, 35),
    ("Κρέμα γάλακτος 1L", "Γαλακτοκομικά", 1, 3.20, 4.30, 28),
    ("Ελαιόλαδο εξαιρετικό 5L", "Λάδια & Ελιές", 2, 31.00, 37.90, 15),
    ("Ηλιέλαιο 10L", "Λάδια & Ελιές", 2, 14.50, 17.90, 20),
    ("Ελιές Καλαμών 3kg", "Λάδια & Ελιές", 2, 11.20, 14.50, 9),
    ("Ξίδι 5L", "Λάδια & Ελιές", 2, 2.60, 3.70, 8),
    ("Νερό 1.5L x6", "Ποτά", 3, 1.35, 1.89, 150),
    ("Αναψυκτικό cola 1.5L", "Ποτά", 3, 1.05, 1.49, 90),
    ("Μπίρα lager 500ml x24", "Ποτά", 3, 16.80, 21.50, 25),
    ("Χυμός πορτοκάλι 1L", "Ποτά", 3, 1.10, 1.59, 60),
    ("Κρασί λευκό 10L", "Ποτά", 3, 13.00, 17.50, 10),
    ("Σόδα 250ml x24", "Ποτά", 3, 5.90, 7.90, 22),
    ("Αλεύρι τ.70 25kg", "Αλεύρι & Ζυμαρικά", 4, 14.20, 17.40, 14),
    ("Μακαρόνια No6 500g x24", "Αλεύρι & Ζυμαρικά", 4, 13.90, 17.20, 20),
    ("Ρύζι καρολίνα 5kg", "Αλεύρι & Ζυμαρικά", 4, 6.80, 8.60, 16),
    ("Ζάχαρη 10kg", "Αλεύρι & Ζυμαρικά", 4, 8.10, 9.90, 18),
    ("Φρυγανιά τριμμένη 5kg", "Αλεύρι & Ζυμαρικά", 4, 5.40, 7.20, 7),
    ("Απορρυπαντικό πιάτων 4L", "Καθαριστικά", 5, 3.40, 4.90, 25),
    ("Χλωρίνη 4L", "Καθαριστικά", 5, 1.70, 2.60, 30),
    ("Χαρτί κουζίνας x12", "Καθαριστικά", 5, 6.20, 8.40, 28),
    ("Χαρτοπετσέτες x3000", "Καθαριστικά", 5, 9.80, 12.90, 20),
    ("Σακούλες απορριμμάτων x100", "Καθαριστικά", 5, 4.10, 5.80, 18),
    ("Πατάτες προτηγανισμένες 10kg", "Κατεψυγμένα", 6, 11.50, 14.90, 30),
    ("Καλαμάρι κατεψυγμένο 1kg", "Κατεψυγμένα", 6, 6.90, 9.20, 14),
    ("Γαρίδες 1kg", "Κατεψυγμένα", 6, 8.80, 11.90, 12),
    ("Σπανάκι κατεψυγμένο 2.5kg", "Κατεψυγμένα", 6, 3.90, 5.40, 10),
    ("Φύλλο κρούστας 2kg", "Κατεψυγμένα", 6, 4.60, 6.30, 9),
    ("Κοτομπουκιές 2.5kg", "Κατεψυγμένα", 6, 12.40, 15.90, 16),
]

STORES = [(1, "Αθήνα Κέντρο", "Αθήνα", 1.3), (2, "Πειραιάς", "Πειραιάς", 1.0),
          (3, "Θεσσαλονίκη", "Θεσσαλονίκη", 1.15), (4, "Πάτρα", "Πάτρα", 0.75)]

DAYS = 90


def build(today: date | None = None, seed: int = 42, side_files: bool = True) -> dict:
    """Ξαναχτίζει ολόκληρη τη βάση. Με side_files=False δεν αγγίζει τα CSV/JSON δίπλα της."""
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

    con.execute("create table suppliers(supplier_id int, name varchar, email varchar, lead_days int)")
    con.executemany("insert into suppliers values (?,?,?,?)", SUPPLIERS)
    con.execute("create table stores(store_id int, name varchar, city varchar)")
    con.executemany("insert into stores values (?,?,?)", [s[:3] for s in STORES])

    con.execute("create table products(sku varchar, name varchar, category varchar, supplier_id int, "
                "unit_cost double, unit_price double)")
    products = []
    for i, (name, cat, sup, cost, price, base) in enumerate(PRODUCTS, start=1):
        products.append((f"P{i:03d}", name, cat, sup, cost, price, base))
    con.executemany("insert into products values (?,?,?,?,?,?)", [p[:6] for p in products])

    # Ημερήσιες πωλήσεις ανά κατάστημα και προϊόν, με εβδομαδιαία εποχικότητα και ελαφρά ανοδική τάση.
    con.execute("create table sales(date date, store_id int, sku varchar, qty int, revenue double, cost double)")
    rows = []
    for d in range(DAYS, 0, -1):
        day = today - timedelta(days=d - 1)
        weekday = [1.0, 0.95, 1.0, 1.05, 1.25, 1.1, 0.35][day.weekday()]
        trend = 1 + 0.0012 * (DAYS - d)
        for store_id, _, _, size in STORES:
            for sku, _, _, _, cost, price, base in products:
                qty = max(0, round(base * size * weekday * trend * rnd.uniform(0.85, 1.15)))
                rows.append((day, store_id, sku, qty, round(qty * price, 2), round(qty * cost, 2)))
    con.executemany("insert into sales values (?,?,?,?,?,?)", rows)

    # Απόθεμα ανά κατάστημα.
    con.execute("create table stock(store_id int, sku varchar, on_hand int, reorder_point int)")
    stock = []
    for store_id, _, _, size in STORES:
        for sku, *_rest, base in products:
            daily = base * size
            stock.append((store_id, sku, round(daily * rnd.uniform(6, 12)), round(daily * 4)))
    con.executemany("insert into stock values (?,?,?,?)", stock)

    # Τιμοκατάλογοι: κάθε προϊόν το προσφέρουν 2-3 προμηθευτές σε διαφορετικές τιμές (για το σενάριο προμηθειών).
    con.execute("create table supplier_prices(supplier_id int, sku varchar, price double, min_qty int, valid_from date)")
    offers = []
    for sku, _, _, main_sup, cost, *_ in products:
        offers.append((main_sup, sku, cost, 1, today - timedelta(days=30)))
        for other in rnd.sample([s[0] for s in SUPPLIERS if s[0] != main_sup], k=rnd.choice([1, 2])):
            offers.append((other, sku, round(cost * rnd.uniform(0.92, 1.12), 2), rnd.choice([1, 5, 10]),
                           today - timedelta(days=rnd.randint(5, 40))))
    con.executemany("insert into supplier_prices values (?,?,?,?,?)", offers)

    # Εβδομαδιαίες ανάγκες ενός μικρού πελάτη (εστιατόριο) για το σενάριο προμηθειών.
    con.execute("create table customer_weekly_needs(customer varchar, sku varchar, weekly_qty int)")
    needs = [("Ταβέρνα Το Λιμανάκι", p[0], q) for p, q in zip(
        [products[i] for i in (0, 1, 6, 7, 10, 12, 16, 18, 21, 23, 26, 27)],
        (6, 10, 2, 3, 20, 4, 2, 3, 4, 5, 8, 10))]
    con.executemany("insert into customer_weekly_needs values (?,?,?)", needs)

    # Τιμολόγια & τράπεζα: 12 πληρωμές, 10 τιμολόγια στο αρχείο → 2 λείπουν.
    con.execute("create table bank_transactions(date date, description varchar, counterparty varchar, amount double)")
    con.execute("create table invoices(invoice_no varchar, supplier_id int, date date, net double, vat double, "
                "total double, source varchar, file varchar)")
    invoices, bank = [], []
    for n in range(12):
        sup = SUPPLIERS[n % len(SUPPLIERS)]
        inv_date = today - timedelta(days=45 - n * 3)
        net = round(rnd.uniform(380, 2900), 2)
        vat = round(net * 0.24, 2)
        total = round(net + vat, 2)
        number = f"INV-{inv_date.year}-{400 + n:04d}"
        bank.append((inv_date + timedelta(days=rnd.randint(5, 12)), f"ΠΛΗΡΩΜΗ {number}", sup[1], -total))
        if n in (4, 9):
            continue                                   # αυτά τα δύο δεν έχουν φτάσει ποτέ
        source = "portal" if sup[0] == 3 else "email"  # τα Ποτά Αιγαίου τα δίνουν μόνο από το portal
        invoices.append((number, sup[0], inv_date, net, vat, total, source, f"{number}.pdf"))
    con.executemany("insert into bank_transactions values (?,?,?,?)", bank)
    # Στον πίνακα «invoices» μπαίνουν μόνο όσα έχουν ήδη αρχειοθετηθεί (όσα ήρθαν με email).
    con.executemany("insert into invoices values (?,?,?,?,?,?,?,?)", [i for i in invoices if i[6] == "email"])
    con.close()
    summary = {"today": str(today), "sales_rows": len(rows), "invoices": len(invoices),
               "missing_invoices": 2, "bank_transactions": len(bank)}
    if not side_files:
        return summary

    # Αρχεία δίπλα στη βάση: κινήσεις τράπεζας σε CSV, λίστα τιμολογίων για το portal και τα PDF.
    with open(config.DATA_DIR / "bank_statement.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "description", "counterparty", "amount"])
        w.writerows(bank)
    sup_by_id = {s[0]: s for s in SUPPLIERS}
    manifest = [{"invoice_no": i[0], "supplier": sup_by_id[i[1]][1], "supplier_email": sup_by_id[i[1]][2],
                 "date": str(i[2]), "net": i[3], "vat": i[4], "total": i[5], "source": i[6], "file": i[7]}
                for i in invoices]
    (config.DATA_DIR / "invoices_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    inbox = config.DATA_DIR / "inbox"
    inbox.mkdir(exist_ok=True)
    for old in inbox.glob("*.json"):
        old.unlink()
    for n, m in enumerate([m for m in manifest if m["source"] == "email"], start=1):
        (inbox / f"mail{n:02d}.json").write_text(json.dumps({
            "from": m["supplier_email"], "date": m["date"],
            "subject": f"Τιμολόγιο {m['invoice_no']}",
            "body": f"Καλησπέρα σας,\n\nσας επισυνάπτουμε το τιμολόγιο {m['invoice_no']} ποσού {m['total']:.2f} €.\n\n"
                    f"Με εκτίμηση,\n{m['supplier']}",
            "attachments": [m["file"]],
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    return summary


# --- «Χαλάσματα» για το demo: ο κριτής πατάει ένα κουμπί και ο agent πρέπει να το πιάσει μόνος του ---

def inject_margin_drop(category: str = "Γαλακτοκομικά", pct: float = 22.0) -> str:
    """Ο προμηθευτής ανέβασε το κόστος μιας κατηγορίας από χθες, οι τιμές πώλησης έμειναν ίδιες."""
    from .tools.data import run_sql
    f = 1 + pct / 100
    run_sql("update sales set cost = round(cost * ?, 2) where date = (select max(date) from sales) "
            "and sku in (select sku from products where category = ?)", [f, category])
    run_sql("update products set unit_cost = round(unit_cost * ?, 2) where category = ?", [f, category])
    return f"Το κόστος της κατηγορίας «{category}» ανέβηκε {pct:.0f}% την τελευταία ημέρα."


def inject_stock_out(sku: str = "P011", store_id: int = 1) -> str:
    """Ένα γρήγορο προϊόν πέφτει κάτω από το όριο αναπαραγγελίας."""
    from .tools.data import run_sql
    run_sql("update stock set on_hand = cast(reorder_point * 0.2 as int) where sku = ? and store_id = ?",
            [sku, store_id])
    return f"Το απόθεμα του {sku} στο κατάστημα {store_id} έπεσε κάτω από το όριο."
