"""Εργαλεία ραφιού: το μοντέλο διαβάζει τη φωτογραφία, ο κώδικας κάνει όλα τα υπόλοιπα.

- read_shelf: το μοντέλο όρασης μετατρέπει τη φωτογραφία σε πίνακα (ράφι, θέση, κωδικός, προσόψεις, πλαίσιο).
- check_planogram: ο κώδικας συγκρίνει τον πίνακα με το πλανόγραμμα και ζωγραφίζει τα ευρήματα στη φωτογραφία.
- replenishment_plan: ο κώδικας υπολογίζει τεμάχια από την αποθήκη και τι πρέπει να παραγγελθεί.
- layout_suggestions: ο κώδικας συγκρίνει χώρο με πωλήσεις και ελέγχει το ύψος των ματιών.
- order_from_warehouse: καταχωρεί παραγγελία στην κεντρική αποθήκη, μόνο μετά από έγκριση.

Κάθε αριθμός γράφεται στο ίχνος ελέγχου (ctx.audit).
"""
import asyncio
import json
import math
from collections import defaultdict
from pathlib import Path

from .. import config
from .. import demo_data
from ..demo_data import DAYS
from . import tool
from .core import safe_path
from .data import _table, run_sql

UPLOADS = config.WORKSPACE / "photos"          # εδώ πέφτουν οι φωτογραφίες από το κινητό
STATUS = {"ok": "σωστό", "missing": "λείπει από το ράφι", "low": "λιγότερες προσόψεις", "extra": "περισσότερες προσόψεις",
          "misplaced": "σε λάθος ράφι", "unknown": "εκτός πλανογράμματος", "order": "λάθος σειρά"}
# Το schema και τα prompts της ανάγνωσης είναι στο agentkit/vision (schema.py, prompts.py).


def find_photo(photo: str) -> Path:
    """Δέχεται 'data/shelf/photos/x.png', 'workspace/photos/x.jpg' ή σκέτο όνομα αρχείου."""
    name = photo.replace("\\", "/").split("/")[-1]
    for candidate in (safe_path(photo), UPLOADS / name, demo_data.PHOTOS_DIR / name):
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"Δεν βρέθηκε η φωτογραφία: {photo}")


def _box(value) -> tuple[int, int, int, int] | None:
    try:
        ymin, xmin, ymax, xmax = (max(0, min(1000, int(v))) for v in value)
    except (TypeError, ValueError):
        return None
    return (ymin, xmin, ymax, xmax) if ymax > ymin and xmax > xmin else None


def _replace(table: str, rows: list[tuple]) -> None:
    run_sql(f"delete from {table}")
    for row in rows:
        run_sql(f"insert into {table} values ({','.join('?' * len(row))})", list(row))


def _current_photo() -> str:
    _, rows = run_sql("select photo from shelf_observation limit 1")
    if not rows:
        raise ValueError("Δεν έχει διαβαστεί φωτογραφία. Κάλεσε πρώτα το read_shelf.")
    return rows[0][0]


