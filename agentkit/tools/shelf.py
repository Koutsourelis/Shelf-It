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

from .. import config, demo_data, rules as decision_rules
from ..demo_data import DAYS
from . import tool
from .core import safe_path
from .data import _table, run_sql

UPLOADS = config.WORKSPACE / "photos"          # εδώ πέφτουν οι φωτογραφίες από το κινητό
STATUS = {"ok": "σωστό", "missing": "λείπει από το ράφι", "low": "λιγότερες προσόψεις", "extra": "περισσότερες προσόψεις",
          "misplaced": "λάθος επίπεδο", "unknown": "εκτός καταλόγου", "order": "λάθος σειρά", "visual": "παρουσίαση"}
# Το schema και τα prompts της ανάγνωσης είναι στο agentkit/vision (schema.py, prompts.py).


def find_photo(photo: str) -> Path:
    """Δέχεται 'data/shelf/photos/x.png', 'workspace/photos/x.jpg', σκέτο όνομα αρχείου ή 'latest' (η πιο πρόσφατη
    λήψη της κάμερας ή του κινητού). Αν λείπει η κατάληξη που ζητήθηκε, δοκιμάζει το ίδιο όνομα ως jpg/jpeg/png/webp."""
    if photo.strip().lower() in ("latest", ""):
        shots = [f for d in (config.WORKSPACE / "live", UPLOADS) if d.is_dir() for f in d.iterdir()
                 if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
        if not shots:
            raise FileNotFoundError("Δεν υπάρχει ακόμη λήψη από την κάμερα ή το κινητό.")
        return max(shots, key=lambda f: f.stat().st_mtime)
    name = photo.replace("\\", "/").split("/")[-1]
    candidates = [safe_path(photo), UPLOADS / name, demo_data.PHOTOS_DIR / name]
    candidates += [c.with_suffix(ext) for c in list(candidates) for ext in (".jpg", ".jpeg", ".png", ".webp")]
    for candidate in candidates:
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
    from ..vision import assess_photo          # μία κλήση: τι υπάρχει, τι λείπει, τι είναι σε λάθος επίπεδο
    from ..vision.assessment import LEVEL_TO_SHELF
    path = find_photo(photo)
    verdict = await assess_photo(path)
    _VERDICTS[path.name] = verdict

    name = path.name
    items, gaps = [], []
    for sh in verdict["shelves"]:
        shelf = LEVEL_TO_SHELF[sh["level"]]
        for pos, it in enumerate(sh["items"], 1):
            box = it.get("box_2d") or (None, None, None, None)
            items.append((name, shelf, pos, it.get("sku"), it.get("label") or "", it.get("facings") or 0,
                          *[box[i] for i in range(4)]))
    for sh in verdict["shelves"]:                       # τα κενά δεν τα δίνει πια το μοντέλο χωριστά
        pass

    if verdict.get("occluded"):
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
        (i[3] or f"άγνωστο: {i[4]}"): f"επίπεδο {i[1]}, {i[5]} προσόψεις, {'σωστά' if True else ''}" for i in items})
    rows = [(i[1], i[3] or "-", i[4], i[5]) for i in items]
    lines = [f"Φωτογραφία {name}: {len(items)} ομάδες προϊόντων.",
             _table(["επίπεδο", "κωδικός", "ετικέτα", "προσόψεις"], rows)]
    if verdict["missing"]:
        lines.append("Λείπουν: " + ", ".join(m["product"] or str(m["sku"]) for m in verdict["missing"]))
    if verdict["misplaced"]:
        lines.append("Λάθος επίπεδο: " + ", ".join(
            f"{m['product']} ({m['from_level']} → {m['to_level']})" for m in verdict["misplaced"]))
    if verdict["foreign"]:
        lines.append("Ξένα στο ράφι: " + ", ".join(f["label"] for f in verdict["foreign"]))
    if verdict["visual_issues"]:
        lines.append("Παρουσίαση: " + "; ".join(v["detail"] for v in verdict["visual_issues"]))
    if verdict.get("summary"):
        lines.append("Εκτίμηση: " + verdict["summary"])
    return "\n".join(lines)


_VERDICTS: dict[str, dict] = {}      # photo όνομα -> εκτίμηση του μοντέλου (τι λείπει, τι είναι λάθος)


