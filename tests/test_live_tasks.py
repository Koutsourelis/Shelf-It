"""Tests για τη ροή χωρίς κλικ: frame → εργασίες → αυτόματη παραγγελία → κλείσιμο. Mock μοντέλο, χωρίς δίκτυο.

    python -m unittest discover tests
"""
import asyncio
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentkit import config, demo_data, live, portal, tasks, vision   # noqa: E402


def frame(color) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (640, 360), color).save(buf, "JPEG")
    return buf.getvalue()


class LiveTasksTest(unittest.TestCase):
    def setUp(self):
        self._saved = {k: getattr(config, k) for k in (
            "LLM_PROVIDER", "VISION_PROVIDER", "DB_PATH", "LIVE_START_AGENT", "AUTO_ORDER", "AUTO_ORDER_MAX_CASES",
            "AUTO_ORDER_MAX_EUR", "LIVE_CONFIRM_FRAMES")}
        self._tmp = tempfile.TemporaryDirectory()
        config.DB_PATH = Path(self._tmp.name) / "test.duckdb"
        demo_data.build()
        config.LLM_PROVIDER, config.VISION_PROVIDER = "mock", ""
        config.LIVE_START_AGENT, config.AUTO_ORDER = False, True
        config.AUTO_ORDER_MAX_CASES, config.AUTO_ORDER_MAX_EUR, config.LIVE_CONFIRM_FRAMES = 3, 50.0, 2
        portal.orders.clear()
        live.STATE.reset()
        vision.set_mock_reading("sample_before")

    def tearDown(self):
        from agentkit.tools import data as data_tools
        if data_tools._con is not None:
            data_tools._con.close()
            data_tools._con = None
        for k, v in self._saved.items():
            setattr(config, k, v)
        live.STATE.reset()
        portal.orders.clear()
        vision.set_mock_reading("sample_before")
        self._tmp.cleanup()

    def send(self, color=(200, 0, 0), force=True) -> dict:
        return asyncio.run(live.process_frame(frame(color), force=force))

    def test_needs_two_frames_before_acting(self):
        first = self.send()
        self.assertEqual(first["status"], "pending")
        self.assertEqual(first["open"], 0)
        second = self.send()
        self.assertEqual(second["status"], "acted")
        self.assertEqual(second["open"], 3)

    def test_phone_photo_acts_on_a_single_frame(self):
        d = asyncio.run(live.process_frame(frame((200, 0, 0)), single=True))   # /capture: σκόπιμη φωτογραφία
        self.assertEqual(d["status"], "acted")
        self.assertEqual(d["open"], 3)

    def test_agent_decides_a_move_and_code_checks_it(self):
        """Mock agent μετά από scan: read_shelf → check → αναπλήρωση → layout_suggestions → propose_move."""
        from agentkit import agent
        config.LIVE_START_AGENT = True

        async def flow():
            d = await live.process_frame(frame((200, 0, 0)), single=True)
            self.assertEqual(d["agent_status"], "running")
            await agent._tasks[live.STATE.agent_run]
            return live.status()
        d = asyncio.run(flow())
        self.assertEqual(d["agent_status"], "done")
        self.assertEqual(len(d["proposals"]), 1)
        p = d["proposals"][0]
        self.assertEqual((p["kind"], p["rule"], p["a"]["sku"], p["b"]["sku"]), ("swap", "K4", "C09", "C05"))
        self.assertGreater(p["a"]["per_facing"], p["b"]["per_facing"])      # ο αριθμός είναι του κώδικα
        self.assertTrue(p["a"]["box"] and p["b"]["box"])                    # για το βέλος στην οθόνη
        self.assertIn("agent", {h["kind"] for h in d["history"]})

    def test_code_rejects_moves_the_numbers_do_not_support(self):
        from agentkit.tools.shelf import propose_move

        class Ctx:
            def audit(self, *a, **k): pass
        run = lambda **k: asyncio.run(propose_move(Ctx(), **k))
        # το C05 έχει το χαμηλότερο περιθώριο ανά πρόσοψη στο ύψος των ματιών: δεν ανεβαίνει εκεί κάτι χειρότερο
        self.assertIn("Δεν καταχωρήθηκε", run(kind="swap", sku_from="C08", sku_to="C05", reason="δοκιμή"))
        self.assertIn("Δεν καταχωρήθηκε", run(kind="swap", sku_from="C01", sku_to="C07", reason="δοκιμή"))   # ούτε μάτια ούτε κέντρο
        self.assertIn("Δεν καταχωρήθηκε", run(kind="facing", sku_from="C04", sku_to="C08", reason="δοκιμή"))  # αρνητικό καθαρό
        self.assertIn("Δεν καταχωρήθηκε", run(kind="swap", sku_from="C09", sku_to="C05", reason="θα ανέβουν 20%"))
        self.assertEqual(tasks.PROPOSALS, [])
        self.assertIn("Καταχωρήθηκε", run(kind="facing", sku_from="C08", sku_to="C04", reason="δοκιμή"))
        self.assertEqual(tasks.PROPOSALS[0]["rule"], "K3")

    def test_same_frame_skips_the_model(self):
        self.send()
        calls = live.STATE.model_calls
        again = self.send(force=False)
        self.assertEqual(again["status"], "unchanged")
        self.assertEqual(live.STATE.model_calls, calls)

    def test_tasks_numbers_and_auto_order(self):
        self.send()
        d = self.send()
        by_kind = {t["id"]: t for t in d["tasks"]}
        c04 = by_kind["missing:C04:2"]                         # 0 στην αποθήκη → παραγγελία
        self.assertEqual(c04["numbers"], {"units": 10, "from_backroom": 0, "to_order": 10, "cases": 1,
                                          "order_eur": 44.0})
        self.assertEqual(c04["order"]["order_no"], "ORD-1001")
        self.assertIn("missing:C04:2", by_kind)
        c02 = by_kind["low:C02:1"]                             # 2 προσόψεις × βάθος 4, υπάρχουν στην αποθήκη
        self.assertEqual(c02["numbers"]["from_backroom"], 8)
        self.assertIsNone(c02["order"])
        self.assertIn("relocate", {t["kind"] for t in d["tasks"]})
        self.assertEqual(len(portal.orders), 1)

    def test_same_findings_do_not_duplicate_tasks_or_orders(self):
        self.send(); self.send()
        self.send((10, 200, 10)); self.send((10, 200, 10))
        self.assertEqual(len(tasks.TASKS), 3)
        self.assertEqual(len(portal.orders), 1)

    def test_fixed_shelf_closes_tasks(self):
        self.send(); self.send()
        vision.set_mock_reading("sample_after")
        self.send((0, 0, 200))
        d = self.send((0, 0, 200))
        self.assertTrue(d["shelf_ok"])
        self.assertEqual(d["open"], 0)
        self.assertEqual(len(d["done"]), 3)
        self.assertTrue(all(t["status"] == "done" for t in tasks.TASKS.values()))

    def test_over_the_limit_waits_for_approval(self):
        config.AUTO_ORDER_MAX_EUR = 10.0
        self.send()
        d = self.send()
        pending = [t for t in d["tasks"] if t["needs_approval"]]
        self.assertEqual(len(pending), 1)
        self.assertEqual(portal.orders, [])
        task = tasks.approve_order(pending[0]["id"], True)
        self.assertEqual(task["order"]["order_no"], "ORD-1001")
        self.assertIsNone(task.get("needs_approval"))

    def test_claim_marks_in_progress_but_camera_closes(self):
        self.send()
        d = self.send()
        tid = d["tasks"][0]["id"]
        self.assertEqual(tasks.claim(tid, "Νίκος")["status"], "in_progress")
        self.assertIsNone(tasks.claim(tid))                    # δεύτερη φορά: δεν είναι πια open
        self.assertEqual(tasks.TASKS[tid]["status"], "in_progress")

    def test_order_tool_approval_follows_the_limit(self):
        from agentkit.tools import REGISTRY, load_all
        load_all()
        order = REGISTRY["order_from_warehouse"]
        self.assertFalse(order.approval_needed({"lines": [{"sku": "C04", "cases": 1}]}))   # 44 € ≤ 50
        self.assertTrue(order.approval_needed({"lines": [{"sku": "C05", "cases": 2}]}))    # 81.6 € > 50
        self.assertTrue(order.approval_needed({"lines": [{"sku": "C04", "cases": 4}]}))    # 4 κιβ. > 3
        config.AUTO_ORDER = False
        self.assertTrue(order.approval_needed({"lines": [{"sku": "C04", "cases": 1}]}))
        self.assertTrue(REGISTRY["send_email"].approval_needed({}))


if __name__ == "__main__":
    unittest.main()
