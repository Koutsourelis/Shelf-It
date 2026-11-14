"""Εργαλεία ιστού: αναζήτηση και ανάγνωση σελίδας (χωρίς browser)."""
import asyncio

import httpx
from bs4 import BeautifulSoup

from . import tool

_UA = {"User-Agent": "Mozilla/5.0 (compatible; agentkit/0.1)"}


def html_to_text(html: str, limit: int = 12000) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())
    return text if len(text) <= limit else text[:limit] + f"\n... [κόπηκε, σύνολο {len(text)} χαρακτήρες]"


@tool(
    "web_search",
    "Αναζήτηση στο διαδίκτυο. Επιστρέφει τίτλους, συνδέσμους και αποσπάσματα.",
    {"query": {"type": "string", "description": "Τι ψάχνεις"}},
)
async def web_search(ctx, query: str) -> str:
    def work():
        from ddgs import DDGS
        return list(DDGS().text(query, max_results=6))
    try:
        results = await asyncio.to_thread(work)
    except Exception as e:  # η αναζήτηση εξαρτάται από εξωτερική υπηρεσία
        return f"Η αναζήτηση απέτυχε ({type(e).__name__}: {e}). Δοκίμασε fetch_url σε γνωστή διεύθυνση."
    if not results:
        return "Κανένα αποτέλεσμα."
    return "\n\n".join(f"{r.get('title')}\n{r.get('href')}\n{r.get('body')}" for r in results)


@tool(
    "fetch_url",
    "Κατέβασε μια σελίδα και πάρε το κείμενό της. Για σελίδες που θέλουν κλικ ή σύνδεση χρησιμοποίησε τα browser_*.",
    {"url": {"type": "string", "description": "Πλήρης διεύθυνση http(s)"}},
)
async def fetch_url(ctx, url: str) -> str:
    async with httpx.AsyncClient(follow_redirects=True, timeout=20, headers=_UA) as client:
        r = await client.get(url)
    if r.status_code >= 400:
        return f"Σφάλμα HTTP {r.status_code} από {url}"
    ctype = r.headers.get("content-type", "")
    if "html" in ctype:
        return html_to_text(r.text)
    return r.text[:12000]