def _verdict(photo: str) -> dict:
    if photo in _VERDICTS:
        return _VERDICTS[photo]
    raise ValueError("Δεν υπάρχει εκτίμηση για αυτή τη φωτογραφία. Κάλεσε πρώτα το read_shelf.")


def _compare() -> dict:
    """Ευρήματα από την εκτίμηση του μοντέλου. Εδώ ΔΕΝ συγκρίνονται θέσεις· ο κώδικας μετράει μόνο το ποσοστό."""
    from ..vision.assessment import LEVEL_TO_SHELF
    photo = _current_photo()
    verdict = _verdict(photo)
    _, catalog = run_sql("select sku, name from products order by sku")
    names = dict(catalog)

    issues, status_of = [], {}
    for item in (i for sh in verdict["shelves"] for i in sh["items"]):
        sku, target, seen = item.get("sku"), item.get("target_facings") or 0, item.get("facings") or 0
        if not sku:
            continue
        if not item.get("placement_ok", True):
            level = next(sh["level"] for sh in verdict["shelves"] if item in sh["items"])
            status, detail = "misplaced", "δεν ταιριάζει στο επίπεδο που στέκει"
            issues.append((photo, sku, names.get(sku, item["label"]), LEVEL_TO_SHELF[level], "misplaced", target, seen, detail))
        elif target and seen < target:
            level = next(sh["level"] for sh in verdict["shelves"] if item in sh["items"])
            issues.append((photo, sku, names.get(sku, item["label"]), LEVEL_TO_SHELF[level], "low", target, seen,
                           f"{seen} από {target} προσόψεις"))
        status_of[sku] = "ok" if not any(i[1] == sku for i in issues) else "low"
    for m in verdict["missing"]:
        issues.append((photo, m.get("sku"), names.get(m["sku"]) if m.get("sku") else m["product"], 0, "missing",
                       m.get("target_facings") or 0, 0, m.get("why") or "δεν φαίνεται στο ράφι"))
        if m.get("sku"):
            status_of[m["sku"]] = "missing"
    for m in verdict["misplaced"]:
        issues.append((photo, m.get("sku"), names.get(m["sku"]) if m.get("sku") else m["product"],
                       LEVEL_TO_SHELF[m["from_level"]], "misplaced", 0, 0,
                       f"πρέπει να πάει στο επίπεδο {m['to_level']}: {m.get('why') or ''}"))
        if m.get("sku"):
            status_of[m["sku"]] = "misplaced"
    for f in verdict["foreign"]:
        issues.append((photo, None, f["label"], LEVEL_TO_SHELF[f["level"]], "unknown", 0, 0,
                       f"«{f['label']}» δεν ανήκει στο τμήμα"))
    for v in verdict["visual_issues"]:
        issues.append((photo, None, v["detail"], LEVEL_TO_SHELF[v["level"]], "visual", 0, 0, v["detail"]))

    present = {i.get("sku") for sh in verdict["shelves"] for i in sh["items"] if i.get("sku")}
    ok = len([s for s in present if status_of.get(s) == "ok"])
    slots = len(catalog) or 1
    return {"photo": photo, "issues": issues, "ok": ok, "slots": slots,
            "compliance": round(100 * ok / slots, 1), "status_of": status_of, "planned": {r[0] for r in catalog},
            "summary": verdict.get("summary", ""), "suggested_layout": verdict.get("suggested_layout", []),
            "shelf_ok": verdict.get("shelf_ok", False)}


