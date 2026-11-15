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
  .portal-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 14px;
    margin-bottom: 18px;
    flex-wrap: wrap;
  }
  .portal-seg { min-width: 280px; }
  @media (max-width: 560px) { .portal-seg { width: 100%; } }

  .ord-section { margin-bottom: 18px; }
  .ord-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 10px 14px;
    border-bottom: 1px solid var(--separator);
  }
  .ord-id {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-family: var(--font-mono);
    font-size: var(--fs-title);
    font-weight: 600;
    color: var(--label-primary);
  }
  .ord-total {
    font-family: var(--font-mono);
    font-size: var(--fs-body);
    color: var(--label-secondary);
    font-variant-numeric: tabular-nums;
  }
  .ord-total strong {
    color: var(--label-primary);
    font-weight: 600;
  }

  .table-scroll {
    width: 100%;
    overflow-x: auto;
  }
  input[type=number] {
    width: 68px;
    font-family: var(--font-mono);
    text-align: right;
    font-variant-numeric: tabular-nums;
  }

  .login-sheet { max-width: 380px; }
  .field-row { margin-bottom: 12px; }
  .field-row label {
    display: block;
    font-size: var(--fs-callout);
    font-weight: 500;
    color: var(--label-secondary);
    margin-bottom: 4px;
  }
  .field-row input { width: 100%; }

  .notice {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 10px 14px;
    border-radius: var(--r-group);
    font-size: var(--fs-body);
    margin-bottom: 14px;
  }
  .notice.ok { background: var(--sys-green-tint); color: var(--sys-green); }
  .notice.err { background: var(--sys-red-tint); color: var(--sys-red); }
