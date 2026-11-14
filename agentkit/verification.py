"""Second-scan verification sessions: workflow and persistence only. NO vision inference happens here.

Purpose: after the owner accepts or corrects a recommendation (agentkit/recommendations.py), someone moves the
product and takes a second photo. This module records that request and that photo so the vision integration
(not built yet) can later compare them. It never decides whether the move happened.

    INTEGRATION_STATUS = {"vision_integration": "pending", "end_to_end_validation": "pending"}

These two readiness flags are reported in every API response, separately from the session status.

STATES (session.status)
  awaiting_rescan   session started for one exact feedback revision; no second-scan image yet.
  awaiting_vision   at least one second-scan image was received, decoded and stored. It stays here until a genuine
                    result arrives from the future vision integration. A received photo is NOT proof the move was
                    done, and the absence of a vision result is NOT evidence that it failed.
  superseded        the owner's current feedback for the recommendation is no longer the revision this session was
                    started for (a newer submission of any decision, including a new "accepted"). The session is
                    frozen: no further uploads; start a new session for the current revision.

  Transitions implemented:
    (start)          -> awaiting_rescan
    awaiting_rescan  -> awaiting_vision      first valid image upload
    awaiting_vision  -> awaiting_vision      further uploads append attempts (history is never overwritten)
    awaiting_rescan | awaiting_vision -> superseded   detected on the next start/upload/read for that recommendation

  FUTURE outcomes, documented but deliberately NOT reachable (no code path or endpoint sets them, and the database
  CHECK constraint rejects them): verified, not_done, inconclusive. They require a real vision result under a
  contract that has not been agreed yet (see planning/VERIFICATION.md). There is no endpoint where a caller can
  assert an outcome.

RULES
  - Start needs an existing recommendation whose CURRENT feedback decision is "accepted" or "corrected".
    Unknown recommendation -> RecommendationNotFound. No feedback yet / "rejected" -> NotVerifiable.
  - A session is bound to the exact feedback revision (feedback_id + submission_id + decision) current at start.
    The caller may pass expected_feedback_id; if it is not the current revision the start is refused (StaleFeedback).
  - Idempotent start: at most one session per (recommendation_id, feedback_id). Starting again for the same
    revision returns the existing session with created=False; it never creates a duplicate.
  - Idempotent upload: the client sends an upload_id per user action. Same upload_id + same bytes returns the stored
    attempt (duplicate=True); same upload_id + different bytes -> UploadConflict.
  - Images are fully decoded with Pillow (JPEG, PNG or WebP only), limited to MAX_IMAGE_BYTES and MAX_PIXELS, and
    stored under a server-generated filename. The client's filename and content type are ignored. Original bytes
    are kept unchanged (EXIF included) because they are private and vision may need full fidelity.

STORAGE (private, same conventions as agentkit/recommendations.py)
  SQLite at state/verifications.sqlite3; images under state/verification_images/<session_id>/ (sibling of the DB).
  state/ is gitignored and outside every static mount (workspace/ is served at /files). Images are deliberately
  NOT written to workspace/photos: the photo watcher there would start an unrelated agent run.
  Overrides for isolated tests: module attribute DB_PATH or env VERIFICATIONS_DB. Paths inside workspace/ are
  refused (UnsafeStorageLocation). The images directory always follows the DB's directory.

TARGET: resolve_target() / session_target() give the placement to check. Cumulative: start from the immutable
original recommendation and apply every stored feedback row, oldest first, up to and including the session's own
feedback_id, each as a partial patch (apply_placement_patch). accepted, rejected and name/price-only corrections
change nothing and reset nothing; a placement correction replaces only the keys it supplies (null clears to null).
Later feedback is never included. GET responses include it as "target", with provenance per corrected key.

Supersession is checked lazily (on access), because recommendations.record_feedback is not hooked. Between a
feedback change and the next access, a stored session still shows its old status; any read reconciles it first.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sqlite3
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from PIL import Image

from . import recommendations as rec_store

INTEGRATION_STATUS = {"vision_integration": "pending", "end_to_end_validation": "pending"}
STATES = ("awaiting_rescan", "awaiting_vision", "superseded")
OPEN_STATES = ("awaiting_rescan", "awaiting_vision")
FUTURE_OUTCOMES = ("verified", "not_done", "inconclusive")   # documented only; not reachable in this module
VERIFIABLE_DECISIONS = ("accepted", "corrected")

MAX_IMAGE_BYTES = 25_000_000          # same limit as POST /api/shelf/photo in agentkit/server.py
MAX_PIXELS = 50_000_000
MIN_SIDE = 64
FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}   # subset of watchers.PHOTO_TYPES

DB_PATH: Optional[Path] = None
DB_ENV = "VERIFICATIONS_DB"
DEFAULT_DB_RELATIVE = Path("state") / "verifications.sqlite3"
IMAGES_DIRNAME = "verification_images"

_SESSION_ID = re.compile(r"^vs_[0-9a-f]{32}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")     # same shape as recommendations._ID

_SCHEMA = """
create table if not exists sessions (
    session_id              text primary key,
    recommendation_id       text not null,
    feedback_id             integer not null,
    feedback_submission_id  text not null,
    feedback_decision       text not null check (feedback_decision in ('accepted', 'corrected')),
    original_image_ref_json text,
    status                  text not null check (status in ('awaiting_rescan', 'awaiting_vision', 'superseded')),
    superseded_by_feedback_id integer,
    superseded_reason       text,
    created_at              text not null,
    updated_at              text not null,
    unique (recommendation_id, feedback_id)
);
create table if not exists scan_attempts (
    attempt_id    integer primary key autoincrement,
    session_id    text not null references sessions(session_id),
    attempt_no    integer not null,
    upload_id     text not null,
    image_file    text not null,
    sha256        text not null,
    format        text not null,
    width         integer not null,
    height        integer not null,
    bytes         integer not null,
    vision_status text not null check (vision_status = 'pending'),
    received_at   text not null,
    unique (session_id, attempt_no),
    unique (session_id, upload_id)
);
"""


class VerificationError(Exception):
    pass


class UnsafeStorageLocation(VerificationError):
    pass


class SessionNotFound(VerificationError, LookupError):
    pass


class NotVerifiable(VerificationError):
    """The recommendation has no owner decision yet, or the current decision is 'rejected'."""


class StaleFeedback(VerificationError):
    """expected_feedback_id is not the recommendation's current feedback revision."""


