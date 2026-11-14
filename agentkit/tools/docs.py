"""Έγγραφα: ανάγνωση PDF (τιμολόγια, τιμοκατάλογοι)."""
import asyncio

from . import tool
from .core import safe_path


@tool(
    "read_pdf",
    "Διάβασε το κείμενο ενός PDF (π.χ. τιμολόγιο ή τιμοκατάλογο).",
    {"path": {"type": "string", "description": "π.χ. 'data/invoices/INV-2026-0412.pdf' ή 'workspace/downloads/x.pdf'"}},
)
async def read_pdf(ctx, path: str) -> str:
    p = safe_path(path)
    if not p.exists():
        return f"Δεν βρέθηκε: {path}"

    def work():
        from pypdf import PdfReader
        reader = PdfReader(str(p))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)

    text = (await asyncio.to_thread(work)).strip()
    if not text:
        return "Το PDF δεν έχει κείμενο (ίσως είναι σαρωμένη εικόνα)."
    return text[:15000]
