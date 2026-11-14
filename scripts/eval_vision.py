"""Μέτρηση του μοντέλου όρασης στην αξιολόγηση ραφιού. Κάτοχος: Άτομο Α.

    python scripts/eval_vision.py                 # όλες οι φωτογραφίες του data/shelf/eval/
    python scripts/eval_vision.py --runs 3        # 3 κλήσεις ανά φωτογραφία: δείχνει και τη σταθερότητα
    python scripts/eval_vision.py --only newim    # μόνο όσες περιέχουν «newim»

Για κάθε φωτογραφία χρειάζεται ένα <όνομα>.truth.json δίπλα της (ή με πεδίο "photo" που δείχνει αλλού):

    {"photo": "data/shelf/photos/newim1.jpeg",
     "items": [{"sku": "C01", "facings": 2}, ...],   # τι φαίνεται πραγματικά
     "missing": ["C04"],                              # τι λείπει πραγματικά
     "shelf_ok": true,                                # είναι το ράφι όπως πρέπει;
     "note": "πώς μετρήθηκε"}

Δεν βαθμολογούμε θέσεις. Το μοντέλο δεν καλείται να βάλει προϊόντα σε «σωστή θέση»· βαθμολογούμε αυτό που
πρέπει να καταλάβει: ποιο προϊόν είναι, πόσες προσόψεις, τι λείπει, αν το ράφι είναι σωστό.

- sku:      βρήκε τα προϊόντα που υπάρχουν (ανά κωδικό, όχι ανά θέση)
- facings:  και με σωστό αριθμό προσόψεων
- false+:   προϊόντα που δήλωσε ενώ δεν υπάρχουν
- missing:  βρήκε σωστά τι λείπει
- ok:       συμφωνεί με το «είναι σωστό το ράφι;»

Στόχος από το BUILD_PLAN: sku ≥ 90%. Τα αποτελέσματα γράφονται στο workspace/eval/ για σύγκριση prompts.
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
from agentkit.vision import assess_photo          # noqa: E402
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
            base = config.ROOT / truth["photo"]
            photo = next((c for c in ([base] + [base.with_suffix(ext) for ext in PHOTO_TYPES]) if c.exists()), None)
        else:
            photo = next((EVAL_DIR / (name + ext) for ext in PHOTO_TYPES if (EVAL_DIR / (name + ext)).exists()), None)
        if not photo or not photo.exists():
            print(f"  [παράλειψη] {name}: δεν βρέθηκε φωτογραφία")
            continue
        cases.append((name, photo, truth))
    return cases


def _seen(verdict: dict) -> dict[str, int]:
    """Κωδικός → προσόψεις, αθροισμένα σε όλα τα επίπεδα. Χωρίς θέσεις."""
    out: dict[str, int] = defaultdict(int)
    for sh in verdict["shelves"]:
        for it in sh["items"]:
            if it.get("sku"):
                out[it["sku"]] += int(it.get("facings") or 0)
    return dict(out)


def score(truth: dict, verdict: dict) -> dict:
    want = {i["sku"]: int(i["facings"]) for i in truth["items"]}
    got = _seen(verdict)
    hit = [k for k in want if k in got]
    want_missing = {s for s in truth.get("missing") or []}
    got_missing = {m["sku"] for m in verdict["missing"] if m.get("sku")}
    return {"slots": len(want), "sku": len(hit), "facings": sum(1 for k in hit if got[k] == want[k]),
            "false_pos": sum(1 for k in got if k not in want),
            "missing_hit": len(want_missing & got_missing), "missing_total": len(want_missing),
            "missing_false": sorted(got_missing - want_missing),
            "ok": None if truth.get("shelf_ok") is None else bool(verdict["shelf_ok"]) == bool(truth["shelf_ok"]),
            "wrong": sorted([f"λείπει {k}" for k in want if k not in got]
                            + [f"{k}: {got[k]} αντί {want[k]}" for k in hit if got[k] != want[k]]
                            + [f"δεν υπάρχει {k}" for k in got if k not in want])
                     + [f"δεν βρήκε ότι λείπει {s}" for s in sorted(want_missing - got_missing)]}


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

    from agentkit.vision import assessment as assess_mod
    rows, total = [], defaultdict(int)
    for name, photo, truth in cases:
        for run in range(args.runs):
            assess_mod._cache.clear()                  # κάθε run = πραγματική νέα κλήση
            t0 = time.time()
            try:
                verdict = await assess_photo(photo)
            except Exception as e:
                print(f"  {name} #{run + 1}: ΑΠΟΤΥΧΙΑ {type(e).__name__}: {e}")
                total["errors"] += 1
                continue
            s = score(truth, verdict)
            s["seconds"] = round(time.time() - t0, 1)
            for k in ("slots", "sku", "facings", "false_pos", "missing_hit", "missing_total"):
                total[k] += s[k]
            total["ok_hits"] += 1 if s["ok"] else 0
            total["ok_total"] += 0 if s["ok"] is None else 1
            total["latency"] += s["seconds"]
            total["n"] += 1
            rows.append({"case": name, "run": run + 1, **s})
            extra = f" · λείπει {s['missing_hit']}/{s['missing_total']}" if s["missing_total"] else ""
            print(f"  {name} #{run + 1}: κωδικοί {s['sku']}/{s['slots']} · προσόψεις {s['facings']}/{s['slots']}"
                  f" · επιπλέον {s['false_pos']}{extra} · σωστό ράφι: "
                  f"{'—' if s['ok'] is None else ('ναι' if s['ok'] else 'ΟΧΙ')} · {s['seconds']} s"
                  + (f"\n      {'; '.join(s['wrong'])}" if s["wrong"] else ""))

    if total["n"]:
        pct = lambda k: round(100 * total[k] / max(total["slots"], 1), 1)
        summary = {"provider": provider, "model": model, "prompt": PROMPT_VERSION,
                   "reference": config.VISION_REFERENCE, "shelf_set": config.SHELF_SET or "shelf",
                   "sku_pct": pct("sku"), "facings_pct": pct("facings"), "false_pos": total["false_pos"],
                   "missing_hit": f"{total['missing_hit']}/{total['missing_total']}",
                   "shelf_ok_pct": round(100 * total["ok_hits"] / total["ok_total"], 1) if total["ok_total"] else None,
                   "errors": total["errors"], "avg_seconds": round(total["latency"] / total["n"], 1), "rows": rows}
        print(f"\nΣύνολο: κωδικοί {summary['sku_pct']}% · προσόψεις {summary['facings_pct']}% · "
              f"επιπλέον {summary['false_pos']} · λείπει {summary['missing_hit']} · "
              f"σωστό ράφι {summary['shelf_ok_pct']}% · σφάλματα {summary['errors']} · "
              f"μέσος χρόνος {summary['avg_seconds']} s")
        out = config.WORKSPACE / "eval"
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"eval_{time.strftime('%Y%m%d_%H%M%S')}_{model.replace('/', '_')}_{PROMPT_VERSION}.json"
        path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(f"Αποθηκεύτηκε: {path.relative_to(config.ROOT)}\n")


if __name__ == "__main__":
    asyncio.run(main())
