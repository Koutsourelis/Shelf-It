"""Χτίζει τα δεδομένα του demo: βάση, κινήσεις τράπεζας, εισερχόμενα και PDF τιμολογίων.

    python scripts/make_demo_data.py            # όλα
    python scripts/make_demo_data.py --no-pdf   # μόνο βάση (γρήγορο, χωρίς browser)
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentkit import config, demo_data  # noqa: E402

INVOICE_HTML = """<html><head><meta charset="utf-8"><style>
body {{ font-family: Arial, sans-serif; margin: 48px; color: #222; }}
h1 {{ font-size: 22px; margin: 0; }} .muted {{ color: #666; font-size: 12px; }}
table {{ width: 100%; border-collapse: collapse; margin-top: 28px; }}
th, td {{ border-bottom: 1px solid #ddd; padding: 8px; text-align: left; font-size: 13px; }}
td.n, th.n {{ text-align: right; }} .tot td {{ font-weight: bold; border-top: 2px solid #222; }}
</style></head><body>
<h1>{supplier}</h1><div class="muted">ΑΦΜ: {afm} · {email}</div>
<h2 style="margin-top:32px">ΤΙΜΟΛΟΓΙΟ ΠΩΛΗΣΗΣ</h2>
<p>Αριθμός τιμολογίου: <b>{invoice_no}</b><br>Ημερομηνία: <b>{date}</b><br>
Πελάτης: <b>Αγορά Plus ΑΕ</b> · ΑΦΜ 099999999</p>
<table><tr><th>Περιγραφή</th><th class="n">Καθαρή αξία</th></tr>
<tr><td>Εμπορεύματα σύμφωνα με δελτία αποστολής περιόδου</td><td class="n">{net:.2f} €</td></tr>
<tr><td>ΦΠΑ 24%</td><td class="n">{vat:.2f} €</td></tr>
<tr class="tot"><td>ΣΥΝΟΛΟ ΠΛΗΡΩΤΕΟ</td><td class="n">{total:.2f} €</td></tr></table>
<p class="muted" style="margin-top:40px">Φανταστικό έγγραφο για επίδειξη. Δεν αντιστοιχεί σε πραγματική συναλλαγή.</p>
</body></html>"""


def make_pdfs() -> int:
    from playwright.sync_api import sync_playwright

    manifest = json.loads((config.DATA_DIR / "invoices_manifest.json").read_text(encoding="utf-8"))
    folders = {"email": config.DATA_DIR / "invoices", "portal": config.DATA_DIR / "portal_invoices"}
    for folder in folders.values():
        folder.mkdir(exist_ok=True)
        for old in folder.glob("*.pdf"):
            old.unlink()
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page()
        for n, m in enumerate(manifest):
            page.set_content(INVOICE_HTML.format(afm=f"0941{n:05d}", email=m["supplier_email"], **m))
            page.pdf(path=str(folders[m["source"]] / m["file"]), format="A4")
        browser.close()
    return len(manifest)


if __name__ == "__main__":
    print("Βάση:", demo_data.build())
    if "--no-pdf" not in sys.argv:
        print("PDF τιμολογίων:", make_pdfs())
    print("Έτοιμο ->", config.DATA_DIR)
