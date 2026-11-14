"""Ο server: κονσόλα, API, ζωντανή ροή γεγονότων, ψεύτικο portal, Telegram, προληπτικοί έλεγχοι.

    python -m agentkit.server
"""
import asyncio
import json
import time
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agent, config, demo_data, events, portal, telegram, watchers
from . import scenarios
from .scenarios import SCENARIOS
from .tools import browser


@asynccontextmanager
async def lifespan(app: FastAPI):
    background = [asyncio.create_task(watchers.loop(telegram.default_notifier)),
                  asyncio.create_task(telegram.poll_loop())]
    yield
    for task in background:
        task.cancel()
    await browser.shutdown()


app = FastAPI(title="agentkit", lifespan=lifespan)
app.include_router(portal.router)
app.mount("/files", StaticFiles(directory=str(config.WORKSPACE)), name="files")
CONSOLE = config.ROOT / "console"


@app.get("/")
async def index():
    return FileResponse(CONSOLE / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/brand/logo")
async def brand_logo():
    path = (CONSOLE / config.PROJECT_LOGO).resolve() if config.PROJECT_LOGO else None
    if not path or CONSOLE.resolve() not in path.parents or not path.is_file():
        raise HTTPException(404, "Δεν έχει οριστεί λογότυπο")
    return FileResponse(path)


@app.get("/api/config")
async def get_config():
    logo = config.PROJECT_LOGO and (CONSOLE / config.PROJECT_LOGO).is_file()
    return {
        "name": config.PROJECT_NAME,
        "tagline": config.PROJECT_TAGLINE,
        "logo": "/brand/logo" if logo else None,
        "provider": config.LLM_PROVIDER,
        "model": {"anthropic": config.ANTHROPIC_MODEL, "openai_compat": config.OPENAI_COMPAT_MODEL}.get(config.LLM_PROVIDER, "mock"),
        "default_scenario": scenarios.get(None).name,
        "auto_approve": config.AUTO_APPROVE,
        "watchers": config.WATCHERS_ENABLED,
        "telegram": bool(config.TELEGRAM_BOT_TOKEN),
        "scenarios": [{"name": s.name, "title": s.title, "description": s.description, "examples": s.examples}
                      for s in SCENARIOS.values()],
    }


class RunRequest(BaseModel):
    goal: str
    scenario: str | None = None


@app.post("/api/runs")
async def create_run(req: RunRequest):
    if not req.goal.strip():
        raise HTTPException(400, "Κενός στόχος")
    return {"run_id": agent.start_run(req.goal.strip(), req.scenario, source="console")}


@app.get("/api/runs")
async def list_runs():
    saved = sorted((p.stem for p in config.RUNS_DIR.glob("*.jsonl") if p.stem != "system"), reverse=True)
    return {"live": list(agent.RUNS.values()), "saved": saved[:50]}


@app.post("/api/runs/{run_id}/cancel")
async def cancel(run_id: str):
    return {"ok": agent.cancel_run(run_id)}


@app.post("/api/runs/{run_id}/replay")
async def replay(run_id: str, speed: float = 1.0):
    if not events.load_run(run_id):
        raise HTTPException(404, "Δεν βρέθηκε αποθηκευμένη εκτέλεση")
    asyncio.create_task(events.replay(run_id, speed))
    return {"ok": True}


class Approval(BaseModel):
    approved: bool


@app.post("/api/approvals/{approval_id}")
async def approve(approval_id: str, body: Approval):
    return {"ok": agent.resolve_approval(approval_id, body.approved)}


@app.get("/api/events")
async def stream():
    """Server-Sent Events: πρώτα το ιστορικό της συνεδρίας, μετά ό,τι συμβαίνει ζωντανά."""
    async def gen():
        q = events.subscribe()
        try:
            for ev in events.history():
                yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(ev, ensure_ascii=False, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            events.unsubscribe(q)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --- Χειριστήρια demo ---------------------------------------------------

@app.post("/api/demo/{action}")
async def demo(action: str):
    if action == "reset":
        await asyncio.to_thread(demo_data.build)
        portal.orders.clear()
        watchers.reset()
        text = "Τα δεδομένα επανήλθαν στην αρχική κατάσταση (πλανόγραμμα, αποθήκη, έλεγχοι, παραγγελίες)."
    elif action == "check_now":
        started = await watchers.check_once(telegram.default_notifier)
        text = f"Έλεγχος τώρα: ξεκίνησαν {len(started)} εκτελέσεις."
    else:
        raise HTTPException(404, "Άγνωστη ενέργεια")
    events.emit("system", "demo", text=text)
    return {"ok": True, "text": text}


# --- Φωτογραφία ραφιού από το κινητό ---------------------------------------

@app.get("/capture")
async def capture_page():
    """Σελίδα για το κινητό: ανοίγει την κάμερα και στέλνει τη φωτογραφία. Θέλει HOST=0.0.0.0 και ίδιο δίκτυο."""
    return FileResponse(CONSOLE / "capture.html", headers={"Cache-Control": "no-store"})


@app.post("/api/shelf/photo")
async def shelf_photo(file: UploadFile):
    """Αποθηκεύει τη φωτογραφία στο workspace/photos και ξεκινά αμέσως τον έλεγχο του ραφιού."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in watchers.PHOTO_TYPES:
        raise HTTPException(400, "Δεκτές μορφές: jpg, png, webp")
    data = await file.read()
    if not data or len(data) > 25_000_000:
        raise HTTPException(400, "Κενό ή πολύ μεγάλο αρχείο (όριο 25 MB)")
    watchers.PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    name = f"shelf_{time.strftime('%H%M%S')}{ext}"
    (watchers.PHOTO_DIR / name).write_bytes(data)
    watchers.mark_seen(name)
    run_id = agent.start_run(watchers.photo_goal(name), "shelf", source="camera", notifier=telegram.default_notifier())
    return {"ok": True, "photo": name, "run_id": run_id}


@app.get("/api/portal/orders")
async def portal_orders():
    return portal.orders


def main():
    print(f"\n  Κονσόλα:  {config.BASE_URL}\n  Κάμερα:   {config.BASE_URL}/capture  (από κινητό: HOST=0.0.0.0 και η IP του laptop)\n"
          f"  Αποθήκη:  {config.BASE_URL}/portal/orders\n"
          f"  Μοντέλο:  {config.LLM_PROVIDER}\n")
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning")


if __name__ == "__main__":
    main()
