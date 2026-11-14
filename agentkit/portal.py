"""Ψεύτικο portal προμηθευτή («Ποτά Αιγαίου B2B») που τρέχει μέσα στον ίδιο server, στο /portal.

Υπάρχει ώστε ο agent να δείχνει πραγματική δουλειά σε browser (σύνδεση, λήψη τιμολογίων,
παραγγελία) χωρίς να εξαρτάται το demo από ξένο site. Σύνδεση: demo / demo.
"""
import html
import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from . import config
from .tools.data import run_sql

router = APIRouter(prefix="/portal")
SUPPLIER_ID = 3
_cart: dict[str, int] = {}
orders: list[dict] = []

_CSS = """<style>
body{font-family:Segoe UI,Arial,sans-serif;margin:0;background:#f4f6f8;color:#1c2733}
header{background:#0b3d5c;color:#fff;padding:14px 28px;display:flex;gap:24px;align-items:center}
header b{font-size:18px} header a{color:#cfe6f5;text-decoration:none}
main{max-width:920px;margin:28px auto;background:#fff;padding:28px;border-radius:10px;box-shadow:0 1px 4px #0002}
table{width:100%;border-collapse:collapse} th,td{padding:9px;border-bottom:1px solid #e3e8ec;text-align:left}
input{padding:8px;border:1px solid #b8c4cc;border-radius:6px} input[type=number]{width:70px}
button,.btn{background:#0b3d5c;color:#fff;border:0;padding:9px 16px;border-radius:6px;cursor:pointer;text-decoration:none}
.ok{background:#e3f5e8;padding:14px;border-radius:8px}.err{color:#b3261e}
</style>"""


def _page(title: str, body: str, logged_in: bool = True) -> HTMLResponse:
    nav = ('<a href="/portal/invoices">Τιμολόγια</a><a href="/portal/catalog">Κατάλογος</a>'
           '<a href="/portal/cart">Καλάθι</a><a href="/portal/logout">Έξοδος</a>') if logged_in else ""
    return HTMLResponse(f"<html><head><meta charset='utf-8'><title>{title} · Ποτά Αιγαίου B2B</title>{_CSS}</head>"
                        f"<body><header><b>Ποτά Αιγαίου B2B</b>{nav}</header><main><h2>{title}</h2>{body}</main></body></html>")


def _authed(request: Request) -> bool:
    return request.cookies.get("portal_session") == "ok"


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return RedirectResponse("/portal/invoices" if _authed(request) else "/portal/login")


@router.get("/login", response_class=HTMLResponse)
async def login_form(error: str = ""):
    err = '<p class="err" id="error">Λάθος στοιχεία σύνδεσης.</p>' if error else ""
    return _page("Σύνδεση πελάτη", f"""{err}<form method="post" action="/portal/login">
        <p><input id="username" name="username" placeholder="Όνομα χρήστη"></p>
        <p><input id="password" name="password" type="password" placeholder="Κωδικός"></p>
        <button id="login" type="submit">Σύνδεση</button></form>
        <p style="color:#667">Στοιχεία επίδειξης: demo / demo</p>""", logged_in=False)


@router.post("/login")
async def login(username: str = Form(""), password: str = Form("")):
    if username == "demo" and password == "demo":
        resp = RedirectResponse("/portal/invoices", status_code=303)
        resp.set_cookie("portal_session", "ok")
        return resp
    return RedirectResponse("/portal/login?error=1", status_code=303)


@router.get("/logout")
async def logout():
    resp = RedirectResponse("/portal/login", status_code=303)
    resp.delete_cookie("portal_session")
    return resp


@router.get("/invoices", response_class=HTMLResponse)
async def invoices(request: Request):
    if not _authed(request):
        return RedirectResponse("/portal/login")
    manifest = json.loads((config.DATA_DIR / "invoices_manifest.json").read_text(encoding="utf-8"))
    rows = "".join(
        f"<tr><td>{m['invoice_no']}</td><td>{m['date']}</td><td>{m['total']:.2f} €</td>"
        f"<td><a class='btn' id='dl-{m['invoice_no']}' href='/portal/invoices/{m['file']}' download>Λήψη PDF {m['invoice_no']}</a></td></tr>"
        for m in manifest if m["source"] == "portal")
    return _page("Τα τιμολόγιά σας", f"<table><tr><th>Αριθμός</th><th>Ημερομηνία</th><th>Σύνολο</th><th></th></tr>{rows}</table>")