@tool(
    "read_shelf",
    "Διάβασε μια φωτογραφία ραφιού: ποια προϊόντα υπάρχουν, σε ποιο ράφι και θέση, με πόσες προσόψεις, και πού "
    "υπάρχουν κενά. Είναι πάντα το πρώτο βήμα. Το αποτέλεσμα αποθηκεύεται στον πίνακα shelf_observation.",
    {"photo": {"type": "string", "description": "π.χ. 'workspace/photos/shelf_101500.jpg' ή 'data/shelf/photos/sample_before.png'"}},
)
async def read_shelf(ctx, photo: str) -> str:
    from ..vision import read_photo          # prompt, schema, cache και mock ζουν στο agentkit/vision
    path = find_photo(photo)
    reading = await read_photo(path)

    name = path.name
    items, gaps = [], []
    for it in reading.get("items") or []:
        sku = it.get("sku")
        box = _box(it.get("box_2d")) or (None, None, None, None)
        items.append((name, int(it.get("shelf") or 0), int(it.get("position") or 0), sku,
                      str(it.get("label") or ""), max(int(it.get("facings") or 0), 0), *box))
    for g in reading.get("gaps") or []:
        box = _box(g.get("box_2d"))
        if box:
            gaps.append((name, int(g.get("shelf") or 0), *box))
    if reading.get("occluded"):
        return "Κάτι κρύβει μέρος του ραφιού (άνθρωπος ή αντικείμενο). Ζήτα νέα λήψη χωρίς εμπόδια."
    if not items:
        return "Δεν αναγνωρίστηκε κανένα προϊόν στη φωτογραφία. Ζήτα νέα λήψη, πιο κοντινή και με καλύτερο φως."

    def store():
        _replace("shelf_observation", items)
        _replace("shelf_gaps", gaps)
        _replace("shelf_issues", [])
        _replace("replenishment", [])
    await asyncio.to_thread(store)

    ctx.audit("extract", source=name, values={
        (i[3] or f"άγνωστο: {i[4]}"): f"ράφι {i[1]}, θέση {i[2]}, {i[5]} προσόψεις" for i in items})
    rows = [(i[1], i[2], i[3] or "-", i[4], i[5]) for i in sorted(items, key=lambda i: (i[1], i[2]))]
    return (f"Φωτογραφία {name}: {len(items)} ομάδες προϊόντων, {len(gaps)} κενά.\n"
            + _table(["ράφι", "θέση", "κωδικός", "ετικέτα", "προσόψεις"], rows)
            + "".join(f"\nΠαρουσίαση, ράφι {v['shelf']}: {v['detail']}" for v in reading.get("visual_issues") or []))


def _compare() -> dict:
    """Σύγκριση παρατήρησης με πλανόγραμμα, ανά κωδικό. Καθαρός κώδικας, χωρίς μοντέλο."""
    photo = _current_photo()
    _, plan = run_sql("select pl.shelf, pl.position, pl.sku, p.name, pl.facings from planogram pl "
                      "join products p using (sku) order by pl.shelf, pl.position")
    _, obs = run_sql("select shelf, position, sku, label, facings from shelf_observation order by shelf, position")
    seen: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for shelf, _pos, sku, _label, facings in obs:
        if sku:
            seen[sku][shelf] += facings
    planned = {r[2] for r in plan}

    issues, status_of, ok = [], {}, 0
    for shelf, _pos, sku, name, facings in plan:
        here = seen[sku].get(shelf, 0)
        elsewhere = sorted(s for s in seen[sku] if s != shelf)
        if here == 0 and elsewhere:
            status, detail = "misplaced", f"βρέθηκε στο ράφι {', '.join(map(str, elsewhere))}, η θέση του είναι στο ράφι {shelf}"
        elif here == 0:
            status, detail = "missing", f"καμία πρόσοψη στο ράφι {shelf}"
        elif here < facings:
            status, detail = "low", f"{here} από {facings} προσόψεις"
        elif here > facings:
            status, detail = "extra", f"{here} προσόψεις αντί για {facings}"
        else:
            status, detail = "ok", ""
            ok += 1
        status_of[sku] = status
        if status != "ok":
            issues.append((photo, sku, name, shelf, status, facings, here, detail))
        if status in ("ok", "low", "extra") and elsewhere:
            issues.append((photo, sku, name, shelf, "misplaced", facings, here,
                           f"υπάρχει και στο ράφι {', '.join(map(str, elsewhere))}"))

    for shelf, _pos, sku, label, facings in obs:
        if not sku or sku not in planned:
            issues.append((photo, sku, label, shelf, "unknown", 0, facings, f"«{label}» στο ράφι {shelf}"))

    for shelf in sorted({r[0] for r in plan}):
        want = [r[2] for r in plan if r[0] == shelf]
        got = []
        for o in obs:
            if o[0] == shelf and o[2] in want and o[2] not in got:
                got.append(o[2])
        expected = [s for s in want if s in got]
        if got != expected:
            issues.append((photo, None, f"Ράφι {shelf}", shelf, "order", 0, 0,
                           f"σειρά {' → '.join(got)}, το πλανόγραμμα θέλει {' → '.join(expected)}"))

    compliance = round(100 * ok / len(plan), 1) if plan else 0.0
    return {"photo": photo, "issues": issues, "ok": ok, "slots": len(plan), "compliance": compliance,
            "status_of": status_of, "planned": planned}


