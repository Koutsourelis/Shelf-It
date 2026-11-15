import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from agentkit import agent, config, demo_data, live, portal, recommendations as rec_store, shelf_talker as st, tasks, telegram, vision
from agentkit.scenarios import get as get_scenario
from agentkit.server import app
from agentkit.tools import load_all


class TestTelegramIntegration(unittest.TestCase):
    def setUp(self) -> None:
        load_all()
        self.tmp = Path(tempfile.mkdtemp(prefix="tg-flow-"))
        self._orig = (
            config.DB_PATH, config.WORKSPACE, config.RUNS_DIR,
            config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID, config.TELEGRAM_ALLOWED_CHATS,
            config.VISION_PROVIDER, config.LLM_PROVIDER,
            rec_store.DB_PATH, st.STATE_DIR, telegram.STATE_FILE,
            telegram.last_chat_id, telegram.bot_username,
        )
        config.DB_PATH = self.tmp / "demo.duckdb"
        config.WORKSPACE = self.tmp / "workspace"
        config.RUNS_DIR = self.tmp / "runs"
        config.WORKSPACE.mkdir(parents=True, exist_ok=True)
        config.RUNS_DIR.mkdir(parents=True, exist_ok=True)
        config.TELEGRAM_BOT_TOKEN = "123456:TEST_TOKEN"
        config.TELEGRAM_CHAT_ID = ""
        config.TELEGRAM_ALLOWED_CHATS = set()
        config.VISION_PROVIDER = "mock"
        config.LLM_PROVIDER = "mock"

        rec_store.DB_PATH = self.tmp / "state" / "recommendations.sqlite3"
        st.STATE_DIR = self.tmp / "state" / "talkers"
        telegram.STATE_FILE = self.tmp / "state" / "telegram_chats.json"
        telegram.last_chat_id = None
        telegram.bot_username = "ShelfSenseDemoBot"

        demo_data.build()
        live.STATE.reset()
        portal.orders.clear()

        self.sent_calls: list[tuple[str, dict]] = []
        self.sent_photos: list[tuple[str, bytes, str, list | None]] = []

        async def fake_call(method: str, **payload) -> dict:
            self.sent_calls.append((method, payload))
            if method == "getMe":
                return {"ok": True, "result": {"username": "ShelfSenseDemoBot"}}
            return {"ok": True, "result": {}}

        async def fake_send_photo(chat_id: str, photo: Path | bytes, caption: str = "", rows=None) -> dict:
            raw = photo.read_bytes() if isinstance(photo, Path) else photo
            self.sent_photos.append((str(chat_id), raw, caption, rows))
            return {"ok": True}

        self._p_call = patch.object(telegram, "_call", side_effect=fake_call)
        self._p_photo = patch.object(telegram, "send_photo", side_effect=fake_send_photo)
        self._p_call.start()
        self._p_photo.start()

    def tearDown(self) -> None:
        self._p_call.stop()
        self._p_photo.stop()
        live.STATE.reset()
        portal.orders.clear()
        (
            config.DB_PATH, config.WORKSPACE, config.RUNS_DIR,
            config.TELEGRAM_BOT_TOKEN, config.TELEGRAM_CHAT_ID, config.TELEGRAM_ALLOWED_CHATS,
            config.VISION_PROVIDER, config.LLM_PROVIDER,
            rec_store.DB_PATH, st.STATE_DIR, telegram.STATE_FILE,
            telegram.last_chat_id, telegram.bot_username,
        ) = self._orig

    def test_start_persists_chat_and_qr_endpoint_works(self) -> None:
        asyncio.run(telegram._handle({"message": {"chat": {"id": 777001}, "text": "/start"}}))
        self.assertIn("777001", telegram.subscribers())
        # Simulate restart clearing RAM
        telegram.last_chat_id = None
        self.assertIn("777001", telegram.subscribers())

        client = TestClient(app)
        links = client.get("/api/links").json()
        self.assertEqual(links["telegram"]["url"], "https://t.me/ShelfSenseDemoBot?start=shelf")
        qr = client.get("/qr.svg?path=telegram")
        self.assertEqual(qr.status_code, 200)
        self.assertIn("<svg", qr.text)

    def test_photo_scan_and_task_claim_button_in_telegram(self) -> None:
        vision.set_mock_assessment("sample_before")
        sample_img = (config.SHELF_DIR / "photos" / "sample_before.png").read_bytes()

        async def fake_download(_fid: str) -> bytes:
            return sample_img

        with patch.object(telegram, "_download_file", side_effect=fake_download), \
             patch.object(config, "LIVE_START_AGENT", False):
            asyncio.run(telegram._handle({
                "message": {
                    "chat": {"id": 888002},
                    "from": {"first_name": "Αναστάσης"},
                    "photo": [{"file_id": "low"}, {"file_id": "high_res_shelf"}],
                }
            }))

        self.assertGreater(len(tasks.open_tasks()), 0)
        # Live _act sent a photo alert with inline claim buttons
        self.assertGreaterEqual(len(self.sent_photos), 1)
        _cid, _raw, caption, rows = self.sent_photos[-1]
        self.assertIn("εκκρεμείς εργασίες", caption)
        assert rows is not None and len(rows[0]) >= 1
        claim_cb = rows[0][0][1]
        self.assertLessEqual(len(claim_cb.encode("utf-8")), 64)

        # Tap the claim button right inside Telegram
        asyncio.run(telegram._handle({
            "callback_query": {
                "id": "cq-1",
                "data": claim_cb,
                "from": {"first_name": "Αναστάσης"},
                "message": {"chat": {"id": 888002}},
            }
        }))
        claimed = [t for t in tasks.open_tasks() if t.get("claimed_by") == "Αναστάσης"]
        self.assertEqual(len(claimed), 1)

    def test_proposal_pushes_to_telegram_and_generates_talker_png_on_tap(self) -> None:
        telegram._remember_chat("999003")
        from agentkit.tools.shelf import _layout_stats, propose_move
        stats = _layout_stats()
        eye_skus = [s for s in stats.values() if s["level"] == "eye"]
        other_skus = [s for s in stats.values() if s["level"] != "eye"]
        hi, lo = next((h, l) for h in other_skus for l in eye_skus if h["per_facing"] > l["per_facing"])

        ctx = agent.RunContext(run_id="tgrun", scenario=get_scenario("shelf"))
        asyncio.run(propose_move(ctx, "swap", hi["sku"], lo["sku"], "Υψηλότερη απόδοση στο μεσαίο ράφι."))

        msg_calls = [p for m, p in self.sent_calls if m == "sendMessage" and "Πρόταση διάταξης" in p.get("text", "")]
        self.assertEqual(len(msg_calls), 1)
        kb = msg_calls[0]["reply_markup"]["inline_keyboard"][0]
        talker_btn = next(b for b in kb if "Ταμπελάκι" in b["text"])
        self.assertLessEqual(len(talker_btn["callback_data"].encode("utf-8")), 64)

        with patch.dict("os.environ", {"FAL_KEY": ""}, clear=False):
            asyncio.run(telegram._handle({
                "callback_query": {
                    "id": "cq-talker-1",
                    "data": talker_btn["callback_data"],
                    "from": {"first_name": "Μαρία"},
                    "message": {"chat": {"id": 999003}},
                }
            }))

        # Verify PNG talker was sent back into Telegram chat as a photo!
        self.assertEqual(len(self.sent_photos), 1)
        _cid, png_bytes, cap, _rows = self.sent_photos[0]
        self.assertTrue(png_bytes.startswith(b"\x89PNG"))
        self.assertIn("Ταμπελάκι ραφιού", cap)

    def test_every_manual_image_notifies_telegram_without_reset(self) -> None:
        telegram._remember_chat("8208481294")
        sample_before = (config.SHELF_DIR / "photos" / "sample_before.png").read_bytes()
        sample_after = (config.SHELF_DIR / "photos" / "sample_after.jpeg").read_bytes()

        with patch.object(config, "LIVE_START_AGENT", False), \
             patch.object(config, "LIVE_CONFIRM_FRAMES", 1):
            # 1st manual image (issues) -> sends photo #1
            vision.set_mock_assessment("sample_before")
            asyncio.run(live.process_frame(sample_before, force=True, single=True))
            self.assertEqual(len(self.sent_photos), 1)
            self.assertIn("εκκρεμείς εργασίες", self.sent_photos[-1][2])

            # 2nd manual image with IDENTICAL issues & NO reset -> still sends photo #2!
            asyncio.run(live.process_frame(sample_before, force=True, single=True))
            self.assertEqual(len(self.sent_photos), 2)
            self.assertIn("εκκρεμείς εργασίες", self.sent_photos[-1][2])

            # Continuous background camera tick (force=False, single=False) -> does NOT spam!
            asyncio.run(live.process_frame(sample_before, force=False, single=False))
            self.assertEqual(len(self.sent_photos), 2)

            # 3rd manual image (clean shelf) -> sends photo #3 ("Το ράφι είναι σωστό ✓")
            vision.set_mock_assessment("sample_after")
            asyncio.run(live.process_frame(sample_after, force=True, single=True))
            self.assertEqual(len(self.sent_photos), 3)
            self.assertIn("Το ράφι είναι σωστό", self.sent_photos[-1][2])

            # 4th manual image (clean shelf again, NO reset) -> still sends photo #4!
            asyncio.run(live.process_frame(sample_after, force=True, single=True))
            self.assertEqual(len(self.sent_photos), 4)
            self.assertIn("Το ράφι είναι σωστό", self.sent_photos[-1][2])


if __name__ == "__main__":
    unittest.main()