class SessionClosed(VerificationError):
    """The session is superseded; it accepts no further uploads."""


class UploadConflict(VerificationError):
    """upload_id was already used for different image bytes."""


class InvalidRequest(VerificationError, ValueError):
    pass


class InvalidImage(VerificationError, ValueError):
    pass


class ImageTooLarge(VerificationError, ValueError):
    pass


# --- storage -------------------------------------------------------------------

def default_db_path() -> Path:
    from . import config
    return config.ROOT / DEFAULT_DB_RELATIVE


def db_path() -> Path:
    from . import config
    if DB_PATH is not None:
        path = Path(DB_PATH)
    elif os.environ.get(DB_ENV, "").strip():
        path = Path(os.environ[DB_ENV].strip())
    else:
        path = default_db_path()
    resolved = path.expanduser().resolve()
    public = config.WORKSPACE.resolve()
    if resolved == public or public in resolved.parents:
        raise UnsafeStorageLocation(f"verification store must not be inside {public} (served at /files)")
    return resolved


def images_dir() -> Path:
    return db_path().parent / IMAGES_DIRNAME


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys = on")
    con.executescript(_SCHEMA)
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


# --- image validation ------------------------------------------------------------

def decode_image(data: bytes) -> dict:
    """Fully decode the bytes. Returns format/width/height/sha256; raises InvalidImage or ImageTooLarge."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        raise InvalidImage("empty upload")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageTooLarge(f"image is larger than {MAX_IMAGE_BYTES} bytes")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as im:
                fmt = im.format
                width, height = im.size
                if fmt not in FORMATS:
                    raise InvalidImage(f"unsupported image format {fmt!r} (allowed: JPEG, PNG, WebP)")
                if width * height > MAX_PIXELS:
                    raise ImageTooLarge(f"image has more than {MAX_PIXELS} pixels")
                if min(width, height) < MIN_SIDE:
                    raise InvalidImage(f"image is smaller than {MIN_SIDE} px on a side")
                im.load()                                    # full decode: truncated/corrupt data fails here
    except (InvalidImage, ImageTooLarge):
        raise
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageTooLarge(f"image has more than {MAX_PIXELS} pixels") from None
    except Exception as e:                                   # PIL raises several types for bad data
        raise InvalidImage(f"not a decodable image: {type(e).__name__}") from None
    return {"format": fmt, "width": width, "height": height, "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data)}


# --- helpers -----------------------------------------------------------------------

def _check_session_id(session_id: Any) -> str:
    if not isinstance(session_id, str) or not _SESSION_ID.match(session_id):
        raise SessionNotFound(f"unknown verification session: {session_id}")
    return session_id


def _current_feedback(recommendation_id: str) -> tuple[dict, Optional[dict]]:
    """(recommendation record, current feedback or None). Raises rec_store.RecommendationNotFound."""
    rec = rec_store.get_recommendation(recommendation_id)
    return rec, rec["current_feedback"]


def _reconcile(con: sqlite3.Connection, recommendation_id: str, current: Optional[dict]) -> None:
    """Mark every open session of this recommendation whose revision is no longer current as superseded."""
    current_id = current["feedback_id"] if current else None
    rows = con.execute("select session_id, feedback_id from sessions where recommendation_id = ? and status in (?, ?)",
                       (recommendation_id, *OPEN_STATES)).fetchall()
    for row in rows:
        if row["feedback_id"] != current_id:
            if current is None:
                reason = "the feedback this session was started for is no longer present"
            else:
                reason = (f"owner feedback changed after the session started (now feedback_id {current_id}, "
                          f"decision '{current['decision']}'); not applied to the revised decision")
            con.execute("update sessions set status = 'superseded', superseded_by_feedback_id = ?, "
                        "superseded_reason = ?, updated_at = ? where session_id = ?",
                        (current_id, reason, _now(), row["session_id"]))


def _attempt_row(row: sqlite3.Row, session_id: str) -> dict:
    return {
        "attempt_no": row["attempt_no"],
        "upload_id": row["upload_id"],
        "image_ref": {"store": IMAGES_DIRNAME, "path": f"{session_id}/{row['image_file']}"},
        "sha256": row["sha256"],
        "format": row["format"],
        "width": row["width"],
        "height": row["height"],
        "bytes": row["bytes"],
        "received_at": row["received_at"],
        "vision_status": row["vision_status"],       # always "pending": no vision call is made anywhere here
    }


def _session_view(con: sqlite3.Connection, session_id: str) -> dict:
    row = con.execute("select * from sessions where session_id = ?", (session_id,)).fetchone()
    if row is None:
        raise SessionNotFound(f"unknown verification session: {session_id}")
    attempts = [_attempt_row(a, session_id) for a in con.execute(
        "select * from scan_attempts where session_id = ? order by attempt_no", (session_id,))]
    return {
        "session_id": row["session_id"],
        "status": row["status"],
        "recommendation_id": row["recommendation_id"],
        "feedback": {"feedback_id": row["feedback_id"], "submission_id": row["feedback_submission_id"],
                     "decision": row["feedback_decision"]},
        "original_image_ref": json.loads(row["original_image_ref_json"]) if row["original_image_ref_json"] else None,
        "superseded": None if row["status"] != "superseded" else {
            "by_feedback_id": row["superseded_by_feedback_id"], "reason": row["superseded_reason"]},
        "scan_attempts": attempts,
        "latest_attempt_no": attempts[-1]["attempt_no"] if attempts else None,
        "vision_result": None,                       # no vision integration exists yet; never fabricated
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        **INTEGRATION_STATUS,
    }


# --- public API ---------------------------------------------------------------------

def start_session(recommendation_id: Any, expected_feedback_id: Any = None) -> dict:
    """Start (or return the existing) session for the recommendation's current accepted/corrected feedback."""
    if not isinstance(recommendation_id, str) or not _ID.match(recommendation_id):
        raise InvalidRequest("recommendation_id must be 1-128 characters of A-Z a-z 0-9 . _ : -")
    if expected_feedback_id is not None and (isinstance(expected_feedback_id, bool)
                                             or not isinstance(expected_feedback_id, int)):
        raise InvalidRequest("expected_feedback_id must be an integer or null")
    rec, current = _current_feedback(recommendation_id)          # RecommendationNotFound propagates
    con = _connect()
    try:
        con.execute("begin immediate")
        _reconcile(con, recommendation_id, current)
        if current is None:
            con.execute("commit")
            raise NotVerifiable(f"recommendation {recommendation_id} has no owner decision yet")
        if expected_feedback_id is not None and expected_feedback_id != current["feedback_id"]:
            con.execute("commit")
            raise StaleFeedback(f"feedback_id {expected_feedback_id} is not the current revision "
                                f"({current['feedback_id']}) of recommendation {recommendation_id}")
        if current["decision"] not in VERIFIABLE_DECISIONS:
            con.execute("commit")
            raise NotVerifiable(f"current owner decision for {recommendation_id} is '{current['decision']}'; "
                                "only accepted or corrected recommendations can be verified")
        existing = con.execute("select session_id from sessions where recommendation_id = ? and feedback_id = ?",
                               (recommendation_id, current["feedback_id"])).fetchone()
        if existing is not None:
            con.execute("commit")
            return {**_session_view(con, existing["session_id"]), "created": False}
        session_id = f"vs_{uuid.uuid4().hex}"
        image_ref = rec["recommendation"].get("image_ref")
        now = _now()
        con.execute("insert into sessions (session_id, recommendation_id, feedback_id, feedback_submission_id, "
                    "feedback_decision, original_image_ref_json, status, created_at, updated_at) "
                    "values (?, ?, ?, ?, ?, ?, 'awaiting_rescan', ?, ?)",
                    (session_id, recommendation_id, current["feedback_id"], current["submission_id"],
                     current["decision"], rec_store._canonical(image_ref) if image_ref is not None else None, now, now))
        con.execute("commit")
        return {**_session_view(con, session_id), "created": True}
    except BaseException:
        if con.in_transaction:
            con.execute("rollback")
        raise
    finally:
        con.close()


