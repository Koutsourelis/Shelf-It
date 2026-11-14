"""Isolated checks for the recommendation store and the owner-feedback API.

    python scripts/check_recommendations.py

What this covers: agentkit/recommendations.py and agentkit/feedback_api.py, against TEMPORARY databases that are
deleted at the end. It never opens the real store (state/recommendations.sqlite3) and never writes to it.

What this is NOT: an end-to-end test. Every recommendation below is a hand-written TEST FIXTURE (IDs start with
"TEST-FIXTURE-", kind "test_fixture"). None of them came from the agent, none is inserted into application data,
and none should be presented as an agent recommendation.

The /files exposure check uses the full server app when it can be imported in this Python; otherwise it says so
and uses an isolated StaticFiles mount that mirrors the one in agentkit/server.py.
No dependencies beyond requirements.txt (fastapi, httpx via TestClient).
"""
from __future__ import annotations

import ast
import copy
import json
import os
import sqlite3
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from agentkit import config                       # noqa: E402
from agentkit import recommendations as store     # noqa: E402

results: list[bool] = []


def report(name: str, ok: bool, detail: str = "") -> None:
    results.append(ok)
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def note(text: str) -> None:
    print(f"  [NOTE] {text}")


def fixture(n: int, **overrides) -> dict:
    """A hand-written test fixture in the provisional contract shape. Not an agent recommendation."""
    rec = {
        "recommendation_id": f"TEST-FIXTURE-{n}",
        "kind": "test_fixture",
        "reason": "isolated test fixture, not an agent recommendation",
        "product": {"sku": f"TEST-SKU-{n}", "name": "Test fixture product"},
        "placement": {"from": {"shelf": 3, "position": 2}, "to": {"shelf": 1, "position": 4}},
        "price": {"amount": 1.5, "currency": "EUR", "source": "test_fixture"},
    }
    rec.update(overrides)
    return rec


def raises(exc, fn, *args) -> bool:
    try:
        fn(*args)
    except exc:
        return True
    return False


def under(path: Path, directory: Path) -> bool:
    path, directory = path.resolve(), directory.resolve()
    return path == directory or directory in path.parents


# --- 1. location -------------------------------------------------------------

def check_location() -> None:
    print("\nStorage location")
    default = store.default_db_path()
    report("default DB is outside workspace/ (served at /files)", not under(default, config.WORKSPACE), str(default))
    report("default DB is under the repo's state/ directory", default.parent == (ROOT / "state").resolve())
    import subprocess
    ignored = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "state/recommendations.sqlite3-wal"]).returncode == 0
    report("state/ (incl. SQLite sidecars) is gitignored", ignored)
    report("demo reset target is a different file", default != config.DB_PATH.resolve(), str(config.DB_PATH))

    saved_path, saved_env = store.DB_PATH, os.environ.pop(store.DB_ENV, None)
    try:
        store.DB_PATH = config.WORKSPACE / "recommendations.sqlite3"
        report("override inside workspace/ is refused", raises(store.UnsafeStorageLocation, store.db_path))
        store.DB_PATH = None
        os.environ[store.DB_ENV] = str(config.WORKSPACE / "sub" / "x.sqlite3")
        report("env override inside workspace/ is refused", raises(store.UnsafeStorageLocation, store.db_path))
        with tempfile.TemporaryDirectory() as tmp:
            os.environ[store.DB_ENV] = str(Path(tmp) / "env.sqlite3")
            report("env override RECOMMENDATIONS_DB is honoured",
                   store.db_path() == (Path(tmp) / "env.sqlite3").resolve())
    finally:
        store.DB_PATH = saved_path
        os.environ.pop(store.DB_ENV, None)
        if saved_env is not None:
            os.environ[store.DB_ENV] = saved_env

    old = config.WORKSPACE / "recommendations.sqlite3"
    if old.exists():
        note(f"a database exists at the OLD location {old}; it is not read, moved or deleted by this check")


# --- 2. store behaviour ------------------------------------------------------

