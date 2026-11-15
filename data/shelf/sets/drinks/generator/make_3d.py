"""3D pass: the same drinks shelves built as a gondola in perspective and shot by a phone.

Usage: python make_3d.py <raw_dir> <out_dir>
Shelves, back panel, uprights and floor are planes in centimetres, projected by a pinhole camera
at eye height. Products are front-facing cut-outs placed in rows on each shelf (rear rows sit
higher in the picture because the camera looks down on them), cans get a lid, everything gets
contact shadows and ambient occlusion. Then the handheld-phone pass of make_real.py.
"""
import json, math, random
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

import make_shelf as ms
from make_shelf import P, PLANOGRAM, DEPTH, OUT, FONT, FONTB
import make_real as mr

W, H = 2400, 1800            # output
SW, SH = 2760, 2070          # rendered scene (cropped/warped to the output)
BAY = 180.0                  # inner bay width cm
UP = 5.0                     # upright width cm
SD = 45.0                    # shelf depth cm
LIPH = 6.0                   # shelf front height cm
GAPCM = 0.4

CLEAR = {s: PLANOGRAM[s][0] for s in PLANOGRAM}
SY = {5: 12.0}
for s in (4, 3, 2, 1):
    SY[s] = SY[s + 1] + CLEAR[s + 1] + LIPH - 1
TOP = SY[1] + CLEAR[1] + 2
HEADER = (TOP + 3, TOP + 19)


class Cam:
    def __init__(self, x=0.0, eye=158.0, dist=250.0, f=2350.0):
        self.x, self.eye, self.D, self.f = BAY / 2 + x, eye, dist, f
        self.cx = SW / 2
        self.cy = 250 + f * (HEADER[1] - eye) / dist

    def p(self, X, Y, Z):
        d = self.D + Z
        return (self.cx + self.f * (X - self.x) / d, self.cy + self.f * (self.eye - Y) / d)

    def s(self, Z):
        return self.f / (self.D + Z)


def poly(d, cam, pts, fill):
    d.polygon([cam.p(*q) for q in pts], fill=fill)


def grad_quad(img, cam, x0, x1, y, z0, z1, c0, c1, steps=24):
    """Horizontal surface at height y from depth z0 to z1, colour c0 -> c1."""
    d = ImageDraw.Draw(img)
    for i in range(steps):
        za, zb = z0 + (z1 - z0) * i / steps, z0 + (z1 - z0) * (i + 1) / steps
        t = i / (steps - 1)
        c = tuple(int(c0[k] + (c1[k] - c0[k]) * t) for k in range(3))
        poly(d, cam, [(x0, y, za), (x1, y, za), (x1, y, zb), (x0, y, zb)], c)


def is_can(fid, hcm):
    return hcm <= 17 and ms.cutout(fid).width / ms.cutout(fid).height > 0.42


def lid(img, cam, x0, x1, ytop, z, dcm):
    """Elliptical can top seen from above."""
    _, yf = cam.p(0, ytop, z); _, yb = cam.p(0, ytop, z + dcm)
    if yf - yb < 2:
        return
    lx0 = cam.p(x0, ytop, z + dcm / 2)[0]; lx1 = cam.p(x1, ytop, z + dcm / 2)[0]
    w, h = max(2, round(lx1 - lx0)), max(2, round(yf - yb))
    L = Image.new("RGBA", (w, h), (0, 0, 0, 0)); ld = ImageDraw.Draw(L)
    ld.ellipse([0, 0, w - 1, h - 1], fill=(168, 170, 174, 255))
    ld.ellipse([w * 0.08, h * 0.12, w * 0.92, h * 0.88], fill=(198, 200, 204, 255))
    ld.ellipse([w * 0.16, h * 0.22, w * 0.84, h * 0.80], fill=(182, 184, 188, 255))
    ld.ellipse([w * 0.42, h * 0.30, w * 0.62, h * 0.55], fill=(150, 152, 156, 255))
    img.paste(L, (round(lx0), round(yb)), L)