def _annotate(photo: str, result: dict) -> Path | None:
    """Ζωγραφίζει ό,τι είδε το μοντέλο: πράσινο σωστό, πορτοκαλί λίγες προσόψεις, κόκκινο λάθος ή ξένο."""
    from matplotlib import font_manager
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    _, boxes = run_sql("select sku, label, shelf, ymin, xmin, ymax, xmax from shelf_observation "
                       "where ymin is not null")
    if not boxes:
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

    for sku, label, shelf, ymin, xmin, ymax, xmax in boxes:
        status = result["status_of"].get(sku, "unknown" if not sku else "ok")
        color = colors.get(status, red)
        r = rect(ymin, xmin, ymax, xmax)
        draw.rectangle(r, outline=color, width=line)
        text = (sku or label or "?") + ("" if status == "ok" else " · " + STATUS.get(status, status))
        tb = draw.textbbox((0, 0), text, font=font)
        top = max(r[1] - (tb[3] - tb[1]) - 8, 0)
        draw.rectangle([r[0], top, r[0] + tb[2] + 10, top + tb[3] + 8], fill=color)
        draw.text((r[0] + 5, top + 2), text, fill="white", font=font)

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
        out.append(_table(["κωδικός", "προϊόν", "επίπεδο", "εύρημα", "λεπτομέρεια"],
                          [(i[1] or "-", i[2], i[3], STATUS.get(i[4], i[4]), i[7]) for i in result["issues"]]))
    else:
        out.append("Το ράφι είναι όπως πρέπει.")
    if result.get("summary"):
        out.append("Εκτίμηση: " + result["summary"])
    for lay in result.get("suggested_layout") or []:
        out.append(f"Πρόταση, επίπεδο {lay['level']}: {' → '.join(lay['order'])} — {lay['why']}")
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

    rules = decision_rules.load()
    # Κ1: πρώτα οι κωδικοί που λείπουν εντελώς, κατά χαμένες πωλήσεις· μετά οι υπόλοιποι, κατά πωλήσεις.
    rows.sort(key=lambda r: (r[6] > 0, -float(daily.get(r[0], 0))))
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
            at_risk[sku] = decision_rules.lost_sales(float(daily.get(sku, 0)), rules)
            ctx.audit("compute", label=f"{sku}: χαμένες πωλήσεις ανά ημέρα (€), κανόνας Κ1",
                      expression="avg_daily_revenue * lost_share",
                      variables={"avg_daily_revenue": round(float(daily.get(sku, 0)), 2),
                                 "lost_share": rules["K1"]["lost_share"]}, result=at_risk[sku])
    await asyncio.to_thread(_replace, "replenishment", lines)
    if not lines:
        return "Δεν χρειάζεται αναπλήρωση: όλες οι προσόψεις του πλανογράμματος υπάρχουν στο ράφι."

    total_backroom = sum(l[5] for l in lines)
    risk = round(sum(at_risk.values()), 2)
    if at_risk:
        ctx.audit("compute", label="Χαμένες πωλήσεις ανά ημέρα (€), σύνολο",
                  expression="sum(lost sales of skus with no facing on the shelf)", variables=at_risk, result=risk)
    out = ["Με σειρά προτεραιότητας (κανόνας Κ1):",
           _table(["κωδικός", "προϊόν", "προσόψεις που λείπουν", "τεμάχια", "από αποθήκη", "προς παραγγελία", "κιβώτια"],
                  [l[1:] for l in lines]),
           f"Σύνολο από την αποθήκη: {total_backroom} τεμάχια σε {sum(1 for l in lines if l[5])} κωδικούς."]
    to_order = [l for l in lines if l[6]]
    if to_order:
        out.append("Η αποθήκη δεν φτάνει για: " + ", ".join(f"{l[1]} ({l[7]} κιβ.)" for l in to_order)
                   + ". Ετοίμασε παραγγελία με το order_from_warehouse.")
    if at_risk:
        out.append(f"Κωδικοί χωρίς καμία πρόσοψη: {', '.join(at_risk)}. Χαμένες πωλήσεις για το κατάστημα: {risk} € ανά "
                   f"ημέρα, δηλαδή το {round(100 * rules['K1']['lost_share'])}% των μέσων πωλήσεων {DAYS} ημερών. "
                   f"Πηγή: {rules['K1']['source']}.")
    out.append(f"Πρώτα η αποθήκη του καταστήματος, μετά παραγγελία (κανόνας Κ2). Πηγή: {rules['K2']['source']}.")
    out.append("Υπόθεση: πίσω από κάθε πρόσοψη που φαίνεται το ράφι είναι γεμάτο. Η κάμερα δεν βλέπει το βάθος.")
    return "\n".join(out)


