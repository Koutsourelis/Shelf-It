"""Starts a Cloudflare Quick Tunnel (HTTPS) + ShelfSense server with PUBLIC_URL auto-configured.

Usage:
    .venv\\Scripts\\python scripts/run_tunnel.py

Why:
  - Venue Guest Wi-Fi often isolates phones from laptops (AP isolation), and Windows Firewall blocks Public LAN ports.
  - Mobile browsers require HTTPS for live camera access, and QR codes work over 4G/5G through the tunnel.
  - Free trycloudflare.com URLs change on every restart, so this launcher captures the fresh URL automatically
    and injects PUBLIC_URL in memory without manual .env edits.
"""
from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
getattr(sys.stdout, "reconfigure", lambda **_: None)(encoding="utf-8")

_TUNNEL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com", re.IGNORECASE)


def _ensure_cloudflared() -> Path:
    found = shutil.which("cloudflared")
    if found:
        return Path(found)
    exe_name = "cloudflared.exe" if os.name == "nt" else "cloudflared"
    local_bin = Path(sys.executable).resolve().parent / exe_name
    if local_bin.is_file():
        return local_bin

    sys_name = platform.system().lower()
    machine = platform.machine().lower()
    if sys_name == "windows":
        asset = "cloudflared-windows-amd64.exe"
    elif sys_name == "darwin":
        asset = "cloudflared-darwin-arm64.tgz" if "arm" in machine else "cloudflared-darwin-amd64.tgz"
    else:
        asset = "cloudflared-linux-arm64" if "aarch64" in machine or "arm" in machine else "cloudflared-linux-amd64"

    if asset.endswith(".tgz"):
        raise RuntimeError("Install cloudflared first (`brew install cloudflared`) and re-run.")

    url = f"https://github.com/cloudflare/cloudflared/releases/latest/download/{asset}"
    print(f"  Λήψη cloudflared ({asset})…")
    local_bin.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, str(local_bin))
    if os.name != "nt":
        local_bin.chmod(0o755)
    return local_bin


def main() -> None:
    port = os.environ.get("PORT", "").strip()
    if not port:
        from dotenv import dotenv_values
        port = (dotenv_values(ROOT / ".env").get("PORT") or "8000").strip()

    bin_path = _ensure_cloudflared()
    target = f"http://127.0.0.1:{port}"
    print(f"\n  Άνοιγμα Cloudflare HTTPS Tunnel προς {target}…")

    proc = subprocess.Popen(
        [str(bin_path), "tunnel", "--no-autoupdate", "--url", target],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    found_url: list[str] = []
    ready = threading.Event()

    def _reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            m = _TUNNEL_RE.search(line)
            if m and not found_url:
                found_url.append(m.group(0))
                ready.set()

    threading.Thread(target=_reader, daemon=True).start()

    try:
        if not ready.wait(timeout=25):
            proc.terminate()
            sys.exit("Δεν βρέθηκε URL από το cloudflared εντός 25s. Έλεγξε τη σύνδεση internet.")

        public_url = found_url[0]
        os.environ["PUBLIC_URL"] = public_url
        print(f"  Δημόσιο HTTPS URL:  {public_url}")
        print(f"  Κινητό (Εργασίες):  {public_url}/tasks")
        print(f"  Κινητό (Σάρωση):    {public_url}/capture")
        print("  (Το QR στην αρχική σελίδα χρησιμοποιεί αυτόματα αυτό το HTTPS link)\n")

        from agentkit import server
        server.main()
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
