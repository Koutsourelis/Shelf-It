"""Εργαλεία browser (Playwright): ο agent ανοίγει σελίδες, πατάει, γράφει, κατεβάζει.

Κάθε εκτέλεση έχει τη δική της καρτέλα. Μετά από κάθε ενέργεια στέλνεται στιγμιότυπο
στην κονσόλα, ώστε ο θεατής να βλέπει τι βλέπει ο agent.
"""
import time

from .. import config
from . import tool
from .web import html_to_text

_pw = None
_browser = None
_pages: dict[str, object] = {}


async def _page(ctx):
    global _pw, _browser
    if _browser is None:
        from playwright.async_api import async_playwright
        _pw = await async_playwright().start()
        _browser = await _pw.chromium.launch(headless=config.BROWSER_HEADLESS)
    page = _pages.get(ctx.run_id)
    if page is None or page.is_closed():
        context = await _browser.new_context(viewport={"width": 1200, "height": 800}, accept_downloads=True)
        page = await context.new_page()
        page.set_default_timeout(10000)
        _pages[ctx.run_id] = page
    return page


async def close_run(run_id: str) -> None:
    page = _pages.pop(run_id, None)
    if page is not None and not page.is_closed():
        await page.context.close()


async def shutdown() -> None:
    global _pw, _browser
    if _browser is not None:
        await _browser.close()
    if _pw is not None:
        await _pw.stop()
    _pw = _browser = None


async def _snapshot(ctx, page) -> str:
    """Στιγμιότυπο στην κονσόλα + σύνοψη της σελίδας για το μοντέλο."""
    name = f"screen_{ctx.run_id}_{int(time.time() * 1000) % 10_000_000}.png"
    shots = config.WORKSPACE / "screens"
    shots.mkdir(exist_ok=True)
    await page.screenshot(path=str(shots / name))
    ctx.emit("screenshot", file=f"screens/{name}", url=page.url)

    # Τα πατήσιμα στοιχεία, για να ξέρει το μοντέλο τι μπορεί να πατήσει ή να συμπληρώσει.
    elements = await page.evaluate(
        """() => [...document.querySelectorAll('a, button, input, select, textarea')].slice(0, 80).map(e => {
            const t = (e.innerText || e.value || e.placeholder || e.getAttribute('aria-label') || '').trim().slice(0, 60);
            const id = e.id ? '#' + e.id : (e.name ? `[name="${e.name}"]` : '');
            return `${e.tagName.toLowerCase()}${id} ${e.type ? '(' + e.type + ')' : ''} "${t}"`;
        })"""
    )
    text = html_to_text(await page.content(), limit=5000)
    return f"URL: {page.url}\nΤίτλος: {await page.title()}\n\nΚΕΙΜΕΝΟ:\n{text}\n\nΣΤΟΙΧΕΙΑ:\n" + "\n".join(elements)


@tool("browser_open", "Άνοιξε μια διεύθυνση στον browser. Επιστρέφει το κείμενο της σελίδας και τα πατήσιμα στοιχεία.",
      {"url": {"type": "string", "description": "Πλήρης διεύθυνση"}})
async def browser_open(ctx, url: str) -> str:
    page = await _page(ctx)
    await page.goto(url, wait_until="domcontentloaded")
    return await _snapshot(ctx, page)


@tool(
    "browser_click",
    "Πάτα ένα στοιχείο της σελίδας. Δώσε είτε CSS selector (π.χ. '#login') είτε το ορατό κείμενό του.",
    {"target": {"type": "string", "description": "CSS selector ή ορατό κείμενο του στοιχείου"}},
)
async def browser_click(ctx, target: str) -> str:
    page = await _page(ctx)
    locator = page.locator(target) if target[:1] in "#.[" else page.get_by_text(target, exact=False)
    await locator.first.click()
    await page.wait_for_load_state("domcontentloaded")
    return await _snapshot(ctx, page)


@tool(
    "browser_type",
    "Γράψε κείμενο σε πεδίο φόρμας.",
    {
        "selector": {"type": "string", "description": "CSS selector του πεδίου, π.χ. '#username' ή '[name=\"qty\"]'"},
        "text": {"type": "string", "description": "Το κείμενο"},
        "press_enter": {"type": "boolean", "description": "Αν θα πατηθεί Enter μετά"},
    },
    required=["selector", "text"],
)
async def browser_type(ctx, selector: str, text: str, press_enter: bool = False) -> str:
    page = await _page(ctx)
    await page.locator(selector).first.fill(text)
    if press_enter:
        await page.locator(selector).first.press("Enter")
        await page.wait_for_load_state("domcontentloaded")
    return await _snapshot(ctx, page)


@tool(
    "browser_download",
    "Πάτα έναν σύνδεσμο λήψης και αποθήκευσε το αρχείο στο workspace/downloads.",
    {"target": {"type": "string", "description": "CSS selector ή ορατό κείμενο του συνδέσμου λήψης"}},
)
async def browser_download(ctx, target: str) -> str:
    page = await _page(ctx)
    locator = page.locator(target) if target[:1] in "#.[" else page.get_by_text(target, exact=False)
    async with page.expect_download() as info:
        await locator.first.click()
    download = await info.value
    folder = config.WORKSPACE / "downloads"
    folder.mkdir(exist_ok=True)
    path = folder / download.suggested_filename
    await download.save_as(str(path))
    ctx.artifact(path)
    return f"Κατέβηκε: workspace/downloads/{path.name}"
