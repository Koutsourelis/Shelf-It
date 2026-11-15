import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from agentkit import agent, config, demo_data, recommendations as rec_store, shelf_talker as st, tasks
from agentkit.scenarios import get as get_scenario
from agentkit.server import app
from agentkit.tools import REGISTRY, load_all


class TestProposalFeedbackAndTalker(unittest.TestCase):
    def setUp(self) -> None:
        load_all()
        self.tmp = Path(tempfile.mkdtemp(prefix="prop-flow-"))
        self._orig_db = config.DB_PATH
        self._orig_ws = config.WORKSPACE
        self._orig_runs = config.RUNS_DIR
        self._orig_rec = rec_store.DB_PATH
        self._orig_st = st.STATE_DIR
        self._orig_tg = config.TELEGRAM_BOT_TOKEN

        config.TELEGRAM_BOT_TOKEN = ""
        config.DB_PATH = self.tmp / "demo.duckdb"
        config.WORKSPACE = self.tmp / "workspace"
        config.RUNS_DIR = self.tmp / "runs"
        config.WORKSPACE.mkdir(parents=True, exist_ok=True)
        config.RUNS_DIR.mkdir(parents=True, exist_ok=True)
        rec_store.DB_PATH = self.tmp / "state" / "recommendations.sqlite3"
        st.STATE_DIR = self.tmp / "state" / "talkers"

        demo_data.build()
        tasks.reset()

    def tearDown(self) -> None:
        tasks.reset()
        config.DB_PATH = self._orig_db
        config.WORKSPACE = self._orig_ws
        config.RUNS_DIR = self._orig_runs
        rec_store.DB_PATH = self._orig_rec
        st.STATE_DIR = self._orig_st
        config.TELEGRAM_BOT_TOKEN = self._orig_tg

    def test_propose_move_registers_recommendation_and_builds_talker(self) -> None:
        scen = get_scenario("shelf")
        self.assertIn("make_shelf_talker", scen.tools)
        ctx = agent.RunContext(run_id="testrun01", scenario=scen)

        # C04 (eye/top high margin) vs lower margin swap: find a valid K4 pair from _layout_stats
        from agentkit.tools.shelf import _layout_stats, propose_move
        stats = _layout_stats()
        eye_skus = [s for s in stats.values() if s["level"] == "eye"]
        other_skus = [s for s in stats.values() if s["level"] != "eye"]
        pair = next((hi, lo) for hi in other_skus for lo in eye_skus if hi["per_facing"] > lo["per_facing"])

        out = asyncio.run(propose_move(ctx, "swap", pair[0]["sku"], pair[1]["sku"],
                                       "Μετακίνηση κωδικού υψηλότερης απόδοσης στο μεσαίο ράφι."))
        self.assertIn("Καταχωρήθηκε", out)
        self.assertEqual(len(tasks.PROPOSALS), 1)

        prop = tasks.PROPOSALS[0]
        rid = prop["recommendation_id"]
        self.assertTrue(rid.startswith("REC-testrun01-swap-"))

        stored = rec_store.get_recommendation(rid)
        self.assertEqual(stored["recommendation"]["product"]["sku"], pair[0]["sku"])

        client = TestClient(app)
        # Confirm name & price via owner_input correction, then generate printable talker PNG (local fallback)
        r_fb = client.post(f"/api/recommendations/{rid}/feedback", json={
            "submission_id": "sub-ui-1",
            "decision": "corrected",
            "decided_by": "manager",
            "correction": {
                "product": {"sku": pair[0]["sku"], "name": pair[0]["name"]},
                "price": {"amount": pair[0]["unit_price"], "currency": "EUR", "source": "owner_confirmation"},
            },
        })
        self.assertEqual(r_fb.status_code, 201)
        self.assertEqual(tasks.PROPOSALS[0].get("decision"), "corrected")

        with patch.dict("os.environ", {"FAL_KEY": ""}, clear=False):
            r_tk = client.post(f"/api/recommendations/{rid}/talker", json={"theme": "fresh"})
        self.assertEqual(r_tk.status_code, 200, r_tk.text)
        body = r_tk.json()
        self.assertEqual(body["status"], "generated")
        self.assertTrue((config.WORKSPACE / body["file"]).is_file())
        self.assertEqual(tasks.PROPOSALS[0].get("talker_file"), body["file"])


if __name__ == "__main__":
    unittest.main()
