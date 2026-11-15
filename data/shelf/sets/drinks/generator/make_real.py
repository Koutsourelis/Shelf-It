"""Photo-real pass: same shelves as make_shelf.py, shot as if by an employee's phone.

Usage: python make_real.py <raw_dir> <out_dir>
Adds neighbouring bays, ceiling and floor, uneven store lighting, product highlights and small
placement errors, then a handheld phone camera (tilt, roll, lens distortion, depth of field,
noise, sharpening, JPEG). Boxes in <name>.reading.json follow the camera warp.
"""
import json, math, random
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance

import make_shelf as ms
from make_shelf import P, PLANOGRAM, DEPTH, PXCM, GAP, UPR, LIP, W, H, OUT, FONT, FONTB

SW, SH = 3400, 2560          # scene canvas
BX, BY = (SW - W) // 2, 330   # main bay position in the scene

# products that are NOT in the catalogue, for the neighbouring bays (file id, height cm)
NEIGHBOUR = {
    1: [("2992311_1", 21), ("6976310_1", 27)],
    2: [("9413600_1", 18), ("9413634_1", 18), ("4694378_1", 18), ("1028329_1", 18), ("9426644_1", 18), ("9426628_1", 18)],
    3: [("1092976_1", 11.5), ("1140259_1", 8.8)],
    4: [("1092976_1", 11.5), ("1140259_1", 8.8)],
    5: [("1661805_1", 31), ("1028335_1_v1", 31)],
}


@lru_cache(maxsize=None)
def unit(fid, hpx):
    """Cut-out product at height hpx with a soft specular streak and cylinder falloff."""
    im = ms.cutout(fid)
    w = max(1, round(im.width * hpx / im.height))
    im = im.resize((w, hpx), Image.LANCZOS)
    a = np.asarray(im).astype(np.float32)
    x = np.linspace(-1, 1, w)[None, :, None]
    fall = 1 - 0.22 * np.abs(x) ** 3
    streak = 34 * np.exp(-((x + 0.42) / 0.09) ** 2) + 14 * np.exp(-((x - 0.55) / 0.05) ** 2)
    rgb = np.clip(a[..., :3] * fall + streak, 0, 255)
    out = np.concatenate([rgb, a[..., 3:]], axis=2).astype(np.uint8)
    return Image.fromarray(out, "RGBA")


def paste_unit(img, u, ox, oy, f):
    if f != 1:
        rgb = ImageEnhance.Brightness(u.convert("RGB")).enhance(f); rgb.putalpha(u.getchannel("A")); u = rgb
    sh = Image.new("L", (u.width + 24, 26), 0)
    ImageDraw.Draw(sh).ellipse([4, 3, u.width + 20, 23], fill=150)
    img.paste((40, 40, 44), (ox - 12, oy + u.height - 14), sh.filter(ImageFilter.GaussianBlur(5)))
    img.paste(u, (ox, oy), u)


def draw_lip(img, rows, labels, rnd):
    d = ImageDraw.Draw(img)
    f_price = ImageFont.truetype(FONTB, 22); f_name = ImageFont.truetype(FONT, 11); f_sku = ImageFont.truetype(FONT, 10)
    for s, yb, clear in rows:
        for i in range(LIP):
            t = i / LIP
            c = int(206 - 70 * t + 18 * math.sin(t * 6))
            d.line([(UPR - 6, yb + i), (W - UPR + 6, yb + i)], fill=(c, c + 2, c + 5))
        d.rectangle([UPR + 4, yb + 7, W - UPR - 4, yb + LIP - 8], fill=(226, 228, 228))
        for x, sku, promo in labels.get(s, []):
            p = P[sku]
            tag = Image.new("RGBA", (120, LIP - 11), (255, 236, 60, 255) if promo else (252, 252, 250, 255))
            td = ImageDraw.Draw(tag)
            td.rectangle([0, 0, 119, LIP - 12], outline=(190, 190, 190))
            td.rectangle([0, 0, 4, LIP - 12], fill=(220, 40, 40) if promo else (230, 120, 30))
            td.text((9, 2), f"{p[3].upper()} {p[2].split()[-1]}", font=f_name, fill=(40, 40, 40))
            td.text((9, 12), f"€{p[5]:.2f}".replace(".", ","), font=f_price, fill=(15, 15, 15))
            td.text((88, 2 if promo else 24), "ΠΡΟΣΦ." if promo else sku, font=f_sku, fill=(150, 20, 20) if promo else (90, 90, 90))
            tag = tag.rotate(rnd.uniform(-1.4, 1.4), resample=Image.BICUBIC, expand=True)
            img.paste(tag, (x + rnd.randint(-3, 3), yb + 4 + rnd.randint(-1, 2)), tag)


