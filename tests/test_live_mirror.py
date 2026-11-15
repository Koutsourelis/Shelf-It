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


if __name__ == "__main__":
    unittest.main()
