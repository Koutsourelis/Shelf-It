"""Isolated checks for the second-scan verification workflow (agentkit/verification.py, verification_api.py).

    python scripts/check_verification.py

Runs against TEMPORARY databases and a temporary image folder that are deleted at the end. It never opens the
real stores (state/recommendations.sqlite3, state/verifications.sqlite3) and never writes to workspace/.

What this is NOT: a scan demonstration or an end-to-end test. Every recommendation is a hand-written TEST FIXTURE
(IDs start with "TEST-FIXTURE-VS-"), every "second scan" is a tiny synthetic image generated in memory with
Pillow (flat colour, no shelf in it). No vision call is made, so nothing here shows that a move was verified.
No network access.
"""
from __future__ import annotations

import io
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from PIL import Image                               # noqa: E402

from agentkit import config                         # noqa: E402
from agentkit import recommendations as rec_store   # noqa: E402
from agentkit import verification as vs             # noqa: E402

results: list[bool] = []


def report(name: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def raises(exc, fn, *args, **kw) -> bool:
    try:
        fn(*args, **kw)
    except exc:
        return True
    return False


def fixture(n: int) -> dict:
    """Hand-written test fixture in the provisional recommendation contract. Not an agent recommendation."""
    return {
        "recommendation_id": f"TEST-FIXTURE-VS-{n}",
        "kind": "test_fixture",
        "reason": "isolated test fixture, not an agent recommendation",
        "product": {"sku": f"TEST-SKU-{n}", "name": "Test fixture product"},
        "placement": {"from": {"shelf": 3, "position": 2}, "to": {"shelf": 1, "position": 4}},
        "image_ref": {"photo": f"TEST-FIXTURE/original_{n}.png"},
    }


def synthetic_image(fmt: str = "PNG", size=(128, 96), color=(200, 30, 30)) -> bytes:
    """Flat-colour synthetic image. A technical fixture only: it shows no shelf and proves nothing."""
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format=fmt)
    return buf.getvalue()


def feedback(rid: str, sub: str, decision: str, **extra) -> dict:
    return rec_store.record_feedback(rid, {"submission_id": sub, "decision": decision, **extra})


# --- store-level checks ----------------------------------------------------------

