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

    def test_propose_move_registers_recommendation_and_builds_talker(self) -> None:
        scen = get_scenario("shelf")
        self.assertIn("make_shelf_talker", scen.tools)
        ctx = agent.RunContext(run_id="testrun01", scenario=scen)

        # C04 (eye/top high margin) vs lower margin swap: find a valid K4 pair from _layout_stats
        from agentkit.tools.shelf import _layout_stats, propose_move
        stats = _layout_stats()
        eye_skus = [s for s in stats.values() if s["level"] == "eye"]
        other_skus = [s for s in stats.values() if s["level"] != "eye"]
        pair = next((hi, lo) for hi in other_skus for lo in eye_skus
                    if hi["per_facing"] > 1.25 * lo["per_facing"] and not hi["heavy"] and not hi["destination"])

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


class TestLiveProposalRules(TestProposalFeedbackAndTalker):
    """The live path (propose_move) applies the same limits as agentkit/rules.py (planning/RESEARCH_CHECK.md)."""

    def _propose(self, kind: str, sku_from: str, sku_to: str) -> str:
        from agentkit.tools.shelf import propose_move
        ctx = agent.RunContext(run_id="testrun02", scenario=get_scenario("shelf"))
        return asyncio.run(propose_move(ctx, kind, sku_from, sku_to, "Δοκιμή κανόνα."))

    def test_propose_move_registers_recommendation_and_builds_talker(self) -> None:
        pass    # covered by the parent class

    def test_k3_rejects_donor_without_one_day_cover(self) -> None:
        from agentkit.tools.shelf import _layout_stats
        stats = _layout_stats()
        donor = next(s for s in stats.values() if s["facings"] > 1 and (s["facings"] - 1) * s["depth"] < s["units"])
        taker = next(s for s in stats.values() if s["sku"] != donor["sku"])
        out = self._propose("facing", donor["sku"], taker["sku"])
        self.assertIn("Δεν καταχωρήθηκε", out)
        self.assertIn("θα άδειαζε", out)
        self.assertEqual(tasks.PROPOSALS, [])

    def test_k4_rejects_small_margin_difference(self) -> None:
        from agentkit.tools.shelf import _layout_stats
        stats = _layout_stats()
        pair = next(((hi, lo) for hi in stats.values() for lo in stats.values()
                     if lo["level"] == "eye" and hi["level"] != "eye" and not hi["destination"] and not hi["heavy"]
                     and lo["per_facing"] < hi["per_facing"] <= 1.25 * lo["per_facing"]), None)
        if pair is None:
            self.skipTest("demo data has no eye-level pair within 25%")
        out = self._propose("swap", pair[0]["sku"], pair[1]["sku"])
        self.assertIn("δεν ξεπερνά κατά 25%", out)

    def test_source_comes_from_rules_json(self) -> None:
        from agentkit import rules as decision_rules
        from agentkit.tools.shelf import _layout_stats
        stats = _layout_stats()
        donor = next(s for s in stats.values() if s["facings"] > 1 and (s["facings"] - 1) * s["depth"] >= s["units"])
        out = ""
        for taker in sorted(stats.values(), key=lambda s: -s["margin"]):
            if taker["sku"] != donor["sku"]:
                out = self._propose("facing", donor["sku"], taker["sku"])
                if "Καταχωρήθηκε" in out:
                    break
        self.assertIn("Καταχωρήθηκε", out)
        self.assertIn(decision_rules.load()["K3"]["source"], tasks.PROPOSALS[0]["source"])
        self.assertIn("όχι του καταστήματος", tasks.PROPOSALS[0]["source"])


if __name__ == "__main__":
    unittest.main()