def _reconcile_session(session_id: str) -> None:
    con = _connect()
    try:
        row = con.execute("select recommendation_id from sessions where session_id = ?", (session_id,)).fetchone()
        if row is None:
            raise SessionNotFound(f"unknown verification session: {session_id}")
        rec_id = row["recommendation_id"]
    finally:
        con.close()
    try:
        _, current = _current_feedback(rec_id)
    except rec_store.RecommendationNotFound:
        current = None
    con = _connect()
    try:
        con.execute("begin immediate")
        _reconcile(con, rec_id, current)
        con.execute("commit")
    except BaseException:
        if con.in_transaction:
            con.execute("rollback")
        raise
    finally:
        con.close()


def _copy(value: Any) -> Any:
    return json.loads(json.dumps(value))


def apply_placement_patch(placement: dict, feedback: dict) -> tuple[dict, list[str]]:
    """Pure: apply ONE feedback row to an effective placement {"to", "from"}. Returns (new placement, changed keys).

    Inputs are never modified; the result is a copy.
      accepted / rejected / corrected without correction.placement -> unchanged (no reset of earlier corrections).
      corrected with correction.placement -> per side ("to", "from") supplied as an object, ONLY the keys in it are
        replaced; a key supplied as null is cleared to null (explicit unknown). Keys not supplied keep their current
        value. A side that is absent or null is treated as not supplied (see planning/VERIFICATION.md).
    """
    result = {side: _copy(placement.get(side)) if isinstance(placement.get(side), dict) else None
              for side in ("to", "from")}
    changed: list[str] = []
    correction = feedback.get("correction") if feedback.get("decision") == "corrected" else None
    patch = (correction or {}).get("placement")
    if isinstance(patch, dict):
        for side in ("to", "from"):
            fields = patch.get(side)
            if not isinstance(fields, dict):
                continue
            merged = dict(result[side] or {})
            for key, value in fields.items():
                merged[key] = _copy(value)
                changed.append(f"{side}.{key}")
            result[side] = merged
    return result, sorted(changed)