def check_store(tmp: Path) -> None:
    print("\nStore (temporary databases)")
    for n in range(1, 8):
        rec_store.register_recommendation(fixture(n))

    report("unknown recommendation is rejected",
           raises(rec_store.RecommendationNotFound, vs.start_session, "TEST-FIXTURE-VS-NOPE"))
    report("recommendation without any owner decision is rejected",
           raises(vs.NotVerifiable, vs.start_session, "TEST-FIXTURE-VS-1"))
    feedback("TEST-FIXTURE-VS-2", "sub-r", "rejected")
    report("rejected decision is rejected", raises(vs.NotVerifiable, vs.start_session, "TEST-FIXTURE-VS-2"))
    report("invalid recommendation_id is rejected", raises(vs.InvalidRequest, vs.start_session, "../x"))

    # accepted -> awaiting_rescan
    fb = feedback("TEST-FIXTURE-VS-3", "sub-a", "accepted")
    s = vs.start_session("TEST-FIXTURE-VS-3")
    report("start on accepted -> awaiting_rescan",
           s["created"] and s["status"] == "awaiting_rescan" and s["scan_attempts"] == [])
    report("session records recommendation and exact feedback revision",
           s["recommendation_id"] == "TEST-FIXTURE-VS-3" and s["feedback"] == {
               "feedback_id": fb["feedback_id"], "submission_id": "sub-a", "decision": "accepted"})
    report("original image reference carried from the recommendation",
           s["original_image_ref"] == {"photo": "TEST-FIXTURE/original_3.png"})
    report("integration readiness reported separately and pending",
           s["vision_integration"] == "pending" and s["end_to_end_validation"] == "pending"
           and s["vision_result"] is None)
    again = vs.start_session("TEST-FIXTURE-VS-3")
    report("repeated start returns the same session, created=False",
           not again["created"] and again["session_id"] == s["session_id"])
    con = sqlite3.connect(str(vs.db_path()))
    n_sessions = con.execute("select count(*) from sessions where recommendation_id = 'TEST-FIXTURE-VS-3'").fetchone()[0]
    con.close()
    report("no duplicate session row was created", n_sessions == 1, f"{n_sessions} row(s)")
    report("expected_feedback_id that is not current is refused",
           raises(vs.StaleFeedback, vs.start_session, "TEST-FIXTURE-VS-3", fb["feedback_id"] + 999))
    report("expected_feedback_id that is current is accepted",
           vs.start_session("TEST-FIXTURE-VS-3", fb["feedback_id"])["session_id"] == s["session_id"])

    # corrected -> awaiting_rescan
    feedback("TEST-FIXTURE-VS-4", "sub-c", "corrected", correction={"placement": {"to": {"shelf": 2, "position": 1}}})
    s4 = vs.start_session("TEST-FIXTURE-VS-4")
    report("start on corrected -> awaiting_rescan", s4["status"] == "awaiting_rescan"
           and s4["feedback"]["decision"] == "corrected")

    # invalid images
    sid = s["session_id"]
    big_header = synthetic_image()
    bad = {
        "empty": b"",
        "not an image": b"this is plain text, not an image",
        "truncated PNG": synthetic_image()[:60],
        "GIF (format not allowed)": synthetic_image("GIF"),
        "too small (16x16)": synthetic_image(size=(16, 16)),
    }
    for label, data in bad.items():
        report(f"invalid image rejected: {label}", raises(vs.InvalidImage, vs.add_scan, sid, "u-bad", data))
    saved_max = vs.MAX_IMAGE_BYTES
    vs.MAX_IMAGE_BYTES = len(big_header) - 1
    report("image over the byte limit rejected", raises(vs.ImageTooLarge, vs.add_scan, sid, "u-big", big_header))
    vs.MAX_IMAGE_BYTES = saved_max
    saved_px = vs.MAX_PIXELS
    vs.MAX_PIXELS = 100 * 100
    report("image over the pixel limit rejected", raises(vs.ImageTooLarge, vs.add_scan, sid, "u-px", big_header))
    vs.MAX_PIXELS = saved_px
    folder = vs.images_dir() / sid
    leftovers = list(folder.iterdir()) if folder.exists() else []
    report("session still awaiting_rescan after rejected uploads, no files written",
           vs.get_session(sid)["status"] == "awaiting_rescan" and not leftovers, f"{len(leftovers)} file(s)")
    report("unknown session id rejected",
           raises(vs.SessionNotFound, vs.add_scan, "vs_" + "0" * 32, "u1", synthetic_image()))
    report("malformed session id rejected", raises(vs.SessionNotFound, vs.get_session, "../../etc"))
    report("invalid upload_id rejected", raises(vs.InvalidRequest, vs.add_scan, sid, "", synthetic_image()))

    # valid upload -> awaiting_vision
    img1 = synthetic_image("JPEG")
    r1 = vs.add_scan(sid, "upload-1", img1)
    stored = vs.scan_image_path(sid, 1)
    report("valid upload -> awaiting_vision", r1["status"] == "awaiting_vision" and not r1["duplicate"])
    report("attempt vision_status pending, no vision result",
           r1["attempt"]["vision_status"] == "pending" and r1["vision_result"] is None
           and r1["vision_integration"] == "pending")
    report("image stored byte-for-byte under a server-generated name",
           stored.read_bytes() == img1 and stored.name.startswith("scan_001_") and stored.suffix == ".jpg")
    report("image stored outside workspace/ (not publicly served, not seen by the photo watcher)",
           config.WORKSPACE.resolve() not in stored.resolve().parents)
    report("re-read still awaiting_vision while integration is pending",
           vs.get_session(sid)["status"] == "awaiting_vision")

    # retries
    r1b = vs.add_scan(sid, "upload-1", img1)
    report("retry with same upload_id + same bytes returns the stored attempt",
           r1b["duplicate"] and r1b["attempt"]["attempt_no"] == 1 and len(r1b["scan_attempts"]) == 1)
    report("same upload_id with different bytes is refused",
           raises(vs.UploadConflict, vs.add_scan, sid, "upload-1", synthetic_image(color=(0, 0, 255))))

    # history preserved
    img2 = synthetic_image("WEBP", color=(0, 128, 0))
    r2 = vs.add_scan(sid, "upload-2", img2)
    report("second attempt appended, first preserved",
           [a["attempt_no"] for a in r2["scan_attempts"]] == [1, 2]
           and vs.scan_image_path(sid, 1).read_bytes() == img1 and vs.scan_image_path(sid, 2).read_bytes() == img2)
    report("still awaiting_vision after several attempts", r2["status"] == "awaiting_vision")

    # superseded
    fb2 = feedback("TEST-FIXTURE-VS-3", "sub-a2", "accepted")
    got = vs.get_session(sid)
    report("new feedback after start -> session superseded",
           got["status"] == "superseded" and got["superseded"]["by_feedback_id"] == fb2["feedback_id"])
    report("superseded session keeps its attempts", len(got["scan_attempts"]) == 2)
    report("upload to superseded session refused",
           raises(vs.SessionClosed, vs.add_scan, sid, "upload-3", synthetic_image()))
    new = vs.start_session("TEST-FIXTURE-VS-3")
    report("new session for the new revision is separate",
           new["created"] and new["session_id"] != sid and new["feedback"]["feedback_id"] == fb2["feedback_id"])
    feedback("TEST-FIXTURE-VS-4", "sub-c2", "rejected")
    s4b = vs.get_session(s4["session_id"])
    report("owner switches to rejected -> session superseded", s4b["status"] == "superseded")
    report("start after rejection refused", raises(vs.NotVerifiable, vs.start_session, "TEST-FIXTURE-VS-4"))

    # future outcomes not reachable
    con = sqlite3.connect(str(vs.db_path()))
    blocked = []
    for outcome in vs.FUTURE_OUTCOMES:
        try:
            con.execute("update sessions set status = ? where session_id = ?", (outcome, new["session_id"]))
            blocked.append(False)
        except sqlite3.IntegrityError:
            blocked.append(True)
    con.close()
    report("database refuses verified / not_done / inconclusive", all(blocked))
    public = [n for n, f in vars(vs).items() if not n.startswith("_") and callable(f)
              and getattr(f, "__module__", None) == vs.__name__ and n[0].islower()]
    report("no public function sets an outcome",
           not any(w in n.lower() for n in public for w in ("verify", "outcome", "result", "set_status")),
           ", ".join(sorted(public)))

    # storage location guard
    saved = vs.DB_PATH
    vs.DB_PATH = config.WORKSPACE / "verifications.sqlite3"
    report("store inside workspace/ refused", raises(vs.UnsafeStorageLocation, vs.db_path))
    vs.DB_PATH = saved


