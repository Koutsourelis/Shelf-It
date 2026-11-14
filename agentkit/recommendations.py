"""Recommendation store: product-placement recommendations from the agent, and the owner's feedback on them.

Storage: SQLite (Python's built-in sqlite3, one transaction per write) at state/recommendations.sqlite3.
  - state/ is private runtime data: gitignored, and outside every static-file mount. In particular it is NOT
    under workspace/, which the server publishes at /files. SQLite's sidecar files (-journal, -wal, -shm) are
    created next to the database, so they stay in state/ too.
  - It is separate from data/demo.duckdb, so /api/demo/reset does not touch it.
  - Overrides, for isolated tests or a different machine layout: set the module attribute DB_PATH, or the
    environment variable RECOMMENDATIONS_DB. db_path() refuses any location inside workspace/.
  - Earlier drafts defaulted to workspace/recommendations.sqlite3. Nothing migrates it automatically; if
    such a file exists, move it to state/ by hand (db_path() never reads or deletes it).

Nothing here creates recommendations on its own. A producer (the agent team's code) calls
register_recommendation() with a real, structured recommendation. Owner feedback arrives over HTTP
(agentkit/feedback_api.py) and is appended next to it; the original recommendation is never modified.

PROVISIONAL PRODUCER CONTRACT (version "0-provisional", to be confirmed with the agent team)
------------------------------------------------------------------------------------------
Required, non-null:
  recommendation_id  str, 1-128 chars of [A-Za-z0-9._:-], starting with a letter or digit. Chosen by the
                     producer and stable: the same recommendation is always registered with the same ID.
  product            object with a non-empty "sku" and/or "name" (str). Which one identifies the product is
                     the producer's call; the store never looks it up or fills it in.
  placement.to       object with at least one non-null value (e.g. shelf, position, level, point, box_2d).
                     The target is what the owner accepts, rejects or corrects.
Optional (absent or null = unknown; never filled in here):
  run_id, kind, reason          str
  placement.from                object
  price                         object: {"amount": number > 0, "currency": "EUR", "source": str}.
                                amount, currency and source go together; amount null = price unknown.
  image_ref                     object, e.g. {"photo": "workspace/photos/...", "annotated": ...}
  evidence and any other keys   kept as given (the contract is provisional)
The payload is stored exactly as received. Re-registering the same ID with identical content is a no-op;
with different content it is rejected (RecommendationConflict), never overwritten.

FEEDBACK (one row per submission, append-only)
  submission_id  str, required, chosen by the client per user action. Retrying with the same submission_id
                 and the same body returns the stored row instead of adding a new one; the same
                 submission_id with a different body is rejected.
  decision       "accepted" | "rejected" | "corrected"
  correction     required non-empty object for "corrected", must be absent/null otherwise. Allowed keys:
                 product, price, placement (same shapes as above). Stored with correction_source
                 "owner_input": it is what the owner said, not something vision observed.
  note, decided_by  optional str
  received_at    set by the server (UTC), never taken from the client.
Several distinct submissions are allowed (the owner may change their mind); the latest one is the current
decision and the earlier ones stay in the history.

OPEN INTEGRATION QUESTIONS (agent team / UI / vision)
  - How the agent issues recommendation_id, and whether one run can produce several recommendations.
  - Whether product identity is always a catalog sku, or a free label when vision returns sku null.
  - Who confirms a price and how it reaches price.source (owner input, evidence pack, catalog).
  - Exact shape of placement (shelf/position/level vs. box_2d/point on the 0-1000 scale).
  - Whether a correction should be allowed to change the product, or only the target placement.
  - Whether demo reset should also clear this store (today it does not, by design).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

CONTRACT_VERSION = "0-provisional"
DECISIONS = ("accepted", "rejected", "corrected")
CORRECTION_KEYS = ("product", "price", "placement")
FEEDBACK_KEYS = {"submission_id", "decision", "correction", "note", "decided_by"}
MAX_PAYLOAD_BYTES = 64_000
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")

DB_PATH: Optional[Path] = None      # None = $RECOMMENDATIONS_DB, else state/recommendations.sqlite3
DB_ENV = "RECOMMENDATIONS_DB"
DEFAULT_DB_RELATIVE = Path("state") / "recommendations.sqlite3"   # relative to the repo root

_SCHEMA = """
create table if not exists recommendations (
    recommendation_id text primary key,
    contract_version  text not null,
    payload_json      text not null,
    payload_sha256    text not null,
    registered_at     text not null
);
create table if not exists feedback (
    feedback_id        integer primary key autoincrement,
    recommendation_id  text not null references recommendations(recommendation_id),
    submission_id      text not null,
    decision           text not null check (decision in ('accepted', 'rejected', 'corrected')),
    correction_json    text,
    correction_source  text check (correction_source is null or correction_source = 'owner_input'),
    note               text,
    decided_by         text,
    request_sha256     text not null,
    received_at        text not null,
    unique (recommendation_id, submission_id)
);
"""


class RecommendationError(Exception):
    """Base class for the errors below."""


class ContractError(RecommendationError, ValueError):
    """The recommendation or the feedback does not match the contract."""


class RecommendationNotFound(RecommendationError, LookupError):
    pass


class RecommendationConflict(RecommendationError):
    """The recommendation ID is already registered with different content."""


class FeedbackConflict(RecommendationError):
    """The submission_id was already used for a different feedback body."""


# --- storage ---------------------------------------------------------------

class UnsafeStorageLocation(RecommendationError):
    """The database path is inside a publicly served directory."""


def default_db_path() -> Path:
    from . import config
    return config.ROOT / DEFAULT_DB_RELATIVE


def db_path() -> Path:
    """Where the store lives: DB_PATH, else $RECOMMENDATIONS_DB, else state/recommendations.sqlite3.

    Raises UnsafeStorageLocation if the result is inside workspace/ (served at /files).
    """
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
        raise UnsafeStorageLocation(f"recommendation database must not be inside {public} (served at /files)")
    return resolved


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=10, isolation_level=None)   # explicit transactions below
    con.row_factory = sqlite3.Row
    con.execute("pragma foreign_keys = on")
    con.executescript(_SCHEMA)
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _canonical(obj: Any) -> str:
    try:
        return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as e:
        raise ContractError(f"not valid JSON data: {e}") from None


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# --- validation ------------------------------------------------------------

def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def _check_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _ID.match(value):
        raise ContractError(f"{field} must be 1-128 characters of A-Z a-z 0-9 . _ : - (starting with a letter or digit)")
    return value


def _check_optional_str(obj: dict, key: str, where: str, max_len: int = 2000) -> None:
    value = obj.get(key)
    if value is not None and (not isinstance(value, str) or len(value) > max_len):
        raise ContractError(f"{where}{key} must be a string of at most {max_len} characters, or null")


def _check_product(product: Any, where: str) -> None:
    if not isinstance(product, dict):
        raise ContractError(f"{where}product must be an object")
    for key in ("sku", "name"):
        if product.get(key) is not None and not isinstance(product[key], str):
            raise ContractError(f"{where}product.{key} must be a string or null")
    if not (_nonempty_str(product.get("sku")) or _nonempty_str(product.get("name"))):
        raise ContractError(f"{where}product needs a non-empty sku or name")


def _check_price(price: Any, where: str) -> None:
    if not isinstance(price, dict):
        raise ContractError(f"{where}price must be an object or null")
    amount = price.get("amount")
    if amount is None:
        return                                        # price unknown; nothing else to check
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount <= 0:
        raise ContractError(f"{where}price.amount must be a number greater than 0, or null if unknown")
    if not isinstance(price.get("currency"), str) or not _CURRENCY.match(price["currency"]):
        raise ContractError(f"{where}price.currency must be a 3-letter ISO code (e.g. EUR) when amount is given")
    if not _nonempty_str(price.get("source")):
        raise ContractError(f"{where}price.source must say where the price came from when amount is given")


def _check_spot(spot: Any, where: str) -> None:
    if not isinstance(spot, dict) or not any(v is not None for v in spot.values()):
        raise ContractError(f"{where} must be an object with at least one non-null value")
    for key in ("shelf", "position"):
        value = spot.get(key)
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 1):
            raise ContractError(f"{where}.{key} must be an integer of 1 or more, or null")


def validate_recommendation(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise ContractError("recommendation must be a JSON object")
    _check_id(payload.get("recommendation_id"), "recommendation_id")
    if "product" not in payload or payload["product"] is None:
        raise ContractError("product is required")
    _check_product(payload["product"], "")
    placement = payload.get("placement")
    if not isinstance(placement, dict):
        raise ContractError("placement is required and must be an object")
    if placement.get("to") is None:
        raise ContractError("placement.to is required")
    _check_spot(placement["to"], "placement.to")
    if placement.get("from") is not None:
        _check_spot(placement["from"], "placement.from")
    if payload.get("price") is not None:
        _check_price(payload["price"], "")
    if payload.get("image_ref") is not None and not isinstance(payload["image_ref"], dict):
        raise ContractError("image_ref must be an object or null")
    for key in ("run_id", "kind", "reason"):
        _check_optional_str(payload, key, "")
    if len(_canonical(payload).encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ContractError(f"recommendation is larger than {MAX_PAYLOAD_BYTES} bytes")
    return payload


def validate_feedback(body: Any) -> dict:
    if not isinstance(body, dict):
        raise ContractError("feedback must be a JSON object")
    unknown = sorted(set(body) - FEEDBACK_KEYS)
    if unknown:
        raise ContractError(f"unknown feedback fields: {', '.join(unknown)}")
    _check_id(body.get("submission_id"), "submission_id")
    decision = body.get("decision")
    if decision not in DECISIONS:
        raise ContractError(f"decision must be one of: {', '.join(DECISIONS)}")
    correction = body.get("correction")
    if decision == "corrected":
        if not isinstance(correction, dict) or not correction:
            raise ContractError("decision 'corrected' needs a non-empty correction object")
        unknown = sorted(set(correction) - set(CORRECTION_KEYS))
        if unknown:
            raise ContractError(f"unknown correction fields: {', '.join(unknown)} (allowed: {', '.join(CORRECTION_KEYS)})")
        if all(v is None for v in correction.values()):
            raise ContractError("correction must change at least one of: " + ", ".join(CORRECTION_KEYS))
        if correction.get("product") is not None:
            _check_product(correction["product"], "correction.")
        if correction.get("price") is not None:
            _check_price(correction["price"], "correction.")
            if correction["price"].get("amount") is None:
                raise ContractError("correction.price.amount is required when correcting the price")
        if correction.get("placement") is not None:
            placement = correction["placement"]
            if not isinstance(placement, dict) or (placement.get("to") is None and placement.get("from") is None):
                raise ContractError("correction.placement needs a 'to' or 'from' object")
            for side in ("to", "from"):
                if placement.get(side) is not None:
                    _check_spot(placement[side], f"correction.placement.{side}")
            unknown = sorted(set(placement) - {"to", "from"})
            if unknown:
                raise ContractError(f"unknown correction.placement fields: {', '.join(unknown)}")
    elif correction is not None:
        raise ContractError(f"decision '{decision}' must not include a correction")
    _check_optional_str(body, "note", "")
    _check_optional_str(body, "decided_by", "", max_len=128)
    return body


# --- public API ------------------------------------------------------------

def register_recommendation(payload: dict) -> dict:
    """Persist a structured recommendation from the producer. Returns the stored record plus "created".

    Idempotent for identical content; raises RecommendationConflict if the ID exists with other content.
    """
    validate_recommendation(payload)
    rec_id = payload["recommendation_id"]
    text = _canonical(payload)
    digest = _sha(text)
    con = _connect()
    try:
        con.execute("begin immediate")
        row = con.execute("select payload_sha256, registered_at from recommendations where recommendation_id = ?",
                          (rec_id,)).fetchone()
        if row is not None:
            con.execute("rollback")
            if row["payload_sha256"] != digest:
                raise RecommendationConflict(
                    f"recommendation {rec_id} is already registered with different content; use a new ID")
            return {"recommendation_id": rec_id, "registered_at": row["registered_at"], "created": False}
        registered_at = _now()
        con.execute("insert into recommendations values (?, ?, ?, ?, ?)",
                    (rec_id, CONTRACT_VERSION, text, digest, registered_at))
        con.execute("commit")
        return {"recommendation_id": rec_id, "registered_at": registered_at, "created": True}
    except BaseException:
        if con.in_transaction:
            con.execute("rollback")
        raise
    finally:
        con.close()


def _feedback_row(row: sqlite3.Row) -> dict:
    return {
        "feedback_id": row["feedback_id"],
        "recommendation_id": row["recommendation_id"],
        "submission_id": row["submission_id"],
        "decision": row["decision"],
        "correction": json.loads(row["correction_json"]) if row["correction_json"] else None,
        "correction_source": row["correction_source"],
        "note": row["note"],
        "decided_by": row["decided_by"],
        "received_at": row["received_at"],
    }


def get_recommendation(recommendation_id: str) -> dict:
    """The original recommendation, its feedback history (oldest first) and the current decision."""
    con = _connect()
    try:
        row = con.execute("select * from recommendations where recommendation_id = ?", (recommendation_id,)).fetchone()
        if row is None:
            raise RecommendationNotFound(f"unknown recommendation: {recommendation_id}")
        history = [_feedback_row(r) for r in con.execute(
            "select * from feedback where recommendation_id = ? order by feedback_id", (recommendation_id,))]
    finally:
        con.close()
    return {
        "recommendation_id": row["recommendation_id"],
        "contract_version": row["contract_version"],
        "registered_at": row["registered_at"],
        "recommendation": json.loads(row["payload_json"]),
        "current_feedback": history[-1] if history else None,
        "feedback_history": history,
    }


def record_feedback(recommendation_id: str, body: dict) -> dict:
    """Append owner feedback. Returns the stored row plus "duplicate" (True when a retry was absorbed)."""
    validate_feedback(body)
    decision = body["decision"]
    correction = body.get("correction") if decision == "corrected" else None
    request_digest = _sha(_canonical({k: body.get(k) for k in sorted(FEEDBACK_KEYS)}))
    con = _connect()
    try:
        con.execute("begin immediate")
        if con.execute("select 1 from recommendations where recommendation_id = ?", (recommendation_id,)).fetchone() is None:
            raise RecommendationNotFound(f"unknown recommendation: {recommendation_id}")
        existing = con.execute("select * from feedback where recommendation_id = ? and submission_id = ?",
                               (recommendation_id, body["submission_id"])).fetchone()
        if existing is not None:
            con.execute("rollback")
            if existing["request_sha256"] != request_digest:
                raise FeedbackConflict(f"submission_id {body['submission_id']} was already used with a different body")
            return {**_feedback_row(existing), "duplicate": True}
        cur = con.execute(
            "insert into feedback (recommendation_id, submission_id, decision, correction_json, correction_source, "
            "note, decided_by, request_sha256, received_at) values (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (recommendation_id, body["submission_id"], decision,
             _canonical(correction) if correction is not None else None,
             "owner_input" if correction is not None else None,
             body.get("note"), body.get("decided_by"), request_digest, _now()))
        row = con.execute("select * from feedback where feedback_id = ?", (cur.lastrowid,)).fetchone()
        con.execute("commit")
        return {**_feedback_row(row), "duplicate": False}
    except BaseException:
        if con.in_transaction:
            con.execute("rollback")
        raise
    finally:
        con.close()