def render_bay(state, rnd, *, main=True):
    rows, bottom = ms.layout()
    img = ms.background(rows, bottom)
    # ambient occlusion inside each compartment: dark under the shelf above, lighter near the tray
    ao = np.ones((H, W), np.float32)
    prev = 44
    for s, yb, clear in rows:
        t = np.linspace(0, 1, yb - prev)
        ao[prev:yb, UPR:W - UPR] = (0.62 + 0.33 * t ** 0.6)[:, None]
        prev = yb + LIP
    ao[:, UPR:UPR + 40] *= np.linspace(0.8, 1, 40)[None, :]
    ao[:, W - UPR - 40:W - UPR] *= np.linspace(1, 0.8, 40)[None, :]
    img = Image.fromarray(np.clip(np.asarray(img).astype(np.float32) * ao[..., None] * np.array([0.93, 0.95, 0.98]), 0, 255).astype(np.uint8))
    labels, boxes = {}, []
    for s, yb, clear in rows:
        if main:
            slots = state[s]
        else:
            opts = NEIGHBOUR[s]
            slots = [(opts[i % len(opts)], rnd.randint(2, 4)) for i in range(rnd.randint(6, 8))]
        widths = []
        for sl in slots:
            if main:
                plan_fac = dict(PLANOGRAM[s][1])[sl[1]]
                widths.append(plan_fac * (unit(P[sl[1]][1], round(P[sl[1]][4] * PXCM)).width + GAP * PXCM))
            else:
                (fid, hcm), fac = sl
                widths.append(fac * (unit(fid, round(hcm * PXCM)).width + GAP * PXCM))
        free = (W - 2 * UPR - 40) - sum(widths)
        gap = max(4, free / (len(slots) + 1))
        x = UPR + 20 + gap / 2
        for sl, sw in zip(slots, widths):
            if main:
                actual, planned, fac, dep = sl
                labels.setdefault(s, []).append((round(x), planned, rnd.random() < 0.12))
                fid, hcm = (P[actual][1], P[actual][4]) if actual else (None, 0)
            else:
                (fid, hcm), fac = sl; dep = DEPTH
            if fac and fid:
                u0 = unit(fid, round(hcm * PXCM))
                step = u0.width + GAP * PXCM
                xs = []
                for k in range(fac):
                    fx = x + k * step + rnd.uniform(-5, 5)
                    pulled = rnd.random() < 0.18  # a unit taken and put back a bit off
                    for r in range(DEPTH - 1, DEPTH - 1 - dep, -1):
                        rr = r + (0.5 if (pulled and r == DEPTH - dep) else 0)
                        sc = 1 - 0.035 * rr
                        u = u0.resize((max(1, round(u0.width * sc)), max(1, round(u0.height * sc))), Image.LANCZOS)
                        if r == DEPTH - dep and rnd.random() < 0.25:
                            u = u.resize((max(1, round(u.width * rnd.uniform(0.86, 0.96))), u.height), Image.LANCZOS)
                        if r == DEPTH - dep:
                            u = u.rotate(rnd.uniform(-1.6, 1.6), resample=Image.BICUBIC, expand=True)
                        ox = round(fx + (u0.width - u.width) / 2)
                        oy = round(yb - 4 - u.height - rr * (13 if s > 1 else 4))
                        paste_unit(img, u, ox, oy, 0.88 ** rr * rnd.uniform(0.95, 1.04))
                    xs.append(fx)
                if main:
                    boxes.append({"sku": actual, "shelf": s, "planned": planned, "facings": fac,
                                  "box": (x - 4, yb - round(hcm * PXCM) - 10, x + fac * step + 4, yb)})
            x += sw + gap
    if main:
        draw_lip(img, rows, labels, rnd)
    else:
        draw_lip(img, rows, {}, rnd)
    sh = Image.new("L", (W, H), 0); sd = ImageDraw.Draw(sh)
    for s, yb, clear in rows:
        sd.rectangle([UPR, yb + LIP, W - UPR, yb + LIP + 30], fill=85)
    img.paste((25, 25, 30), (0, 0), sh.filter(ImageFilter.GaussianBlur(16)))
    return img, boxes, bottom