# --- HTTP checks -------------------------------------------------------------------

def check_api(tmp: Path) -> None:
    print("\nHTTP API (isolated FastAPI app with only the verification and feedback routers)")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agentkit import feedback_api, verification_api

    app = FastAPI()
    app.include_router(feedback_api.router)
    app.include_router(verification_api.router)
    c = TestClient(app)
    rec_store.register_recommendation(fixture(20))
    rec_store.register_recommendation(fixture(21))

    report("POST start, unknown recommendation -> 404",
           c.post("/api/verifications", json={"recommendation_id": "TEST-FIXTURE-VS-NOPE"}).status_code == 404)
    c.post("/api/recommendations/TEST-FIXTURE-VS-21/feedback", json={"submission_id": "h-r", "decision": "rejected"})
    report("POST start, rejected -> 409",
           c.post("/api/verifications", json={"recommendation_id": "TEST-FIXTURE-VS-21"}).status_code == 409)
    report("POST start, unknown field (e.g. verified) -> 422",
           c.post("/api/verifications", json={"recommendation_id": "TEST-FIXTURE-VS-20", "verified": True})
           .status_code == 422)
    c.post("/api/recommendations/TEST-FIXTURE-VS-20/feedback", json={"submission_id": "h-a", "decision": "accepted"})
    r = c.post("/api/verifications", json={"recommendation_id": "TEST-FIXTURE-VS-20"})
    sid = r.json().get("session_id")
    report("POST start -> 201 awaiting_rescan", r.status_code == 201 and r.json()["status"] == "awaiting_rescan")
    r2 = c.post("/api/verifications", json={"recommendation_id": "TEST-FIXTURE-VS-20"})
    report("POST start retry -> 200 same session", r2.status_code == 200 and r2.json()["session_id"] == sid)

    files = {"file": ("client-name.exe", synthetic_image(), "application/octet-stream")}
    up = c.post(f"/api/verifications/{sid}/scans", files=files, data={"upload_id": "h-up-1"})
    body = up.json()
    report("POST scan -> 201 awaiting_vision", up.status_code == 201 and body["status"] == "awaiting_vision")
    report("client filename and content type ignored; name is server-generated",
           body["attempt"]["image_ref"]["path"].startswith(f"{sid}/scan_001_")
           and body["attempt"]["image_ref"]["path"].endswith(".png"))
    up2 = c.post(f"/api/verifications/{sid}/scans", files=files, data={"upload_id": "h-up-1"})
    report("POST scan retry -> 200 duplicate, one attempt",
           up2.status_code == 200 and up2.json()["duplicate"] and len(up2.json()["scan_attempts"]) == 1)
    bad = c.post(f"/api/verifications/{sid}/scans", files={"file": ("x.png", b"not an image", "image/png")},
                 data={"upload_id": "h-up-2"})
    report("POST scan invalid image -> 422", bad.status_code == 422)
    report("POST scan without upload_id -> 422",
           c.post(f"/api/verifications/{sid}/scans", files=files).status_code == 422)
    g = c.get(f"/api/verifications/{sid}")
    report("GET -> awaiting_vision, readiness pending",
           g.status_code == 200 and g.json()["status"] == "awaiting_vision"
           and g.json()["vision_integration"] == "pending" and g.json()["end_to_end_validation"] == "pending")
    report("GET unknown session -> 404", c.get("/api/verifications/vs_" + "f" * 32).status_code == 404)
    routes = {(m, rt.path) for rt in verification_api.router.routes for m in getattr(rt, "methods", [])}
    report("only start / read / upload routes exist", routes == {
        ("POST", "/api/verifications"), ("GET", "/api/verifications/{session_id}"),
        ("POST", "/api/verifications/{session_id}/scans")}, str(sorted(routes)))
    c.post("/api/recommendations/TEST-FIXTURE-VS-20/feedback",
           json={"submission_id": "h-c", "decision": "corrected", "correction": {"placement": {"to": {"shelf": 2}}}})
    report("GET after feedback change -> superseded", c.get(f"/api/verifications/{sid}").json()["status"] == "superseded")
    report("POST scan to superseded -> 409",
           c.post(f"/api/verifications/{sid}/scans", files=files, data={"upload_id": "h-up-3"}).status_code == 409)


