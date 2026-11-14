"""Μοτίβο «το μοντέλο εξάγει, ο κώδικας υπολογίζει».

- extract_fields: το μοντέλο διαβάζει ένα έγγραφο και επιστρέφει συγκεκριμένα πεδία (τίποτα άλλο).
- compute: κάθε αριθμητική πράξη γίνεται εδώ, με κανονικό κώδικα, όχι «με το μυαλό» του μοντέλου.
- Και τα δύο γράφουν στο ίχνος ελέγχου (ctx.audit), ώστε κάθε αριθμός του τελικού παραδοτέου
  να έχει πηγή: από ποιο έγγραφο διαβάστηκε ή με ποιον τύπο υπολογίστηκε.
"""
import ast
import operator

from ..llm.structured import structured
from . import tool
from .core import safe_path

_TYPES = {"string": "string", "number": "number", "integer": "integer", "boolean": "boolean", "date": "string"}


async def _read_document(path: str) -> str:
    p = safe_path(path)
    if not p.exists():
        raise FileNotFoundError(path)
    if p.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        return "\n\n".join((page.extract_text() or "") for page in PdfReader(str(p)).pages)
    return p.read_text(encoding="utf-8", errors="replace")


@tool(
    "extract_fields",
    "Διάβασε ένα έγγραφο (PDF ή κείμενο) και βγάλε συγκεκριμένα πεδία σε JSON. Χρησιμοποίησέ το για κάθε "
    "στοιχείο που θα μπει σε υπολογισμό ή σε παραδοτέο, ώστε να καταγραφεί η πηγή του. Πεδίο που δεν υπάρχει "
    "στο έγγραφο επιστρέφει null.",
    {
        "path": {"type": "string", "description": "π.χ. 'data/invoices/INV-2026-0400.pdf'"},
        "fields": {
            "type": "array",
            "description": "Τα πεδία που θέλεις.",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Όνομα πεδίου με λατινικούς χαρακτήρες, π.χ. total"},
                    "type": {"type": "string", "enum": list(_TYPES)},
                    "description": {"type": "string", "description": "Τι ακριβώς είναι το πεδίο"},
                },
                "required": ["name", "type", "description"],
            },
        },
    },
)
async def extract_fields(ctx, path: str, fields: list) -> str:
    import json
    text = (await _read_document(path))[:30000]
    schema = {
        "type": "object",
        "properties": {
            f["name"]: {"anyOf": [{"type": _TYPES.get(f["type"], "string")}, {"type": "null"}],
                        "description": f["description"] + (" (μορφή YYYY-MM-DD)" if f["type"] == "date" else "")}
            for f in fields
        },
        "required": [f["name"] for f in fields],
        "additionalProperties": False,
    }
    values = await structured(
        "Εξάγεις στοιχεία από έγγραφα. Γράφεις μόνο ό,τι αναγράφεται ρητά στο έγγραφο. Αν ένα πεδίο δεν υπάρχει, "
        "δίνεις null. Δεν υπολογίζεις και δεν συμπεραίνεις τιμές. Αριθμοί χωρίς σύμβολα νομίσματος, με τελεία για δεκαδικά.",
        f"ΕΓΓΡΑΦΟ ({path}):\n\n{text}", schema)
    values = {f["name"]: values.get(f["name"]) for f in fields}
    ctx.audit("extract", source=path, values=values)
    return json.dumps(values, ensure_ascii=False)


# --- Ασφαλής αριθμητική: μόνο αριθμοί, μεταβλητές και βασικές πράξεις ---------------------------
_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.Pow: operator.pow, ast.Mod: operator.mod, ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS = {"round": round, "abs": abs, "min": min, "max": max, "sum": lambda *a: sum(a)}


def safe_eval(expression: str, variables: dict) -> float:
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.Name):
            if node.id not in variables:
                raise ValueError(f"Άγνωστη μεταβλητή: {node.id}")
            return float(variables[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS and not node.keywords:
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        raise ValueError("Επιτρέπονται μόνο αριθμοί, μεταβλητές, + - * / ** % και round/abs/min/max/sum.")
    return ev(ast.parse(expression, mode="eval"))


@tool(
    "compute",
    "Κάνε έναν αριθμητικό υπολογισμό με κώδικα. ΚΑΘΕ αριθμός που δεν διαβάστηκε αυτούσιος από εργαλείο "
    "(διαφορές, ποσοστά, αθροίσματα, επίπτωση σε ευρώ) πρέπει να βγαίνει από εδώ, ποτέ από νοερό υπολογισμό.",
    {
        "label": {"type": "string", "description": "Τι υπολογίζεται, π.χ. 'Διαφορά πληρωμής - τιμολογίου'"},
        "expression": {"type": "string", "description": "Τύπος με ονόματα μεταβλητών, π.χ. 'round(paid - total, 2)'"},
        "variables": {"type": "object", "description": "Τιμές των μεταβλητών, π.χ. {\"paid\": 1240.5, \"total\": 1200}"},
    },
)
async def compute(ctx, label: str, expression: str, variables: dict) -> str:
    result = safe_eval(expression, variables or {})
    ctx.audit("compute", label=label, expression=expression, variables=variables, result=result)
    return f"{label} = {result}"
