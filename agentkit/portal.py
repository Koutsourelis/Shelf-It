"""Πύλη της κεντρικής αποθήκης που τρέχει μέσα στον ίδιο server, στο /portal.

Εδώ καταλήγουν οι παραγγελίες του καταστήματος όταν ένας κωδικός δεν υπάρχει στην αποθήκη του.
Ο agent παραγγέλνει με το εργαλείο order_from_warehouse (place_order παρακάτω)· οι ίδιες σελίδες
δουλεύουν και χειροκίνητα ή με τα εργαλεία browser. Σύνδεση: demo / demo. Είναι προσομοίωση.
"""
import html

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .tools.data import run_sql

router = APIRouter(prefix="/portal")
_cart: dict[str, int] = {}
orders: list[dict] = []

_EXTRA_CSS = """<style>
  .subbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
    padding-bottom: 18px;
    border-bottom: 1px solid var(--line);
    margin-bottom: 22px;
    flex-wrap: wrap;
  }
  .subbar h1 { margin: 0; font-size: 22px; font-weight: 700; letter-spacing: -0.02em; }
  .subnav { display: flex; gap: 6px; flex-wrap: wrap; }
  .subnav a {
    font-size: 13px;
    font-weight: 600;
    color: var(--fg2);
    text-decoration: none;
    padding: 6px 11px;
    border-radius: 7px;
    background: var(--card);
    border: 1px solid var(--line);
  }
  .subnav a:hover { background: var(--card2); }
  .ord-card {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: var(--r);
    box-shadow: var(--shadow);
    margin-bottom: 16px;
    overflow: hidden;
  }
  .ord-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 13px 18px;
    background: var(--bg);
    border-bottom: 1px solid var(--line);
  }
  .ord-no { font-family: var(--mono); font-size: 15px; font-weight: 600; color: var(--fg); }
  .ord-tot { font-family: var(--mono); font-size: 15px; font-weight: 600; color: var(--fg); font-variant-numeric: tabular-nums; }
  input[type=text], input[type=password], input[type=number], input:not([type]) {
    font-family: var(--font);
    font-size: 14px;
    padding: 8px 11px;
    border: 1px solid var(--line-strong);
    border-radius: 7px;
    background: var(--card);
    color: var(--fg);
  }
  input[type=number] { width: 74px; font-family: var(--mono); text-align: right; }
  .login-box { max-width: 400px; }
  .login-box .field { margin-bottom: 12px; }
  .login-box label { display: block; font-size: 12.5px; font-weight: 600; color: var(--fg2); margin-bottom: 4px; }
  .login-box input { width: 100%; }
  .banner-ok {
    padding: 12px 15px;
    border-radius: 8px;
    background: var(--okbg);
    border: 1px solid var(--okline);
    color: var(--ok);
    font-weight: 500;
    margin-bottom: 16px;
  }
  .banner-err {
    padding: 10px 14px;
    border-radius: 8px;
    background: var(--badbg);
    border: 1px solid var(--badline);
    color: var(--bad);
    font-size: 13.5px;
    font-weight: 500;
    margin-bottom: 14px;
  }
</style>"""


def _page(title: str, body: str, logged_in: bool = True) -> HTMLResponse:
    subnav = (
        '<div class="subnav">'
        '<a href="/portal/orders">Παραγγελίες</a>'
        '<a href="/portal/catalog">Κατάλογος</a>'
        '<a href="/portal/cart">Καλάθι</a>'
        + ('<a href="/portal/logout">Αποσύνδεση</a>' if logged_in else '<a href="/portal/login">Σύνδεση</a>')
        + '</div>'
    )
    return HTMLResponse(
        f"<!doctype html><html lang='el'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<title>{html.escape(title)} · Κεντρική Αποθήκη · ShelfSense</title>"
        f"<link rel='icon' href='/ui/logo.svg' type='image/svg+xml'>"
        f"<link rel='stylesheet' href='/ui/app.css'>{_EXTRA_CSS}</head>"
        f"<body><header class='topbar'>"
        f"<a class='brand' href='/'><img src='/ui/logo.svg' alt=''>ShelfSense</a>"
        f"<nav><a href='/shelf'>Ράφι</a><a href='/tasks'>Εργασίες</a>"
        f"<a class='on' href='/portal/orders'>Αποθήκη</a><a href='/dev'>Κονσόλα</a></nav>"
        f"<div class='right'><span class='pill plain'>Κεντρική Αποθήκη (ERP)</span></div>"
        f"</header><main class='wrap'>"
        f"<div class='subbar'><h1>{html.escape(title)}</h1>{subnav}</div>"
        f"{body}</main></body></html>"
    )


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
    err = '<div class="banner-err" id="error">Λάθος στοιχεία σύνδεσης.</div>' if error else ""
    return _page("Σύνδεση καταστήματος", f"""<div class="card login-box">{err}
        <form method="post" action="/portal/login">
          <div class="field"><label for="username">Όνομα χρήστη</label><input id="username" name="username" placeholder="demo"></div>
          <div class="field"><label for="password">Κωδικός πρόσβασης</label><input id="password" name="password" type="password" placeholder="••••"></div>
          <button id="login" type="submit" style="width:100%;margin-top:4px">Είσοδος στην πύλη</button>
        </form>
        <p class="mut" style="font-size:12.5px;margin:14px 0 0">Περιβάλλον προσομοίωσης · Στοιχεία: <code>demo</code> / <code>demo</code></p>
        </div>""", logged_in=False)