def check_store(tmp: Path) -> None:
    print("\nStore (temporary database)")
    store.DB_PATH = tmp / "store.sqlite3"
    rec = fixture(1)
    original = copy.deepcopy(rec)

    first = store.register_recommendation(rec)
    again = store.register_recommendation(copy.deepcopy(rec))
    report("register creates, identical re-register is a no-op", first["created"] and not again["created"])

    con = sqlite3.connect(str(store.DB_PATH))           # fresh connection = what a restart would see
    stored = con.execute("select payload_json from recommendations where recommendation_id = ?",
                         (rec["recommendation_id"],)).fetchone()
    con.close()
    report("recommendation persists on disk", stored is not None and json.loads(stored[0]) == original)

    changed = fixture(1, reason="different content, same ID")
    report("same ID with different content is rejected",
           raises(store.RecommendationConflict, store.register_recommendation, changed))

    bad_recs = [None, {}, fixture(2, product=None), fixture(3, placement={"to": {}}),
                fixture(4, price={"amount": -1, "currency": "EUR", "source": "x"}),
                fixture(5, recommendation_id="../etc")]
    report("invalid recommendations are rejected",
           all(raises(store.ContractError, store.register_recommendation, b) for b in bad_recs))

    rid = rec["recommendation_id"]
    bad_feedback = [
        None, [], {"decision": "accepted"},                                  # missing submission_id
        {"submission_id": "s", "decision": "maybe"},
        {"submission_id": "s", "decision": "corrected"},                     # correction missing
        {"submission_id": "s", "decision": "corrected", "correction": {}},
        {"submission_id": "s", "decision": "corrected", "correction": {"colour": "red"}},
        {"submission_id": "s", "decision": "corrected", "correction": {"price": {"amount": None}}},
        {"submission_id": "s", "decision": "accepted", "correction": {"placement": {"to": {"shelf": 2}}}},
        {"submission_id": "s", "decision": "accepted", "received_at": "2020-01-01"},   # client timestamp
    ]
    report("invalid feedback is rejected",
           all(raises(store.ContractError, store.record_feedback, rid, b) for b in bad_feedback))
    report("feedback for an unknown recommendation is rejected",
           raises(store.RecommendationNotFound, store.record_feedback, "TEST-FIXTURE-missing",
                  {"submission_id": "s1", "decision": "accepted"}))

    body = {"submission_id": "sub-1", "decision": "corrected",
            "correction": {"placement": {"to": {"shelf": 2, "position": 1}}}, "note": "test fixture"}
    a = store.record_feedback(rid, body)
    b = store.record_feedback(rid, copy.deepcopy(body))
    report("retry with same submission_id + body returns the stored row",
           not a["duplicate"] and b["duplicate"] and a["feedback_id"] == b["feedback_id"])
    report("correction is labelled owner_input", a["correction_source"] == "owner_input")
    report("same submission_id with a different body is rejected",
           raises(store.FeedbackConflict, store.record_feedback, rid, {"submission_id": "sub-1", "decision": "rejected"}))

    store.record_feedback(rid, {"submission_id": "sub-2", "decision": "accepted"})
    view = store.get_recommendation(rid)
    report("latest submission is current, earlier ones stay in history",
           view["current_feedback"]["submission_id"] == "sub-2" and len(view["feedback_history"]) == 2)
    report("original recommendation is unchanged after feedback", view["recommendation"] == original)

    # concurrent duplicate submissions: many threads, same submission_id and body
    rid2 = store.register_recommendation(fixture(6))["recommendation_id"]
    dup_body = {"submission_id": "sub-concurrent", "decision": "accepted"}
    outcomes, errors, barrier = [], [], threading.Barrier(16)

    def submit() -> None:
        try:
            barrier.wait()
            outcomes.append(store.record_feedback(rid2, dict(dup_body)))
        except Exception as e:                           # noqa: BLE001 — reported below
            errors.append(repr(e))

    threads = [threading.Thread(target=submit) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    created = [o for o in outcomes if not o["duplicate"]]
    history = store.get_recommendation(rid2)["feedback_history"]
    report("16 concurrent identical submissions store exactly one row",
           not errors and len(created) == 1 and len(history) == 1
           and {o["feedback_id"] for o in outcomes} == {history[0]["feedback_id"]},
           f"created={len(created)} rows={len(history)} errors={errors[:2]}")


# --- 3. HTTP API (isolated app with only the feedback router) ------------------

def check_api(tmp: Path) -> None:
    print("\nFeedback API (isolated FastAPI app, temporary database, events diverted to a temp dir)")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from agentkit import feedback_api

    store.DB_PATH = tmp / "api.sqlite3"
    rid = store.register_recommendation(fixture(10))["recommendation_id"]
    app = FastAPI()
    app.include_router(feedback_api.router)
    c = TestClient(app)
    url = f"/api/recommendations/{rid}"
    r1 = c.post(url + "/feedback", json={"submission_id": "h1", "decision": "accepted"})
    r2 = c.post(url + "/feedback", json={"submission_id": "h1", "decision": "accepted"})
    r3 = c.post(url + "/feedback", json={"submission_id": "h1", "decision": "rejected"})
    r4 = c.post(url + "/feedback", content=b"{not json", headers={"content-type": "application/json"})
    r5 = c.post("/api/recommendations/TEST-FIXTURE-missing/feedback", json={"submission_id": "h", "decision": "accepted"})
    g = c.get(url)
    report("POST 201 new / 200 retry / 409 reused id / 422 bad JSON / 404 unknown",
           [r1.status_code, r2.status_code, r3.status_code, r4.status_code, r5.status_code] == [201, 200, 409, 422, 404],
           str([r1.status_code, r2.status_code, r3.status_code, r4.status_code, r5.status_code]))
    report("GET returns original + history", g.status_code == 200 and len(g.json()["feedback_history"]) == 1
           and g.json()["recommendation"] == fixture(10))


# --- 4. /files cannot serve the database ---------------------------------------

def _static_mount_dirs_from_source() -> list[Path]:
    """Directories of every StaticFiles(...) in agentkit/server.py, resolved without importing the server."""
    tree = ast.parse((ROOT / "agentkit" / "server.py").read_text(encoding="utf-8"))
    dirs = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "StaticFiles":
            kw = {k.arg: k.value for k in node.keywords}
            expr = kw.get("directory") or (node.args[0] if node.args else None)
            dirs.append(Path(eval(compile(ast.Expression(expr), "server.py", "eval"),  # noqa: S307 — own source
                                  {"__builtins__": {}},
                                  {"config": config, "CONSOLE": config.ROOT / "console", "str": str, "Path": Path})))
    return dirs


def _probe(client, prefix: str, name: str) -> list[int]:
    paths = [f"{prefix}/{name}", f"{prefix}/../state/{name}", f"{prefix}/%2e%2e/state/{name}",
             f"{prefix}/..%2fstate%2f{name}", f"{prefix}/{name}-wal", f"{prefix}/{name}-journal"]
    return [client.get(p).status_code for p in paths]


def check_files(tmp: Path) -> None:
    print("\nDownload through /files")
    from fastapi import FastAPI
    from fastapi.staticfiles import StaticFiles
    from fastapi.testclient import TestClient

    try:
        dirs = _static_mount_dirs_from_source()
        report("server.py static mounts found", bool(dirs), ", ".join(str(d) for d in dirs))
        report("default DB is outside every static mount in server.py",
               all(not under(store.default_db_path(), d) for d in dirs))
    except Exception as e:                                   # noqa: BLE001
        report("server.py static mounts could be resolved", False, repr(e))

    try:
        from agentkit import server                          # full app; lifespan is NOT started
        full = TestClient(server.app)
        mode = "full application (agentkit.server.app, lifespan not started)"
    except Exception as e:                                   # noqa: BLE001
        full = None
        note(f"full server app could not be imported in this Python ({sys.version.split()[0]}): "
             f"{type(e).__name__}: {e}. Using an isolated mount only.")
    if full is not None:
        name = store.default_db_path().name
        codes = _probe(full, "/files", name)
        report(f"{mode}: DB name and traversal paths under /files are not served", all(c == 404 for c in codes),
               str(codes) + ("" if store.default_db_path().exists() else " (no real DB exists yet)"))

    # isolated mirror of server.py: tmp/workspace mounted at /files, tmp/state holds a real SQLite file
    ws, st = tmp / "workspace", tmp / "state"
    ws.mkdir()
    st.mkdir()
    (ws / "public.txt").write_text("public")
    db = st / "recommendations.sqlite3"
    sqlite3.connect(str(db)).close()
    app = FastAPI()
    app.mount("/files", StaticFiles(directory=str(ws)), name="files")
    c = TestClient(app)
    report("isolated mount: positive control file is served", c.get("/files/public.txt").status_code == 200)
    codes = _probe(c, "/files", db.name)
    report("isolated mount: DB in sibling state/ is not served, incl. traversal", all(x == 404 for x in codes), str(codes))


def main() -> int:
    print("\nRecommendation store checks (isolated; temporary databases; hand-written test fixtures)")
    default = store.default_db_path()
    existed_before = default.exists()
    saved_path, saved_env = store.DB_PATH, os.environ.pop(store.DB_ENV, None)
    saved_runs = config.RUNS_DIR
    with tempfile.TemporaryDirectory(prefix="reco-check-") as t:
        tmp = Path(t)
        config.RUNS_DIR = tmp / "runs"           # feedback_api emits events; keep them out of the real runs/
        config.RUNS_DIR.mkdir()
        try:
            check_location()
            check_store(tmp)
            check_api(tmp)
            check_files(tmp)
        finally:
            store.DB_PATH = saved_path
            config.RUNS_DIR = saved_runs
            if saved_env is not None:
                os.environ[store.DB_ENV] = saved_env
    report("real store was not created or touched by these checks", default.exists() == existed_before)
    report("temporary directory removed", not tmp.exists())
    failed = results.count(False)
    print(f"\n{len(results) - failed}/{len(results)} checks passed" + ("" if not failed else f", {failed} FAILED"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