def _annotate(photo: str, result: dict) -> Path | None:
    """Ζωγραφίζει τα ευρήματα πάνω στη φωτογραφία: πράσινο σωστό, πορτοκαλί προσόψεις, κόκκινο λάθος ή κενό."""
    from matplotlib import font_manager
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    _, boxes = run_sql("select o.sku, o.label, o.shelf, o.ymin, o.xmin, o.ymax, o.xmax, pl.shelf "
                       "from shelf_observation o left join planogram pl using (sku) where o.ymin is not null")
    _, gaps = run_sql("select ymin, xmin, ymax, xmax from shelf_gaps")
    if not boxes and not gaps:
        return None
    colors = {"ok": (46, 160, 67), "low": (230, 150, 0), "extra": (230, 150, 0)}
    red = (207, 34, 46)
    with Image.open(find_photo(photo)) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
    w, h = im.size
    line = max(3, round(min(w, h) / 220))
    font = ImageFont.truetype(font_manager.findfont("DejaVu Sans"), max(14, round(min(w, h) / 45)))
    draw = ImageDraw.Draw(im)

    def rect(ymin, xmin, ymax, xmax):
        return [xmin * w / 1000, ymin * h / 1000, xmax * w / 1000, ymax * h / 1000]

    for sku, label, shelf, ymin, xmin, ymax, xmax, planned_shelf in boxes:
        status = "unknown" if not sku or planned_shelf is None else (
            "misplaced" if planned_shelf != shelf else result["status_of"].get(sku, "ok"))
        color = colors.get(status, red)
        r = rect(ymin, xmin, ymax, xmax)
        draw.rectangle(r, outline=color, width=line)
        text = (sku or "?") + ("" if status == "ok" else " · " + STATUS[status])
        tb = draw.textbbox((0, 0), text, font=font)
        top = max(r[1] - (tb[3] - tb[1]) - 8, 0)                  # η ετικέτα κάθεται πάνω από το πλαίσιο
        draw.rectangle([r[0], top, r[0] + tb[2] + 10, top + tb[3] + 8], fill=color)
        draw.text((r[0] + 5, top + 2), text, fill="white", font=font)
    for ymin, xmin, ymax, xmax in gaps:
        r = rect(ymin, xmin, ymax, xmax)
        draw.rectangle(r, outline=red, width=line)
        draw.line([r[0], r[1], r[2], r[3]], fill=red, width=line)
        draw.line([r[0], r[3], r[2], r[1]], fill=red, width=line)
        tb = draw.textbbox((0, 0), "κενό", font=font)
        cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
        draw.rectangle([cx - tb[2] / 2 - 6, cy - tb[3] / 2 - 4, cx + tb[2] / 2 + 6, cy + tb[3] / 2 + 6], fill=red)
        draw.text((cx - tb[2] / 2, cy - tb[3] / 2), "κενό", fill="white", font=font)

    out = config.WORKSPACE / f"shelf_check_{Path(photo).stem}.png"
    im.save(out)
    return out


