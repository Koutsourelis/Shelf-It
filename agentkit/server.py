"""Ο server: σελίδες, API, ζωντανή ροή γεγονότων, ψεύτικο portal, Telegram, προληπτικοί έλεγχοι.

    python -m agentkit.server

Σελίδες:
    /          αρχική: κάρτες για κάθε σελίδα και QR για το κινητό
    /shelf     οθόνη ραφιού: live κάμερα, φανάρι, εργασίες, χρονολόγιο      (console/shelf.html)
    /tasks     κινητό υπαλλήλου: εργασίες με φωτογραφία                     (console/tasks.html)
    /portal    κεντρική αποθήκη (προσομοίωση)
    /dev       για εμάς και τους κριτές: agent, εργαλεία, ίχνος ελέγχου, ρυθμίσεις, mock  (console/index.html)
"""
import asyncio
import io
import json
import socket
import time
from pathlib import Path
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agent, config, demo_data, events, live, portal, tasks, telegram, vision, watchers
from . import scenarios
from .scenarios import SCENARIOS
from .tools import browser


@asynccontextmanager
async def lifespan(app: FastAPI):
    background = [asyncio.create_task(watchers.loop(telegram.default_notifier)),
                  asyncio.create_task(telegram.poll_loop()),
                  asyncio.create_task(live.reminder_loop())]
    yield
    for task in background:
        task.cancel()
    await browser.shutdown()


app = FastAPI(title="agentkit", lifespan=lifespan)
app.include_router(portal.router)
from . import feedback_api  # noqa: E402  (recommendations + owner feedback, agentkit/feedback_api.py)
app.include_router(feedback_api.router)
from . import verification_api  # noqa: E402  (second-scan sessions, agentkit/verification_api.py; vision pending)
app.include_router(verification_api.router)
app.mount("/files", StaticFiles(directory=str(config.WORKSPACE)), name="files")
CONSOLE = config.ROOT / "console"
app.mount("/ui", StaticFiles(directory=str(CONSOLE / "ui")), name="ui")   # κοινό στυλ των σελίδων


def _page(name: str) -> FileResponse:
    return FileResponse(CONSOLE / name, headers={"Cache-Control": "no-store"})


@app.get("/")
async def home():
    """Αρχική: μία κάρτα ανά σελίδα και QR για να ανοίξει το κινητό τις εργασίες χωρίς να γράψει IP."""
    return _page("home.html")


@app.get("/dev")
async def dev():
    """Η αναλυτική κονσόλα του agent: πλάνο, εργαλεία, εγκρίσεις, ίχνος ελέγχου, replay."""
    return _page("index.html")


@app.get("/agent")
async def agent_alias():
    return RedirectResponse("/dev")


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
    return {"run_id": agent.start_run(req.goal.strip(), req.scenario, source="console",
                                      notifier=telegram.default_notifier())}


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
        live.STATE.reset()
        text = "Τα δεδομένα επανήλθαν στην αρχική κατάσταση (πλανόγραμμα, αποθήκη, έλεγχοι, παραγγελίες)."
    elif action == "reset_tasks":
        live.STATE.reset()
        text = "Οι εργασίες και το χρονολόγιο μηδενίστηκαν."
    elif action == "check_now":
        started = await watchers.check_once(telegram.default_notifier)
        text = f"Έλεγχος τώρα: ξεκίνησαν {len(started)} εκτελέσεις."
    elif action == "test_telegram":
        res = await telegram.send_test_ping()
        if not res["ok"]:
            raise HTTPException(400, res["text"])
        text = res["text"]
    else:
        raise HTTPException(404, "Άγνωστη ενέργεια")
    events.emit("system", "demo", text=text)
    return {"ok": True, "text": text}


# --- Φωτογραφία ραφιού από το κινητό ---------------------------------------

@app.get("/capture")
async def capture_page():
    """Σελίδα για το κινητό: ανοίγει την κάμερα και στέλνει τη φωτογραφία. Θέλει HOST=0.0.0.0 και ίδιο δίκτυο."""
    return _page("capture.html")


