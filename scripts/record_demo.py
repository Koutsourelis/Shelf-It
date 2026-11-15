"""Γράφει βίντεο της κονσόλας την ώρα που δουλεύει ο agent. Ο server πρέπει να τρέχει.

    python scripts/record_demo.py --replay <run_id>          # ξαναπαίζει αποθηκευμένη εκτέλεση
    python scripts/record_demo.py --goal "..." --scenario shelf   # νέα ζωντανή εκτέλεση
    python scripts/record_demo.py --replay <run_id> --speed 2

Το βίντεο (.webm, 1280x720, χωρίς ήχο) γράφεται στο workspace/video/. Τα .webm ανεβαίνουν
κατευθείαν σε YouTube/Loom/Drive· για αφήγηση, πρόσθεσε ήχο με το Clipchamp των Windows.
Στις ζωντανές εκτελέσεις όρισε AUTO_APPROVE=1 στο .env, αλλιώς η εγγραφή περιμένει έγκριση.
"""
import argparse
import asyncio
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from agentkit import config  # noqa: E402


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--replay", help="run_id αποθηκευμένης εκτέλεσης (φάκελος runs/)")
    ap.add_argument("--goal", help="στόχος για νέα ζωντανή εκτέλεση")
    ap.add_argument("--scenario", default=config.DEFAULT_SCENARIO)
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--timeout", type=int, default=600, help="μέγιστα δευτερόλεπτα αναμονής")
    ap.add_argument("--name", default="demo")
    ap.add_argument("--plain", action="store_true", help="κανονική προβολή αντί για λειτουργία παρουσίασης")
    args = ap.parse_args()
    if not args.replay and not args.goal:
        ap.error("Δώσε --replay <run_id> ή --goal \"...\"")

    from playwright.async_api import async_playwright
    out_dir = config.WORKSPACE / "video"
    out_dir.mkdir(exist_ok=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        context = await browser.new_context(
            viewport={"width": 1280, "height": 720}, color_scheme="dark",
            record_video_dir=str(out_dir), record_video_size={"width": 1280, "height": 720})
        page = await context.new_page()
        await page.goto(f"{config.BASE_URL}/dev?present={0 if args.plain else 1}")
        await page.wait_for_selector("#scenario option", state="attached")
        await asyncio.sleep(1)

        # Μετράμε πόσα «τελικά αποτελέσματα» υπάρχουν ήδη, για να περιμένουμε το καινούριο.
        if args.replay:
            r = await page.request.post(f"{config.BASE_URL}/api/runs/{args.replay}/replay?speed={args.speed}")
            if not r.ok:
                sys.exit(f"Δεν βρέθηκε αποθηκευμένη εκτέλεση {args.replay}")
        else:
            await page.select_option("#scenario", args.scenario)
            await page.fill("#goalInput", args.goal)
            await asyncio.sleep(0.8)
            await page.click("#go")

        print("Εγγραφή… (περιμένω να τελειώσει η εκτέλεση)")
        await asyncio.sleep(2)
        await page.wait_for_selector("#timeline .ev.final", timeout=args.timeout * 1000)
        await asyncio.sleep(3)          # λίγα δευτερόλεπτα στο τελικό αποτέλεσμα

        video = page.video
        await context.close()
        raw = Path(await video.path())
        final = out_dir / f"{args.name}_{time.strftime('%Y%m%d_%H%M%S')}.webm"
        shutil.move(str(raw), final)
        await browser.close()
    print("Έτοιμο:", final)


if __name__ == "__main__":
    asyncio.run(main())
