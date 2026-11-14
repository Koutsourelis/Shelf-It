"""make_shelf_talker: printable shelf talker for a stored recommendation (logic in agentkit/shelf_talker.py).

INTEGRATION HOOK (agent / UI owners; this file does not change any scenario):
  - Agent: add "make_shelf_talker" to the shelf scenario's `tools` list in agentkit/scenarios.py. Until then the
    tool is registered but no scenario can call it (agent._call_tool refuses tools outside scenario.tools).
  - Approval: needs_approval=True, so the console/Telegram approval card shows the exact call input
    (recommendation_id, product_name, price_amount, currency, theme) before the billable fal request.
    Approval happens before input validation (agent.py order); a bad input after approval sends nothing to fal.
  - Confirmation: the name and price must come from owner feedback with a correction
    (POST /api/recommendations/{id}/feedback, decision "corrected", correction.product.name and
    correction.price {amount, currency, source}). "accepted" alone does not confirm name or price.
    The UI can read what is confirmed with agentkit.shelf_talker.confirmed_inputs(recommendation_id).
  - Output: on "generated" the PNG is emitted as an artifact (workspace/talkers/..., served at /files/talkers/...).
"""
import json

from .. import shelf_talker
from . import tool


@tool(
    "make_shelf_talker",
    "Φτιάχνει εκτυπώσιμο ταμπελάκι ραφιού (PNG) για μια αποθηκευμένη πρόταση: διακοσμητικό φόντο από το fal "
    "(χρεώνεται, θέλει έγκριση) και ακριβώς το όνομα και η τιμή που επιβεβαίωσε ο ιδιοκτήτης, γραμμένα τοπικά. "
    "Δώσε το όνομα και την τιμή ΑΚΡΙΒΩΣ όπως τα επιβεβαίωσε ο ιδιοκτήτης στη διόρθωσή του· η απλή αποδοχή της "
    "θέσης δεν επιβεβαιώνει όνομα ή τιμή. Αν λείπουν, το εργαλείο το λέει και δεν στέλνει τίποτα. Μην επινοείς "
    "τιμή. Αν η απάντηση είναι 'pending', κάλεσέ το ξανά με τα ίδια στοιχεία (συνεχίζει χωρίς νέα χρέωση).",
    {
        "recommendation_id": {"type": "string", "description": "ID της αποθηκευμένης πρότασης"},
        "product_name": {"type": "string", "description": "Όνομα προϊόντος όπως το επιβεβαίωσε ο ιδιοκτήτης"},
        "price_amount": {"type": "number", "description": "Τιμή όπως την επιβεβαίωσε ο ιδιοκτήτης, π.χ. 2.49"},
        "currency": {"type": "string", "description": "Νόμισμα ISO όπως το επιβεβαίωσε ο ιδιοκτήτης, π.χ. EUR"},
        "theme": {"type": "string", "enum": list(shelf_talker.THEMES),
                  "description": "Ύφος του διακοσμητικού φόντου (χωρίς κείμενο)"},
    },
    required=["recommendation_id", "product_name", "price_amount", "currency"],
    needs_approval=True,
)
async def make_shelf_talker(ctx, recommendation_id: str, product_name: str = None, price_amount: float = None,
                            currency: str = None, theme: str = "fresh") -> str:
    result = await shelf_talker.generate(recommendation_id, product_name, price_amount, currency, theme,
                                         log=lambda text: ctx.emit("log", text=text))
    if result.get("status") == "generated":
        path = shelf_talker.config.WORKSPACE / result["file"].removeprefix("workspace/")
        ctx.artifact(path)
        ctx.audit("owner_input", field="shelf_talker_price", value=result["price_text"],
                  recommendation_id=recommendation_id, source="owner feedback correction")
    return json.dumps(result, ensure_ascii=False, default=str)
