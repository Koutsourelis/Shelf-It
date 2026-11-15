"""Local HTTPS for the phone camera (agentkit/tls.py) and the address each phone page gets. No network.

    python -m unittest tests.test_tls
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentkit import config, server, tls   # noqa: E402


class PhoneUrlTest(unittest.TestCase):
    def setUp(self):
        self._saved = (config.HOST, config.PORT, config.PUBLIC_URL, config.HTTPS_PORT, server.HTTPS, config.lan_ip)
        config.HOST, config.PORT, config.PUBLIC_URL, config.HTTPS_PORT = "0.0.0.0", 8000, "", 8443
        config.lan_ip = lambda: "192.0.2.10"
        server.HTTPS = None

    def tearDown(self):
        config.HOST, config.PORT, config.PUBLIC_URL, config.HTTPS_PORT, server.HTTPS, config.lan_ip = self._saved

    def test_without_https_every_page_is_plain_http(self):
        self.assertEqual(server._phone_url("/cam")["url"], "http://192.0.2.10:8000/cam")

    def test_camera_page_goes_to_https_and_the_rest_stay_on_http(self):
        server.HTTPS = {"ip": "192.0.2.10", "port": 8443}
        cam = server._phone_url("/cam")
        self.assertEqual(cam["url"], "https://192.0.2.10:8443/cam")
        self.assertTrue(cam["self_signed"])
        self.assertEqual(server._phone_url("/tasks")["url"], "http://192.0.2.10:8000/tasks")       # no warning for staff
        self.assertEqual(server._phone_url("/capture")["url"], "http://192.0.2.10:8000/capture")   # file input, works on http

    def test_a_tunnel_wins_over_local_https(self):
        server.HTTPS = {"ip": "192.0.2.10", "port": 8443}
        config.PUBLIC_URL = "https://example.trycloudflare.com/"
        self.assertEqual(server._phone_url("/cam")["url"], "https://example.trycloudflare.com/cam")

    def test_local_https_is_skipped_when_it_cannot_help(self):
        config.HOST = "127.0.0.1"                       # the phone cannot reach the server at all
        self.assertIsNone(tls.prepare())
        config.HOST, config.HTTPS_PORT = "0.0.0.0", 0   # switched off in .env
        self.assertIsNone(tls.prepare())
        config.HTTPS_PORT, config.PUBLIC_URL = 8443, "https://example.trycloudflare.com"   # the tunnel is already HTTPS
        self.assertIsNone(tls.prepare())


@unittest.skipUnless(tls.openssl(), "needs the openssl program")
class CertificateTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._saved, tls.TLS_DIR = tls.TLS_DIR, Path(self._tmp.name) / "tls"

    def tearDown(self):
        tls.TLS_DIR = self._saved
        self._tmp.cleanup()

    def test_certificate_names_the_lan_address_and_is_reused(self):
        import ssl
        cert, key = tls.ensure_cert("192.0.2.10")
        self.assertTrue(cert.is_file() and key.is_file())
        info = ssl._ssl._test_decode_cert(str(cert))
        self.assertIn(("IP Address", "192.0.2.10"), info["subjectAltName"])
        self.assertIn(("DNS", "localhost"), info["subjectAltName"])
        made = cert.stat().st_mtime_ns
        self.assertEqual(tls.ensure_cert("192.0.2.10")[0].stat().st_mtime_ns, made)     # not made again on every start
        other, _ = tls.ensure_cert("192.0.2.11")                                         # new address, new certificate
        self.assertNotEqual(other, cert)

    def test_busy_port_is_detected(self):
        import socket
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            s.listen(1)
            self.assertFalse(tls.port_free("127.0.0.1", s.getsockname()[1]))


if __name__ == "__main__":
    unittest.main()