@tool(
    "layout_suggestions",
    "Έλεγξε τη διάταξη του πλανογράμματος με τους κανόνες category management Κ3 έως Κ6: ύψος ματιών, οριζόντιο "
    "κέντρο, ιδιωτική ετικέτα δίπλα στον ηγέτη, χώρος έναντι πωλήσεων. Κάθε πρόταση έχει τέσσερα μέρη (τι, κανόνας, "
    "αριθμός, πηγή)· μετάφερέ τα αυτούσια και μην προσθέτεις δικούς σου αριθμούς ή ποσοστά αύξησης.",
    {},
)
async def layout_suggestions(ctx) -> str:
    _, rows = await asyncio.to_thread(run_sql, """
        with s as (select sku, sum(qty) qty, sum(revenue) rev, sum(revenue - cost) margin from sales group by 1)
        select pl.sku, p.name, p.brand, p.category, pl.shelf, pl.level, pl.position, pl.facings, pl.depth,
               coalesce(s.qty, 0), coalesce(s.rev, 0), coalesce(s.margin, 0)
        from planogram pl join products p using (sku) left join s using (sku) order by pl.shelf, pl.position""")
    slots = [decision_rules.Slot(sku, name, brand or "", category or "", shelf, level, position, facings, depth,
                                 float(qty) / DAYS, float(rev) / DAYS, float(margin) / DAYS)
             for sku, name, brand, category, shelf, level, position, facings, depth, qty, rev, margin in rows]
    suggestions, skipped = decision_rules.evaluate(slots)

    for s in suggestions:
        ctx.audit("compute", label=f"{s.rule}: {s.title}", expression=s.expression, variables=s.variables, result=s.result)
    path = config.WORKSPACE / "suggestions.json"
    path.write_text(json.dumps({"suggestions": [s.as_dict() for s in suggestions], "skipped": skipped},
                               ensure_ascii=False, indent=2), encoding="utf-8")
    ctx.artifact(path)

    total_facings = sum(s.facings for s in slots) or 1
    total_rev = sum(s.revenue_day for s in slots) or 1
    table = [(s.sku, s.name, s.shelf, s.level, s.facings, round(100 * s.facings / total_facings, 1),
              round(100 * s.revenue_day / total_rev, 1), round(s.margin_per_facing, 2)) for s in slots]
    out = [_table(["κωδικός", "προϊόν", "ράφι", "επίπεδο", "προσόψεις", "% χώρου", "% πωλήσεων", "€ περιθώριο/πρόσοψη/ημέρα"], table)]
    out += [f"\nΠρόταση {n}\n{s.as_text()}" for n, s in enumerate(suggestions, start=1)]
    if not suggestions and not skipped:
        out.append("Καμία πρόταση: η διάταξη συμφωνεί με τους κανόνες.")
    out += skipped
    out.append(f"\nΟι πωλήσεις είναι {DAYS} ημερών. Η θέση (Κ4, Κ5, Κ6) έχει προτεραιότητα έναντι των προσόψεων (Κ3). "
               "Αλλαγή πλανογράμματος αποφασίζει ο category manager. Αρχείο: workspace/suggestions.json")
    return "\n".join(out)


ELASTICITY = 0.17          # ελαστικότητα χώρου, Eisend 2014 (planning/DECISION_RULES.md, Κ3)
SOURCES = {
    "K3": "Eisend 2014, ελαστικότητα χώρου 0,17",
    "K4": "Drèze, Hoch & Purk 1994· Chandon κ.ά. 2009 (ύψος ματιών)",
    "K5": "Atalay, Bodur & Rasolofoarison 2012 (οριζόντιο κέντρο)",
}
LEVEL_EL = {"top": "πάνω", "eye": "ύψος ματιών", "bottom": "κάτω"}


