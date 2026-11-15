"""Composite a front-on Greek drinks shelf from product packshots.

Usage: python make_shelf.py <raw_dir> <out_dir>
Writes one JPEG per variant plus <name>.truth.json and <name>.reading.json,
and catalog.csv / planogram.csv for the set.
"""
import csv, json, math, random, sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance

RAW = Path(sys.argv[1]); OUT = Path(sys.argv[2]); OUT.mkdir(parents=True, exist_ok=True)
CUT = OUT / "_cutouts"; CUT.mkdir(exist_ok=True)
FONT = "C:/Windows/Fonts/arial.ttf"; FONTB = "C:/Windows/Fonts/arialbd.ttf"

# sku, file id, name, brand, height cm, price (sklavenitis.gr, 15 Nov 2026), category
PRODUCTS = [
    # shelf 1: beer bottles
    ("D01", "8010035_1", "Μπίρα Lager φιάλη 500ml", "Άλφα", 25.0, 1.71, "Μπίρα"),
    ("D02", "6124978_1", "Μπίρα Lager φιάλη 500ml", "Βεργίνα", 25.0, 1.52, "Μπίρα"),
    ("D03", "5461447_1", "Μπίρα Weiss φιάλη 500ml", "Βεργίνα", 25.0, 1.90, "Μπίρα"),
    ("D04", "5461462_1", "Μπίρα Red φιάλη 500ml", "Βεργίνα", 25.0, 1.95, "Μπίρα"),
    ("D05", "4026670_1", "Μπίρα Lager φιάλη 500ml", "Άμστελ", 25.0, 1.71, "Μπίρα"),
    ("D06", "4088878_1", "Μπίρα Pilsner φιάλη 500ml", "Kaiser", 25.5, 2.05, "Μπίρα"),
    ("D07", "1588360_1", "Μπίρα Μαύρη φιάλη 330ml", "Φιξ", 19.0, 1.71, "Μπίρα"),
    ("D08", "1584071_1", "Μπίρα Αφιλτράριστη φιάλη 330ml", "Μάμος", 19.0, 1.50, "Μπίρα"),
    # shelf 2: 500ml cans
    ("D11", "8010084_1", "Μπίρα Lager κουτί 500ml", "Άλφα", 16.8, 1.45, "Μπίρα"),
    ("D12", "7247307_1", "Μπίρα Lager κουτί 500ml", "Mythos", 16.8, 1.70, "Μπίρα"),
    ("D13", "6293229_1", "Μπίρα Lager κουτί 500ml", "Φιξ", 16.8, 1.48, "Μπίρα"),
    ("D14", "1828003_1_v1", "Μπίρα Lager κουτί 500ml", "Βεργίνα", 16.8, 1.58, "Μπίρα"),
    ("D15", "4026399_1", "Μπίρα Lager κουτί 500ml", "Άμστελ", 16.8, 1.52, "Μπίρα"),
    ("D16", "4025888_1", "Μπίρα Lager κουτί 500ml", "Heineken", 16.8, 1.77, "Μπίρα"),
    ("D17", "4089264_1", "Μπίρα Pilsner κουτί 500ml", "Kaiser", 16.8, 1.96, "Μπίρα"),
    # shelf 3: 330ml cans
    ("D21", "8010068_1", "Μπίρα Lager κουτί 330ml", "Άλφα", 11.5, 1.08, "Μπίρα"),
    ("D22", "5464516_1", "Μπίρα Lager κουτί 330ml", "Mythos", 11.5, 1.20, "Μπίρα"),
    ("D23", "6293302_1", "Μπίρα Lager κουτί 330ml", "Φιξ", 11.5, 1.08, "Μπίρα"),
    ("D24", "7311160_1", "Μπίρα Lager κουτί 330ml", "Βεργίνα", 11.5, 1.05, "Μπίρα"),
    ("D25", "4026381_1", "Μπίρα Lager κουτί 330ml", "Άμστελ", 11.5, 0.75, "Μπίρα"),
    ("D26", "4025854_1", "Μπίρα Lager κουτί 330ml", "Heineken", 11.5, 1.32, "Μπίρα"),
    ("D27", "4089231_1", "Μπίρα Pilsner κουτί 330ml", "Kaiser", 11.5, 1.42, "Μπίρα"),
    # shelf 4: alcohol-free beer and soft drink cans
    ("D31", "1400062_1", "Μπίρα χωρίς αλκοόλ κουτί 330ml", "Άλφα", 11.5, 0.88, "Μπίρα χωρίς αλκοόλ"),
    ("D32", "1253058_1", "Άνευ μπίρα χωρίς αλκοόλ κουτί 330ml", "Φιξ", 11.5, 0.90, "Μπίρα χωρίς αλκοόλ"),
    ("D33", "1289210_1", "Free μπίρα χωρίς αλκοόλ κουτί 330ml", "Άμστελ", 11.5, 0.88, "Μπίρα χωρίς αλκοόλ"),
    ("D34", "1646373_1", "0.0% μπίρα χωρίς αλκοόλ κουτί 330ml", "Mythos", 11.5, 1.00, "Μπίρα χωρίς αλκοόλ"),
    ("D35", "1480344_1", "Μπίρα χωρίς αλκοόλ κουτί 330ml", "Βεργίνα", 11.5, 0.87, "Μπίρα χωρίς αλκοόλ"),
    ("D36", "4102455_1", "Original Taste κουτί 330ml", "Coca-Cola", 11.5, 0.93, "Αναψυκτικά"),
    ("D37", "2992261_1", "Zero κουτί 330ml", "Coca-Cola", 11.5, 0.93, "Αναψυκτικά"),
    ("D38", "3265501_1", "Σόδα με λεμόνι κουτί 330ml", "Ήβη", 11.5, 0.72, "Αναψυκτικά"),
    # shelf 5: 1.5L bottles
    ("D41", "9413584_1_v2", "Πορτοκαλάδα με ανθρακικό 1,5lt", "Λουξ", 31.0, 1.95, "Αναψυκτικά"),
    ("D42", "9413618_1_v2", "Λεμονάδα 1,5lt", "Λουξ", 31.0, 1.95, "Αναψυκτικά"),
    ("D43", "9426701_1", "Cola 1,5lt", "Λουξ", 31.0, 1.95, "Αναψυκτικά"),
    ("D44", "8509549_1", "Λεμονάδα με ανθρακικό 1,5lt", "ΕΨΑ", 31.0, 1.60, "Αναψυκτικά"),
    ("D45", "4095204_1", "Πορτοκαλάδα με ανθρακικό 1,5lt", "Ήβη", 31.0, 1.58, "Αναψυκτικά"),
    ("D46", "1033987_1", "Πορτοκαλάδα χωρίς ανθρακικό 1,5lt", "Ήβη", 31.0, 1.98, "Αναψυκτικά"),
    ("D47", "2992360_1", "Zero 1,5lt", "Coca-Cola", 31.0, 1.97, "Αναψυκτικά"),
]
P = {p[0]: p for p in PRODUCTS}

