import unittest
from fastapi.testclient import TestClient

from agentkit import config, live
from agentkit.server import app


class TestLiveMobileMirror(unittest.TestCase):
    def setUp(self) -> None:
        live.STATE.reset()

    def tearDown(self) -> None:
        live.STATE.reset()

    def test_cam_page_and_preview_relay(self) -> None:
        client = TestClient(app)

        r_cam = client.get("/cam")
        self.assertEqual(r_cam.status_code, 200)
        self.assertIn("Ζωντανή κάμερα", r_cam.text)

        links = client.get("/api/links").json()
        self.assertIn("cam", links)
        self.assertTrue(links["cam"]["url"].endswith("/cam"))

        # Before any mobile preview arrives -> 204
        self.assertEqual(client.get("/api/shelf/preview.jpg").status_code, 204)

        sample = (config.SHELF_DIR / "photos" / "sample_before.png").read_bytes()
        up = client.post("/api/shelf/preview", files={"file": ("preview.jpg", sample, "image/jpeg")})
        self.assertEqual(up.status_code, 200)
        ts = up.json()["ts"]

        # Desktop mirror fetches frame -> 200
        got = client.get("/api/shelf/preview.jpg?since=0")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.content, sample)
        header_ts = float(got.headers["X-Preview-Ts"])

        # Subsequent poll with same timestamp -> 204 (zero wasted bandwidth)
        same = client.get(f"/api/shelf/preview.jpg?since={header_ts}")
        self.assertEqual(same.status_code, 204)

        # Reset clears mobile preview buffer
        client.post("/api/live/reset")
        self.assertEqual(client.get("/api/shelf/preview.jpg").status_code, 204)

    def test_pitch_black_frame_is_skipped_without_calling_gemini(self) -> None:
        import io
        from PIL import Image
        from unittest.mock import patch as mpatch

        buf = io.BytesIO()
        Image.new("RGB", (320, 240), (0, 0, 0)).save(buf, format="JPEG")
        black_jpeg = buf.getvalue()

        with mpatch.object(config, "VISION_PROVIDER", "gemini"):
            client = TestClient(app)
            r = client.post("/api/shelf/frame?force=1", files={"file": ("black.jpg", black_jpeg, "image/jpeg")})
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["status"], "dark")
            self.assertEqual(live.STATE.model_calls, 0)

    def test_exif_chronological_before_after_without_filenames(self) -> None:
        import asyncio
        import shutil
        import tempfile
        from pathlib import Path
        from PIL import Image
        from agentkit import demo_data, watchers
        from agentkit.tools import shelf as shelf_tools

        tmp = Path(tempfile.mkdtemp())
        orig_ws, orig_db, orig_uploads, orig_wdir = (
            config.WORKSPACE, config.DB_PATH, shelf_tools.UPLOADS, watchers.PHOTO_DIR
        )
        try:
            config.WORKSPACE = tmp / "ws"
            config.DB_PATH = tmp / "demo.duckdb"
            shelf_tools.UPLOADS = config.WORKSPACE / "photos"
            watchers.PHOTO_DIR = shelf_tools.UPLOADS
            shelf_tools.UPLOADS.mkdir(parents=True, exist_ok=True)
            demo_data.build()

            # Write IMG_9001.jpg FIRST on disk, but give it a LATER EXIF timestamp (15:30:00)
            # Write IMG_1002.jpg SECOND on disk, but give it an EARLIER EXIF timestamp (14:05:00)
            src_before = Image.open(config.SHELF_DIR / "photos" / "sample_before.png").convert("RGB")
            src_after = Image.new("RGB", src_before.size, (220, 225, 230))

            ex_after = Image.Exif()
            ex_after[36867] = "2026:11:15 15:30:00"
            p_newer = shelf_tools.UPLOADS / "IMG_9001.jpg"
            src_after.save(p_newer, format="JPEG", exif=ex_after)

            ex_before = Image.Exif()
            ex_before[36867] = "2026:11:15 14:05:00"
            p_older = shelf_tools.UPLOADS / "IMG_1002.jpg"
            src_before.save(p_older, format="JPEG", exif=ex_before)

            # Even though IMG_1002.jpg has a newer st_mtime, EXIF DateTimeOriginal orders it as 'previous'!
            self.assertEqual(shelf_tools.find_photo("previous").name, "IMG_1002.jpg")
            self.assertEqual(shelf_tools.find_photo("latest").name, "IMG_9001.jpg")

            # Check planogram on IMG_1002.jpg then IMG_9001.jpg -> generates before_after.png automatically!
            class DummyCtx:
                def __init__(self) -> None:
                    self.artifacts: list[str] = []
                def audit(self, *a, **kw) -> None: pass
                def artifact(self, p: Path) -> None: self.artifacts.append(p.name)
                def emit(self, *a, **kw) -> None: pass

            ctx = DummyCtx()
            from unittest.mock import patch as mpatch
            with mpatch.object(config, "VISION_PROVIDER", "mock"):
                asyncio.run(shelf_tools.read_shelf(ctx, "previous"))
                out1 = asyncio.run(shelf_tools.check_planogram(ctx))
                self.assertNotIn("before_after.png", ctx.artifacts)

                asyncio.run(shelf_tools.read_shelf(ctx, "latest"))
                out2 = asyncio.run(shelf_tools.check_planogram(ctx))
                self.assertIn("before_after.png", ctx.artifacts)
                self.assertTrue((config.WORKSPACE / "before_after.png").is_file())
                self.assertIn("Προηγούμενος έλεγχος (IMG_1002.jpg)", out2)
        finally:
            config.WORKSPACE = orig_ws
            config.DB_PATH = orig_db
            shelf_tools.UPLOADS = orig_uploads
            watchers.PHOTO_DIR = orig_wdir
            shutil.rmtree(tmp, ignore_errors=True)

    def test_remote_phone_camera_trigger_and_pause(self) -> None:
        import shutil
        import tempfile
        from pathlib import Path
        from unittest.mock import patch as mpatch
        from agentkit import agent, watchers

        tmp = Path(tempfile.mkdtemp())
        orig_ws, orig_runs, orig_wdir = config.WORKSPACE, config.RUNS_DIR, watchers.PHOTO_DIR
        try:
            config.WORKSPACE = tmp / "ws"
            config.RUNS_DIR = tmp / "runs"
            watchers.PHOTO_DIR = config.WORKSPACE / "photos"
            config.RUNS_DIR.mkdir(parents=True, exist_ok=True)

            client = TestClient(app)
            # Without active phone preview -> 409
            r409 = client.post("/api/shelf/remote_trigger?mode=live")
            self.assertEqual(r409.status_code, 409)

            # Toggle remote pause works and surfaces on /api/shelf/remote_state
            rp = client.post("/api/shelf/remote_trigger?mode=toggle_pause")
            self.assertTrue(rp.json()["paused"])
            st = client.get("/api/shelf/remote_state").json()
            self.assertTrue(st["paused"])
            client.post("/api/shelf/remote_trigger?mode=toggle_pause")

            # Upload a preview frame from /cam, then trigger console capture from laptop
            sample = (config.SHELF_DIR / "photos" / "sample_before.png").read_bytes()
            client.post("/api/shelf/preview", files={"file": ("preview.jpg", sample, "image/png")})
            with mpatch.object(agent, "start_run", return_value="mockrun123") as mock_start:
                rc = client.post("/api/shelf/remote_trigger?mode=console")
                self.assertEqual(rc.status_code, 200)
                self.assertEqual(rc.json()["run_id"], "mockrun123")
                mock_start.assert_called_once()
        finally:
            config.WORKSPACE = orig_ws
            config.RUNS_DIR = orig_runs
            watchers.PHOTO_DIR = orig_wdir
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