@tool(
    "check_planogram",
    "Σύγκρινε ό,τι διάβασε το read_shelf με το πλανόγραμμα. Επιστρέφει τα ευρήματα ανά κωδικό (λείπει, λιγότερες "
    "προσόψεις, λάθος ράφι, λάθος σειρά, εκτός πλανογράμματος), το ποσοστό συμμόρφωσης και τη φωτογραφία με τα "
    "ευρήματα σημειωμένα. Δείχνει και τον προηγούμενο έλεγχο, για σύγκριση πριν και μετά.",
    {},
)
async def check_planogram(ctx) -> str:
    def work():
        result = _compare()
        _, previous = run_sql("select photo, compliance_pct, issues from shelf_checks order by checked_at desc limit 1")
        _replace("shelf_issues", result["issues"])
        run_sql("insert into shelf_checks values (now(), ?, ?, ?)",
                [result["photo"], result["compliance"], len(result["issues"])])
        return result, previous, _annotate(result["photo"], result)
    result, previous, image = await asyncio.to_thread(work)

    ctx.audit("compute", label="Συμμόρφωση με το πλανόγραμμα (%)", expression="round(100 * correct_slots / slots, 1)",
              variables={"correct_slots": result["ok"], "slots": result["slots"]}, result=result["compliance"])
    if image:
        ctx.artifact(image)
        ctx.emit("screenshot", file=image.name, url=f"Έλεγχος ραφιού · {result['compliance']}% συμμόρφωση")

    out = [f"Συμμόρφωση: {result['compliance']}% ({result['ok']} από {result['slots']} θέσεις σωστές), "
           f"{len(result['issues'])} ευρήματα."]
    if previous:
        out.append(f"Προηγούμενος έλεγχος ({previous[0][0]}): {previous[0][1]}%, {previous[0][2]} ευρήματα.")
    if result["issues"]:
        out.append(_table(["κωδικός", "προϊόν", "ράφι", "εύρημα", "λεπτομέρεια"],
                          [(i[1] or "-", i[2], i[3], STATUS[i[4]], i[7]) for i in result["issues"]]))
    else:
        out.append("Το ράφι συμφωνεί πλήρως με το πλανόγραμμα.")
    if image:
        out.append(f"Σημειωμένη φωτογραφία: workspace/{image.name}")
    return "\n".join(out)


@tool(
    "replenishment_plan",
    "Υπολόγισε τι χρειάζεται για να γεμίσει το ράφι: τεμάχια ανά κωδικό, πόσα υπάρχουν στην αποθήκη του "
    "καταστήματος και πόσα πρέπει να παραγγελθούν (σε κιβώτια). Υπολογίζει και τις ημερήσιες πωλήσεις που "
    "κινδυνεύουν από τους κωδικούς που λείπουν εντελώς. Κάλεσέ το μετά το read_shelf.",
    {},
)
async def replenishment_plan(ctx) -> str:
    def work():
        photo = _current_photo()
        _, rows = run_sql("""
            select pl.sku, p.name, pl.facings, pl.depth, p.case_size, coalesce(b.on_hand, 0), coalesce(o.seen, 0)
            from planogram pl join products p using (sku) left join backroom b using (sku)
            left join (select sku, sum(facings) seen from shelf_observation where sku is not null group by 1) o using (sku)
            order by pl.shelf, pl.position""")
        _, daily = run_sql("select sku, sum(revenue) / count(distinct date) from sales group by 1")
        return photo, rows, dict(daily)
    photo, rows, daily = await asyncio.to_thread(work)

    lines, at_risk = [], {}
    for sku, name, facings, depth, case_size, on_hand, seen in rows:
        missing = max(facings - seen, 0)
        if not missing:
            continue
        units = missing * depth
        from_backroom = min(units, on_hand)
        to_order = units - from_backroom
        cases = math.ceil(to_order / case_size) if to_order else 0
        lines.append((photo, sku, name, missing, units, from_backroom, to_order, cases))
        ctx.audit("compute", label=f"{sku}: τεμάχια για αναπλήρωση", expression="missing_facings * depth",
                  variables={"missing_facings": missing, "depth": depth}, result=units)
        if to_order:
            ctx.audit("compute", label=f"{sku}: κιβώτια προς παραγγελία",
                      expression="ceil((units - backroom_on_hand) / case_size)",
                      variables={"units": units, "backroom_on_hand": on_hand, "case_size": case_size}, result=cases)
        if seen == 0:
            at_risk[sku] = round(float(daily.get(sku, 0)), 2)
    await asyncio.to_thread(_replace, "replenishment", lines)
    if not lines:
        return "Δεν χρειάζεται αναπλήρωση: όλες οι προσόψεις του πλανογράμματος υπάρχουν στο ράφι."

    total_backroom = sum(l[5] for l in lines)
    risk = round(sum(at_risk.values()), 2)
    if at_risk:
        ctx.audit("compute", label="Πωλήσεις σε κίνδυνο ανά ημέρα (€)",
                  expression="sum(avg_daily_revenue of skus with no facing on the shelf)", variables=at_risk, result=risk)
    out = [_table(["κωδικός", "προϊόν", "προσόψεις που λείπουν", "τεμάχια", "από αποθήκη", "προς παραγγελία", "κιβώτια"],
                  [l[1:] for l in lines]),
           f"Σύνολο από την αποθήκη: {total_backroom} τεμάχια σε {sum(1 for l in lines if l[5])} κωδικούς."]
    to_order = [l for l in lines if l[6]]
    if to_order:
        out.append("Η αποθήκη δεν φτάνει για: " + ", ".join(f"{l[1]} ({l[7]} κιβ.)" for l in to_order)
                   + ". Ετοίμασε παραγγελία με το order_from_warehouse.")
    if at_risk:
        out.append(f"Κωδικοί χωρίς καμία πρόσοψη: {', '.join(at_risk)}. Πωλήσεις σε κίνδυνο: {risk} € ανά ημέρα "
                   f"(μέσος όρος {DAYS} ημερών).")
    out.append("Υπόθεση: πίσω από κάθε πρόσοψη που φαίνεται το ράφι είναι γεμάτο. Η κάμερα δεν βλέπει το βάθος.")
    return "\n".join(out)


