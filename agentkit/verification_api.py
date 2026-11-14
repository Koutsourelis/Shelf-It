"""HTTP API for second-scan verification sessions. Workflow and storage: agentkit/verification.py.

    POST /api/verifications                     JSON {"recommendation_id": str, "expected_feedback_id"?: int}
                                                201 new session, 200 existing session for the same feedback revision
    GET  /api/verifications/{session_id}        current state (reconciled with the owner's current feedback)
    POST /api/verifications/{session_id}/scans  multipart: file=<image>, upload_id=<client key per user action>
                                                201 stored new attempt, 200 retry of the same upload_id

Errors: 404 unknown recommendation/session; 409 rejected/no decision, stale feedback, superseded session,
upload_id reused for other bytes; 413 image too large; 422 invalid request or undecodable image.

There is deliberately no endpoint that accepts a verification outcome: no caller can assert "verified".
Every response carries vision_integration: "pending" and end_to_end_validation: "pending".
This router does not touch POST /api/shelf/photo, does not write to workspace/photos and starts no agent run.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from . import recommendations as rec_store
from . import verification as vs

router = APIRouter(prefix="/api/verifications", tags=["verifications"])

_START_KEYS = {"recommendation_id", "expected_feedback_id"}


def _http(e: Exception) -> HTTPException:
    if isinstance(e, (rec_store.RecommendationNotFound, vs.SessionNotFound)):
        return HTTPException(404, str(e))
    if isinstance(e, (vs.NotVerifiable, vs.StaleFeedback, vs.SessionClosed, vs.UploadConflict)):
        return HTTPException(409, str(e))
    if isinstance(e, vs.ImageTooLarge):
        return HTTPException(413, str(e))
    if isinstance(e, (vs.InvalidRequest, vs.InvalidImage)):
        return HTTPException(422, str(e))
    raise e


@router.post("")
async def start(request: Request):
    try:
        body = json.loads(await request.body() or b"null")
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(422, "request body must be valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(422, "request body must be a JSON object")
    unknown = sorted(set(body) - _START_KEYS)
    if unknown:
        raise HTTPException(422, f"unknown fields: {', '.join(unknown)}")
    try:
        session = await asyncio.to_thread(vs.start_session, body.get("recommendation_id"),
                                          body.get("expected_feedback_id"))
    except Exception as e:
        raise _http(e)
    return JSONResponse(session, status_code=201 if session["created"] else 200)


@router.get("/{session_id}")
async def read(session_id: str):
    try:
        return await asyncio.to_thread(vs.get_session, session_id)
    except Exception as e:
        raise _http(e)


@router.post("/{session_id}/scans")
async def upload_scan(session_id: str, file: UploadFile = File(...), upload_id: str = Form(...)):
    data = await file.read(vs.MAX_IMAGE_BYTES + 1)      # never read more than the limit + 1 byte
    try:
        result = await asyncio.to_thread(vs.add_scan, session_id, upload_id, data)
    except Exception as e:
        raise _http(e)
    return JSONResponse(result, status_code=200 if result["duplicate"] else 201)
