"""Εργαλεία δεδομένων: ερωτήματα SQL στη βάση του demo και γραφήματα."""
import asyncio
import re
import threading

import duckdb

from .. import config
from . import tool

_con: duckdb.DuckDBPyConnection | None = None
_lock = threading.Lock()


def db() -> duckdb.DuckDBPyConnection:
    """Μία κοινή σύνδεση για όλη τη διεργασία (η DuckDB δεν δέχεται μικτές συνδέσεις στο ίδιο αρχείο)."""
    global _con
    if _con is None:
        if not config.DB_PATH.exists():
            raise FileNotFoundError("Δεν υπάρχει data/demo.duckdb. Τρέξε: python scripts/make_demo_data.py")
        _con = duckdb.connect(str(config.DB_PATH))
    return _con


def run_sql(sql: str, params: list | None = None) -> tuple[list[str], list[tuple]]:
    with _lock:
        cur = db().cursor()
        cur.execute(sql, params or [])
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchall() if cur.description else []
        return cols, rows


_READ_ONLY = re.compile(r"^\s*(select|with|describe|show|summarize|explain)\b", re.I)


def _table(cols: list[str], rows: list[tuple], limit: int = 200) -> str:
    out = [" | ".join(cols)]
    for r in rows[:limit]:
        out.append(" | ".join("" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v)) for v in r))
    if len(rows) > limit:
        out.append(f"... [{len(rows)} γραμμές συνολικά, εμφανίζονται οι πρώτες {limit}]")
    return "\n".join(out)


@tool("describe_data", "Δείξε τους πίνακες της βάσης, τις στήλες τους και πόσες γραμμές έχουν. Κάλεσέ το πριν γράψεις SQL.", {})
async def describe_data(ctx) -> str:
    def work():
        _, tables = run_sql("select table_name from information_schema.tables where table_schema='main' order by 1")
        parts = []
        for (t,) in tables:
            _, cols = run_sql(f'describe "{t}"')
            _, n = run_sql(f'select count(*) from "{t}"')
            parts.append(f"{t} ({n[0][0]} γραμμές): " + ", ".join(f"{c[0]} {c[1]}" for c in cols))
        return "\n".join(parts)
    return await asyncio.to_thread(work)


@tool(
    "sql_query",
    "Τρέξε ερώτημα SQL (DuckDB, μόνο ανάγνωση) στα δεδομένα της επιχείρησης και πάρε τον πίνακα αποτελεσμάτων. "
    "Κάνε τις συναθροίσεις μέσα στο SQL· επιστρέφονται το πολύ 200 γραμμές.",
    {"sql": {"type": "string", "description": "Ένα ερώτημα SELECT"}},
)
async def sql_query(ctx, sql: str) -> str:
    if not _READ_ONLY.match(sql):
        return "Επιτρέπονται μόνο ερωτήματα ανάγνωσης (SELECT / WITH / DESCRIBE)."
    cols, rows = await asyncio.to_thread(run_sql, sql)
    return _table(cols, rows) if rows else "(κανένα αποτέλεσμα)"


@tool(
    "make_chart",
    "Φτιάξε γράφημα PNG από ερώτημα SQL και αποθήκευσέ το στο workspace. Η πρώτη στήλη του ερωτήματος είναι "
    "ο άξονας Χ· κάθε επόμενη αριθμητική στήλη γίνεται μία σειρά.",
    {
        "sql": {"type": "string", "description": "Ερώτημα SELECT: πρώτη στήλη = Χ, οι υπόλοιπες = τιμές"},
        "kind": {"type": "string", "enum": ["line", "bar"], "description": "Τύπος γραφήματος"},
        "title": {"type": "string", "description": "Τίτλος που λέει το συμπέρασμα"},
        "filename": {"type": "string", "description": "π.χ. 'space_vs_sales.png'"},
    },
)
async def make_chart(ctx, sql: str, kind: str, title: str, filename: str) -> str:
    if not _READ_ONLY.match(sql):
        return "Επιτρέπονται μόνο ερωτήματα ανάγνωσης."
    cols, rows = await asyncio.to_thread(run_sql, sql)
    if not rows:
        return "Το ερώτημα δεν έφερε γραμμές, δεν έγινε γράφημα."
    if not filename.lower().endswith(".png"):
        filename += ".png"
    path = config.WORKSPACE / filename.replace("\\", "/").split("/")[-1]

    def draw():
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        x = [str(r[0]) for r in rows]
        fig, ax = plt.subplots(figsize=(9, 4.5), dpi=110)
        series = [(cols[i], [r[i] for r in rows]) for i in range(1, len(cols))
                  if isinstance(rows[0][i], (int, float)) or hasattr(rows[0][i], "__float__")]
        width = 0.8 / max(len(series), 1)
        for n, (name, ys) in enumerate(series):
            ys = [float(v) if v is not None else 0.0 for v in ys]
            if kind == "bar":
                ax.bar([i + n * width for i in range(len(x))], ys, width=width, label=name)
            else:
                ax.plot(x, ys, marker="o", markersize=3, linewidth=2, label=name)
        if kind == "bar":
            ax.set_xticks([i + width * (len(series) - 1) / 2 for i in range(len(x))])
            ax.set_xticklabels(x)
        step = max(len(x) // 12, 1)
        for i, label in enumerate(ax.get_xticklabels()):
            label.set_visible(i % step == 0)
            label.set_rotation(35)
            label.set_ha("right")
        ax.set_title(title, loc="left", fontweight="bold")
        ax.spines[["top", "right"]].set_visible(False)
        ax.grid(axis="y", alpha=0.25)
        if len(series) > 1:
            ax.legend(frameon=False)
        fig.tight_layout()
        fig.savefig(path)
        plt.close(fig)

    await asyncio.to_thread(draw)
    ctx.artifact(path)
    return f"Το γράφημα αποθηκεύτηκε: workspace/{path.name} (ενσωμάτωσέ το σε HTML ως <img src=\"{path.name}\">)"
