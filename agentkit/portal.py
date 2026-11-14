"""Ψεύτικο portal της κεντρικής αποθήκης που τρέχει μέσα στον ίδιο server, στο /portal.

Εδώ καταλήγουν οι παραγγελίες του καταστήματος όταν ένας κωδικός δεν υπάρχει στην αποθήκη του.
Ο agent παραγγέλνει με το εργαλείο order_from_warehouse (place_order παρακάτω)· οι ίδιες σελίδες
δουλεύουν και με το χέρι ή με τα εργαλεία browser. Σύνδεση: demo / demo. Είναι προσομοίωση.
"""
import html

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .tools.data import run_sql

router = APIRouter(prefix="/portal")
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
    nav = ('<a href="/portal/catalog">Κατάλογος</a><a href="/portal/orders">Παραγγελίες</a>'
           '<a href="/portal/cart">Καλάθι</a><a href="/portal/logout">Έξοδος</a>') if logged_in else ""
    return HTMLResponse(f"<html><head><meta charset='utf-8'><title>{title} · Κεντρική Αποθήκη</title>{_CSS}</head>"
                        f"<body><header><b>Κεντρική Αποθήκη</b>{nav}</header><main><h2>{title}</h2>{body}</main></body></html>")


def _authed(request: Request) -> bool:
    return request.cookies.get("portal_session") == "ok"


def _lines(cases_by_sku: dict[str, int]) -> tuple[list[dict], float]:
    lines, total = [], 0.0
    for sku, cases in cases_by_sku.items():
        _, r = run_sql("select name, unit_cost, case_size from products where sku = ?", [sku])
        if r and cases > 0:
            units = cases * r[0][2]
            lines.append({"sku": sku, "name": r[0][0], "cases": cases, "units": units, "sum": round(units * r[0][1], 2)})
            total += units * r[0][1]
    return lines, round(total, 2)


def place_order(cases_by_sku: dict[str, int]) -> dict:
    """Καταχωρεί παραγγελία. Το καλεί το εργαλείο order_from_warehouse και το checkout της σελίδας."""
    lines, total = _lines(cases_by_sku)
    order = {"order_no": f"ORD-{1000 + len(orders) + 1}", "lines": lines, "total": total}
    if lines:
        orders.append(order)
    return order


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return RedirectResponse("/portal/orders" if _authed(request) else "/portal/login")


@router.get("/login", response_class=HTMLResponse)
async def login_form(error: str = ""):
    err = '<p class="err" id="error">Λάθος στοιχεία σύνδεσης.</p>' if error else ""
    return _page("Σύνδεση καταστήματος", f"""{err}<form method="post" action="/portal/login">
        <p><input id="username" name="username" placeholder="Όνομα χρήστη"></p>
        <p><input id="password" name="password" type="password" placeholder="Κωδικός"></p>
        <button id="login" type="submit">Σύνδεση</button></form>
        <p style="color:#667">Στοιχεία επίδειξης: demo / demo</p>""", logged_in=False)


@router.post("/login")
async def login(username: str = Form(""), password: str = Form("")):
    if username == "demo" and password == "demo":
        resp = RedirectResponse("/portal/orders", status_code=303)
        resp.set_cookie("portal_session", "ok")
        return resp
    return RedirectResponse("/portal/login?error=1", status_code=303)


@router.get("/logout")
async def logout():
    resp = RedirectResponse("/portal/login", status_code=303)
    resp.delete_cookie("portal_session")
    return resp


@router.get("/orders", response_class=HTMLResponse)
async def orders_page():
    """Ανοιχτή σελίδα (χωρίς σύνδεση), για να φαίνεται στο demo ότι η παραγγελία του agent έφτασε."""
    if not orders:
        return _page("Παραγγελίες καταστήματος", "<p>Δεν υπάρχει ακόμη παραγγελία.</p>")
    blocks = []
    for o in reversed(orders):
        rows = "".join(f"<tr><td>{l['sku']}</td><td>{html.escape(l['name'])}</td><td>{l['cases']}</td><td>{l['units']}</td>"
                       f"<td>{l['sum']:.2f} €</td></tr>" for l in o["lines"])
        blocks.append(f"<p class='ok'><b>{o['order_no']}</b> · Σύνολο <b>{o['total']:.2f} €</b></p>"
                      f"<table><tr><th>Κωδικός</th><th>Προϊόν</th><th>Κιβώτια</th><th>Τεμάχια</th><th>Αξία</th></tr>{rows}</table>")
    return _page("Παραγγελίες καταστήματος", "".join(blocks))


@router.get("/catalog", response_class=HTMLResponse)
async def catalog(request: Request, added: str = ""):
    if not _authed(request):
        return RedirectResponse("/portal/login")
    _, items = run_sql("select sku, name, brand, unit_cost, case_size from products order by sku")
    note = f'<p class="ok" id="added">Προστέθηκε στο καλάθι: {html.escape(added)}</p>' if added else ""
    rows = "".join(
        f"<tr><td>{sku}</td><td>{html.escape(name)} · {html.escape(brand)}</td><td>{price:.2f} €</td><td>{case}</td>"
        f"<td><form method='post' action='/portal/cart/add' style='margin:0;display:flex;gap:6px'>"
        f"<input type='hidden' name='sku' value='{sku}'><input type='number' id='qty-{sku}' name='qty' value='1' min='1'>"
        f"<button id='add-{sku}' type='submit'>Προσθήκη {sku}</button></form></td></tr>"
        for sku, name, brand, price, case in items)
    return _page("Κατάλογος", f"{note}<table><tr><th>Κωδικός</th><th>Προϊόν</th><th>Τιμή τεμαχίου</th>"
                 f"<th>Τεμάχια ανά κιβώτιο</th><th>Κιβώτια</th></tr>{rows}</table>")


@router.post("/cart/add")
async def cart_add(sku: str = Form(...), qty: int = Form(1)):
    _cart[sku] = _cart.get(sku, 0) + max(qty, 1)
    return RedirectResponse(f"/portal/catalog?added={sku}", status_code=303)


@router.get("/cart", response_class=HTMLResponse)
async def cart(request: Request):
    if not _authed(request):
        return RedirectResponse("/portal/login")
    lines, total = _lines(_cart)
    if not lines:
        return _page("Καλάθι", "<p>Το καλάθι είναι άδειο.</p>")
    rows = "".join(f"<tr><td>{l['sku']}</td><td>{html.escape(l['name'])}</td><td>{l['cases']}</td><td>{l['sum']:.2f} €</td></tr>" for l in lines)
    return _page("Καλάθι", f"<table><tr><th>Κωδικός</th><th>Προϊόν</th><th>Κιβώτια</th><th>Αξία</th></tr>{rows}</table>"
                 f"<p id='total'><b>Σύνολο: {total:.2f} €</b></p>"
                 "<form method='post' action='/portal/checkout'><button id='checkout' type='submit'>Υποβολή παραγγελίας</button></form>")


@router.post("/checkout", response_class=HTMLResponse)
async def checkout(request: Request):
    if not _authed(request):
        return RedirectResponse("/portal/login", status_code=303)
    order = place_order(dict(_cart))
    _cart.clear()
    return _page("Η παραγγελία καταχωρήθηκε",
                 f"<p class='ok' id='confirmation'>Αριθμός παραγγελίας <b>{order['order_no']}</b> · Σύνολο <b>{order['total']:.2f} €</b></p>")