@router.post("/login")
async def login(username: str = Form(""), password: str = Form("")):
    if (username, password) == ("demo", "demo"):
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
async def orders_page(request: Request):
    """Ανοιχτή σελίδα (χωρίς υποχρεωτική σύνδεση), ώστε να φαίνεται άμεσα ότι η παραγγελία του agent έφτασε."""
    logged = _authed(request)
    if not orders:
        return _page(
            "Παραγγελίες καταστήματος",
            '<div class="card empty" style="background:var(--card)">'
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" style="color:var(--mut)">'
            '<path d="M21 8l-9-5-9 5v8l9 5 9-5V8Z" stroke-width="2" stroke-linejoin="round"/>'
            '<path d="M3.3 8L12 13l8.7-5M12 13v8" stroke-width="2"/></svg>'
            'Δεν έχουν καταχωρηθεί ακόμη παραγγελίες αναπλήρωσης.</div>',
            logged_in=logged,
        )
    blocks = []
    for o in reversed(orders):
        rows = "".join(
            f"<tr><td><span class='sku-chip'>{html.escape(l['sku'])}</span></td>"
            f"<td>{html.escape(l['name'])}</td>"
            f"<td class='num-col'>{l['cases']}</td>"
            f"<td class='num-col'>{l['units']}</td>"
            f"<td class='num-col'>{l['sum']:.2f} €</td></tr>"
            for l in o["lines"]
        )
        blocks.append(
            f"<section class='ord-card'>"
            f"<div class='ord-head'>"
            f"<div style='display:flex;align-items:center;gap:10px'>"
            f"<span class='ord-no'>{html.escape(o['order_no'])}</span>"
            f"<span class='pill ok'>Καταχωρήθηκε</span></div>"
            f"<div class='ord-tot'>Σύνολο: {o['total']:.2f} €</div></div>"
            f"<table class='tbl'><thead><tr><th>Κωδικός</th><th>Προϊόν</th>"
            f"<th class='num-col'>Κιβώτια</th><th class='num-col'>Τεμάχια</th><th class='num-col'>Αξία</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></section>"
        )
    return _page("Παραγγελίες καταστήματος", "".join(blocks), logged_in=logged)


@router.get("/catalog", response_class=HTMLResponse)
async def catalog(request: Request, added: str = ""):
    if not _authed(request):
        return RedirectResponse("/portal/login")
    _, items = run_sql("select sku, name, brand, unit_cost, case_size from products order by sku")
    note = f'<div class="banner-ok" id="added">Προστέθηκε στο καλάθι ο κωδικός {html.escape(added)}.</div>' if added else ""
    rows = "".join(
        f"<tr><td><span class='sku-chip'>{html.escape(sku)}</span></td>"
        f"<td><b>{html.escape(name)}</b> <span class='mut'>· {html.escape(brand)}</span></td>"
        f"<td class='num-col'>{price:.2f} €</td>"
        f"<td class='num-col'>{case}</td>"
        f"<td style='width:220px'><form method='post' action='/portal/cart/add' style='margin:0;display:flex;gap:6px;justify-content:flex-end'>"
        f"<input type='hidden' name='sku' value='{html.escape(sku)}'>"
        f"<input type='number' id='qty-{html.escape(sku)}' name='qty' value='1' min='1'>"
        f"<button id='add-{html.escape(sku)}' class='ghost' type='submit' style='padding:7px 11px;font-size:13px'>Προσθήκη</button></form></td></tr>"
        for sku, name, brand, price, case in items
    )
    return _page(
        "Κατάλογος κεντρικής αποθήκης",
        f"{note}<div class='card' style='padding:0;overflow:hidden'>"
        f"<table class='tbl'><thead><tr><th>Κωδικός</th><th>Προϊόν</th><th class='num-col'>Κόστος μονάδας</th>"
        f"<th class='num-col'>Τεμ. / κιβώτιο</th><th class='num-col'>Παραγγελία</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>",
    )


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
        return _page("Καλάθι παραγγελίας", '<div class="card empty" style="background:var(--card)">Το καλάθι είναι άδειο.</div>')
    rows = "".join(
        f"<tr><td><span class='sku-chip'>{html.escape(l['sku'])}</span></td>"
        f"<td>{html.escape(l['name'])}</td>"
        f"<td class='num-col'>{l['cases']}</td>"
        f"<td class='num-col'>{l['sum']:.2f} €</td></tr>"
        for l in lines
    )
    return _page(
        "Καλάθι παραγγελίας",
        f"<div class='card' style='padding:0;overflow:hidden;margin-bottom:16px'>"
        f"<table class='tbl'><thead><tr><th>Κωδικός</th><th>Προϊόν</th><th class='num-col'>Κιβώτια</th><th class='num-col'>Αξία</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
        f"<div class='card' style='display:flex;align-items:center;justify-content:space-between;gap:12px'>"
        f"<div id='total' class='mono' style='font-size:16px;font-weight:600'>Σύνολο: {total:.2f} €</div>"
        f"<form method='post' action='/portal/checkout' style='margin:0'><button id='checkout' type='submit'>Υποβολή παραγγελίας</button></form></div>",
    )


@router.post("/checkout", response_class=HTMLResponse)
async def checkout(request: Request):
    if not _authed(request):
        return RedirectResponse("/portal/login", status_code=303)
    order = place_order(dict(_cart))
    _cart.clear()
    return _page(
        "Η παραγγελία καταχωρήθηκε",
        f"<div class='banner-ok' id='confirmation'>Αριθμός παραγγελίας <b>{html.escape(order['order_no'])}</b> · Σύνολο <b>{order['total']:.2f} €</b></div>"
        f"<a class='btn ghost' href='/portal/orders'>Προβολή όλων των παραγγελιών</a>",
    )