# shelf -> (clear height cm, [(sku, facings), ...])
PLANOGRAM = {
    1: (29, [("D01", 3), ("D02", 3), ("D03", 2), ("D04", 2), ("D05", 3), ("D06", 2), ("D07", 3), ("D08", 3)]),
    2: (20, [("D11", 4), ("D12", 4), ("D13", 3), ("D14", 3), ("D15", 3), ("D16", 3), ("D17", 2)]),
    3: (15, [("D21", 4), ("D22", 4), ("D23", 3), ("D24", 3), ("D25", 3), ("D26", 3), ("D27", 2)]),
    4: (15, [("D31", 3), ("D32", 2), ("D33", 2), ("D34", 2), ("D35", 2), ("D36", 3), ("D37", 3), ("D38", 2)]),
    5: (35, [("D41", 2), ("D42", 2), ("D43", 2), ("D44", 2), ("D45", 2), ("D46", 2), ("D47", 2)]),
}
LEVEL = {1: "top", 2: "eye", 3: "eye", 4: "bottom", 5: "bottom"}
DEPTH = 4  # units behind each facing when full

W, H = 2400, 1800
PXCM = 12.4
GAP = 0.35  # cm between facings
UPR = 70     # upright width px
LIP = 46     # shelf front (price channel) height px