def resolve_target(recommendation: dict, feedback_history: list[dict], feedback_id: int) -> dict:
    """Pure: the placement a second scan should be checked against, for the session's feedback revision.

    Starts from the immutable original recommendation.placement and applies every stored feedback row in
    chronological order (feedback_id ascending) up to AND INCLUDING feedback_id, each as a partial patch
    (apply_placement_patch). Feedback recorded after feedback_id is never included. The revision itself must be
    "accepted" or "corrected" (else ValueError); an earlier "rejected" row changes nothing and resets nothing.
    Nothing is guessed or filled in. Inputs are never modified.

    Returns copies: {"to", "from", "corrected_fields", "basis", "provenance"} where
      corrected_fields        every key whose effective value came from an owner correction, not the original;
      provenance.field_sources  {key: feedback_id of the correction that last set it};
      provenance.placement_feedback_ids  revisions that supplied at least one effective placement key;
      provenance.considered_feedback_ids every revision processed (original + these = the full derivation).
    """
    rows = sorted(feedback_history, key=lambda f: f["feedback_id"])
    target = next((f for f in rows if f["feedback_id"] == feedback_id), None)
    if target is None:
        raise LookupError(f"feedback {feedback_id} is not in the recommendation's history")
    if target.get("decision") not in VERIFIABLE_DECISIONS:
        raise ValueError(f"decision {target.get('decision')!r} is not verifiable")
    original = recommendation.get("placement") or {}
    placement = {side: original.get(side) for side in ("to", "from")}
    sources: dict[str, int] = {}
    considered: list[int] = []
    for row in rows:
        if row["feedback_id"] > feedback_id:
            break
        placement, changed = apply_placement_patch(placement, row)
        for key in changed:
            sources[key] = row["feedback_id"]
        considered.append(row["feedback_id"])
    return {
        "to": placement["to"],
        "from": placement["from"],
        "corrected_fields": sorted(sources),
        "basis": {"recommendation_id": recommendation.get("recommendation_id"),
                  "feedback_id": feedback_id, "decision": target["decision"]},
        "provenance": {"considered_feedback_ids": considered,
                       "placement_feedback_ids": sorted(set(sources.values())),
                       "field_sources": dict(sorted(sources.items()))},
    }


