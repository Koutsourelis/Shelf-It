"""HTTP API for owner feedback on recommendations. Storage and the contract are in agentkit/recommendations.py.

    GET  /api/recommendations/{id}            original recommendation, feedback history, current decision
    POST /api/recommendations/{id}/feedback   {"submission_id", "decision", "correction"?, "note"?, "decided_by"?}

Errors: 404 unknown recommendation, 409 submission_id reused with a different body, 422 invalid request.
Recommendations are registered by the producer in code (register_recommendation), not over this API.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from . import events
from . import recommendations as store

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


@router.get("/{recommendation_id}")
async def get_recommendation(recommendation_id: str):
    try:
        return await asyncio.to_thread(store.get_recommendation, recommendation_id)
    except store.RecommendationNotFound as e:
        raise HTTPException(404, str(e))


@router.post("/{recommendation_id}/feedback")
async def post_feedback(recommendation_id: str, request: Request):
    try:
        body = json.loads(await request.body() or b"null")
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(422, "request body must be valid JSON")
    try:
        row = await asyncio.to_thread(store.record_feedback, recommendation_id, body)
    except store.RecommendationNotFound as e:
        raise HTTPException(404, str(e))
    except store.FeedbackConflict as e:
        raise HTTPException(409, str(e))
    except store.ContractError as e:
        raise HTTPException(422, str(e))
    if not row["duplicate"]:
        events.emit("system", "recommendation_feedback", recommendation_id=recommendation_id,
                    decision=row["decision"], feedback_id=row["feedback_id"])
        from . import tasks
        await asyncio.to_thread(tasks.update_proposal_feedback, recommendation_id, decision=row["decision"])
    return JSONResponse(row, status_code=200 if row["duplicate"] else 201)


def _local_talker_art(theme: str) -> bytes:
    """Καθαρό διακοσμητικό φόντο (1024x768) όταν δεν έχει οριστεί FAL_KEY στο .env, ώστε το UI να παράγει PNG και offline."""
    import io
    from PIL import Image, ImageDraw
    palettes = {
        "fresh": ((26, 94, 72), (54, 148, 112), (218, 242, 230)),
        "warm": ((138, 72, 32), (196, 118, 58), (248, 232, 212)),
        "minimal": ((34, 48, 62), (72, 98, 124), (226, 234, 242)),
    }
    dark, mid, soft = palettes.get(theme, palettes["fresh"])
    W, H = 1024, 768
    img = Image.new("RGB", (W, H), dark)
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / max(H - 1, 1)
        r = round(dark[0] * (1 - t) + mid[0] * t)
        g = round(dark[1] * (1 - t) + mid[1] * t)
        b = round(dark[2] * (1 - t) + mid[2] * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))
    draw.ellipse((-120, -140, 440, 420), fill=mid)
    draw.ellipse((640, 340, 1180, 880), fill=soft)
    draw.ellipse((700, 400, 1120, 820), fill=mid)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


async def build_talker_for_recommendation(recommendation_id: str, theme: str = "fresh") -> dict:
    """Δημιουργεί PNG ταμπελάκι (fal αν υπάρχει FAL_KEY, αλλιώς τοπικά μέσω Pillow) και ενημερώνει το proposal."""
    import os
    from . import config, shelf_talker as st, tasks
    if theme not in st.THEMES:
        theme = "fresh"
    try:
        conf, missing, summary = await asyncio.to_thread(st.confirmed_inputs, recommendation_id)
    except st.TalkerError as e:
        raise HTTPException(404 if e.status == "not_found" else 422, e.message)
    if conf is None:
        raise HTTPException(409, {"message": "Χρειάζεται πρώτα επιβεβαίωση ονόματος και τιμής.", "missing": missing, "summary": summary})

    if os.environ.get("FAL_KEY", "").strip():
        res = await st.generate(recommendation_id, conf.product_name, float(conf.amount), conf.currency, theme)
        if res.get("status") != "generated":
            raise HTTPException(502, res.get("message") or res.get("status") or "fal error")
        rel = res["file"].removeprefix("workspace/")
        await asyncio.to_thread(tasks.update_proposal_feedback, recommendation_id, talker_file=rel, talker_source="fal")
        return {"status": "generated", "source": "fal", "file": rel, "price_text": res["price_text"]}

    def _build_local() -> dict:
        art = _local_talker_art(theme)
        p_txt = st.price_text(conf.amount, conf.currency)
        img = st.render(art, conf.product_name, p_txt)
        tid = st.talker_id(conf, theme)
        rel = f"talkers/talker_{tid}_local.png"
        out_path = config.WORKSPACE / rel
        st._write_png(img, out_path)
        tasks.update_proposal_feedback(recommendation_id, talker_file=rel, talker_source="local")
        return {"status": "generated", "source": "local", "file": rel, "price_text": p_txt}

    return await asyncio.to_thread(_build_local)


@router.post("/{recommendation_id}/talker")
async def create_talker(recommendation_id: str, request: Request):
    """Δημιουργεί εκτυπώσιμο PNG ταμπελάκι για πρόταση με επιβεβαιωμένο όνομα & τιμή (fal αν υπάρχει FAL_KEY, αλλιώς τοπικά)."""
    raw = await request.body()
    try:
        body = json.loads(raw or b"{}") if raw else {}
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(422, "request body must be valid JSON")
    theme = (body.get("theme") or "fresh") if isinstance(body, dict) else "fresh"
    return await build_talker_for_recommendation(recommendation_id, theme)