def cutout(fid):
    cache = CUT / f"{fid}.png"
    if cache.exists():
        return Image.open(cache)
    im = Image.open(RAW / f"{fid}.png").convert("RGB")
    a = np.asarray(im).astype(np.int16)
    near = (np.abs(255 - a).max(axis=2) < 14).astype(np.uint8) * 255
    m = Image.fromarray(near).convert("L").copy()
    w, h = m.size
    for seed in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1), (w // 2, 0), (w // 2, h - 1)]:
        if m.getpixel(seed) == 255:
            ImageDraw.floodfill(m, seed, 128)
    bg = (np.array(m) == 128)
    alpha = Image.fromarray(np.where(bg, 0, 255).astype(np.uint8), "L")
    alpha = alpha.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.2))
    rgba = im.copy(); rgba.putalpha(alpha)
    rgba = rgba.crop(alpha.point(lambda v: 255 if v > 40 else 0).getbbox())
    rgba.save(cache)
    return rgba


def product_img(sku, hpx):
    im = cutout(P[sku][1])
    w = max(1, round(im.width * hpx / im.height))
    return im.resize((w, hpx), Image.LANCZOS)


def shade(im, f):
    rgb = ImageEnhance.Brightness(im.convert("RGB")).enhance(f)
    rgb.putalpha(im.getchannel("A")); return rgb


def layout():
    """Return shelf geometry: list of (shelf, y_base, clear_px) top to bottom."""
    y = 60
    rows = []
    for s in range(1, 6):
        clear = round(PLANOGRAM[s][0] * PXCM)
        y += clear
        rows.append((s, y, clear))
        y += LIP + 8
    return rows, y


