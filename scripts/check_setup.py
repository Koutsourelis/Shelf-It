"""Έλεγχος εγκατάστασης. Τρέξε το σε κάθε νέο laptop και πριν από το demo:

    python scripts/check_setup.py

Ελέγχει: πακέτα, δεδομένα, βρόχο agent (με το ψεύτικο μοντέλο), προληπτικούς ελέγχους,
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
    demo_data.build(side_files=False)
    pdfs = len(list((config.DATA_DIR / "invoices").glob("*.pdf")))
    report("Δεδομένα demo", config.DB_PATH.exists() and pdfs > 0, f"{pdfs} PDF τιμολογίων"
           if pdfs else "λείπουν τα PDF → τρέξε: python scripts/make_demo_data.py")

    # Βρόχος agent με το ψεύτικο μοντέλο (χωρίς κλειδί, χωρίς internet).
    real_provider, config.LLM_PROVIDER = config.LLM_PROVIDER, "mock"
    config.AUTO_APPROVE = True
    final = await agent.run_agent("Δοκιμή", "analyst", source="check")
    run = list(agent.RUNS.values())[-1]
    report("Βρόχος agent (ψεύτικο μοντέλο)", run["status"] == "done" and {"report.html", "margin_trend.png"} <= set(run["artifacts"]),
           f"παραδοτέα: {', '.join(run['artifacts'])}")

    # Προληπτικοί έλεγχοι: σε καθαρά δεδομένα δεν πρέπει να χτυπούν, μετά το «χάλασμα» πρέπει.
    demo_data.build(side_files=False)
    quiet = watchers.margin_drop() is None and watchers.stock_low() is None
    demo_data.inject_margin_drop()
    demo_data.inject_stock_out()
    fired = watchers.margin_drop() is not None and watchers.stock_low() is not None
    from agentkit.tools import data as data_tools
    if data_tools._con is not None:
        data_tools._con.close()
        data_tools._con = None
    config.DB_PATH.unlink(missing_ok=True)
    report("Προληπτικοί έλεγχοι", quiet and fired, f"ήσυχοι σε καθαρά δεδομένα: {quiet}, χτυπούν μετά το χάλασμα: {fired}")

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