def build_scene(state, rnd):
    bay, boxes, bottom = render_bay(state, rnd)
    left, _, _ = render_bay(None, random.Random(rnd.random()), main=False)
    right, _, _ = render_bay(None, random.Random(rnd.random()), main=False)
    sc = Image.new("RGB", (SW, SH), (232, 233, 230))
    d = ImageDraw.Draw(sc)
    # ceiling and hanging category sign
    for y in range(BY):
        c = int(238 - 30 * (y / BY))
        d.line([(0, y), (SW, y)], fill=(c, c, c - 3))
    for lx in (SW * 0.22, SW * 0.62, SW * 1.02):
        d.rectangle([lx - 260, 18, lx + 260, 44], fill=(255, 255, 250))
    d.rectangle([BX + 700, 200, BX + W - 700, 310], fill=(28, 92, 60))
    d.line([(BX + 760, 0), (BX + 760, 200)], fill=(90, 90, 90), width=3)
    d.line([(BX + W - 760, 0), (BX + W - 760, 200)], fill=(90, 90, 90), width=3)
    fs = ImageFont.truetype(FONTB, 64)
    t = "ΜΠΥΡΕΣ · ΑΝΑΨΥΚΤΙΚΑ"
    tw = d.textlength(t, font=fs)
    d.text((BX + W / 2 - tw / 2, 218), t, font=fs, fill=(250, 250, 245))
    # bays
    sc.paste(left, (BX - W + UPR, BY)); sc.paste(right, (BX + W - UPR, BY)); sc.paste(bay, (BX, BY))
    # floor with soft reflection of the lower shelf
    fy = BY + bottom
    floor = Image.new("RGB", (SW, SH - fy), (205, 200, 192))
    fd = ImageDraw.Draw(floor)
    for i, x in enumerate(range(-2000, SW + 2000, 300)):
        fd.line([(x, SH - fy), (SW / 2 + (x - SW / 2) * 0.55, 0)], fill=(185, 180, 172), width=3)
    for y in (40, 110, 210, 350, 540):
        fd.line([(0, y), (SW, y)], fill=(185, 180, 172), width=3)
    refl = sc.crop((0, fy - (SH - fy), SW, fy)).transpose(Image.FLIP_TOP_BOTTOM).filter(ImageFilter.GaussianBlur(10))
    floor = Image.blend(floor, refl, 0.16)
    sc.paste(floor, (0, fy))
    boxes = [dict(b, box=(b["box"][0] + BX, b["box"][1] + BY, b["box"][2] + BX, b["box"][3] + BY)) for b in boxes]
    return sc, boxes


def light(sc, rnd, *, gain, warm):
    a = np.asarray(sc).astype(np.float32)
    yy, xx = np.mgrid[0:SH, 0:SW].astype(np.float32)
    lum = 0.86 + 0.0 * xx
    for lx in (SW * 0.22, SW * 0.62, SW * 1.02):
        lum += 0.16 * np.exp(-(((xx - lx) / 900) ** 2 + ((yy - 200) / 1500) ** 2))
    lum += 0.05 * np.exp(-(((xx - rnd.uniform(0.3, 0.7) * SW) / 500) ** 2 + ((yy - rnd.uniform(0.3, 0.6) * SH) / 500) ** 2))
    a *= (lum * gain)[..., None]
    tint = np.array([1 + warm - 0.012, 1.0 + 0.006, 1 - warm + 0.018], np.float32)
    return np.clip(a * tint, 0, 255)


def remap(src, xs, ys):
    h, w = src.shape[:2]
    x0 = np.clip(np.floor(xs).astype(np.int32), 0, w - 2); y0 = np.clip(np.floor(ys).astype(np.int32), 0, h - 2)
    fx = np.clip(xs - x0, 0, 1); fy = np.clip(ys - y0, 0, 1)
    a = src[y0, x0]; b = src[y0, x0 + 1]; c = src[y0 + 1, x0]; d = src[y0 + 1, x0 + 1]
    return (a * (1 - fx) * (1 - fy) + b * fx * (1 - fy) + c * (1 - fx) * fy + d * fx * fy)