def place_unit(img, cam, fid, hcm, X, Ys, z, shade, turn=1.0, rot=0.0):
    u0 = ms.cutout(fid)
    wcm = hcm * u0.width / u0.height
    sc = cam.s(z)
    hp = max(2, round(hcm * sc))
    u = mr.unit(fid, hp)
    if turn != 1.0:
        u = u.resize((max(1, round(u.width * turn)), u.height), Image.LANCZOS)
    if rot:
        u = u.rotate(rot, resample=Image.BICUBIC, expand=True)
    x0, y0 = cam.p(X, Ys + hcm, z)
    x1, yb = cam.p(X + wcm, Ys, z)
    # contact shadow on the shelf surface
    _, ysb = cam.p(X, Ys, z + wcm * 0.9)
    sw, sh = max(4, round(x1 - x0 + 16)), max(4, round(yb - ysb + 10))
    S = Image.new("L", (sw, sh), 0)
    ImageDraw.Draw(S).ellipse([4, 2, sw - 4, sh - 2], fill=150)
    img.paste((30, 30, 34), (round(x0 - 8), round(ysb - 2)), S.filter(ImageFilter.GaussianBlur(max(2, sh / 4))))
    if shade != 1:
        a = np.asarray(u).astype(np.float32); a[..., :3] *= shade
        u = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8), "RGBA")
    ox = round(x0 + ((x1 - x0) - u.width) / 2)
    img.paste(u, (ox, round(yb - u.height)), u)
    if is_can(fid, hcm):
        lid(img, cam, X + wcm * 0.04, X + wcm * 0.96, Ys + hcm - 0.15, z + wcm * 0.03, wcm * 0.94)
    return (x0, y0 - (cam.p(0, Ys + hcm, z)[1] - cam.p(0, Ys + hcm, z + wcm)[1]), x1, yb)