@app.get("/cam")
async def cam_page():
    """Συνεχής ζωντανή κάμερα κινητού (viewfinder): στέλνει αυτόματα frames στο Gemini & mirror στο /shelf."""
    return _page("cam.html")


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
    name = f"shelf_{time.strftime('%H%M%S')}_{int((time.time() % 1) * 1000):03d}{ext}"
    (watchers.PHOTO_DIR / name).write_bytes(data)
    watchers.mark_seen(name)
    run_id = agent.start_run(watchers.photo_goal(name), "shelf", source="camera", notifier=telegram.default_notifier())
    live.STATE.last_console_run = run_id
    return {"ok": True, "photo": name, "run_id": run_id}


@app.post("/api/shelf/photos_batch")
async def shelf_photos_batch(files: list[UploadFile]):
    """Ανεβάζει 1 ή περισσότερες φωτογραφίες από την Κονσόλα (/dev), τις ταξινομεί αυτόματα κατά EXIF χρόνο λήψης
    (χωρίς να απαιτείται 'before'/'after' στο όνομα!) και τρέχει διαδοχικά Πριν -> Μετά."""
    from .tools.shelf import photo_timestamp
    if not files:
        raise HTTPException(400, "Δεν επιλέχθηκαν φωτογραφίες")
    watchers.PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for idx, f in enumerate(files[:4]):
        ext = Path(f.filename or ".jpg").suffix.lower()
        if ext not in watchers.PHOTO_TYPES:
            ext = ".jpg"
        data = await f.read()
        if not data or len(data) > 25_000_000:
            continue
        name = f"upload_{time.strftime('%H%M%S')}_{idx + 1}{ext}"
        p = watchers.PHOTO_DIR / name
        p.write_bytes(data)
        watchers.mark_seen(name)
        saved.append(p)
    if not saved:
        raise HTTPException(400, "Καμία έγκυρη φωτογραφία")
    saved.sort(key=lambda p: (photo_timestamp(p), p.stat().st_mtime, p.name))

    first = saved[0]
    first_run = agent.start_run(watchers.photo_goal(first.name), "shelf", source="console",
                                notifier=telegram.default_notifier())
    if len(saved) > 1:
        async def _chain_rest(initial_id: str, remaining: list[Path]) -> None:
            curr = initial_id
            for nxt in remaining:
                t = agent._tasks.get(curr)
                if t:
                    try:
                        await asyncio.wait_for(asyncio.shield(t), timeout=240)
                    except Exception:
                        pass
                curr = agent.start_run(watchers.photo_goal(nxt.name), "shelf", source="console",
                                       notifier=telegram.default_notifier())
        asyncio.create_task(_chain_rest(first_run, saved[1:]))
    return {"ok": True, "photos": [p.name for p in saved], "run_id": first_run}


@app.get("/api/evidence/{sku}")
async def evidence(sku: str, audience: str = "", refresh: bool = False):
    """Το πακέτο τεκμηρίων ενός κωδικού, για την οθόνη. Μορφή: planning/EVIDENCE.md."""
    from .tools.evidence import build_pack
    try:
        return await build_pack(sku.strip().upper(), audience.strip(), refresh)
    except ValueError as e:
        raise HTTPException(404, str(e))


# --- Live κάμερα (agentkit/live.py) ------------------------------------------

@app.get("/shelf")
async def shelf_page():
    """Οθόνη ραφιού: η κάμερα στέλνει frame κάθε LIVE_INTERVAL_SECONDS, φανάρι, εργασίες, χρονολόγιο."""
    return _page("shelf.html")


@app.get("/live")
async def live_page():
    return RedirectResponse("/shelf")


@app.get("/tasks")
async def tasks_page():
    """Κινητό υπαλλήλου: οι εργασίες με φωτογραφία. Κλείνουν μόνες τους όταν η κάμερα δει το ράφι σωστό."""
    return _page("tasks.html")


