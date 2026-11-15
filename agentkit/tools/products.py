"""Product identity from Open Food Facts: barcode, pack size, category, image (agentkit/off.py)."""
from .. import off
from . import tool
from .data import run_sql

_STATUS = {
    "matched": "Βρέθηκε το ίδιο προϊόν",
    "similar": "Δεν βρέθηκε η ίδια μάρκα· συγκρίσιμο προϊόν της ίδιας κατηγορίας",
    "weak": "Αβέβαιη αντιστοίχιση· να την ελέγξει άνθρωπος",
    "not_found": "Δεν βρέθηκε στο Open Food Facts",
    "error": "Το Open Food Facts δεν απάντησε",
}


def describe(res: dict, where: str) -> str:
    """One result of off.identify() as text for the model and the audit trail."""
    lines = [f"{_STATUS.get(res.get('status'), res.get('status'))} (βαθμός {res.get('score', 0):.2f}, {where})."]
    m = res.get("match")
    if m:
        lines += [f"Barcode: {m['barcode'] or '-'}", f"Όνομα: {m['name'] or '-'}", f"Μάρκα: {m['brand'] or '-'}",
                  f"Συσκευασία: {m['quantity'] or '-'}", f"Κατηγορίες: {', '.join(m['categories'][-3:]) or '-'}",
                  f"Σελίδα: {m['url']}"]
    if res.get("error"):
        lines.append(f"Σφάλμα: {res['error']}")
    lines.append(f"Πηγή: {off.LICENSE}. Μόνο ταυτότητα προϊόντος· πωλήσεις και κόστος δεν υπάρχουν εκεί.")
    return "\n".join(lines)


@tool(
    "product_identity",
    "Ποιο ακριβώς προϊόν είναι ένας κωδικός ή μια ετικέτα: barcode, μάρκα, συσκευασία, κατηγορία, από το Open Food "
    "Facts. Με sku διαβάζει πρώτα την αποθηκευμένη αναζήτηση (δουλεύει χωρίς δίκτυο). Με name και brand ψάχνει "
    "ζωντανά, π.χ. για προϊόν της φωτογραφίας που δεν είναι στον κατάλογο.",
    {"sku": {"type": "string", "description": "Κωδικός του καταλόγου, π.χ. T03"},
     "name": {"type": "string", "description": "Όνομα προϊόντος, αν δεν υπάρχει κωδικός"},
     "brand": {"type": "string", "description": "Μάρκα, αν είναι γνωστή"}},
    required=[],
)
async def product_identity(ctx, sku: str = "", name: str = "", brand: str = "") -> str:
    category = ""
    if sku:
        cached = off.load_cache().get(sku)
        if cached:
            return describe(cached, "αποθηκευμένη αναζήτηση του " + sku)
        _, rows = run_sql("select name, brand, category from products where sku = ?", [sku])
        if not rows:
            return f"Ο κωδικός {sku} δεν υπάρχει στον κατάλογο."
        name, brand, category = rows[0]
    if not name:
        return "Δώσε sku ή name."
    try:
        res = await off.identify(name, brand, category)
    except Exception as e:  # εξωτερική υπηρεσία
        res = {"status": "error", "score": 0.0, "error": f"{type(e).__name__}: {e}", "match": None}
    return describe(res, "ζωντανή αναζήτηση")
