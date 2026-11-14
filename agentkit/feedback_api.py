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
    return JSONResponse(row, status_code=200 if row["duplicate"] else 201)