@app.post("/api/shelf/frame")
async def shelf_frame(file: UploadFile, force: bool = False, single: bool = False):
    """Ένα frame από τη ζωντανή κάμερα. force=1: διάβασέ το ακόμη κι αν μοιάζει με το προηγούμενο («Scan τώρα»).
    single=1: φωτογραφία από το κινητό (/capture), μετράει ως επιβεβαιωμένη χωρίς δεύτερο frame."""
    data = await file.read()
    if not data or len(data) > 10_000_000:
        raise HTTPException(400, "Κενό ή πολύ μεγάλο frame (όριο 10 MB)")
    try:
        return await live.process_frame(data, force=force, single=single)
    except Exception as e:
        events.emit("system", "log", text=f"Live frame: {type(e).__name__}: {e}")
        raise HTTPException(502, f"{type(e).__name__}: {e}")


@app.post("/api/shelf/preview")
async def shelf_preview(file: UploadFile):
    """Ελαφρύ live frame από το /cam κινητού μόνο στη μνήμη (RAM), για ζωντανό mirror στο /shelf & /dev χωρίς κλήση LLM."""
    data = await file.read()
    if not data or len(data) > 4_000_000:
        raise HTTPException(400, "Άκυρο preview frame")
    live.STATE.preview_jpeg = data
    live.STATE.preview_ts = time.time()
    snap = live.STATE.remote_snap
    live.STATE.remote_snap = None
    return {"ok": True, "ts": live.STATE.preview_ts, "snap": snap, "paused": live.STATE.remote_paused}


@app.get("/api/shelf/remote_state")
async def shelf_remote_state():
    """Heartbeat για το /cam κινητού όταν είναι σε παύση, ώστε το laptop να μπορεί να το ξυπνήσει ή να ζητήσει λήψη."""
    snap = live.STATE.remote_snap
    live.STATE.remote_snap = None
    return {
        "snap": snap,
        "paused": live.STATE.remote_paused,
        "mobile_online": bool(live.STATE.preview_jpeg and (time.time() - live.STATE.preview_ts < 20.0)),
    }


@app.post("/api/shelf/remote_trigger")
async def shelf_remote_trigger(mode: str = "live"):
    """Τηλεχειρισμός της σταθερής κάμερας κινητού (/cam) από το laptop (/shelf ή /dev)."""
    if mode == "toggle_pause":
        live.STATE.remote_paused = not live.STATE.remote_paused
        return {"ok": True, "paused": live.STATE.remote_paused}

    fresh = bool(live.STATE.preview_jpeg and (time.time() - live.STATE.preview_ts < 25.0))
    if not fresh:
        raise HTTPException(409, "Δεν βρέθηκε ενεργή κάμερα κινητού (/cam). Άνοιξε πρώτα το /cam στο κινητό.")

    if mode == "console":
        prev_run = live.STATE.last_console_run
        live.STATE.remote_snap = "console"
        for _ in range(18):
            await asyncio.sleep(0.1)
            if live.STATE.remote_snap is None and live.STATE.last_console_run != prev_run and live.STATE.last_console_run:
                return {"ok": True, "run_id": live.STATE.last_console_run, "source": "mobile_highres"}
        # Fallback: χρησιμοποίησε αμέσως το πιο πρόσφατο frame του κινητού από τη RAM
        live.STATE.remote_snap = None
        watchers.PHOTO_DIR.mkdir(parents=True, exist_ok=True)
        name = f"shelf_{time.strftime('%H%M%S')}_cam.jpg"
        (watchers.PHOTO_DIR / name).write_bytes(live.STATE.preview_jpeg or b"")
        watchers.mark_seen(name)
        run_id = agent.start_run(watchers.photo_goal(name), "shelf", source="camera", notifier=telegram.default_notifier())
        live.STATE.last_console_run = run_id
        return {"ok": True, "run_id": run_id, "photo": name, "source": "mobile_preview"}

    # mode == "live": εντολή στο /cam να στείλει αμέσως full-res frame στο Gemini
    before_frames = live.STATE.frames
    live.STATE.remote_snap = "live"
    for _ in range(16):
        await asyncio.sleep(0.1)
        if live.STATE.remote_snap is None:
            return {"ok": True, "triggered": True, "source": "mobile_highres"}
    # Fallback αν το κινητό δεν πρόλαβε να τραβήξει high-res (π.χ. ήταν σε /capture): αναλύουμε το τελευταίο frame
    live.STATE.remote_snap = None
    if live.STATE.preview_jpeg and live.STATE.frames == before_frames:
        res = await live.process_frame(live.STATE.preview_jpeg, force=True, single=True)
        return {"ok": True, "triggered": True, "source": "mobile_preview", "status": res.get("status")}
    return {"ok": True, "triggered": True}