@tool(
    "layout_suggestions",
    "Έλεγξε τη διάταξη του πλανογράμματος με κανόνες category management: μερίδιο χώρου έναντι μεριδίου πωλήσεων "
    "ανά κωδικό, και αν στο ύψος των ματιών βρίσκονται οι κωδικοί με το υψηλότερο περιθώριο ανά πρόσοψη. "
    "Επιστρέφει έως δύο προτάσεις με τους αριθμούς που τις στηρίζουν.",
    {},
)
async def layout_suggestions(ctx) -> str:
    _, rows = await asyncio.to_thread(run_sql, """
        with s as (select sku, sum(revenue) rev, sum(revenue - cost) margin from sales group by 1)
        select pl.sku, p.name, pl.shelf, pl.level, pl.facings, s.rev, s.margin
        from planogram pl join products p using (sku) join s using (sku) order by pl.shelf, pl.position""")
    if not rows:
        return "Δεν υπάρχουν πωλήσεις για το πλανόγραμμα."
    total_facings = sum(r[4] for r in rows)
    total_rev = sum(r[5] for r in rows) or 1
    table, stats = [], {}
    for sku, name, shelf, level, facings, rev, margin in rows:
        space = 100 * facings / total_facings
        sales = 100 * rev / total_rev
        per_facing = margin / DAYS / facings
        stats[sku] = {"name": name, "shelf": shelf, "level": level, "facings": facings, "space": round(space, 1),
                      "sales": round(sales, 1), "index": round(sales / space, 2), "per_facing": round(per_facing, 2)}
        table.append((sku, name, shelf, level, facings, round(space, 1), round(sales, 1),
                      stats[sku]["index"], stats[sku]["per_facing"]))

    suggestions = []
    eye = [s for s in stats if stats[s]["level"] == "eye"]
    rest = [s for s in stats if stats[s]["level"] != "eye"]
    if eye and rest:
        best = max(rest, key=lambda s: stats[s]["per_facing"])
        worst = min(eye, key=lambda s: stats[s]["per_facing"])
        if stats[best]["per_facing"] > 1.25 * stats[worst]["per_facing"]:
            ctx.audit("compute", label="Περιθώριο ανά πρόσοψη ανά ημέρα (€)", expression="margin / days / facings",
                      variables={best: stats[best]["per_facing"], worst: stats[worst]["per_facing"], "days": DAYS},
                      result=round(stats[best]["per_facing"] - stats[worst]["per_facing"], 2))
            suggestions.append(
                f"Ύψος ματιών: το {best} ({stats[best]['name']}) αποδίδει {stats[best]['per_facing']} € περιθώριο ανά "
                f"πρόσοψη την ημέρα από το ράφι {stats[best]['shelf']}, ενώ το {worst} ({stats[worst]['name']}) αποδίδει "
                f"{stats[worst]['per_facing']} € στο ύψος των ματιών. Πρόταση: να αλλάξουν θέση.")
    under = max(stats, key=lambda s: stats[s]["index"])
    over = min(stats, key=lambda s: stats[s]["index"])
    if stats[under]["index"] >= 1.3 and stats[over]["index"] <= 0.7 and stats[over]["facings"] > 1:
        ctx.audit("compute", label="Δείκτης χώρου (μερίδιο πωλήσεων / μερίδιο χώρου)", expression="sales_share / space_share",
                  variables={under: stats[under]["index"], over: stats[over]["index"]}, result=stats[under]["index"])
        suggestions.append(
            f"Χώρος: το {under} ({stats[under]['name']}) κάνει το {stats[under]['sales']}% των πωλήσεων με "
            f"{stats[under]['space']}% του χώρου, ενώ το {over} ({stats[over]['name']}) κάνει {stats[over]['sales']}% με "
            f"{stats[over]['space']}%. Πρόταση: μία πρόσοψη από το {over} στο {under}.")

    out = [_table(["κωδικός", "προϊόν", "ράφι", "επίπεδο", "προσόψεις", "% χώρου", "% πωλήσεων", "δείκτης", "€ περιθώριο/πρόσοψη/ημέρα"], table)]
    out += suggestions or ["Καμία πρόταση: η διάταξη συμφωνεί με τους κανόνες."]
    out.append(f"Οι πωλήσεις είναι {DAYS} ημερών. Οι προτάσεις δεν προβλέπουν αύξηση πωλήσεων· δείχνουν μόνο τη σημερινή "
               "απόδοση του χώρου. Αλλαγή πλανογράμματος αποφασίζει ο category manager.")
    return "\n".join(out)