def label_strip(cam, s, labels, rnd):
    """Price channel on the shelf front, drawn flat (parallel to the image plane)."""
    sc = cam.s(-2)
    wpx = round((BAY + 2) * sc); hpx = round(LIPH * sc)
    L = Image.new("RGB", (wpx, hpx), (70, 72, 78))
    d = ImageDraw.Draw(L)
    for i in range(hpx):
        t = i / hpx
        c = int(120 - 50 * t)
        d.line([(0, i), (wpx, i)], fill=(c, c + 2, c + 6))
    d.rectangle([0, 0, wpx, max(1, round(hpx * 0.07))], fill=(200, 202, 206))
    ch0, ch1 = round(hpx * 0.14), round(hpx * 0.86)
    d.rectangle([2, ch0, wpx - 2, ch1], fill=(232, 233, 232))
    fp = ImageFont.truetype(FONTB, max(8, round(hpx * 0.36)))
    fn = ImageFont.truetype(FONT, max(6, round(hpx * 0.17)))
    for xcm, sku, promo in labels:
        p = P[sku]
        lw = round(9.5 * sc); lx = round((xcm + 1) * sc) + rnd.randint(-2, 2)
        tag = Image.new("RGB", (lw, ch1 - ch0 - 2), (255, 232, 60) if promo else (253, 253, 251))
        td = ImageDraw.Draw(tag)
        td.rectangle([0, 0, lw - 1, tag.height - 1], outline=(185, 185, 185))
        td.rectangle([0, 0, max(2, lw // 28), tag.height], fill=(215, 40, 40) if promo else (230, 120, 30))
        td.text((lw * 0.07, tag.height * 0.04), f"{p[3].upper()} {p[2].split()[-1]}", font=fn, fill=(40, 40, 40))
        td.text((lw * 0.07, tag.height * 0.32), f"€{p[5]:.2f}".replace(".", ","), font=fp, fill=(12, 12, 12))
        td.text((lw * 0.72, tag.height * 0.72), "ΠΡΟΣΦ." if promo else sku, font=fn, fill=(150, 20, 20) if promo else (100, 100, 100))
        L.paste(tag.rotate(rnd.uniform(-1.2, 1.2), resample=Image.BICUBIC, fillcolor=(232, 233, 232)), (lx, ch0 + 1))
    return L


def bay(img, cam, X0, slots_by_shelf, rnd, main):
    """Draw one bay whose inner left edge is at X0. Returns boxes for the main bay."""
    d = ImageDraw.Draw(img)
    boxes = []
    # back panel with pegboard holes and per-compartment ambient occlusion
    bz = SD + 3
    bx0, by0 = cam.p(X0, HEADER[0], bz); bx1, by1 = cam.p(X0 + BAY, 0, bz)
    panel = np.full((max(2, round(by1 - by0)), max(2, round(bx1 - bx0)), 3), (196, 199, 203), np.float32)
    ph, pw = panel.shape[:2]
    def py(Y): return cam.p(0, Y, bz)[1] - by0
    for s in (1, 2, 3, 4, 5):
        ya, yb_ = int(max(0, py(SY[s] + CLEAR[s] + (2 if s > 1 else 2)))), int(min(ph, py(SY[s])))
        if s == 1: ya = int(max(0, py(TOP)))
        if yb_ > ya:
            t = np.linspace(0, 1, yb_ - ya)[:, None, None]
            panel[ya:yb_] *= 0.58 + 0.34 * t ** 0.7
    xs = np.arange(pw)
    edge = np.clip(np.minimum(xs, pw - 1 - xs) / (pw * 0.06), 0, 1) * 0.25 + 0.75
    panel *= edge[None, :, None]
    P_ = Image.fromarray(panel.clip(0, 255).astype(np.uint8)); pd = ImageDraw.Draw(P_)
    step = cam.s(bz) * 2.5
    for gx in np.arange(step, pw, step * 1.6):
        for gy in np.arange(step, ph, step):
            pd.ellipse([gx - 1.4, gy - 1.4, gx + 1.4, gy + 1.4], fill=(120, 122, 126))
    img.paste(P_, (round(bx0), round(by0)))
    # inner faces of the uprights
    for ux, sign in ((X0, 1), (X0 + BAY, -1)):
        side = (138, 142, 148) if (cam.x - ux) * sign > 0 else (110, 114, 120)
        poly(d, cam, [(ux, 0, -3), (ux, TOP + 2, -3), (ux, TOP + 2, bz), (ux, 0, bz)], side)
    # shelves bottom -> top
    for s in (5, 4, 3, 2, 1):
        Ys = SY[s]
        grad_quad(img, cam, X0, X0 + BAY, Ys, 0, SD, (178, 181, 186), (120, 123, 128))
        if main:
            slots = slots_by_shelf[s]
            items = []
            for actual, planned, fac, dep in slots:
                fid, hcm = P[planned][1], P[planned][4]
                wcm = hcm * ms.cutout(fid).width / ms.cutout(fid).height
                items.append(dict(planned=planned, actual=actual, fac=fac, dep=dep,
                                  plan_fac=dict(PLANOGRAM[s][1])[planned], wcm=wcm))
        else:
            opts = mr.NEIGHBOUR[s]
            items = []
            for i in range(rnd.randint(6, 8)):
                fid, hcm = opts[i % len(opts)]
                f = rnd.randint(2, 4)
                items.append(dict(fid=fid, hcm=hcm, fac=f, dep=rnd.choice([2, 3, 4]), plan_fac=f,
                                  wcm=hcm * ms.cutout(fid).width / ms.cutout(fid).height))
        tot = sum(it["plan_fac"] * (it["wcm"] + GAPCM) for it in items)
        gap = max(0.5, (BAY - 3 - tot) / (len(items) + 1))
        x = X0 + 1.5 + gap / 2
        labels = []
        draws = []
        for it in items:
            if main:
                labels.append((x - X0, it["planned"], rnd.random() < 0.12))
                fid = P[it["actual"]][1] if it["actual"] else None
                hcm = P[it["actual"]][4] if it["actual"] else 0
            else:
                fid, hcm = it["fid"], it["hcm"]
            if it["fac"] and fid:
                wcm = hcm * ms.cutout(fid).width / ms.cutout(fid).height
                stepcm = wcm + GAPCM
                for k in range(it["fac"]):
                    fx = x + k * stepcm + rnd.uniform(-0.4, 0.4)
                    pulled = rnd.random() < 0.18
                    turn = rnd.uniform(0.86, 0.96) if rnd.random() < 0.22 else 1.0
                    for r in range(DEPTH - 1, DEPTH - 1 - it["dep"], -1):
                        front = r == DEPTH - it["dep"]
                        z = 1.5 + r * (wcm + 0.6) + (wcm * 0.5 if pulled and front else 0)
                        draws.append((z, fid, hcm, fx, 0.9 ** r * rnd.uniform(0.95, 1.04),
                                      turn if front else 1.0, rnd.uniform(-1.4, 1.4) if front else 0, it))
            it["x"] = x
            x += it["plan_fac"] * (it["wcm"] + GAPCM) + gap
        rects = {}
        for z, fid, hcm, fx, shade, turn, rot, it in sorted(draws, key=lambda t: -t[0]):
            r = place_unit(img, cam, fid, hcm, fx, Ys, z, shade, turn, rot)
            rects.setdefault(id(it), []).append(r)
        if main:
            for it in items:
                rs = rects.get(id(it))
                if rs:
                    boxes.append({"sku": it["actual"], "shelf": s, "planned": it["planned"], "facings": it["fac"],
                                  "box": (min(q[0] for q in rs) - 4, min(q[1] for q in rs) - 4,
                                          max(q[2] for q in rs) + 4, max(q[3] for q in rs) + 2)})
        # shelf front with price channel
        strip = label_strip(cam, s, labels if main else [], rnd)
        lx, ly = cam.p(X0 - 1, Ys + 1, -2)
        img.paste(strip, (round(lx), round(ly)))
        # soft shadow the shelf throws on the products right below it
        if s < 5 or True:
            pass
    # front faces of the uprights
    for ux in (X0 - UP, X0 + BAY):
        poly(d, cam, [(ux, 0, -3), (ux + UP, 0, -3), (ux + UP, TOP + 2, -3), (ux, TOP + 2, -3)], (150, 154, 160))
        x0_, y0_ = cam.p(ux, TOP + 2, -3); x1_, y1_ = cam.p(ux + UP, 0, -3)
        for yy in np.arange(y0_ + 8, y1_, cam.s(-3) * 2.5):
            d.rectangle([(x0_ + x1_) / 2 - 3, yy, (x0_ + x1_) / 2 + 3, yy + 9], fill=(92, 95, 100))
    return boxes


def scene(state, cam, rnd):
    img = Image.new("RGB", (SW, SH), (226, 227, 224))
    d = ImageDraw.Draw(img)
    hy = cam.p(0, cam.eye, 1e5)[1]
    # far wall / ceiling glow
    for y in range(0, SH):
        c = int(236 - 22 * min(1, y / max(1, hy)))
        d.line([(0, y), (SW, y)], fill=(c, c, c - 2))
    # floor plane from the camera to the gondola base
    fy0 = cam.p(0, 0, SD + 3)[1]
    for y in range(int(fy0), SH):
        t = (y - fy0) / max(1, SH - fy0)
        c = int(200 + 18 * t)
        d.line([(0, y), (SW, y)], fill=(c, c - 4, c - 12))
    for X in np.arange(-600, 800, 60):
        d.line([cam.p(X, 0, SD + 3), cam.p(X, 0, -240)], fill=(184, 179, 170), width=3)
    for Z in (-200, -140, -80, -20, 40):
        d.line([cam.p(-800, 0, Z), cam.p(1000, 0, Z)], fill=(184, 179, 170), width=3)
    boxes = []
    for X0, main in ((-(BAY + UP), False), (BAY + UP, False), (0.0, True)):
        b = bay(img, cam, X0, state, random.Random(rnd.random()) if not main else rnd, main)
        if main: boxes = b
    # gondola base (kick plate) across the run
    poly(d, cam, [(-400, 0, -1), (600, 0, -1), (600, SY[5] - LIPH, -1), (-400, SY[5] - LIPH, -1)], (64, 66, 72))
    # header band with category sign
    poly(d, cam, [(-400, HEADER[0], -3), (600, HEADER[0], -3), (600, HEADER[1], -3), (-400, HEADER[1], -3)], (40, 44, 50))
    hx0, hy0 = cam.p(BAY * 0.28, HEADER[1] - 1.5, -4); hx1, hy1 = cam.p(BAY * 0.72, HEADER[0] + 1.5, -4)
    d.rectangle([hx0, hy0, hx1, hy1], fill=(28, 96, 62))
    t = "ΜΠΥΡΕΣ · ΑΝΑΨΥΚΤΙΚΑ"
    size = max(10, round((hy1 - hy0) * 0.62))
    while True:
        fs = ImageFont.truetype(FONTB, size); tw = d.textlength(t, font=fs)
        if tw <= (hx1 - hx0) * 0.86 or size <= 10: break
        size -= 2
    d.text(((hx0 + hx1) / 2 - tw / 2, (hy0 + hy1) / 2 - size * 0.6), t, font=fs, fill=(250, 250, 245))
    return img, boxes


def light(img, rnd, gain, warm):
    a = np.asarray(img).astype(np.float32)
    yy, xx = np.mgrid[0:SH, 0:SW].astype(np.float32)
    lum = 0.84 + 0.20 * np.exp(-((yy - 0) / (SH * 0.9)) ** 2)
    for lx in (0.2, 0.6, 1.0):
        lum += 0.08 * np.exp(-(((xx - lx * SW) / 700) ** 2 + (yy / 1400) ** 2))
    lum += 0.04 * np.exp(-(((xx - rnd.uniform(0.3, 0.7) * SW) / 500) ** 2 + ((yy - rnd.uniform(0.3, 0.6) * SH) / 500) ** 2))
    a *= (lum * gain)[..., None]
    return np.clip(a * np.array([1 + warm - 0.012, 1.006, 1 - warm + 0.018], np.float32), 0, 255)


def maps(cam_post):
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    nx = (xx - W / 2) / (W / 2); ny = (yy - H / 2) / (W / 2)
    f = 1 + cam_post["barrel"] * (nx * nx + ny * ny)
    nx, ny = nx * f, ny * f
    th = math.radians(cam_post["roll"])
    rx = nx * math.cos(th) - ny * math.sin(th); ry = nx * math.sin(th) + ny * math.cos(th)
    den = 1 + cam_post["yaw"] * rx + cam_post["pitch"] * ry
    half = cam_post["span"] / 2
    return SW / 2 + cam_post["dx"] + rx * half / den, SH / 2 + cam_post["dy"] + ry * half / den


def post(arr, cp, rnd):
    sx, sy = maps(cp)
    cx, cy = SW / 2 + cp["dx"], SH / 2 + cp["dy"]
    out = np.empty((H, W, 3), np.float32)
    for ch, k in ((0, 1.0012), (1, 1.0), (2, 0.9988)):
        out[..., ch] = mr.remap(arr[..., ch], cx + (sx - cx) * k, cy + (sy - cy) * k)
    img = Image.fromarray(np.clip(out, 0, 255).astype(np.uint8))
    soft = img.filter(ImageFilter.GaussianBlur(2.2))
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    m = np.clip((((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2 - 0.6) / 0.9, 0, 1)
    img = Image.composite(soft, img, Image.fromarray((m * 255).astype(np.uint8)))
    a = np.asarray(img).astype(np.float32)
    if cp.get("shake"):
        k = cp["shake"]; a = sum(np.roll(a, (round(i * 0.3), i), axis=(0, 1)) for i in range(-k, k + 1)) / (2 * k + 1)
    a *= (1 - 0.11 * (((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2))[..., None]
    a = 255 * (a / 255) ** 0.96
    a = a + 0.10 * (a - a.mean(axis=2, keepdims=True))
    g = np.random.default_rng(rnd.randint(0, 10 ** 6))
    shadow = 1.6 - a.mean(axis=2, keepdims=True) / 255
    a += g.normal(0, 2.6, (H, W, 1)) * shadow
    chn = g.normal(0, 3.0, (H // 6, W // 6, 3)).astype(np.float32)
    chn = np.asarray(Image.fromarray(np.clip(chn * 10 + 128, 0, 255).astype(np.uint8)).resize((W, H), Image.BILINEAR)).astype(np.float32)
    a += (chn - 128) / 10 * shadow
    img = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
    return img.filter(ImageFilter.UnsharpMask(radius=1.6, percent=70, threshold=2))


def to_output(boxes, cp):
    sx, sy = maps(cp)
    st = 4
    gx, gy = sx[::st, ::st].ravel(), sy[::st, ::st].ravel()
    oy, ox = np.mgrid[0:H:st, 0:W:st]; ox, oy = ox.ravel(), oy.ravel()
    for b in boxes:
        x0, y0, x1, y1 = b["box"]
        px, py = [], []
        for X, Y in [(x0, y0), (x1, y0), (x0, y1), (x1, y1), ((x0 + x1) / 2, y0), ((x0 + x1) / 2, y1)]:
            i = np.argmin((gx - X) ** 2 + (gy - Y) ** 2); px.append(ox[i]); py.append(oy[i])
        b["out"] = (min(px), min(py), max(px), max(py))
    return boxes


POST = dict(span=2420, dx=0, dy=0, roll=0.0, yaw=0.0, pitch=0.0, barrel=0.012, shake=0)


def make(name, state, *, seed, cam, cp, gain=1.0, warm=0.0, note=""):
    rnd = random.Random(seed)
    img, boxes = scene(state, cam, rnd)
    img = img.filter(ImageFilter.GaussianBlur(0.7))
    out = post(light(img, rnd, gain, warm), cp, rnd)
    out.save(OUT / f"{name}.jpg", quality=82, subsampling=2)
    ob = to_output(boxes, cp)
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


if __name__ == "__main__":
    ms.autofill(); ms.write_set()
    rnd = random.Random(11)
    full = ms.full_state

    make("drinks_full", full(), seed=1, cam=Cam(x=12, eye=160), cp=dict(POST, roll=0.8, pitch=0.02),
         note="Γεμάτο ράφι, σύμφωνο με το planogram.")

    st = full()
    for s in st:
        for sl in st[s]:
            sl[3] = rnd.choice([1, 1, 2])
            if sl[2] > 2 and rnd.random() < 0.6: sl[2] -= 1
    make("drinks_half", st, seed=2, gain=0.97, cam=Cam(x=-25, eye=155), cp=dict(POST, roll=-1.2, pitch=0.03, shake=1),
         note="Μισογεμάτο: λίγο βάθος, μερικές προσόψεις λείπουν.")

    st = full()
    for s in st:
        for sl in st[s]:
            r = rnd.random()
            sl[2] = 0 if r < 0.35 else (1 if r < 0.8 else min(2, sl[2])); sl[3] = 1
    make("drinks_empty", st, seed=3, gain=0.94, cam=Cam(x=30, eye=162), cp=dict(POST, roll=0.6, pitch=-0.02),
         note="Σχεδόν άδειο: πολλά κενά, το πολύ 1–2 προσόψεις.")

    st = full()
    for s, sku in [(2, "D12"), (3, "D22"), (5, "D43")]:
        for sl in st[s]:
            if sl[1] == sku: sl[2] = 0
    make("drinks_gaps", st, seed=4, cam=Cam(x=0, eye=158), cp=dict(POST, roll=-0.7, pitch=0.03),
         note="Γεμάτο, εκτός από τρία κενά: D12, D22, D43.")

    st = full()
    for s in st:
        for sl in st[s]:
            if sl[1] == "D25": sl[0] = "D26"; sl[3] = 2
            if sl[1] == "D44": sl[0] = "D42"
            if sl[1] == "D16": sl[2] = 1; sl[3] = 1
    make("drinks_misplaced", st, seed=5, cam=Cam(x=-10, eye=164), cp=dict(POST, roll=1.0, pitch=0.02),
         note="Λάθος προϊόν σε δύο θέσεις (Heineken στη θέση Άμστελ 330, Λουξ λεμονάδα στη θέση ΕΨΑ), Heineken 500 με 1 πρόσοψη.")

    st = full()
    for s in st:
        for sl in st[s]:
            sl[3] = rnd.choice([1, 2, 3])
            if rnd.random() < 0.25: sl[2] = max(0, sl[2] - 2)
    make("drinks_angle", st, seed=6, gain=0.9, warm=0.045, cam=Cam(x=-30, eye=152),
         cp=dict(POST, roll=1.6, yaw=0.05, pitch=0.03, dx=150, shake=1),
         note="Μισογεμάτο, θερμότερο φως, λήψη από τα αριστερά.")