@router.get("/invoices/{name}")
async def invoice_file(name: str, request: Request):
    path = config.DATA_DIR / "portal_invoices" / name.replace("/", "").replace("\\", "")
    if not _authed(request) or not path.exists():
        return HTMLResponse("Δεν βρέθηκε", status_code=404)
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@router.get("/catalog", response_class=HTMLResponse)
async def catalog(request: Request, added: str = ""):
    if not _authed(request):
        return RedirectResponse("/portal/login")
    _, items = run_sql("select sp.sku, p.name, sp.price, sp.min_qty from supplier_prices sp join products p using (sku) "
                       "where sp.supplier_id = ? order by p.name", [SUPPLIER_ID])
    note = f'<p class="ok" id="added">Προστέθηκε στο καλάθι: {html.escape(added)}</p>' if added else ""
    rows = "".join(
        f"<tr><td>{sku}</td><td>{html.escape(name)}</td><td>{price:.2f} €</td><td>{min_qty}</td>"
        f"<td><form method='post' action='/portal/cart/add' style='margin:0;display:flex;gap:6px'>"
        f"<input type='hidden' name='sku' value='{sku}'><input type='number' id='qty-{sku}' name='qty' value='{min_qty}' min='1'>"
        f"<button id='add-{sku}' type='submit'>Προσθήκη {sku}</button></form></td></tr>"
        for sku, name, price, min_qty in items)
    return _page("Κατάλογος & τιμές", f"{note}<table><tr><th>Κωδικός</th><th>Προϊόν</th><th>Τιμή</th><th>Ελάχ. ποσότητα</th><th></th></tr>{rows}</table>")


@router.post("/cart/add")
async def cart_add(sku: str = Form(...), qty: int = Form(1)):
    _cart[sku] = _cart.get(sku, 0) + max(qty, 1)
    return RedirectResponse(f"/portal/catalog?added={sku}", status_code=303)


def _cart_lines():
    lines, total = [], 0.0
    for sku, qty in _cart.items():
        _, r = run_sql("select p.name, sp.price from supplier_prices sp join products p using (sku) "
                       "where sp.supplier_id = ? and sp.sku = ?", [SUPPLIER_ID, sku])
        if r:
            lines.append({"sku": sku, "name": r[0][0], "qty": qty, "price": r[0][1], "sum": round(qty * r[0][1], 2)})
            total += qty * r[0][1]
    return lines, round(total, 2)


@router.get("/cart", response_class=HTMLResponse)
async def cart(request: Request):
    if not _authed(request):
        return RedirectResponse("/portal/login")
    lines, total = _cart_lines()
    if not lines:
        return _page("Καλάθι", "<p>Το καλάθι είναι άδειο.</p>")
    rows = "".join(f"<tr><td>{l['sku']}</td><td>{html.escape(l['name'])}</td><td>{l['qty']}</td><td>{l['sum']:.2f} €</td></tr>" for l in lines)
    return _page("Καλάθι", f"<table><tr><th>Κωδικός</th><th>Προϊόν</th><th>Ποσότητα</th><th>Αξία</th></tr>{rows}</table>"
                 f"<p id='total'><b>Σύνολο: {total:.2f} €</b></p>"
                 "<form method='post' action='/portal/checkout'><button id='checkout' type='submit'>Υποβολή παραγγελίας</button></form>")


@router.post("/checkout", response_class=HTMLResponse)
async def checkout(request: Request):
    if not _authed(request):
        return RedirectResponse("/portal/login", status_code=303)
    lines, total = _cart_lines()
    number = f"ORD-{1000 + len(orders) + 1}"
    orders.append({"order_no": number, "lines": lines, "total": total})
    _cart.clear()
    return _page("Η παραγγελία καταχωρήθηκε",
                 f"<p class='ok' id='confirmation'>Αριθμός παραγγελίας <b>{number}</b> · Σύνολο <b>{total:.2f} €</b></p>")