@app.get("/api/shelf/preview.jpg")
async def get_shelf_preview(since: float = 0.0):
    """Επιστρέφει το τελευταίο live frame κινητού αν είναι φρέσκο (<20s) και νεότερο από το since."""
    raw = live.STATE.preview_jpeg
    ts = live.STATE.preview_ts
    # the header carries ts with three decimals, so compare at that precision or the same frame is sent again
    if not raw or (time.time() - ts > 20.0) or round(ts, 3) <= round(since, 3):
        return Response(status_code=204)
    return Response(raw, media_type="image/jpeg",
                    headers={"X-Preview-Ts": f"{ts:.3f}", "Cache-Control": "no-store"})


@app.get("/api/live/status")
async def live_status():
    return live.status()


@app.post("/api/live/reset")
async def live_reset():
    live.STATE.reset()
    portal.orders.clear()
    return {"ok": True}


@app.get("/api/tasks")
async def list_tasks():
    return tasks.summary()


class Claim(BaseModel):
    who: str = ""


@app.post("/api/tasks/{task_id}/claim")
async def claim_task(task_id: str, body: Claim | None = None):
    """«Το κάνω»: ο υπάλληλος αναλαμβάνει. Η εργασία κλείνει όταν η κάμερα δει το ράφι σωστό, όχι με κλικ."""
    task = tasks.claim(task_id, body.who if body else "")
    if not task:
        raise HTTPException(404, "Η εργασία δεν υπάρχει ή δεν είναι ανοιχτή")
    return task


@app.post("/api/tasks/{task_id}/order")
async def approve_task_order(task_id: str, body: Approval):
    """Μόνο για παραγγελίες πάνω από τα όρια αυτονομίας (AUTO_ORDER_MAX_*)."""
    task = await asyncio.to_thread(tasks.approve_order, task_id, body.approved)
    if not task:
        raise HTTPException(404, "Δεν υπάρχει παραγγελία που περιμένει έγκριση")
    return task


@app.post("/api/shelf/reference")
async def set_reference(file: UploadFile | None = None):
    """«Αυτό είναι το σωστό ράφι»: το frame γίνεται φωτογραφία αναφοράς για το μοντέλο όρασης."""
    data = await file.read() if file else b""
    if not data:
        raise HTTPException(400, "Χρειάζεται frame")
    refs = config.SHELF_DIR / "refs"
    refs.mkdir(parents=True, exist_ok=True)
    (refs / "shelf_ok.jpg").write_bytes(data)
    config.VISION_REFERENCE = "data/shelf/refs/shelf_ok.jpg"     # ισχύει αμέσως, μέχρι το επόμενο restart
    tasks.log("setup", "Αποθηκεύτηκε η φωτογραφία του σωστού ραφιού")
    return {"ok": True, "reference": config.VISION_REFERENCE}


def _phone_url(path: str) -> dict:
    """Η διεύθυνση που ανοίγει το κινητό. Με HOST=127.0.0.1 ο server δεν φαίνεται από το δίκτυο."""
    if config.PUBLIC_URL:
        return {"url": config.PUBLIC_URL.rstrip("/") + path, "reachable": True}
    ip = config.lan_ip()
    reachable = config.HOST not in ("127.0.0.1", "localhost") and bool(ip)
    return {"url": f"http://{ip or config.HOST}:{config.PORT}{path}", "reachable": reachable}


