"""Βασικά εργαλεία: πλάνο, μήνυμα στον χρήστη, αρχεία στον χώρο εργασίας."""
from pathlib import Path

from .. import config
from . import tool


def safe_path(rel: str) -> Path:
    """Επιτρέπει πρόσβαση μόνο μέσα στο workspace/ και στο data/."""
    rel = rel.replace("\\", "/").lstrip("/")
    for base in (config.WORKSPACE, config.DATA_DIR):
        if rel.startswith(base.name + "/"):
            rel = rel[len(base.name) + 1:]
            p = (base / rel).resolve()
            break
    else:
        base = config.WORKSPACE
        p = (base / rel).resolve()
    if base.resolve() not in p.parents and p != base.resolve():
        raise ValueError("Η διαδρομή βγαίνει έξω από τον επιτρεπόμενο φάκελο.")
    return p


@tool(
    "update_plan",
    "Δήλωσε ή ενημέρωσε το πλάνο σου. Κάλεσέ το ΠΡΩΤΟ, πριν από κάθε άλλη ενέργεια, και ξανά κάθε φορά "
    "που τελειώνει ένα βήμα. Ο χρήστης το βλέπει ζωντανά.",
    {"steps": {
        "type": "array",
        "description": "Όλα τα βήματα με τη σειρά.",
        "items": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Σύντομη περιγραφή του βήματος"},
                "status": {"type": "string", "enum": ["pending", "in_progress", "done"]},
            },
            "required": ["title", "status"],
        },
    }},
)
async def update_plan(ctx, steps: list) -> str:
    ctx.emit("plan", steps=steps)
    return "Το πλάνο ενημερώθηκε."


@tool(
    "notify_user",
    "Στείλε σύντομο μήνυμα προόδου στον χρήστη (κονσόλα και Telegram) χωρίς να σταματήσεις τη δουλειά.",
    {"message": {"type": "string", "description": "Το μήνυμα"}},
)
async def notify_user(ctx, message: str) -> str:
    await ctx.notify(message)
    return "Στάλθηκε."


@tool(
    "headline_result",
    "Δήλωσε το ένα βασικό αποτέλεσμα της δουλειάς σου, όπως θα το έλεγες σε μία φράση στον διευθυντή "
    "(π.χ. τιμή «1.240 €», ετικέτα «όφελος ανά μήνα»). Κάλεσέ το μία φορά, λίγο πριν το τελικό σου μήνυμα. "
    "Η τιμή πρέπει να έχει βγει από SQL ή από το compute, όχι από νοερή πράξη.",
    {"value": {"type": "string", "description": "Ο αριθμός με τη μονάδα του, π.χ. «1.240 €», «3 τιμολόγια», «−4,2 μονάδες»"},
     "label": {"type": "string", "description": "Τι μετράει ο αριθμός, σε 2 έως 5 λέξεις"},
     "detail": {"type": "string", "description": "Προαιρετικά: μία σύντομη πρόταση για το πώς προκύπτει"}},
    required=["value", "label"],
)
async def headline_result(ctx, value: str, label: str, detail: str = "") -> str:
    ctx.emit("headline", value=value, label=label, detail=detail)
    return "Καταγράφηκε."


@tool(
    "list_files",
    "Δείξε τα αρχεία ενός φακέλου. Διαθέσιμοι φάκελοι: 'workspace' (εδώ γράφεις) και 'data' (υλικό εισόδου).",
    {"folder": {"type": "string", "description": "π.χ. 'data/invoices' ή 'workspace'"}},
)
async def list_files(ctx, folder: str) -> str:
    p = safe_path(folder)
    if not p.exists():
        return f"Ο φάκελος {folder} δεν υπάρχει."
    rows = []
    for f in sorted(p.iterdir()):
        rows.append(f"{f.name}/" if f.is_dir() else f"{f.name}  ({f.stat().st_size} bytes)")
    return "\n".join(rows) or "(άδειος)"


@tool(
    "read_file",
    "Διάβασε αρχείο κειμένου (txt, md, csv, json, html). Για PDF χρησιμοποίησε το read_pdf.",
    {"path": {"type": "string", "description": "π.χ. 'data/bank_statement.csv'"}},
)
async def read_file(ctx, path: str) -> str:
    p = safe_path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    return text if len(text) <= 20000 else text[:20000] + f"\n... [κόπηκε, σύνολο {len(text)} χαρακτήρες]"


@tool(
    "write_file",
    "Γράψε αρχείο στο workspace (αναφορά .md/.html, .csv, .json). Τα αρχεία εμφανίζονται στον χρήστη ως παραδοτέα.",
    {
        "path": {"type": "string", "description": "Όνομα αρχείου μέσα στο workspace, π.χ. 'report.html'"},
        "content": {"type": "string", "description": "Το πλήρες περιεχόμενο"},
    },
)
async def write_file(ctx, path: str, content: str) -> str:
    p = safe_path(path)
    if config.WORKSPACE.resolve() not in p.parents:
        return "Επιτρέπεται εγγραφή μόνο στο workspace."
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    ctx.artifact(p)
    return f"Γράφτηκε: workspace/{p.relative_to(config.WORKSPACE).as_posix()}"
