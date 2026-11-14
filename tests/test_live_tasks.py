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

# Τα tests τρέχουν πάντα στο βασικό σετ (data/shelf), ό,τι SHELF_SET κι αν έχει το τερματικό.
config.SHELF_SET = ""
config.SHELF_DIR = config.DATA_DIR / "shelf"
demo_data.SHELF_DIR = config.SHELF_DIR
demo_data.PHOTOS_DIR = demo_data.SHELF_DIR / "photos"


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
        vision.set_mock_assessment("sample_before")

    def tearDown(self):
        from agentkit.tools import data as data_tools
        if data_tools._con is not None:
            data_tools._con.close()
            data_tools._con = None
        for k, v in self._saved.items():
            setattr(config, k, v)
        live.STATE.reset()
        portal.orders.clear()
        vision.set_mock_assessment("sample_before")
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
        vision.set_mock_assessment("sample_after")
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
