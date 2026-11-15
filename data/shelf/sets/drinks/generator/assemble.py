"""Assemble the three rendered sets into data/shelf/sets/drinks of the team repo.

Usage: python assemble.py <shelfgen_dir> <set_dir>
"""
import csv, json, shutil, sys
from pathlib import Path

SRC, DST = Path(sys.argv[1]), Path(sys.argv[2])
SETS = [("out_3d", "drinks_"), ("out_real", "drinks_real_"), ("out", "drinks_flat_")]
VARIANTS = ["full", "half", "empty", "gaps", "misplaced", "angle"]
LEVEL = {1: "top", 2: "eye", 3: "eye", 4: "bottom", 5: "bottom"}

(DST / "photos").mkdir(parents=True, exist_ok=True); (DST / "eval").mkdir(exist_ok=True)
for f in ("catalog.csv", "planogram.csv"):
    texts = {(SRC / d / f).read_text(encoding="utf-8") for d, _ in SETS}
    assert len(texts) == 1, f"{f} differs between renders"
    (DST / f).write_text(texts.pop(), encoding="utf-8")

cat = {r["sku"]: r for r in csv.DictReader(open(DST / "catalog.csv", encoding="utf-8"))}
plan = list(csv.DictReader(open(DST / "planogram.csv", encoding="utf-8")))
target = {r["sku"]: int(r["facings"]) for r in plan}
shelf_of = {r["sku"]: int(r["shelf"]) for r in plan}

with open(DST / "backroom.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["sku", "on_hand"])
    for sku in cat:
        # D12 (Mythos 500) and D43 (Λουξ cola) empty in the backroom, so the gaps photo triggers an order
        w.writerow([sku, 0 if sku in ("D12", "D43") else (48 if shelf_of[sku] < 5 else 18)])


def name_of(sku):
    return f"{cat[sku]['brand']} {cat[sku]['name']}"


def assessment(truth, reading):
    present = {}
    for it in reading["items"]:
        present.setdefault(it["sku"], 0); present[it["sku"]] += it["facings"]
    shelves = []
    for s in range(1, 6):
        items = []
        for it in reading["items"]:
            if it["shelf"] != s:
                continue
            planned = [r["sku"] for r in plan if int(r["shelf"]) == s][it["position"] - 1]
            items.append({"label": it["label"], "sku": it["sku"], "facings": it["facings"],
                          "target_facings": target[planned], "placement_ok": it["sku"] == planned,
                          "box_2d": it["box_2d"]})
        shelves.append({"level": LEVEL[s], "items": items})
    missing = [{"sku": sku, "product": name_of(sku), "target_facings": target[sku],
                "why": "Κωδικός του planogram που δεν φαίνεται στο ράφι."} for sku in truth["missing"]]
    wrong = [i for sh in shelves for i in sh["items"] if not i["placement_ok"]]
    short = [i for sh in shelves for i in sh["items"] if i["placement_ok"] and i["facings"] < i["target_facings"]]
    visual = [{"level": LEVEL[shelf_of[i["sku"]]], "type": "other",
               "detail": f"{i['label']}: προϊόν σε θέση άλλου κωδικού."} for i in wrong]
    ok = not (missing or wrong or short)
    parts = []
    if missing: parts.append(f"λείπουν {len(missing)} κωδικοί")
    if short: parts.append(f"{len(short)} κωδικοί με λιγότερες προσόψεις")
    if wrong: parts.append(f"{len(wrong)} θέσεις με λάθος προϊόν")
    summary = ("Ράφι ποτών σύμφωνο με το planogram." if ok else
               "Ράφι ποτών: " + ", ".join(parts) + ". Χρειάζεται αναπλήρωση από την αποθήκη και διόρθωση θέσεων.")
    layout = [{"level": LEVEL[s], "order": [r["sku"] for r in plan if int(r["shelf"]) == s],
               "why": "Όπως το planogram του σετ."} for s in range(1, 6)]
    return {"shelf_ok": ok, "occluded": False, "shelves": shelves, "missing": missing, "misplaced": [],
            "foreign": [], "visual_issues": visual, "suggested_layout": layout, "summary": summary}


def put(src_dir, src_name, dst_name):
    shutil.copyfile(SRC / src_dir / f"{src_name}.jpg", DST / "photos" / f"{dst_name}.jpg")
    reading = json.loads((SRC / src_dir / f"{src_name}.reading.json").read_text(encoding="utf-8"))
    truth = json.loads((SRC / src_dir / f"{src_name}.truth.json").read_text(encoding="utf-8"))
    on_shelf = {it["sku"] for it in truth["items"]}
    truth["missing"] = sorted(sku for sku in target if sku not in on_shelf)
    truth["photo"] = f"data/shelf/sets/drinks/photos/{dst_name}.jpg"
    merged = {}
    for it in truth["items"]:  # same product in two places on one shelf counts once, facings added
        k = (it["sku"], it["shelf"])
        merged[k] = dict(it, facings=merged[k]["facings"] + it["facings"]) if k in merged else dict(it)
    truth["items"] = list(merged.values())
    (DST / "photos" / f"{dst_name}.reading.json").write_text(json.dumps(reading, ensure_ascii=False, indent=2), encoding="utf-8")
    (DST / "photos" / f"{dst_name}.assessment.json").write_text(
        json.dumps(assessment(truth, reading), ensure_ascii=False, indent=2), encoding="utf-8")
    return truth


for d, prefix in SETS:
    for v in VARIANTS:
        t = put(d, f"drinks_{v}", prefix + v)
        (DST / "eval" / f"{prefix}{v}.truth.json").write_text(json.dumps(t, ensure_ascii=False, indent=2), encoding="utf-8")
        print(prefix + v, "missing", t["missing"])
# mock before/after pair for /shelf?dev=1 and check_setup
put("out_3d", "drinks_gaps", "sample_before")
put("out_3d", "drinks_full", "sample_after")

gen = DST / "generator"; gen.mkdir(exist_ok=True)
for f in ("scrape.py", "dl.py", "make_shelf.py", "make_real.py", "make_3d.py", "assemble.py"):
    shutil.copyfile(SRC / f, gen / f)
