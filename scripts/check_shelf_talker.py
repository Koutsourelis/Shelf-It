"""Isolated checks for the shelf talker (agentkit/shelf_talker.py, agentkit/tools/talker.py).

    python scripts/check_shelf_talker.py [--keep DIR]

Everything runs against TEMPORARY copies: recommendation database, workspace/, state/talkers/ and runs/ are
redirected to a temp directory that is deleted at the end (or copied to DIR with --keep, to look at the PNGs).
fal is replaced by an httpx.MockTransport: NO network request is made and nothing is billed. FAL_KEY is
replaced by a dummy value for the duration of the script; the real key is never read or printed.

What this is NOT: a real provider validation. Recommendations below are TEST FIXTURES ("TEST-FIXTURE-" IDs),
the artwork is a locally drawn gradient, and the provider request IDs are fake.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import httpx                                        # noqa: E402
from PIL import Image, ImageDraw                    # noqa: E402

from agentkit import config                         # noqa: E402
from agentkit import recommendations as store       # noqa: E402
from agentkit import shelf_talker as st             # noqa: E402

DUMMY_KEY = "test-dummy-key-not-real"
results: list[bool] = []


def report(name: str, ok: bool, detail: str = "") -> None:
    ok = bool(ok)
    results.append(ok)
    print(f"[{'OK ' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))


def fake_art() -> bytes:
    img = Image.new("RGB", (1024, 768))
    d = ImageDraw.Draw(img)
    for y in range(768):
        d.line((0, y, 1024, y), fill=(120 + y // 8, 180, 120 + y // 12))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


class FakeFal:
    """Mock of the fal queue + image host. Records every request (host, path, whether auth was sent)."""

    def __init__(self, mode: str = "ok", status_url: str | None = None):
        self.mode, self.calls, self.submits = mode, [], 0
        self.status_url = status_url
        self.art = fake_art()

    def handler(self, req: httpx.Request) -> httpx.Response:
        auth = req.headers.get("authorization")
        self.calls.append({"host": req.url.host, "path": req.url.path, "method": req.method, "auth": auth})
        host, path = req.url.host, req.url.path
        if host == "queue.fal.run" and req.method == "POST" and path == "/fal-ai/flux/schnell":
            self.submits += 1
            if self.mode == "submit_timeout":
                raise httpx.ReadTimeout("timed out", request=req)
            if self.mode == "submit_500":
                return httpx.Response(502, json={"detail": "bad gateway"})
            if self.mode == "submit_401":
                return httpx.Response(401, json={"detail": "unauthorized"})
            body = json.loads(req.content)
            assert "prompt" in body and "no text" in body["prompt"]
            rid = f"fake-req-{self.submits}"
            base = f"https://queue.fal.run/fal-ai/flux/requests/{rid}"
            return httpx.Response(200, json={"request_id": rid, "response_url": base,
                                             "status_url": self.status_url or base + "/status",
                                             "cancel_url": base + "/cancel", "queue_position": 0})
        if host == "queue.fal.run" and path.endswith("/status"):
            if self.mode == "queued":
                return httpx.Response(202, json={"status": "IN_QUEUE", "queue_position": 3})
            if self.mode == "provider_error":
                return httpx.Response(200, json={"status": "COMPLETED", "error": "boom", "error_type": "runner_error"})
            return httpx.Response(200, json={"status": "COMPLETED", "metrics": {"inference_time": 0.4}})
        if host == "queue.fal.run" and "/fal-ai/flux/requests/" in path:
            return httpx.Response(200, json={
                "images": [{"url": "https://v3.fal.media/files/fake/art.png", "width": 1024, "height": 768,
                            "content_type": "image/png"}],
                "timings": {"inference": 0.4}, "seed": 42,
                "has_nsfw_concepts": [self.mode == "nsfw"], "prompt": "x"})
        if host == "v3.fal.media":
            return httpx.Response(200, content=self.art, headers={"content-type": "image/png"})
        return httpx.Response(404, json={"detail": f"unexpected {req.method} {req.url}"})

    def transports(self):
        t = httpx.MockTransport(self.handler)
        return {"transport": t, "download_transport": t}


def register(rec_id: str, **extra) -> None:
    store.register_recommendation({"recommendation_id": rec_id, "kind": "test_fixture",
                                   "product": {"sku": "SKU-TEST", "name": "Producer name"},
                                   "placement": {"to": {"shelf": 2, "position": 1}},
                                   "price": {"amount": 9.99, "currency": "EUR", "source": "test_fixture"}, **extra})


def feedback(rec_id: str, sid: str, decision: str, correction=None) -> None:
    body = {"submission_id": sid, "decision": decision}
    if correction is not None:
        body["correction"] = correction
    store.record_feedback(rec_id, body)


GREEK = "Ελαιόλαδο Κρήτης Εξαιρετικό Παρθένο 1 λίτρο"


def confirm(rec_id: str, name=GREEK, amount=7.49, currency="EUR") -> None:
    feedback(rec_id, "s1", "accepted")
    feedback(rec_id, "s2", "corrected", {"product": {"sku": "SKU-TEST", "name": name},
                                         "price": {"amount": amount, "currency": currency, "source": "owner_input"}})


async def main(keep: str | None) -> int:
    tmp = Path(tempfile.mkdtemp(prefix="talker-check-"))
    saved = (store.DB_PATH, st.STATE_DIR, config.WORKSPACE, config.RUNS_DIR, os.environ.get("FAL_KEY"))
    store.DB_PATH = tmp / "state" / "recommendations.sqlite3"
    st.STATE_DIR = tmp / "state" / "talkers"
    config.WORKSPACE = tmp / "workspace"
    config.RUNS_DIR = tmp / "runs"
    for d in (config.WORKSPACE, config.RUNS_DIR):
        d.mkdir(parents=True)
    os.environ["FAL_KEY"] = DUMMY_KEY
    st.TOTAL_BUDGET_S, st.POLL_INTERVAL_S = 3.0, 0.05
    try:
        await run_checks(tmp)
    finally:
        if keep:
            shutil.copytree(tmp, keep, dirs_exist_ok=True)
            print(f"Kept test output in {keep}")
        shutil.rmtree(tmp, ignore_errors=True)
        store.DB_PATH, st.STATE_DIR, config.WORKSPACE, config.RUNS_DIR, real = saved
        if real is None:
            os.environ.pop("FAL_KEY", None)
        else:
            os.environ["FAL_KEY"] = real
    print(f"\n{sum(results)}/{len(results)} checks passed")
    return 0 if all(results) else 1


async def run_checks(tmp: Path) -> None:
    gen = st.generate

    # --- inputs -------------------------------------------------------------------
    fal = FakeFal()
    r = await gen("TEST-FIXTURE-missing", GREEK, 7.49, "EUR", **fal.transports())
    report("unknown recommendation -> not_found, no request", r["status"] == "not_found" and not fal.calls, r)

    register("TEST-FIXTURE-nofb")
    r = await gen("TEST-FIXTURE-nofb", GREEK, 7.49, "EUR", **fal.transports())
    report("no feedback -> missing_inputs", r["status"] == "missing_inputs" and not fal.calls, r)

    register("TEST-FIXTURE-accepted")
    feedback("TEST-FIXTURE-accepted", "s1", "accepted")
    r = await gen("TEST-FIXTURE-accepted", "Producer name", 9.99, "EUR", **fal.transports())
    report("placement acceptance alone does not confirm name/price",
           r["status"] == "missing_inputs" and len(r["missing"]) == 2 and not fal.calls, r)

    register("TEST-FIXTURE-priceonly")
    feedback("TEST-FIXTURE-priceonly", "s1", "corrected",
             {"price": {"amount": 3.2, "currency": "EUR", "source": "owner_input"}})
    r = await gen("TEST-FIXTURE-priceonly", "Producer name", 3.2, "EUR", **fal.transports())
    report("price confirmed but name not -> missing name only",
           r["status"] == "missing_inputs" and len(r["missing"]) == 1 and "name" in r["missing"][0], r)

    register("TEST-FIXTURE-rejected")
    confirm("TEST-FIXTURE-rejected")
    feedback("TEST-FIXTURE-rejected", "s3", "rejected")
    r = await gen("TEST-FIXTURE-rejected", GREEK, 7.49, "EUR", **fal.transports())
    report("latest decision rejected -> refused", r["status"] == "missing_inputs" and not fal.calls, r)

    register("TEST-FIXTURE-ok")
    confirm("TEST-FIXTURE-ok")
    r = await gen("TEST-FIXTURE-ok", GREEK + " ", 7.49, "EUR", **fal.transports())
    report("name differs from owner-confirmed -> input_mismatch", r["status"] == "input_mismatch" and not fal.calls, r)
    r = await gen("TEST-FIXTURE-ok", GREEK, 7.50, "EUR", **fal.transports())
    report("price differs -> input_mismatch", r["status"] == "input_mismatch", r)
    r = await gen("TEST-FIXTURE-ok", GREEK, 7.49, "USD", **fal.transports())
    report("currency differs -> input_mismatch", r["status"] == "input_mismatch", r)
    r = await gen("TEST-FIXTURE-ok", GREEK, 7.491, "EUR", **fal.transports())
    report("3-decimal price -> invalid_input (no rounding)", r["status"] == "invalid_input", r)
    r = await gen("TEST-FIXTURE-ok", None, 7.49, "EUR", **fal.transports())
    report("missing product_name argument -> missing_inputs", r["status"] == "missing_inputs" and not fal.calls, r)
    r = await gen("TEST-FIXTURE-ok", GREEK, 7.49, "EUR", theme="logo", **fal.transports())
    report("unknown theme -> invalid_input", r["status"] == "invalid_input", r)

    os.environ["FAL_KEY"] = ""
    r = await gen("TEST-FIXTURE-ok", GREEK, 7.49, "EUR", **fal.transports())
    report("FAL_KEY absent -> not_configured, no request", r["status"] == "not_configured" and not fal.calls, r)
    os.environ["FAL_KEY"] = DUMMY_KEY

    # --- happy path -------------------------------------------------------------------
    r = await gen("TEST-FIXTURE-ok", GREEK, 7.49, "EUR", **fal.transports())
    ok = r["status"] == "generated" and fal.submits == 1
    report("confirmed inputs -> generated", ok, r)
    png = config.WORKSPACE / r.get("file", "workspace/x").removeprefix("workspace/")
    report("PNG exists under workspace/talkers/", png.exists() and png.parent.name == "talkers", str(png))
    if png.exists():
        with Image.open(png) as im:
            im.verify()
        with Image.open(png) as im:
            report("PNG decodes, 1200x1600", im.format == "PNG" and im.size == (1200, 1600), str(im.size))
    queue = [c for c in fal.calls if c["host"] == "queue.fal.run"]
    media = [c for c in fal.calls if c["host"] != "queue.fal.run"]
    report("auth header sent to queue.fal.run only", all(c["auth"] == f"Key {DUMMY_KEY}" for c in queue) and queue)
    report("no auth header sent to the image host", media and all(c["auth"] is None for c in media), media)
    report("status polled at owner/app URL (fal-ai/flux/requests/...)",
           any(c["path"] == "/fal-ai/flux/requests/fake-req-1/status" for c in queue))
    report("tool result carries no request_id", "fake-req" not in json.dumps(r), r)
    meta = st.load_record(r["talker_id"])
    report("private metadata: request_id, model_id, inputs, generated_at, sha256",
           meta["request_id"] == "fake-req-1" and meta["model_id"] == "fal-ai/flux/schnell"
           and meta["recommendation_id"] == "TEST-FIXTURE-ok" and meta["inputs"]["price_text"] == "7,49 €"
           and meta["generated_at"] and meta["png_sha256"] and meta["timings"], meta)
    report("metadata stored outside workspace/", config.WORKSPACE.resolve() not in st.state_dir().parents)
    report("art prompt has no product name or price", GREEK not in meta["fal_arguments"]["prompt"]
           and "7" not in meta["fal_arguments"]["prompt"])
    n = len(fal.calls)
    r2 = await gen("TEST-FIXTURE-ok", GREEK, 7.49, "EUR", **fal.transports())
    report("same inputs again -> reused, no new request", r2["status"] == "generated" and r2["reused"]
           and len(fal.calls) == n)

    # --- reliability ---------------------------------------------------------------------
    register("TEST-FIXTURE-ambig")
    confirm("TEST-FIXTURE-ambig")
    fal = FakeFal("submit_timeout")
    r = await gen("TEST-FIXTURE-ambig", GREEK, 7.49, "EUR", **fal.transports())
    report("read timeout on submit -> submit_ambiguous", r["status"] == "submit_ambiguous", r)
    fal2 = FakeFal()
    r = await gen("TEST-FIXTURE-ambig", GREEK, 7.49, "EUR", **fal2.transports())
    report("after ambiguous submit: no blind resubmit", r["status"] == "submit_ambiguous" and not fal2.calls, r)

    register("TEST-FIXTURE-502")
    confirm("TEST-FIXTURE-502")
    fal = FakeFal("submit_500")
    r = await gen("TEST-FIXTURE-502", GREEK, 7.49, "EUR", **fal.transports())
    report("5xx on submit -> submit_ambiguous", r["status"] == "submit_ambiguous", r)

    register("TEST-FIXTURE-401")
    confirm("TEST-FIXTURE-401")
    fal = FakeFal("submit_401")
    r = await gen("TEST-FIXTURE-401", GREEK, 7.49, "EUR", **fal.transports())
    report("4xx on submit -> submit_failed (honest)", r["status"] == "submit_failed" and DUMMY_KEY not in json.dumps(r), r)

    register("TEST-FIXTURE-queued")
    confirm("TEST-FIXTURE-queued")
    fal = FakeFal("queued")
    r = await gen("TEST-FIXTURE-queued", GREEK, 7.49, "EUR", **fal.transports())
    report("still queued at deadline -> pending (bounded)", r["status"] == "pending" and fal.submits == 1, r)
    fal.mode = "ok"
    r = await gen("TEST-FIXTURE-queued", GREEK, 7.49, "EUR", **fal.transports())
    report("pending resumed with same request_id, no resubmit", r["status"] == "generated" and fal.submits == 1, r)

    register("TEST-FIXTURE-err")
    confirm("TEST-FIXTURE-err")
    fal = FakeFal("provider_error")
    r = await gen("TEST-FIXTURE-err", GREEK, 7.49, "EUR", **fal.transports())
    report("COMPLETED with error -> provider_failed", r["status"] == "provider_failed", r)
    report("no PNG after provider failure", not list((config.WORKSPACE / "talkers").glob("*TEST-FIXTURE-err*")))

    register("TEST-FIXTURE-nsfw")
    confirm("TEST-FIXTURE-nsfw")
    fal = FakeFal("nsfw")
    r = await gen("TEST-FIXTURE-nsfw", GREEK, 7.49, "EUR", **fal.transports())
    report("safety-flagged image -> provider_failed", r["status"] == "provider_failed", r)

    register("TEST-FIXTURE-evilurl")
    confirm("TEST-FIXTURE-evilurl")
    fal = FakeFal(status_url="https://evil.example/steal/status")
    r = await gen("TEST-FIXTURE-evilurl", GREEK, 7.49, "EUR", **fal.transports())
    report("status_url on a foreign host is ignored; key never sent there",
           r["status"] == "generated" and not any(c["host"] == "evil.example" for c in fal.calls), r)

    # --- rendering ------------------------------------------------------------------------
    report("Greek price formatting", st.price_text(st._cents(1234.5), "EUR") == "1.234,50 €"
           and st.price_text(st._cents(12), "USD") == "12,00 USD")
    font = st.pick_font(GREEK + "€")
    report("a font with Greek glyphs is available", bool(font), font)
    long_name = "Πολύ " * 60
    try:
        st.render(fake_art(), long_name.strip(), "1,00 €")
        report("over-long name -> render_failed (no truncation)", False)
    except st.TalkerError as e:
        report("over-long name -> render_failed (no truncation)", e.status == "render_failed")
    img = st.render(fake_art(), "Φέτα ΠΟΠ Δωδώνη 400γρ", "4,95 €")
    img.save(config.WORKSPACE / "talkers" / "render_sample_feta.png")

    # --- through the agent's approval mechanism -----------------------------------------------
    from agentkit import agent
    from agentkit.llm import ToolCall
    from agentkit.scenarios import Scenario
    from agentkit.tools import REGISTRY
    tool = REGISTRY.get("make_shelf_talker")
    report("tool registered with needs_approval=True", tool is not None and tool.needs_approval)
    scen = Scenario(name="talker-check", title="t", description="t", prompt="t", tools=["make_shelf_talker"])
    register("TEST-FIXTURE-agent")
    confirm("TEST-FIXTURE-agent", name="Γιαούρτι στραγγιστό 2%", amount=2.3)
    fal = FakeFal()
    real_generate = st.generate

    async def patched(*a, **k):
        return await real_generate(*a, **k, **fal.transports())
    st.generate = patched
    saved_auto = config.AUTO_APPROVE
    config.AUTO_APPROVE = False
    try:
        call = ToolCall(id="c1", name="make_shelf_talker",
                        input={"recommendation_id": "TEST-FIXTURE-agent", "product_name": "Γιαούρτι στραγγιστό 2%",
                               "price_amount": 2.3, "currency": "EUR"})
        for answer in (False, True):
            ctx = agent.RunContext(run_id=f"talker-check-{answer}", scenario=scen)
            task = asyncio.create_task(agent._call_tool(ctx, call))
            for _ in range(100):
                await asyncio.sleep(0.01)
                if agent._approvals:
                    break
            pending = list(agent._approvals)
            report(f"approval requested before the fal call (answer={answer})", len(pending) == 1 and not fal.calls
                   if not answer else len(pending) == 1)
            agent.resolve_approval(pending[0], answer)
            res = await task
            if not answer:
                report("declined approval -> error result, no fal request", res.is_error and not fal.calls,
                       res.content)
            else:
                out = json.loads(res.content)
                report("approved -> generated + artifact emitted", out["status"] == "generated"
                       and ctx.artifacts == [out["file"].removeprefix("workspace/")], res.content)
    finally:
        st.generate = real_generate
        config.AUTO_APPROVE = saved_auto


if __name__ == "__main__":
    keep = sys.argv[sys.argv.index("--keep") + 1] if "--keep" in sys.argv else None
    raise SystemExit(asyncio.run(main(keep)))