# --- target resolution -------------------------------------------------------------

def check_target(tmp: Path) -> None:
    print("\nTarget resolution (original recommendation + feedback history up to the session's own revision)")
    import copy
    base = fixture(30)
    base["placement"] = {"from": {"shelf": 3, "position": 2}, "to": {"shelf": 1, "position": 4, "level": "eye"}}
    original = copy.deepcopy(base)
    orig_to, orig_from = original["placement"]["to"], original["placement"]["from"]

    def fb(fid: int, decision: str, correction=None) -> dict:
        return {"feedback_id": fid, "decision": decision, **({"correction": correction} if correction else {})}

    def place(to=None, frm=None) -> dict:
        p = {}
        if to is not None:
            p["to"] = to
        if frm is not None:
            p["from"] = frm
        return {"placement": p}

    name_price = {"product": {"name": "Owner-confirmed name"}, "price": {"amount": 2.4, "currency": "EUR",
                                                                         "source": "owner"}}

    # --- pure: single revision behaves as before
    t = vs.resolve_target(base, [fb(1, "accepted")], 1)
    report("accepted keeps the original target", t["to"] == orig_to and t["from"] == orig_from
           and t["corrected_fields"] == [] and t["provenance"]["placement_feedback_ids"] == [])
    t = vs.resolve_target(base, [fb(2, "corrected", name_price)], 2)
    report("name/price-only correction keeps the original target", t["to"] == orig_to and t["from"] == orig_from
           and t["corrected_fields"] == [])
    t = vs.resolve_target(base, [fb(3, "corrected", place(to={"position": 6}))], 3)
    report("partial placement correction replaces only the supplied field",
           t["to"] == {"shelf": 1, "position": 6, "level": "eye"} and t["from"] == orig_from
           and t["corrected_fields"] == ["to.position"])
    no_from = fixture(31)
    no_from["placement"] = {"to": {"shelf": 1}}
    t = vs.resolve_target(no_from, [fb(5, "accepted")], 5)
    report("missing original 'from' stays null, not invented", t["from"] is None and t["to"] == {"shelf": 1})
    report("rejected revision is not resolvable", raises(ValueError, vs.resolve_target, base,
                                                         [fb(6, "rejected")], 6))
    report("unknown revision is not resolvable", raises(LookupError, vs.resolve_target, base, [fb(1, "accepted")], 9))

    # --- pure: cumulative history
    hist = [fb(1, "corrected", place(to={"shelf": 2, "position": 4})), fb(2, "corrected", name_price)]
    t = vs.resolve_target(base, hist, 2)
    report("placement correction then name/price-only: earlier placement kept",
           t["to"] == {"shelf": 2, "position": 4, "level": "eye"} and t["from"] == orig_from
           and t["provenance"]["field_sources"] == {"to.position": 1, "to.shelf": 1}
           and t["provenance"]["considered_feedback_ids"] == [1, 2] and t["basis"]["feedback_id"] == 2)
    t = vs.resolve_target(base, [hist[0], fb(2, "accepted")], 2)
    report("placement correction then accepted: correction not reset",
           t["to"] == {"shelf": 2, "position": 4, "level": "eye"} and t["basis"]["decision"] == "accepted"
           and t["provenance"]["placement_feedback_ids"] == [1])
    t = vs.resolve_target(base, [hist[0], fb(2, "rejected"), fb(3, "accepted")], 3)
    report("an intermediate rejection does not reset earlier corrections",
           t["to"] == {"shelf": 2, "position": 4, "level": "eye"} and t["provenance"]["considered_feedback_ids"] == [1, 2, 3])
    multi = [fb(1, "corrected", place(to={"shelf": 2})), fb(2, "corrected", place(to={"position": 5})),
             fb(3, "corrected", place(frm={"position": 1}))]
    t = vs.resolve_target(base, multi, 3)
    report("multiple partial placement corrections preserve earlier fields",
           t["to"] == {"shelf": 2, "position": 5, "level": "eye"} and t["from"] == {"shelf": 3, "position": 1}
           and t["provenance"]["field_sources"] == {"from.position": 3, "to.position": 2, "to.shelf": 1}
           and t["provenance"]["placement_feedback_ids"] == [1, 2, 3])
    t = vs.resolve_target(base, multi + [fb(4, "corrected", place(to={"shelf": 7}))], 2)
    report("revision cut-off: later corrections are excluded",
           t["to"] == {"shelf": 2, "position": 5, "level": "eye"} and t["from"] == orig_from
           and t["provenance"]["considered_feedback_ids"] == [1, 2])
    t = vs.resolve_target(base, list(reversed(multi)), 2)
    report("history order on input does not matter (sorted by feedback_id)",
           t["to"] == {"shelf": 2, "position": 5, "level": "eye"})
    nulls = [fb(1, "corrected", place(to={"shelf": 2, "position": 4})),
             fb(2, "corrected", place(to={"position": None})), fb(3, "corrected", name_price)]
    t = vs.resolve_target(base, nulls, 3)
    report("explicit null clears an earlier corrected field; later name/price keeps it cleared",
           t["to"] == {"shelf": 2, "position": None, "level": "eye"}
           and t["provenance"]["field_sources"] == {"to.position": 2, "to.shelf": 1})
    t = vs.resolve_target(base, [fb(1, "corrected", {"placement": {"to": {"level": None}, "from": None}})], 1)
    report("explicit null clears an original field; side given as null is not supplied",
           t["to"] == {"shelf": 1, "position": 4, "level": None} and t["from"] == orig_from)
    for body in ({"submission_id": "v-1", "decision": "corrected", "correction": place(to={"position": None, "shelf": 2})},
                 {"submission_id": "v-2", "decision": "corrected",
                  "correction": {"placement": {"to": {"level": None, "shelf": 1}, "from": None}}}):
        report(f"null-correction shape {body['submission_id']} is accepted by the unchanged validator",
               not raises(rec_store.ContractError, rec_store.validate_feedback, copy.deepcopy(body)))
    hist_copy = copy.deepcopy(multi)
    t = vs.resolve_target(base, multi, 3)
    t["to"]["shelf"] = 99
    t["from"]["position"] = 99
    report("original recommendation and feedback rows unchanged by resolution",
           base == original and multi == hist_copy)
    p0 = {"to": {"shelf": 1}, "from": None}
    p1, changed = vs.apply_placement_patch(p0, fb(1, "corrected", place(to={"position": 2})))
    report("apply_placement_patch is pure and returns a copy",
           p0 == {"to": {"shelf": 1}, "from": None} and p1 == {"to": {"shelf": 1, "position": 2}, "from": None}
           and changed == ["to.position"])

    # --- store-backed: the user's example and historical sessions
    ex = fixture(32)
    ex["placement"] = {"to": {"shelf": 3, "position": 2}}
    ex_original = copy.deepcopy(ex)
    rec_store.register_recommendation(ex)
    rid = ex["recommendation_id"]
    f1 = feedback(rid, "x-1", "accepted")
    f2 = feedback(rid, "x-2", "corrected", correction=place(to={"shelf": 2, "position": 4}))
    f3 = feedback(rid, "x-3", "corrected", correction=name_price)
    s3 = vs.start_session(rid, f3["feedback_id"])
    got = vs.get_session(s3["session_id"])
    report("example: session for the name/price revision still targets shelf 2, position 4",
           got["target"]["to"] == {"shelf": 2, "position": 4} and got["target"]["basis"]["feedback_id"] == f3["feedback_id"]
           and got["target"]["provenance"]["field_sources"] == {"to.position": f2["feedback_id"],
                                                                 "to.shelf": f2["feedback_id"]})
    report("GET target and in-process session_target agree", got["target"] == vs.session_target(s3["session_id"]))
    history_before = copy.deepcopy(rec_store.get_recommendation(rid)["feedback_history"])

    f4 = feedback(rid, "x-4", "corrected", correction=place(to={"position": 9}))
    old = vs.get_session(s3["session_id"])
    report("historical session: superseded, later correction excluded from its target",
           old["status"] == "superseded" and old["target"]["to"] == {"shelf": 2, "position": 4}
           and old["target"]["provenance"]["considered_feedback_ids"]
           == [f1["feedback_id"], f2["feedback_id"], f3["feedback_id"]])
    s4 = vs.start_session(rid, f4["feedback_id"])
    new = vs.get_session(s4["session_id"])
    report("new session includes the later partial correction on top of earlier ones",
           new["target"]["to"] == {"shelf": 2, "position": 9} and new["status"] == "awaiting_rescan"
           and new["target"]["provenance"]["field_sources"] == {"to.position": f4["feedback_id"],
                                                                 "to.shelf": f2["feedback_id"]})
    feedback(rid, "x-5", "rejected")
    report("rejected current decision still refuses a new session", raises(vs.NotVerifiable, vs.start_session, rid))
    f6 = feedback(rid, "x-6", "accepted")
    s6 = vs.get_session(vs.start_session(rid, f6["feedback_id"])["session_id"])
    report("accepted after a rejection keeps the cumulative corrections",
           s6["target"]["to"] == {"shelf": 2, "position": 9} and s6["target"]["basis"]["decision"] == "accepted")
    stored = rec_store.get_recommendation(rid)
    report("stored original recommendation and earlier feedback rows unchanged",
           stored["recommendation"] == ex_original and stored["feedback_history"][:3] == history_before[:3])
    report("readiness still pending, no vision result",
           s6["vision_integration"] == "pending" and s6["end_to_end_validation"] == "pending"
           and s6["vision_result"] is None and s6["status"] == "awaiting_rescan")