def session_target(session_id: Any) -> dict:
    """resolve_target() for the session's OWN feedback revision: the stored history up to that exact feedback_id,
    never feedback recorded after it (so a superseded session keeps the target it was started for)."""
    _check_session_id(session_id)
    con = _connect()
    try:
        row = con.execute("select recommendation_id, feedback_id from sessions where session_id = ?",
                          (session_id,)).fetchone()
    finally:
        con.close()
    if row is None:
        raise SessionNotFound(f"unknown verification session: {session_id}")
    rec = rec_store.get_recommendation(row["recommendation_id"])
    try:
        return resolve_target(rec["recommendation"], rec["feedback_history"], row["feedback_id"])
    except LookupError:
        raise SessionNotFound(f"feedback {row['feedback_id']} of session {session_id} is no longer stored") from None


def get_session(session_id: Any) -> dict:
    """Current state of a session, after reconciling it with the owner's current feedback.
    Includes "target": the placement resolved from the original recommendation and the session's own feedback."""
    _check_session_id(session_id)
    _reconcile_session(session_id)
    con = _connect()
    try:
        view = _session_view(con, session_id)
    finally:
        con.close()
    return {**view, "target": session_target(session_id)}


def add_scan(session_id: Any, upload_id: Any, data: bytes) -> dict:
    """Validate and store one second-scan image as a new attempt. Returns the session view plus "attempt"
    and "duplicate". Never calls vision; the session goes to (or stays in) awaiting_vision."""
    _check_session_id(session_id)
    if not isinstance(upload_id, str) or not _ID.match(upload_id):
        raise InvalidRequest("upload_id must be 1-128 characters of A-Z a-z 0-9 . _ : -")
    info = decode_image(data)                            # validate before touching the store
    _reconcile_session(session_id)
    con = _connect()
    written: Optional[Path] = None
    try:
        con.execute("begin immediate")
        session = con.execute("select status from sessions where session_id = ?", (session_id,)).fetchone()
        if session is None:
            raise SessionNotFound(f"unknown verification session: {session_id}")
        prior = con.execute("select * from scan_attempts where session_id = ? and upload_id = ?",
                            (session_id, upload_id)).fetchone()
        if prior is not None:
            con.execute("rollback")
            if prior["sha256"] != info["sha256"]:
                raise UploadConflict(f"upload_id {upload_id} was already used for a different image")
            return {**_session_view(con, session_id), "attempt": _attempt_row(prior, session_id), "duplicate": True}
        if session["status"] not in OPEN_STATES:
            con.execute("rollback")
            raise SessionClosed(f"session {session_id} is {session['status']}; start a new session for the "
                                "current owner decision")
        attempt_no = con.execute("select coalesce(max(attempt_no), 0) + 1 from scan_attempts where session_id = ?",
                                 (session_id,)).fetchone()[0]
        filename = f"scan_{attempt_no:03d}_{uuid.uuid4().hex[:12]}{FORMATS[info['format']]}"
        folder = images_dir() / session_id
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = folder / f".{filename}.tmp"
        tmp.write_bytes(bytes(data))
        os.replace(tmp, folder / filename)
        written = folder / filename
        now = _now()
        con.execute("insert into scan_attempts (session_id, attempt_no, upload_id, image_file, sha256, format, width, "
                    "height, bytes, vision_status, received_at) values (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)",
                    (session_id, attempt_no, upload_id, filename, info["sha256"], info["format"], info["width"],
                     info["height"], info["bytes"], now))
        con.execute("update sessions set status = 'awaiting_vision', updated_at = ? where session_id = ?",
                    (now, session_id))
        con.execute("commit")
        written = None
        attempt = con.execute("select * from scan_attempts where session_id = ? and attempt_no = ?",
                              (session_id, attempt_no)).fetchone()
        return {**_session_view(con, session_id), "attempt": _attempt_row(attempt, session_id), "duplicate": False}
    except BaseException:
        if con.in_transaction:
            con.execute("rollback")
        if written is not None:
            written.unlink(missing_ok=True)
        raise
    finally:
        con.close()


def scan_image_path(session_id: str, attempt_no: int) -> Path:
    """Private, in-process access to a stored second-scan image (for the future vision integration)."""
    _check_session_id(session_id)
    con = _connect()
    try:
        row = con.execute("select image_file from scan_attempts where session_id = ? and attempt_no = ?",
                          (session_id, attempt_no)).fetchone()
    finally:
        con.close()
    if row is None:
        raise SessionNotFound(f"no scan attempt {attempt_no} in session {session_id}")
    return images_dir() / session_id / row["image_file"]