def _layout_stats() -> dict[str, dict]:
    """Ανά κωδικό του πλανογράμματος: θέση, χώρος, πωλήσεις και περιθώριο. Όλοι οι αριθμοί από SQL."""
    _, rows = run_sql("""
        with s as (select sku, sum(revenue) rev, sum(revenue - cost) margin, sum(qty) qty from sales group by 1)
        select pl.sku, p.name, p.brand, p.category, pl.shelf, pl.level, pl.position, pl.facings,
               coalesce(s.rev, 0), coalesce(s.margin, 0), coalesce(s.qty, 0)
        from planogram pl join products p using (sku) left join s using (sku) order by pl.shelf, pl.position""")
    total_facings = sum(r[7] for r in rows) or 1
    total_rev = sum(r[8] for r in rows) or 1
    per_shelf: dict[int, list[int]] = defaultdict(list)
    for r in rows:
        per_shelf[r[4]].append(r[6])
    stats = {}
    for sku, name, brand, category, shelf, level, position, facings, rev, margin, qty in rows:
        slots = sorted(per_shelf[shelf])
        center = len(slots) % 2 == 1 and len(slots) > 1 and position == slots[len(slots) // 2]
        space, sales = 100 * facings / total_facings, 100 * rev / total_rev
        stats[sku] = {"sku": sku, "name": name, "brand": brand, "category": category, "shelf": shelf, "level": level,
                      "position": position, "center": center, "facings": facings, "space": round(space, 1),
                      "sales": round(sales, 1), "index": round(sales / (space or 1), 2), "units": round(qty / DAYS, 1),
                      "margin": round(margin / DAYS, 2), "per_facing": round(margin / DAYS / max(facings, 1), 2)}
    return stats


def _sku_boxes() -> dict[str, list[int]]:
    """Πού φαίνεται κάθε κωδικός στην τελευταία ανάγνωση (ένωση των κουτιών του), για το βέλος στην οθόνη."""
    _, rows = run_sql("select sku, min(ymin), min(xmin), max(ymax), max(xmax) from shelf_observation "
                      "where sku is not null and ymin is not null group by 1")
    return {r[0]: [int(v) for v in r[1:]] for r in rows}


def _side(s: dict, boxes: dict) -> dict:
    return {"sku": s["sku"], "name": s["name"], "shelf": s["shelf"], "level": s["level"], "position": s["position"],
            "facings": s["facings"], "per_facing": s["per_facing"], "box": boxes.get(s["sku"])}


@tool(
    "propose_move",
    "Καταχώρισε ΜΙΑ απόφασή σου για αλλαγή θέσης στο ράφι, ώστε να φανεί στην οθόνη του υπεύθυνου. "
    "kind=swap: οι δύο κωδικοί ανταλλάσσουν θέση (ύψος ματιών ή κέντρο ραφιού). kind=facing: μία πρόσοψη φεύγει "
    "από τον sku_from και πάει στον sku_to. Ο κώδικας υπολογίζει τους αριθμούς και απορρίπτει ό,τι δεν στηρίζεται· "
    "αν απορριφθεί, διάλεξε άλλη αλλαγή ή καμία. Κάλεσε πρώτα το layout_suggestions.",
    {"kind": {"type": "string", "enum": ["swap", "facing"], "description": "swap = ανταλλαγή θέσης, facing = μεταφορά μίας πρόσοψης"},
     "sku_from": {"type": "string", "description": "Κωδικός, π.χ. C09. Στο facing: αυτός που χάνει την πρόσοψη."},
     "sku_to": {"type": "string", "description": "Ο άλλος κωδικός. Στο facing: αυτός που παίρνει την πρόσοψη."},
     "reason": {"type": "string", "description": "Το σκεπτικό σου σε μία πρόταση, για τον υπεύθυνο. Χωρίς ποσά και "
                                                 "ποσοστά: τους αριθμούς τους γράφει ο κώδικας."}},
)
async def propose_move(ctx, kind: str, sku_from: str, sku_to: str, reason: str) -> str:
    from .. import tasks
    stats, boxes = await asyncio.to_thread(lambda: (_layout_stats(), _sku_boxes()))
    sku_from, sku_to, reason = sku_from.strip().upper(), sku_to.strip().upper(), " ".join(reason.split())[:240]
    unknown = [s for s in (sku_from, sku_to) if s not in stats]
    if unknown or sku_from == sku_to:
        return f"Δεν καταχωρήθηκε: {'άγνωστος κωδικός ' + ', '.join(unknown) if unknown else 'χρειάζονται δύο διαφορετικοί κωδικοί'}."
    if "€" in reason or "%" in reason:
        return "Δεν καταχωρήθηκε: το σκεπτικό δεν περιέχει ποσά ή ποσοστά. Ξαναγράψ' το χωρίς αριθμούς."
    a, b = stats[sku_from], stats[sku_to]

    if kind == "swap":
        if a["level"] != b["level"] and "eye" in (a["level"], b["level"]):
            rule, spot = "K4", "στο ύψος των ματιών"
            inn, out = (a, b) if b["level"] == "eye" else (b, a)          # inn: αυτός που πάει στην καλή θέση
        elif a["shelf"] == b["shelf"] and (a["center"] or b["center"]):
            rule, spot = "K5", f"στο κέντρο του ραφιού {a['shelf']}"
            inn, out = (a, b) if b["center"] else (b, a)
        else:
            return ("Δεν καταχωρήθηκε: αυτή η ανταλλαγή δεν φέρνει κωδικό ούτε στο ύψος των ματιών (Κ4) ούτε στο "
                    "κέντρο ραφιού (Κ5), άρα καμία πηγή μας δεν τη στηρίζει. Διάλεξε άλλη αλλαγή ή καμία.")
        if inn["per_facing"] <= out["per_facing"]:
            return (f"Δεν καταχωρήθηκε: {spot} θα πήγαινε το {inn['sku']} με {inn['per_facing']} € περιθώριο ανά "
                    f"πρόσοψη την ημέρα, λιγότερο από τα {out['per_facing']} € του {out['sku']} που είναι ήδη εκεί.")
        diff = round(inn["per_facing"] - out["per_facing"], 2)
        ctx.audit("compute", label=f"{rule}: περιθώριο ανά πρόσοψη ανά ημέρα (€), {inn['sku']} έναντι {out['sku']}",
                  expression="margin / days / facings", result=diff,
                  variables={inn["sku"]: inn["per_facing"], out["sku"]: out["per_facing"], "days": DAYS})
        text = f"Άλλαξε θέση: {inn['name']} {spot}, {out['name']} στο ράφι {inn['shelf']}"
        numbers = (f"{inn['name']}: {inn['per_facing']} € περιθώριο ανά πρόσοψη την ημέρα (ράφι {inn['shelf']}, "
                   f"{LEVEL_EL.get(inn['level'], inn['level'])}) · {out['name']}: {out['per_facing']} € {spot}")
        note = "Δείχνει τη σημερινή απόδοση του χώρου· δεν προβλέπει αύξηση πωλήσεων."
    elif kind == "facing":
        rule = "K3"
        if a["facings"] <= 1:
            return f"Δεν καταχωρήθηκε: το {a['sku']} έχει μία μόνο πρόσοψη και δεν μπορεί να δώσει άλλη."
        gain = b["margin"] * (((b["facings"] + 1) / b["facings"]) ** ELASTICITY - 1)
        loss = a["margin"] * (1 - ((a["facings"] - 1) / a["facings"]) ** ELASTICITY)
        net = round(gain - loss, 2)
        ctx.audit("compute", label=f"K3: μία πρόσοψη από {a['sku']} σε {b['sku']}, καθαρό περιθώριο ανά ημέρα (€)",
                  expression="m_to * (((n_to + 1) / n_to) ^ 0.17 - 1) - m_from * (1 - ((n_from - 1) / n_from) ^ 0.17)",
                  variables={"m_to": b["margin"], "n_to": b["facings"], "m_from": a["margin"], "n_from": a["facings"]},
                  result=net)
        if net <= 0:
            return (f"Δεν καταχωρήθηκε: κέρδος {gain:.2f} € − απώλεια {loss:.2f} € = {net:.2f} € την ημέρα. "
                    "Η μεταφορά δεν συμφέρει· διάλεξε άλλη αλλαγή ή καμία.")
        text = f"Μία πρόσοψη από {a['name']} σε {b['name']}"
        numbers = f"κέρδος {gain:.2f} € − απώλεια {loss:.2f} € = +{net:.2f} € περιθώριο την ημέρα"
        note = "Εκτίμηση με τη μέση ελαστικότητα χώρου της βιβλιογραφίας, όχι μέτρηση σε αυτό το ράφι."
    else:
        return "Δεν καταχωρήθηκε: το kind είναι swap ή facing."

    source = f"{SOURCES[rule]}· πωλήσεις {DAYS} ημερών"
    await asyncio.to_thread(tasks.add_proposal, {
        "kind": kind, "rule": rule, "text": text, "numbers": numbers, "reason": reason, "source": source, "note": note,
        "a": _side(a, boxes), "b": _side(b, boxes)})
    return (f"Καταχωρήθηκε και φαίνεται στην οθόνη του υπεύθυνου: {text}.\nΑριθμός: {numbers}.\nΠηγή: {source}.\n{note} "
            "Την αλλαγή στο πλανόγραμμα την εγκρίνει ο category manager.")


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