@app.get("/photo/{name}")
async def photo(name: str):
    """Φωτογραφία του ενεργού σετ (data/shelf[/sets/<set>]/photos). Αν λείπει η κατάληξη, δοκιμάζει jpg/jpeg/png/webp."""
    photos_dir = (config.SHELF_DIR / "photos").resolve()
    base = (photos_dir / name).resolve()
    if base.parent != photos_dir:
        raise HTTPException(404, "Δεν υπάρχει αυτή η φωτογραφία")
    candidates = [base] + [base.with_suffix(ext) for ext in (".jpg", ".jpeg", ".png", ".webp")]
    found = next((c for c in candidates if c.is_file()), None)
    if not found:
        raise HTTPException(404, "Δεν υπάρχει αυτή η φωτογραφία")
    return FileResponse(found, headers={"Cache-Control": "no-store"})


@app.get("/api/links")
async def links():
    return {
        "tasks": _phone_url("/tasks"),
        "cam": _phone_url("/cam"),
        "capture": _phone_url("/capture"),
        "shelf": _phone_url("/shelf"),
        "telegram": {
            "enabled": bool(config.TELEGRAM_BOT_TOKEN),
            "username": telegram.bot_username,
            "url": telegram.bot_url(),
            "subscribers": len(telegram.subscribers()),
        },
        "host": config.HOST,
    }


@app.get("/qr.svg")
async def qr(path: str = "/tasks"):
    """QR για το κινητό (σελίδες αυτού του server ή το συνδεδεμένο Telegram bot)."""
    if path == "telegram":
        target = telegram.bot_url()
        if not target:
            raise HTTPException(404, "Δεν είναι ενεργό το Telegram bot")
    elif path.startswith("/") and not path.startswith("//"):
        target = _phone_url(path)["url"]
    else:
        raise HTTPException(400, "Μόνο σελίδες αυτού του server")
    import qrcode
    import qrcode.image.svg
    img = qrcode.make(target, image_factory=qrcode.image.svg.SvgPathImage, box_size=12, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return Response(buf.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


@app.post("/api/live/mock/{name}")
async def live_mock(name: str):
    """Μόνο με LLM_PROVIDER=mock: τι «βλέπει» το ψεύτικο μοντέλο (π.χ. sample_before, sample_after)."""
    try:
        vision.set_mock_assessment(name)          # η ροή χρησιμοποιεί την αξιολόγηση
        try:
            vision.set_mock_reading(name)         # η παλιά ανάγνωση, αν υπάρχει
        except FileNotFoundError:
            pass
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))
    return {"ok": True, "mock": name}


