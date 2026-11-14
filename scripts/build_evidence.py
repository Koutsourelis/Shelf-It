"""Ετοιμάζει και αποθηκεύει τα πακέτα τεκμηρίων όλων των προϊόντων του καταλόγου (data/evidence/).

    python scripts/build_evidence.py                      # ό,τι λείπει
    python scripts/build_evidence.py --refresh            # νέα αναζήτηση για όλες τις κατηγορίες
    python scripts/build_evidence.py --audience φοιτητές  # για συγκεκριμένο κοινό

Θέλει πραγματικό μοντέλο στο .env (με LLM_PROVIDER=mock δεν γίνεται αναζήτηση). Τρέξε το πριν από το demo,
με δίκτυο· μετά το demo δουλεύει από τα αποθηκευμένα.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from agentkit.tools.data import run_sql          # noqa: E402
from agentkit.tools.evidence import build_pack   # noqa: E402


async def main() -> None:
    refresh = "--refresh" in sys.argv
    audience = sys.argv[sys.argv.index("--audience") + 1] if "--audience" in sys.argv else ""
    _, products = run_sql("select sku, category from products order by sku")
    searched = set()                     # κάθε κατηγορία ξαναψάχνεται το πολύ μία φορά ανά εκτέλεση
    for sku, category in products:
        pack = await build_pack(sku, audience, refresh and category not in searched)
        searched.add(category)
        print(f"{sku} | {pack['category']} | {pack['status']} | πηγές {pack['sources']} | με αριθμό "
              f"{pack['numeric_evidence']} | απορρίφθηκαν {pack['dropped_claims']} | {pack['provider']}"
              + (f" | {pack['reason']}" if pack["reason"] else ""))
        for e in pack["evidence"]:
            print(f"    - {e['claim']} [{e['published'] or 'χωρίς ημερομηνία'}] {e['url']}")


if __name__ == "__main__":
    asyncio.run(main())
