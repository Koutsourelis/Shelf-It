"""Πρώτη δοκιμή του treg: μία κλήση σε κάθε εργαλείο που χρησιμοποιεί το πακέτο τεκμηρίων.

    python scripts/treg_probe.py            # με τη λέξη «καφές»
    python scripts/treg_probe.py γιαούρτι

Θέλει TREG_TOKEN στο .env. Τυπώνει για κάθε εργαλείο: αν απάντησε, το κόστος, τη μορφή της απάντησης (μόνο ονόματα
πεδίων) και τι κατάφερε να διαβάσει ο κώδικας. Δεν τυπώνει το token. Κοστίζει λιγότερο από ένα cent.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from agentkit import config                      # noqa: E402
from agentkit.tools import evidence as ev        # noqa: E402


def shape(node, depth: int = 0) -> str:
    """Η μορφή ενός JSON: ονόματα πεδίων και μεγέθη λιστών, χωρίς το περιεχόμενο."""
    if isinstance(node, dict):
        if depth >= 3:
            return "{…}"
        return "{" + ", ".join(f"{k}: {shape(v, depth + 1)}" for k, v in list(node.items())[:12]) + "}"
    if isinstance(node, list):
        return f"[{len(node)} × {shape(node[0], depth + 1)}]" if node else "[]"
    return type(node).__name__


async def main() -> None:
    word = sys.argv[1] if len(sys.argv) > 1 else "καφές"
    if not config.TREG_TOKEN:
        print("Δεν υπάρχει TREG_TOKEN στο .env.")
        sys.exit(1)
    query = f"{word} αγορά {config.EVIDENCE_REGION} πωλήσεις"
    calls = [(config.TREG_NEWS_TOOL, {config.TREG_QUERY_PARAM: query}),
             (config.TREG_SEARCH_TOOL, {config.TREG_QUERY_PARAM: query}),
             (config.TREG_TRENDS_TOOL, {"keywords": [word], "country": config.EVIDENCE_COUNTRY})]
    failed = 0
    for tool_id, body in calls:
        log: list[dict] = []
        print(f"\n== {tool_id}  {body}")
        try:
            data = await ev.treg_call(tool_id, body, log)
        except Exception:
            failed += 1
            print(f"   ΑΠΟΤΥΧΙΑ: {log[0]['error']}")
            continue
        print(f"   κόστος: {log[0]['cost_usd']} $ · πάροχος: {log[0].get('served_by')}")
        print(f"   μορφή: {shape(data)[:900]}")
        if tool_id == config.TREG_TRENDS_TOOL:
            points = ev._series(data)
            print(f"   χρονοσειρά: {len(points)} σημεία → {ev.trend_change(points)}")
        else:
            found: list[dict] = []
            ev._harvest(data, found)
            print(f"   αποτελέσματα που διαβάστηκαν: {len(found)}, με ημερομηνία: {sum(1 for r in found if r['published'])}")
            for r in found[:3]:
                print(f"     - {r['title'][:70]} | {r['published']} | {r['url'][:80]}")
    sys.exit(1 if failed == len(calls) else 0)


if __name__ == "__main__":
    asyncio.run(main())