def background(rows, bottom):
    rng = np.random.default_rng(3)
    bg = Image.new("RGB", (W, H), (214, 216, 218))
    d = ImageDraw.Draw(bg)
    # back panel: vertical gradient + perforated slots
    arr = np.asarray(bg).astype(np.float32)
    grad = np.linspace(1.04, 0.86, H)[:, None, None]
    arr = np.clip(arr * grad, 0, 255)
    bg = Image.fromarray(arr.astype(np.uint8)); d = ImageDraw.Draw(bg)
    for x in range(UPR + 40, W - UPR, 300):
        for yy in range(30, H, 26):
            d.rectangle([x, yy, x + 3, yy + 12], fill=(150, 152, 155))
    # header
    d.rectangle([0, 0, W, 44], fill=(70, 74, 80))
    # floor
    d.rectangle([0, bottom, W, H], fill=(196, 170, 140))
    for x in range(-400, W + 400, 260):
        d.line([(x, H), (W / 2 + (x - W / 2) * 0.6, bottom)], fill=(176, 150, 122), width=3)
    d.line([(0, bottom + 40), (W, bottom + 40)], fill=(176, 150, 122), width=3)
    # shelf trays (seen slightly from above) under the products
    for s, yb, clear in rows:
        d.rectangle([UPR, yb - 18, W - UPR, yb + 2], fill=(176, 179, 183))
    # uprights
    for x0 in (0, W - UPR):
        d.rectangle([x0, 0, x0 + UPR, H], fill=(150, 154, 160))
        d.rectangle([x0 + 8, 0, x0 + 14, H], fill=(120, 124, 130))
        for yy in range(20, H, 34):
            d.rectangle([x0 + UPR // 2 - 4, yy, x0 + UPR // 2 + 4, yy + 14], fill=(95, 98, 104))
    return bg


def draw_lip(img, rows, labels):
    d = ImageDraw.Draw(img)
    f_price = ImageFont.truetype(FONTB, 22); f_name = ImageFont.truetype(FONT, 11)
    f_sku = ImageFont.truetype(FONT, 10)
    for s, yb, clear in rows:
        # soft shadow on products just above the lip comes from the shelf above (handled in post)
        d.rectangle([UPR - 6, yb, W - UPR + 6, yb + LIP], fill=(168, 172, 178))
        d.rectangle([UPR - 6, yb, W - UPR + 6, yb + 4], fill=(205, 208, 212))
        d.rectangle([UPR - 6, yb + LIP - 5, W - UPR + 6, yb + LIP], fill=(120, 124, 130))
        d.rectangle([UPR + 4, yb + 7, W - UPR - 4, yb + LIP - 8], fill=(236, 237, 236))
        for x, sku in labels.get(s, []):
            p = P[sku]
            lx = x; lw = 118
            d.rectangle([lx, yb + 8, lx + lw, yb + LIP - 9], fill=(255, 255, 255), outline=(200, 200, 200))
            d.rectangle([lx, yb + 8, lx + 5, yb + LIP - 9], fill=(230, 120, 30))
            nm = f"{p[3].upper()} {p[2].split()[-1]}"
            d.text((lx + 9, yb + 10), nm, font=f_name, fill=(40, 40, 40))
            d.text((lx + 9, yb + 23), f"€{p[5]:.2f}".replace(".", ","), font=f_price, fill=(15, 15, 15))
            d.text((lx + lw - 30, yb + 31), sku, font=f_sku, fill=(90, 90, 90))


def render(name, state, *, seed=0, angle=0.0, light=1.0, warm=0.0, extras=None, note=""):
    """state: shelf -> list of (sku_in_slot, planned_sku, facings_present, depth_present)."""
    rnd = random.Random(seed)
    rows, bottom = layout()
    img = background(rows, bottom)
    labels = {}
    truth_items, reading_items = [], []
    for s, yb, clear in rows:
        slots = state[s]
        widths = []
        for actual, planned, fac, dep in slots:
            plan_fac = dict(PLANOGRAM[s][1])[planned]
            unit_h = round(P[planned][4] * PXCM)
            uw = product_img(planned, unit_h).width + GAP * PXCM
            widths.append(plan_fac * uw)
        free = (W - 2 * UPR - 40) - sum(widths)
        gap = max(6, free / (len(slots) + 1))
        x = UPR + 20 + gap / 2
        for (actual, planned, fac, dep), sw in zip(slots, widths):
            labels.setdefault(s, []).append((round(x), planned))
            if fac and actual:
                unit_h = round(P[actual][4] * PXCM)
                pim = product_img(actual, unit_h)
                step = pim.width + GAP * PXCM
                # facings sit from the left of the slot; missing ones leave the right side empty
                for k in range(fac):
                    fx = x + k * step + rnd.uniform(-3, 3)
                    for r in range(DEPTH - 1, DEPTH - 1 - dep, -1):
                        sc = 1 - 0.035 * r
                        u = pim.resize((max(1, round(pim.width * sc)), max(1, round(pim.height * sc))), Image.LANCZOS)
                        u = shade(u, 0.88 ** r)
                        if abs(rot := rnd.uniform(-0.8, 0.8)) > 0.2 and r == DEPTH - dep:
                            u = u.rotate(rot, resample=Image.BICUBIC, expand=True)
                        ox = round(fx + (pim.width - u.width) / 2)
                        oy = round(yb - 4 - u.height - r * (13 if s > 1 else 4))
                        # contact shadow
                        sh = Image.new("L", (u.width + 20, 22), 0)
                        ImageDraw.Draw(sh).ellipse([4, 2, u.width + 16, 20], fill=120)
                        sh = sh.filter(ImageFilter.GaussianBlur(5))
                        img.paste((60, 60, 64), (ox - 10, oy + u.height - 12), sh)
                        img.paste(u, (ox, oy), u)
                bx0, bx1 = x, x + fac * step
                top = yb - unit_h - 6
                reading_items.append({
                    "sku": actual, "label": f"{P[actual][3]} {P[actual][2]}", "shelf": s,
                    "position": [p for _, p, _, _ in slots].index(planned) + 1, "facings": fac,
                    "box_2d": [round(top / H * 1000), round(bx0 / W * 1000), round(yb / H * 1000), round(bx1 / W * 1000)],
                })
                truth_items.append({"sku": actual, "shelf": s, "facings": fac})
            x += sw + gap
    draw_lip(img, rows, labels)
    # shadow under each lip onto the products of the shelf below (light from above)
    sh = Image.new("L", (W, H), 0); sd = ImageDraw.Draw(sh)
    for s, yb, clear in rows:
        sd.rectangle([UPR, yb + LIP, W - UPR, yb + LIP + 26], fill=70)
    sh = sh.filter(ImageFilter.GaussianBlur(14))
    img.paste((30, 30, 34), (0, 0), sh)
    for e in extras or []:
        e(img)
    img = post(img, rnd, angle=angle, light=light, warm=warm)
    img.save(OUT / f"{name}.jpg", quality=90)
    missing = sorted({pl for s in state for (a, pl, f, d) in state[s] if not f})
    truth = {"photo": f"data/shelf/sets/drinks/photos/{name}.jpg", "items": truth_items,
             "missing": missing, "shelf_ok": not missing and all(
                 a == pl and f == dict(PLANOGRAM[s][1])[pl] for s in state for a, pl, f, d in state[s]),
             "note": note}
    (OUT / f"{name}.truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / f"{name}.reading.json").write_text(json.dumps({"items": reading_items}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(name, "items", len(truth_items), "missing", missing)


def post(img, rnd, *, angle, light, warm):
    a = np.asarray(img).astype(np.float32)
    yy, xx = np.mgrid[0:H, 0:W]
    v = 1 - 0.28 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H * 0.4) / (H * 0.7)) ** 2)
    a *= np.clip(v, 0.55, 1)[..., None] * light
    a[..., 0] *= 1 + warm; a[..., 2] *= 1 - warm
    a += np.random.default_rng(rnd.randint(0, 99)).normal(0, 3.2, a.shape)
    img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    if angle:
        # simple keystone: camera a bit to one side / below
        d = angle * W
        coeffs = find_coeffs([(0, 0), (W, 0), (W, H), (0, H)],
                             [(d * 0.4, d * 0.5), (W, 0), (W, H), (d * 0.4, H - d * 0.5)])
        img = img.transform((W, H), Image.PERSPECTIVE, coeffs, Image.BICUBIC, fillcolor=(120, 120, 120))
    return img.filter(ImageFilter.GaussianBlur(0.7)).filter(ImageFilter.UnsharpMask(2, 40, 2))