</style>"""


def _page(title: str, body: str, logged_in: bool = True, active: str = "orders") -> HTMLResponse:
    def seg_cls(key: str) -> str:
        return ' class="on"' if active == key else ""

    auth_link = (
        '<a href="/portal/logout" style="font-size:12px;margin-left:8px">Αποσύνδεση</a>'
        if logged_in
        else '<a href="/portal/login"' + seg_cls("login") + ">Σύνδεση</a>"
    )
    subnav = (
        '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">'
        '<div class="seg portal-seg" role="navigation" aria-label="Ενότητες αποθήκης">'
        f'<a href="/portal/orders"{seg_cls("orders")}>Παραγγελίες</a>'
        f'<a href="/portal/catalog"{seg_cls("catalog")}>Κατάλογος</a>'
        f'<a href="/portal/cart"{seg_cls("cart")}>Καλάθι</a>'
        + ("" if logged_in else auth_link)
        + "</div>"
        + (auth_link if logged_in else "")
        + "</div>"
    )
    tabbar = (
        "<nav class='ios-tabbar' aria-label='Πλοήγηση κινητού'>"
        "<a href='/'><svg viewBox='0 0 24 24' fill='none' stroke='currentColor'><path d='M3 10.5L12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1v-9.5Z' stroke-linejoin='round'/></svg><span>Αρχική</span></a>"
        "<a href='/tasks'><svg viewBox='0 0 24 24' fill='none' stroke='currentColor'><path d='M9 11l3 3L22 4' stroke-linecap='round' stroke-linejoin='round'/><path d='M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11' stroke-linecap='round'/></svg><span>Εργασίες</span><span class='tab-badge' data-tab-tasks-badge hidden>0</span></a>"
        "<a href='/capture'><svg viewBox='0 0 24 24' fill='none' stroke='currentColor'><path d='M4 7h3l2-2h6l2 2h3a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2Z'/><circle cx='12' cy='13' r='3.5'/></svg><span>Σάρωση</span></a>"
        "<a class='on' href='/portal/orders'><svg viewBox='0 0 24 24' fill='none' stroke='currentColor'><path d='M21 8l-9-5-9 5v8l9 5 9-5V8Z' stroke-linejoin='round'/><path d='M3.3 8L12 13l8.7-5M12 13v8'/></svg><span>Αποθήκη</span></a>"
        "</nav>"
    )
    return HTMLResponse(
        f"<!doctype html><html lang='el'><head><meta charset='utf-8'>"
        f"<meta name='viewport' content='width=device-width, initial-scale=1, viewport-fit=cover'>"
        f"<meta name='theme-color' content='#f5f5f7'>"
        f"<title>{html.escape(title)} · Αποθήκη · Shelf-it</title>"
        f"<link rel='icon' href='/ui/logo.svg' type='image/svg+xml'>"
        f"<link rel='stylesheet' href='/ui/app.css'>"
        f"<script src='/ui/shell.js'></script>{_EXTRA_CSS}</head>"
        f"<body class='has-tabbar'><header class='topbar'>"
        f"<a class='brand' href='/'><img src='/ui/logo.svg' alt=''>Shelf-it</a>"
        f"<nav class='seg-nav' aria-label='Κύρια πλοήγηση'>"
        f"<a href='/'>Αρχική</a><a href='/shelf'>Ράφι</a><a href='/tasks'>Εργασίες</a>"
        f"<a class='on' href='/portal/orders'>Αποθήκη</a><a href='/dev'>Κονσόλα</a></nav>"
        f"<div class='right'>"
        f"<button type='button' class='theme-btn' data-theme-toggle aria-label='Εναλλαγή θέματος'>"
        f"<svg viewBox='0 0 24 24' fill='none' stroke='currentColor'><circle cx='12' cy='12' r='8'/>"
        f"<path d='M12 4v16a8 8 0 0 0 0-16Z' fill='currentColor' stroke='none'/></svg>"
        f"<span class='theme-lbl'>Auto</span></button></div>"
        f"</header><main class='wrap'>"
        f"<div class='portal-head'><h1 class='page-title'>{html.escape(title)}</h1>{subnav}</div>"
        f"{body}</main>{tabbar}"
        f"<script>fetch('/api/live/status').then(r=>r.json()).then(s=>window.ShelfSenseShell?.setTaskBadge(s.open)).catch(()=>{{}});</script>"
        f"</body></html>"
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
    err = '<div class="notice err" id="error">Λάθος στοιχεία σύνδεσης.</div>' if error else ""
    return _page(
        "Σύνδεση καταστήματος",
        f"""{err}<div class="group-surface group-pad login-sheet">
        <form method="post" action="/portal/login">
          <div class="field-row"><label for="username">Όνομα χρήστη</label><input id="username" name="username" type="text" placeholder="demo"></div>
          <div class="field-row"><label for="password">Κωδικός</label><input id="password" name="password" type="password" placeholder="••••"></div>
          <button id="login" type="submit" style="width:100%;margin-top:4px">Είσοδος</button>
        </form>
        <p class="mut" style="font-size:var(--fs-foot);margin:12px 0 0">Προσομοίωση αποθήκης · Στοιχεία: <code>demo</code> / <code>demo</code></p>
        </div>""",
        logged_in=False,
        active="login",
    )


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
            '<div class="group-surface"><div class="empty">'
            '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor">'
            '<path d="M21 8l-9-5-9 5v8l9 5 9-5V8Z" stroke-linejoin="round"/>'
            '<path d="M3.3 8L12 13l8.7-5M12 13v8"/></svg>'
            'Δεν έχουν καταχωρηθεί ακόμη παραγγελίες αναπλήρωσης.</div></div>',
            logged_in=logged,
            active="orders",
        )
    blocks = []
    for o in reversed(orders):
        rows = "".join(
            f"<tr><td class='sku-code'>{html.escape(l['sku'])}</td>"
            f"<td>{html.escape(l['name'])}</td>"
            f"<td class='num-col'>{l['cases']}</td>"
            f"<td class='num-col'>{l['units']}</td>"
            f"<td class='num-col'><strong>{l['sum']:.2f} €</strong></td></tr>"
            for l in o["lines"]
        )
        blocks.append(
            f"<section class='group-surface ord-section'>"
            f"<div class='ord-bar'>"
            f"<span class='ord-id'><span class='sdot ok'></span>{html.escape(o['order_no'])}</span>"
            f"<span class='ord-total'>Σύνολο <strong>{o['total']:.2f} €</strong></span></div>"
            f"<div class='table-scroll'><table class='tbl'><thead><tr>"
            f"<th>Κωδικός</th><th>Προϊόν</th><th class='num-col'>Κιβώτια</th>"
            f"<th class='num-col'>Τεμάχια</th><th class='num-col'>Αξία</th>"
            f"</tr></thead><tbody>{rows}</tbody></table></div></section>"
        )
    return _page("Παραγγελίες καταστήματος", "".join(blocks), logged_in=logged, active="orders")


@router.get("/catalog", response_class=HTMLResponse)
async def catalog(request: Request, added: str = ""):
    if not _authed(request):
        return RedirectResponse("/portal/login")
    _, items = run_sql("select sku, name, brand, unit_cost, case_size from products order by sku")
    note = f'<div class="notice ok" id="added">Προστέθηκε στο καλάθι ο κωδικός {html.escape(added)}.</div>' if added else ""
    rows = "".join(
        f"<tr><td class='sku-code'>{html.escape(sku)}</td>"
        f"<td><strong style='font-weight:500'>{html.escape(name)}</strong> <span class='mut'>· {html.escape(brand)}</span></td>"
        f"<td class='num-col'>{price:.2f} €</td>"
        f"<td class='num-col'>{case}</td>"
        f"<td style='width:200px'><form method='post' action='/portal/cart/add' style='margin:0;display:flex;gap:6px;justify-content:flex-end'>"
        f"<input type='hidden' name='sku' value='{html.escape(sku)}'>"
        f"<input type='number' id='qty-{html.escape(sku)}' name='qty' value='1' min='1'>"
        f"<button id='add-{html.escape(sku)}' class='ghost' type='submit'>Προσθήκη</button></form></td></tr>"
        for sku, name, brand, price, case in items
    )
    return _page(
        "Κατάλογος αποθήκης",
        f"{note}<div class='group-surface'><div class='table-scroll'>"
        f"<table class='tbl'><thead><tr><th>Κωδικός</th><th>Προϊόν</th><th class='num-col'>Κόστος μονάδας</th>"
        f"<th class='num-col'>Τεμ. / κιβώτιο</th><th class='num-col'>Παραγγελία</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div></div>",
        active="catalog",
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
        return _page("Καλάθι", '<div class="group-surface"><div class="empty">Το καλάθι είναι άδειο.</div></div>', active="cart")
    rows = "".join(
        f"<tr><td class='sku-code'>{html.escape(l['sku'])}</td>"
        f"<td>{html.escape(l['name'])}</td>"
        f"<td class='num-col'>{l['cases']}</td>"
        f"<td class='num-col'><strong>{l['sum']:.2f} €</strong></td></tr>"
        for l in lines
    )
    return _page(
        "Καλάθι",
        f"<div class='group-surface' style='margin-bottom:14px'><div class='table-scroll'>"
        f"<table class='tbl'><thead><tr><th>Κωδικός</th><th>Προϊόν</th><th class='num-col'>Κιβώτια</th><th class='num-col'>Αξία</th></tr></thead>"
        f"<tbody>{rows}</tbody></table></div>"
        f"<div class='group-row' style='justify-content:space-between'>"
        f"<span id='total' class='mono' style='font-weight:600'>Σύνολο: {total:.2f} €</span>"
        f"<form method='post' action='/portal/checkout' style='margin:0'><button id='checkout' type='submit'>Υποβολή παραγγελίας</button></form>"
        f"</div></div>",
        active="cart",
    )


@router.post("/checkout", response_class=HTMLResponse)
async def checkout(request: Request):
    if not _authed(request):
        return RedirectResponse("/portal/login", status_code=303)
    order = place_order(dict(_cart))
    _cart.clear()
    return _page(
        "Η παραγγελία καταχωρήθηκε",
        f"<div class='notice ok' id='confirmation'>Αριθμός παραγγελίας <b>{html.escape(order['order_no'])}</b> · Σύνολο <b>{order['total']:.2f} €</b></div>"
        f"<a class='btn ghost' href='/portal/orders'>Προβολή παραγγελιών</a>",
        active="orders",
    )
