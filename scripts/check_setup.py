"""Έλεγχος εγκατάστασης. Τρέξε το σε κάθε νέο laptop και πριν από το demo:

    python scripts/check_setup.py

Ελέγχει: πακέτα, δεδομένα, όλη τη ροή του ραφιού (με το ψεύτικο μοντέλο), τον προληπτικό έλεγχο,
browser και, αν έχει οριστεί πραγματικός πάροχος στο .env, μια πραγματική κλήση στο μοντέλο.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

results = []


def report(name: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    print(f"  [{'OK ' if ok else 'ΑΠΟΤΥΧΙΑ'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> None:
    print("\nΈλεγχος εγκατάστασης\n")
    try:
        from agentkit import agent, config, demo_data, watchers
        from agentkit.tools import REGISTRY
        report("Πακέτα και κώδικας", True, f"{len(REGISTRY)} εργαλεία")
    except Exception as e:
        report("Πακέτα και κώδικας", False, f"{type(e).__name__}: {e} → τρέξε: pip install -r requirements.txt")
        return

    # Ο έλεγχος δουλεύει σε δικό του αντίγραφο της βάσης, ώστε να τρέχει και όσο είναι ανοιχτός ο server.
    config.DB_PATH = config.DATA_DIR / "_check.duckdb"
    summary = demo_data.build()
    sample = demo_data.PHOTOS_DIR / "sample_before.png"
    report("Δεδομένα demo", config.DB_PATH.exists() and sample.exists(),
           f"{summary['products']} κωδικοί, {summary['planogram_slots']} θέσεις πλανογράμματος" if sample.exists()
           else "λείπουν οι δοκιμαστικές φωτογραφίες → τρέξε: python scripts/make_demo_data.py --samples")

    # Βρόχος agent με το ψεύτικο μοντέλο (χωρίς κλειδί, χωρίς internet): όλη η ροή του ραφιού.
    real_provider, config.LLM_PROVIDER = config.LLM_PROVIDER, "mock"
    config.AUTO_APPROVE = True
    await agent.run_agent("Δοκιμή", "shelf", source="check")
    run = list(agent.RUNS.values())[-1]
    from agentkit import portal
    from agentkit.tools.data import run_sql
    _, check = run_sql("select compliance_pct, issues from shelf_checks order by checked_at desc limit 1")
    expected = {"shelf_report.md", "shelf_check_sample_before.png"}
    report("Βρόχος agent (ψεύτικο μοντέλο)",
           run["status"] == "done" and expected <= set(run["artifacts"]) and bool(check) and len(portal.orders) == 1,
           f"συμμόρφωση {check[0][0] if check else '-'}%, {check[0][1] if check else '-'} ευρήματα, "
           f"παραγγελίες: {len(portal.orders)}, παραδοτέα: {', '.join(run['artifacts'])}")
    portal.orders.clear()

    # Πακέτο τεκμηρίων: με το ψεύτικο μοντέλο δεν γίνεται αναζήτηση· ελέγχουμε μορφή και περιθώριο από κώδικα.
    from agentkit.tools.evidence import build_pack
    pack = await build_pack("C01")
    report("Πακέτο τεκμηρίων", pack["margin_pct"] is not None and pack["status"] in ("sufficient", "insufficient"),
           f"{pack['sku']}: περιθώριο {pack['margin_pct']}%, status {pack['status']}, πηγές {pack['sources']}")

    # Προληπτικός έλεγχος: ήσυχος όσο δεν υπάρχει νέα φωτογραφία, χτυπά μόλις πέσει μία στο workspace/photos.
    watchers.reset()
    quiet = watchers.new_photo() is None and watchers.new_photo() is None
    probe = watchers.PHOTO_DIR / "_check_probe.png"
    probe.write_bytes(sample.read_bytes())
    hit = watchers.new_photo()
    probe.unlink(missing_ok=True)
    watchers.reset()
    from agentkit.tools import data as data_tools
    if data_tools._con is not None:
        data_tools._con.close()
        data_tools._con = None
    config.DB_PATH.unlink(missing_ok=True)
    report("Προληπτικός έλεγχος (νέα φωτογραφία)", quiet and hit is not None,
           f"ήσυχος χωρίς νέα φωτογραφία: {quiet}, χτυπά με νέα φωτογραφία: {hit is not None}")

    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page()
            await page.set_content("<h1>ok</h1>")
            ok = await page.inner_text("h1") == "ok"
            await browser.close()
        report("Browser (Playwright)", ok)
    except Exception as e:
        report("Browser (Playwright)", False, f"{type(e).__name__} → τρέξε: python -m playwright install chromium")

    if real_provider == "mock":
        print("  [ -- ] Πραγματικό μοντέλο — δεν ελέγχθηκε (LLM_PROVIDER=mock στο .env)")
    else:
        config.LLM_PROVIDER = real_provider
        try:
            from agentkit.llm import new_conversation
            conv = new_conversation("Απάντησε με μία λέξη.", [])
            conv.add_user("Πες «έτοιμος».")
            turn = await conv.step()
            report(f"Πραγματικό μοντέλο ({real_provider}: {conv.model})", bool(turn.text.strip()), turn.text.strip()[:60])
        except Exception as e:
            report(f"Πραγματικό μοντέλο ({real_provider})", False, f"{type(e).__name__}: {str(e)[:160]}")

    print("\n" + ("Όλα εντάξει." if all(results) else "Υπάρχουν αποτυχίες, δες παραπάνω.") + "\n")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
