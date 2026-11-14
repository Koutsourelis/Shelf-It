"""Μέτρηση του μοντέλου όρασης. Κάτοχος: Άτομο Α.

    python scripts/eval_vision.py                 # όλες οι φωτογραφίες του data/shelf/eval/
    python scripts/eval_vision.py --runs 3        # 3 κλήσεις ανά φωτογραφία: δείχνει και τη σταθερότητα
    python scripts/eval_vision.py --only shelf_01

Για κάθε φωτογραφία χρειάζεται ένα <όνομα>.truth.json δίπλα της (ή με πεδίο "photo" που δείχνει αλλού):

    {"photo": "data/shelf/photos/sample_before.png",          (προαιρετικό)
     "items": [{"sku": "C01", "shelf": 1, "facings": 2}, ...], (η αλήθεια: τι υπάρχει, σε ποιο ράφι, πόσες προσόψεις)
     "occluded": false}

Μετρά ανά (κωδικός, ράφι):
- sku_shelf: βρήκε το σωστό προϊόν στο σωστό ράφι (αυτό καθορίζει «λείπει» και «λάθος ράφι»)
- facings:   και με σωστό αριθμό προσόψεων (αυτό καθορίζει «λίγες προσόψεις» και την αναπλήρωση)
- false_pos: (κωδικός, ράφι) που είπε το μοντέλο ενώ δεν υπάρχουν
Στόχος από το BUILD_PLAN: sku_shelf ≥ 90%. Τα αποτελέσματα γράφονται στο workspace/eval/ για σύγκριση prompts.
"""
import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from agentkit import config                       # noqa: E402
from agentkit.vision import read_photo            # noqa: E402
from agentkit.vision.prompts import PROMPT_VERSION  # noqa: E402

EVAL_DIR = config.SHELF_DIR / "eval"          # ακολουθεί το SHELF_SET
PHOTO_TYPES = (".jpg", ".jpeg", ".png", ".webp")


def _cases(only: str | None) -> list[tuple[str, Path, dict]]:
    cases = []
    for truth_file in sorted(EVAL_DIR.glob("*.truth.json")):
        name = truth_file.name[: -len(".truth.json")]
        if only and only not in name:
            continue
        truth = json.loads(truth_file.read_text(encoding="utf-8"))
        if truth.get("photo"):
            photo = config.ROOT / truth["photo"]
        else:
            photo = next((EVAL_DIR / (name + ext) for ext in PHOTO_TYPES if (EVAL_DIR / (name + ext)).exists()), None)
        if not photo or not photo.exists():
            print(f"  [παράλειψη] {name}: δεν βρέθηκε φωτογραφία")
            continue
        cases.append((name, photo, truth))
    return cases


def _by_slot(items) -> dict[tuple, int]:
    out: dict[tuple, int] = defaultdict(int)
    for it in items:
        if it.get("sku"):
            out[(it["sku"], int(it["shelf"]))] += int(it.get("facings") or 0)
    return out


def score(truth: dict, reading: dict) -> dict:
    want, got = _by_slot(truth["items"]), _by_slot(reading["items"])
    hit = [k for k in want if k in got]
    return {"slots": len(want), "sku_shelf": len(hit), "facings": sum(1 for k in hit if got[k] == want[k]),
            "false_pos": sum(1 for k in got if k not in want),
            "occluded_ok": bool(reading.get("occluded")) == bool(truth.get("occluded")),
            "wrong": sorted([f"λείπει {k[0]}@{k[1]}" for k in want if k not in got]
                            + [f"{k[0]}@{k[1]}: {got[k]} αντί {want[k]}" for k in hit if got[k] != want[k]]
                            + [f"επιπλέον {k[0]}@{k[1]}" for k in got if k not in want])}


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--only")
    args = ap.parse_args()

    from agentkit import demo_data
    if not config.DB_PATH.exists():
        demo_data.build()
    cases = _cases(args.only)
    if not cases:
        sys.exit(f"Δεν βρέθηκαν περιπτώσεις στο {EVAL_DIR}. Δες το README εκεί.")

    provider, model = config.vision_provider(), config.vision_model()
    print(f"\nEval όρασης · {provider}/{model} · prompt {PROMPT_VERSION} · "
          f"αναφορά: {config.VISION_REFERENCE or 'καμία'} · {len(cases)} φωτογραφίες × {args.runs}\n")

    from agentkit.vision import reader
    rows, total = [], defaultdict(int)
    for name, photo, truth in cases:
        for run in range(args.runs):
            reader._cache.clear()                      # κάθε run = πραγματική νέα κλήση
            t0 = time.time()
            try:
                reading = await read_photo(photo)
            except Exception as e:
                print(f"  {name} #{run + 1}: ΑΠΟΤΥΧΙΑ {type(e).__name__}: {e}")
                total["errors"] += 1
                continue
            s = score(truth, reading)
            s["seconds"] = round(time.time() - t0, 1)
            for k in ("slots", "sku_shelf", "facings", "false_pos"):
                total[k] += s[k]
            total["latency"] += s["seconds"]
            total["n"] += 1
            rows.append({"case": name, "run": run + 1, **s})
            print(f"  {name} #{run + 1}: θέσεις {s['sku_shelf']}/{s['slots']} · προσόψεις {s['facings']}/{s['slots']}"
                  f" · επιπλέον {s['false_pos']} · {s['seconds']} s" + (f"\n      {'; '.join(s['wrong'])}" if s["wrong"] else ""))

    if total["n"]:
        pct = lambda k: round(100 * total[k] / max(total["slots"], 1), 1)
        summary = {"provider": provider, "model": model, "prompt": PROMPT_VERSION,
                   "reference": config.VISION_REFERENCE, "sku_shelf_pct": pct("sku_shelf"), "facings_pct": pct("facings"),
                   "false_pos": total["false_pos"], "errors": total["errors"],
                   "avg_seconds": round(total["latency"] / total["n"], 1), "rows": rows}
        print(f"\nΣύνολο: σωστό προϊόν/ράφι {summary['sku_shelf_pct']}% · σωστές προσόψεις {summary['facings_pct']}% · "
              f"επιπλέον {summary['false_pos']} · σφάλματα {summary['errors']} · μέσος χρόνος {summary['avg_seconds']} s")
        out = config.WORKSPACE / "eval"
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"eval_{time.strftime('%Y%m%d_%H%M%S')}_{model.replace('/', '_')}_{PROMPT_VERSION}.json"
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Αποθηκεύτηκε: {path.relative_to(config.ROOT)}\n")


if __name__ == "__main__":
    asyncio.run(main())