@app.get("/api/system")
async def system():
    """Για το /dev: τι είναι ρυθμισμένο, τι λείπει και τι να κάνεις γι\' αυτό. Κανένα κλειδί δεν επιστρέφεται."""
    from .tools import REGISTRY
    ref = (config.ROOT / config.VISION_REFERENCE) if config.VISION_REFERENCE else None
    eval_cases = sorted(p.name[: -len(".truth.json")] for p in (config.SHELF_DIR / "eval").glob("*.truth.json"))
    evals = sorted((config.WORKSPACE / "eval").glob("eval_*.json"))
    phone = _phone_url("/tasks")
    def check(ok: bool, text: str, fix: str = "", level: str = "no") -> dict:
        return {"ok": ok, "text": text, "fix": "" if ok else fix, "level": "ok" if ok else level}
    return {
        "shelf_set": config.SHELF_SET or "shelf",
        "vision": {
            "provider": config.vision_provider(), "model": config.vision_model(),
            "prompt": __import__("agentkit.vision.prompts", fromlist=["PROMPT_VERSION"]).PROMPT_VERSION,
            "reference": config.VISION_REFERENCE or None,
            "timeout": config.VISION_TIMEOUT_SECONDS, "max_image_side": config.VISION_MAX_IMAGE_SIDE,
            "media_resolution": config.GEMINI_MEDIA_RESOLUTION or "προεπιλογή μοντέλου",
        },
        "live": {"interval": config.LIVE_INTERVAL_SECONDS, "confirm_frames": config.LIVE_CONFIRM_FRAMES,
                 "diff_threshold": config.LIVE_DIFF_THRESHOLD, "start_agent": config.LIVE_START_AGENT,
                 "frames": live.STATE.frames, "model_calls": live.STATE.model_calls},
        "autonomy": {"auto_order": config.AUTO_ORDER, "max_cases": config.AUTO_ORDER_MAX_CASES,
                     "max_eur": config.AUTO_ORDER_MAX_EUR, "reminder_minutes": config.TASK_REMINDER_MINUTES,
                     "auto_approve_all": config.AUTO_APPROVE},
        "agent": {"provider": config.LLM_PROVIDER, "scenarios": list(SCENARIOS), "tools": sorted(REGISTRY),
                  "runs": len(agent.RUNS)},
        "phone": {"url": phone["url"], "reachable": phone["reachable"], "host": config.HOST,
                  "public_url": config.PUBLIC_URL or None, "telegram": bool(config.TELEGRAM_BOT_TOKEN),
                  "telegram_bot": f"@{telegram.bot_username}" if telegram.bot_username else None,
                  "telegram_subscribers": len(telegram.subscribers())},
        "data": {"eval_cases": eval_cases, "last_eval": evals[-1].name if evals else None},
        "checks": [
            check(config.vision_provider() != "mock", f"Μοντέλο όρασης: {config.vision_model()}",
                  "Βάλε κλειδί Gemini στο .env (OPENAI_COMPAT_* ή VISION_PROVIDER=gemini + GEMINI_API_KEY). "
                  "Με mock το ράφι δεν διαβάζεται πραγματικά.", "mid"),
            check(bool(ref and ref.is_file()), "Φωτογραφία αναφοράς του σωστού ραφιού",
                  "Πάτα «Αυτό είναι το σωστό ράφι» στο /shelf, ή όρισε VISION_REFERENCE στο .env.", "mid"),
            check(len(eval_cases) >= 10, f"Eval set: {len(eval_cases)} περιπτώσεις",
                  "Βάλε 10–15 φωτογραφίες με .truth.json στο data/shelf/eval/ (δες το README εκεί) και τρέξε "
                  "python scripts/eval_vision.py --runs 3.", "mid"),
            check(bool(evals), "Έχει τρέξει eval όρασης",
                  "python scripts/eval_vision.py --runs 3 · στόχος sku_shelf ≥ 90%.", "mid"),
            check(phone["reachable"], f"Το κινητό φτάνει τον server: {phone['url']}",
                  "Βάλε HOST=0.0.0.0 στο .env και ξεκίνα ξανά τον server (ή PUBLIC_URL αν χρησιμοποιείς tunnel).", "mid"),
            check(bool(config.TELEGRAM_BOT_TOKEN), "Telegram για ειδοποιήσεις",
                  "Προαιρετικό: TELEGRAM_BOT_TOKEN στο .env. Χωρίς αυτό οι εργασίες φαίνονται μόνο στις σελίδες.", "mid"),
            check(not config.AUTO_APPROVE, "AUTO_APPROVE=0 (οι μεγάλες παραγγελίες θέλουν έγκριση)",
                  "Με AUTO_APPROVE=1 εγκρίνονται ΟΛΑ χωρίς ερώτηση· άφησέ το 0 στο demo.", "mid"),
        ],
    }


@app.get("/api/portal/orders")
async def portal_orders():
    return portal.orders


def main():
    phone = _phone_url("/tasks")
    print(f"\n  Αρχική:    {config.BASE_URL}\n"
          f"  Ράφι:      {config.BASE_URL}/shelf   (κάμερα, frame κάθε {config.LIVE_INTERVAL_SECONDS}s)\n"
          f"  Κινητό:    {phone['url']}" + ("" if phone["reachable"] else "   (θέλει HOST=0.0.0.0 στο .env)") + "\n"
          f"  Αποθήκη:   {config.BASE_URL}/portal/orders\n"
          f"  Dev:       {config.BASE_URL}/dev\n"
          f"  Μοντέλο:   agent {config.LLM_PROVIDER} · όραση {config.vision_provider()}\n")
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="warning")


if __name__ == "__main__":
    main()