def _order_needs_approval(args: dict) -> bool:
    """Αυτονομία μέσα σε όρια: έγκριση μόνο αν η παραγγελία ξεπερνά AUTO_ORDER_MAX_CASES ή AUTO_ORDER_MAX_EUR."""
    if not config.AUTO_ORDER:
        return True
    from .. import portal
    try:
        cases = {l["sku"]: int(l["cases"]) for l in args.get("lines") or []}
    except (KeyError, TypeError, ValueError):
        return True
    _lines, total = portal._lines(cases)
    return sum(cases.values()) > config.AUTO_ORDER_MAX_CASES or total > config.AUTO_ORDER_MAX_EUR


@tool(
    "order_from_warehouse",
    "Καταχώρισε παραγγελία στην κεντρική αποθήκη για κωδικούς που δεν υπάρχουν στην αποθήκη του καταστήματος. "
    "Μικρές παραγγελίες γίνονται αμέσως· πάνω από τα όρια του καταστήματος θέλει έγκριση ανθρώπου. Χρησιμοποίησε τα κιβώτια που έβγαλε το replenishment_plan.",
    {"lines": {
        "type": "array",
        "description": "Οι γραμμές της παραγγελίας.",
        "items": {"type": "object",
                  "properties": {"sku": {"type": "string"}, "cases": {"type": "integer", "description": "Κιβώτια"}},
                  "required": ["sku", "cases"]},
    }},
    needs_approval=_order_needs_approval,     # χωρίς έγκριση μέσα στα όρια του .env
)
async def order_from_warehouse(ctx, lines: list) -> str:
    from .. import portal
    order = await asyncio.to_thread(portal.place_order, {l["sku"]: int(l["cases"]) for l in lines})
    if not order["lines"]:
        return "Η παραγγελία δεν είχε έγκυρες γραμμές."
    return (f"Η παραγγελία {order['order_no']} καταχωρήθηκε στην κεντρική αποθήκη: "
            + ", ".join(f"{l['sku']} × {l['cases']} κιβ. ({l['units']} τεμ.)" for l in order["lines"])
            + f". Αξία {order['total']:.2f} €. Φαίνεται στο {config.BASE_URL}/portal/orders")