def check_server_registration() -> None:
    print("\nServer registration")
    try:
        from agentkit import server
    except Exception as e:                       # e.g. optional deps of other features missing in this venv
        print(f"  [NOTE] agentkit.server could not be imported here ({type(e).__name__}); registration not checked")
        return
    paths = set(server.app.openapi()["paths"])          # schema only; no request, no storage access
    report("server registers the verification routes",
           {"/api/verifications", "/api/verifications/{session_id}", "/api/verifications/{session_id}/scans"} <= paths)
    report("vision team's /api/shelf/photo route still present", "/api/shelf/photo" in paths)


def main() -> int:
    print("\nVerification workflow checks (isolated; temporary storage; TEST FIXTURES and synthetic images only;"
          " no vision call)")
    real = [rec_store.default_db_path(), vs.default_db_path(), vs.default_db_path().parent / vs.IMAGES_DIRNAME]
    before = [p.exists() for p in real]
    photos = config.WORKSPACE / "photos"
    photos_before = sorted(p.name for p in photos.iterdir()) if photos.exists() else None
    saved = (rec_store.DB_PATH, vs.DB_PATH, config.RUNS_DIR)
    saved_env = {k: os.environ.pop(k, None) for k in (rec_store.DB_ENV, vs.DB_ENV)}
    with tempfile.TemporaryDirectory(prefix="verif-check-") as t:
        tmp = Path(t)
        config.RUNS_DIR = tmp / "runs"           # feedback_api emits events; keep them out of the real runs/
        config.RUNS_DIR.mkdir()
        try:
            rec_store.DB_PATH = tmp / "a" / "recommendations.sqlite3"
            vs.DB_PATH = tmp / "a" / "verifications.sqlite3"
            check_store(tmp)
            rec_store.DB_PATH = tmp / "b" / "recommendations.sqlite3"
            vs.DB_PATH = tmp / "b" / "verifications.sqlite3"
            check_api(tmp)
            rec_store.DB_PATH = tmp / "c" / "recommendations.sqlite3"
            vs.DB_PATH = tmp / "c" / "verifications.sqlite3"
            check_target(tmp)
        finally:
            rec_store.DB_PATH, vs.DB_PATH, config.RUNS_DIR = saved
            for k, v in saved_env.items():
                if v is not None:
                    os.environ[k] = v
    check_server_registration()
    report("real stores and image folder not created or touched", [p.exists() for p in real] == before)
    after = sorted(p.name for p in photos.iterdir()) if photos.exists() else None
    report("workspace/photos unchanged (no agent run triggered)", after == photos_before)
    report("temporary directory removed", not tmp.exists())
    failed = results.count(False)
    print(f"\n{len(results) - failed}/{len(results)} checks passed" + ("" if not failed else f", {failed} FAILED"))
    print("These are isolated technical checks, not a scan demonstration. Vision integration and end-to-end "
          "validation remain pending.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
