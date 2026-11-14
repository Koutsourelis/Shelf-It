"""Χτίζει τα δεδομένα του demo από τα CSV του data/shelf/.

    python scripts/make_demo_data.py             # ξαναχτίζει τη βάση (τρέξε το μετά από κάθε αλλαγή στα CSV)
    python scripts/make_demo_data.py --samples   # ξαναφτιάχνει και τις δύο δοκιμαστικές «φωτογραφίες» ραφιού

Οι δοκιμαστικές φωτογραφίες είναι σχέδια, όχι αληθινές λήψεις. Υπάρχουν για να τρέχει όλη η ροή με το
ψεύτικο μοντέλο, χωρίς κλειδί. Δίπλα σε καθεμία γράφεται ένα .reading.json: αυτό που «βλέπει» το ψεύτικο μοντέλο.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentkit import demo_data  # noqa: E402

W, H, UNIT, LEFT, SHELF_H = 1200, 900, 110, 70, 270
COLORS = ["#b5651d", "#3b6ea5", "#7a4a8c", "#2f7d5b", "#c0392b", "#d08a1d", "#5d4037", "#4f8a3c", "#34495e"]

# Κάθε ράφι: λίστα (κωδικός ή None για κενό, προσόψεις). Το «after» είναι ακριβώς το πλανόγραμμα.
# Το «before» έχει τρία λάθη: ο C02 έχει 1 από 3 προσόψεις, ο C04 λείπει, ο C08 είναι στο ράφι 1 αντί για το 3.
LAYOUTS = {
    "sample_before": [
        [("C01", 2), ("C02", 1), (None, 2), ("C03", 2), ("C08", 2)],
        [(None, 2), ("C05", 2), ("C06", 2)],
        [("C07", 2), (None, 2), ("C09", 3)],
    ],
    "sample_after": [
        [("C01", 2), ("C02", 3), ("C03", 2)],
        [("C04", 2), ("C05", 2), ("C06", 2)],
        [("C07", 2), ("C08", 2), ("C09", 3)],
    ],
}


def make_samples() -> int:
    from matplotlib import font_manager
    from PIL import Image, ImageDraw, ImageFont

    catalog = {p["sku"]: p for p in demo_data._rows("catalog.csv")}
    order = sorted(catalog)
    font = ImageFont.truetype(font_manager.findfont("DejaVu Sans"), 15)
    bold = ImageFont.truetype(font_manager.findfont("DejaVu Sans:bold"), 16)
    demo_data.PHOTOS_DIR.mkdir(parents=True, exist_ok=True)

    for name, shelves in LAYOUTS.items():
        im = Image.new("RGB", (W, H), "#e9e4dc")
        draw = ImageDraw.Draw(im)
        items, gaps = [], []
        for s, groups in enumerate(shelves, start=1):
            top, bottom = 60 + (s - 1) * SHELF_H, 60 + (s - 1) * SHELF_H + 210
            draw.rectangle([30, bottom, W - 30, bottom + 22], fill="#8d7b68")       # η σανίδα του ραφιού
            x, position = LEFT, 0
            for sku, facings in groups:
                x0, x1 = x, x + facings * UNIT
                box = [round(1000 * (top + 20) / H), round(1000 * x0 / W), round(1000 * bottom / H), round(1000 * x1 / W)]
                if sku is None:
                    gaps.append({"shelf": s, "box_2d": box})
                else:
                    position += 1
                    p = catalog[sku]
                    for f in range(facings):
                        fx = x0 + f * UNIT
                        draw.rounded_rectangle([fx + 6, top + 20, fx + UNIT - 6, bottom], radius=8,
                                               fill=COLORS[order.index(sku) % len(COLORS)], outline="#222")
                        draw.text((fx + 14, top + 34), p["brand"][:8], fill="white", font=bold)
                        for n, word in enumerate(p["name"].split()[:3]):
                            draw.text((fx + 14, top + 70 + n * 20), word[:10], fill="white", font=font)
                        draw.text((fx + 14, bottom - 30), sku, fill="white", font=font)
                    items.append({"sku": sku, "label": f"{p['brand']} {p['name']}", "shelf": s, "position": position,
                                  "facings": facings, "box_2d": box})
                x = x1 + 8
        draw.text((30, H - 30), "Δοκιμαστικό σχέδιο ραφιού, όχι αληθινή φωτογραφία", fill="#666", font=font)
        im.save(demo_data.PHOTOS_DIR / f"{name}.png")
        (demo_data.PHOTOS_DIR / f"{name}.reading.json").write_text(
            json.dumps({"items": items, "gaps": gaps}, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(LAYOUTS)


if __name__ == "__main__":
    print("Βάση:", demo_data.build())
    if "--samples" in sys.argv:
        print("Δοκιμαστικές φωτογραφίες:", make_samples())
    print("Έτοιμο ->", demo_data.SHELF_DIR)