def camera_maps(cam, scale=1.0):
    """Source (scene) coordinates for every output pixel."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    nx = (xx - W / 2) / (W / 2); ny = (yy - H / 2) / (W / 2)
    r2 = nx * nx + ny * ny
    f = (1 + cam["barrel"] * r2) * scale
    nx, ny = nx * f, ny * f
    th = math.radians(cam["roll"])
    rx = nx * math.cos(th) - ny * math.sin(th); ry = nx * math.sin(th) + ny * math.cos(th)
    den = 1 + cam["yaw"] * rx + cam["pitch"] * ry
    half = cam["span"] / 2
    sx = SW / 2 + cam["dx"] + rx * half / den
    sy = BY + H / 2 + cam["dy"] + ry * half / den
    return sx, sy


def shoot(sc_arr, cam, rnd):
    sx, sy = camera_maps(cam)
    out = np.empty((H, W, 3), np.float32)
    cx, cy = SW / 2 + cam["dx"], BY + H / 2 + cam["dy"]
    for ch, k in ((0, 1.0012), (1, 1.0), (2, 0.9988)):  # lateral chromatic aberration
        out[..., ch] = remap(sc_arr[..., ch], cx + (sx - cx) * k, cy + (sy - cy) * k)
    img = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
    # depth of field / lens softness towards the corners, slight hand shake
    soft = img.filter(ImageFilter.GaussianBlur(2.4))
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    m = np.clip((((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2 - 0.55) / 0.9, 0, 1)
    img = Image.composite(soft, img, Image.fromarray((m * 255).astype(np.uint8)))
    if cam.get("shake"):
        a = np.asarray(img).astype(np.float32)
        k = cam["shake"]
        a = sum(np.roll(a, (round(i * 0.3), i), axis=(0, 1)) for i in range(-k, k + 1)) / (2 * k + 1)
        img = Image.fromarray(a.astype(np.uint8))
    a = np.asarray(img).astype(np.float32)
    # vignette, tone curve
    v = 1 - 0.22 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2) / 2
    a *= v[..., None]
    a = 255 * (a / 255) ** 0.96
    a = a + 0.10 * (a - a.mean(axis=2, keepdims=True))  # phone saturation boost
    # sensor noise: luminance + low-frequency chroma, stronger in shadows
    g = np.random.default_rng(rnd.randint(0, 10 ** 6))
    shadow = 1.6 - a.mean(axis=2, keepdims=True) / 255
    a += g.normal(0, 2.6, (H, W, 1)) * shadow
    ch = g.normal(0, 3.0, (H // 6, W // 6, 3)).astype(np.float32)
    ch = np.asarray(Image.fromarray(np.clip(ch * 10 + 128, 0, 255).astype(np.uint8)).resize((W, H), Image.BILINEAR)).astype(np.float32)
    a += (ch - 128) / 10 * shadow
    img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    return img.filter(ImageFilter.UnsharpMask(radius=1.6, percent=70, threshold=2))


def boxes_to_output(boxes, cam):
    sx, sy = camera_maps(cam)
    st = 4
    gx, gy = sx[::st, ::st].ravel(), sy[::st, ::st].ravel()
    oy, ox = np.mgrid[0:H:st, 0:W:st]; ox, oy = ox.ravel(), oy.ravel()
    res = []
    for b in boxes:
        x0, y0, x1, y1 = b["box"]
        pts = [(x0, y0), (x1, y0), (x0, y1), (x1, y1), ((x0 + x1) / 2, y0), ((x0 + x1) / 2, y1)]
        px, py = [], []
        for X, Y in pts:
            i = np.argmin((gx - X) ** 2 + (gy - Y) ** 2)
            px.append(ox[i]); py.append(oy[i])
        res.append(dict(b, out=(min(px), min(py), max(px), max(py))))
    return res


def make(name, state, *, seed, cam, gain=1.0, warm=0.0, note=""):
    rnd = random.Random(seed)
    sc, boxes = build_scene(state, rnd)
    sc = sc.filter(ImageFilter.GaussianBlur(0.9))
    arr = light(sc, rnd, gain=gain, warm=warm)
    img = shoot(arr, cam, rnd)
    img.save(OUT / f"{name}.jpg", quality=80, subsampling=2)
    ob = boxes_to_output(boxes, cam)
    reading = {"items": [{
        "sku": b["sku"], "label": f"{P[b['sku']][3]} {P[b['sku']][2]}", "shelf": b["shelf"],
        "position": [sl[1] for sl in state[b["shelf"]]].index(b["planned"]) + 1, "facings": b["facings"],
        "box_2d": [round(b["out"][1] / H * 1000), round(b["out"][0] / W * 1000),
                   round(b["out"][3] / H * 1000), round(b["out"][2] / W * 1000)]} for b in ob]}
    missing = sorted({pl for s in state for (a, pl, f, d) in state[s] if not f})
    ok = not missing and all(a == pl and f == dict(PLANOGRAM[s][1])[pl] for s in state for a, pl, f, d in state[s])
    truth = {"photo": f"data/shelf/sets/drinks/photos/{name}.jpg",
             "items": [{"sku": b["sku"], "shelf": b["shelf"], "facings": b["facings"]} for b in ob],
             "missing": missing, "shelf_ok": ok, "note": note}
    (OUT / f"{name}.truth.json").write_text(json.dumps(truth, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / f"{name}.reading.json").write_text(json.dumps(reading, ensure_ascii=False, indent=2), encoding="utf-8")
    print(name, len(ob), "missing", missing)
    return ob


CAM = dict(span=2600, dx=0, dy=-80, roll=0.0, yaw=0.0, pitch=0.0, barrel=0.012, shake=0)

if __name__ == "__main__":
    ms.autofill(); ms.write_set()
    rnd = random.Random(11)
    full = ms.full_state

    make("drinks_full", full(), seed=1, cam=dict(CAM, roll=0.9, yaw=0.03, pitch=0.025),
         note="Γεμάτο ράφι, σύμφωνο με το planogram.")

    st = full()
    for s in st:
        for sl in st[s]:
            sl[3] = rnd.choice([1, 1, 2])
            if sl[2] > 2 and rnd.random() < 0.6: sl[2] -= 1
    make("drinks_half", st, seed=2, gain=0.97, cam=dict(CAM, roll=-1.3, yaw=-0.04, pitch=0.03, dx=40, shake=1),
         note="Μισογεμάτο: λίγο βάθος, μερικές προσόψεις λείπουν.")

    st = full()
    for s in st:
        for sl in st[s]:
            r = rnd.random()
            sl[2] = 0 if r < 0.35 else (1 if r < 0.8 else min(2, sl[2])); sl[3] = 1
    make("drinks_empty", st, seed=3, gain=0.94, cam=dict(CAM, roll=0.6, yaw=0.05, pitch=-0.02, dx=-30),
         note="Σχεδόν άδειο: πολλά κενά, το πολύ 1–2 προσόψεις.")

    st = full()
    for s, sku in [(2, "D12"), (3, "D22"), (5, "D43")]:
        for sl in st[s]:
            if sl[1] == sku: sl[2] = 0
    make("drinks_gaps", st, seed=4, cam=dict(CAM, roll=-0.7, yaw=0.02, pitch=0.04),
         note="Γεμάτο, εκτός από τρία κενά: D12, D22, D43.")

    st = full()
    for s in st:
        for sl in st[s]:
            if sl[1] == "D25": sl[0] = "D26"; sl[3] = 2
            if sl[1] == "D44": sl[0] = "D42"
            if sl[1] == "D16": sl[2] = 1; sl[3] = 1
    make("drinks_misplaced", st, seed=5, cam=dict(CAM, roll=1.1, yaw=-0.025, pitch=0.02, dy=10),
         note="Λάθος προϊόν σε δύο θέσεις (Heineken στη θέση Άμστελ 330, Λουξ λεμονάδα στη θέση ΕΨΑ), Heineken 500 με 1 πρόσοψη.")

    st = full()
    for s in st:
        for sl in st[s]:
            sl[3] = rnd.choice([1, 2, 3])
            if rnd.random() < 0.25: sl[2] = max(0, sl[2] - 2)
    make("drinks_angle", st, seed=6, gain=0.9, warm=0.045,
         cam=dict(CAM, roll=1.8, yaw=0.13, pitch=0.03, dx=60, span=2700, shake=1),
         note="Μισογεμάτο, θερμότερο φως, λήψη από τα αριστερά.")