def find_coeffs(dst, src):
    m = []
    for (x, y), (X, Y) in zip(dst, src):
        m.append([x, y, 1, 0, 0, 0, -X * x, -X * y]); m.append([0, 0, 0, x, y, 1, -Y * x, -Y * y])
    return np.linalg.solve(np.array(m, float), np.array(src, float).reshape(8)).tolist()


def full_state(depth=DEPTH):
    return {s: [[sku, sku, f, depth] for sku, f in PLANOGRAM[s][1]] for s in PLANOGRAM}


def autofill():
    usable = W - 2 * UPR - 40
    for sh, (clear, items) in PLANOGRAM.items():
        items = [list(i) for i in items]
        uw = {sku: product_img(sku, round(P[sku][4] * PXCM)).width + GAP * PXCM for sku, _ in items}
        k = 0
        while True:
            tot = sum(uw[a] * f for a, f in items) + 14 * (len(items) + 1)
            i = k % len(items)
            if tot + uw[items[i][0]] > usable:
                break
            items[i][1] += 1; k += 1
        PLANOGRAM[sh] = (clear, [tuple(i) for i in items])


def write_set():
    with open(OUT / "catalog.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["sku", "name", "brand", "category", "unit_cost", "unit_price", "daily_units", "case_size",
                    "price_source", "cost_source"])
        rng = random.Random(7)
        for sku, fid, name, brand, h, price, cat in PRODUCTS:
            cs = 6 if h >= 30 else 24
            w.writerow([sku, name, brand, cat, f"{price * 0.68:.2f}", f"{price:.2f}", rng.randint(6, 30), cs,
                        "sklavenitis.gr 15 Nov 2026", "φανταστικό κόστος (68% της τιμής)"])
    with open(OUT / "planogram.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(["shelf", "level", "position", "sku", "facings", "depth"])
        for s, (_, items) in PLANOGRAM.items():
            for i, (sku, fac) in enumerate(items, 1):
                w.writerow([s, LEVEL[s], i, sku, fac, DEPTH])


if __name__ == "__main__":
    autofill()
    write_set()
    rnd = random.Random(11)

    # 1. full, compliant
    render("drinks_full", full_state(), seed=1, note="Γεμάτο ράφι, σύμφωνο με το planogram.")

    # 2. half-full: every slot has fewer units in depth, some facings gone
    st = full_state()
    for s in st:
        for slot in st[s]:
            slot[3] = rnd.choice([1, 1, 2])
            if slot[2] > 2 and rnd.random() < 0.6:
                slot[2] -= 1
    render("drinks_half", st, seed=2, light=0.97, note="Μισογεμάτο: λίγο βάθος, μερικές προσόψεις λείπουν.")

    # 3. mostly empty (end of a hot Saturday)
    st = full_state()
    for s in st:
        for slot in st[s]:
            r = rnd.random()
            slot[2] = 0 if r < 0.35 else (1 if r < 0.8 else min(2, slot[2]))
            slot[3] = 1
    render("drinks_empty", st, seed=3, light=0.95, note="Σχεδόν άδειο: πολλά κενά, το πολύ 1–2 προσόψεις.")

    # 4. specific gaps: three SKUs out of stock, rest full
    st = full_state()
    for s, sku in [(2, "D12"), (3, "D22"), (5, "D43")]:
        for slot in st[s]:
            if slot[1] == sku:
                slot[2] = 0
    render("drinks_gaps", st, seed=4, note="Γεμάτο, εκτός από τρία κενά: D12, D22, D43.")

    # 5. misplaced: wrong product in two slots
    st = full_state()
    for s in st:
        for slot in st[s]:
            if slot[1] == "D25": slot[0] = "D26"; slot[3] = 2   # Heineken in Amstel's slot
            if slot[1] == "D44": slot[0] = "D42"                # Λουξ λεμονάδα in ΕΨΑ's slot
            if slot[1] == "D16": slot[2] = 1; slot[3] = 1
    render("drinks_misplaced", st, seed=5, note="Λάθος προϊόν σε δύο θέσεις (Heineken στη θέση Άμστελ 330, Λουξ λεμονάδα στη θέση ΕΨΑ), Heineken 500 με 1 πρόσοψη.")

    # 6. same as half but different light and a slight angle (phone held at the side)
    st = full_state()
    for s in st:
        for slot in st[s]:
            slot[3] = rnd.choice([1, 2, 3])
            if rnd.random() < 0.25: slot[2] = max(0, slot[2] - 2)
    render("drinks_angle", st, seed=6, angle=0.035, light=0.9, warm=0.05,
           note="Μισογεμάτο, θερμότερο φως, λήψη λίγο από τα αριστερά.")
