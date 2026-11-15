"""Local HTTPS for the phone camera, without a tunnel.

Mobile browsers give a page the live camera (`getUserMedia`) only over HTTPS. `/cam` is such a page: the phone shows
live video and sends a frame as a photo for analysis every few seconds. On the same Wi-Fi the simplest way to get
HTTPS is for the server to speak it itself, on a second port, with a certificate it makes for its own address.

The certificate is self-signed, so the phone shows a warning the first time ("Advanced" → "Proceed"). It is
written under `state/tls/`, which git ignores: a private key never goes in the repo. It names the laptop's current
LAN address, so a new one is made when the address changes or the old one is about to expire.

Needs the `openssl` program (present on macOS and Linux, and inside Git for Windows). Without it there is no local
HTTPS and the phone camera needs the tunnel: `python scripts/run_tunnel.py`.
"""
import shutil
import socket
import subprocess
import time
from pathlib import Path

from . import config

TLS_DIR = config.ROOT / "state" / "tls"
VALID_DAYS = 30
RENEW_AFTER_DAYS = 25
_GIT_FOR_WINDOWS = (Path(r"C:\Program Files\Git\usr\bin\openssl.exe"), Path(r"C:\Program Files\Git\mingw64\bin\openssl.exe"))


def openssl() -> str | None:
    found = shutil.which("openssl")
    if found:
        return found
    return next((str(p) for p in _GIT_FOR_WINDOWS if p.is_file()), None)


def port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
        except OSError:
            return False
    return True


def ensure_cert(ip: str) -> tuple[Path, Path]:
    """The certificate and key for this LAN address, made on first use. Raises RuntimeError if it cannot be made."""
    cert, key = TLS_DIR / f"{ip}.cert.pem", TLS_DIR / f"{ip}.key.pem"
    fresh = cert.is_file() and key.is_file() and time.time() - cert.stat().st_mtime < RENEW_AFTER_DAYS * 86400
    if fresh:
        return cert, key
    exe = openssl()
    if not exe:
        raise RuntimeError("δεν βρέθηκε το πρόγραμμα openssl")
    TLS_DIR.mkdir(parents=True, exist_ok=True)
    done = subprocess.run(
        [exe, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", str(VALID_DAYS),
         "-keyout", str(key), "-out", str(cert), "-subj", "/CN=Shelf-it local",
         "-addext", f"subjectAltName=IP:{ip},IP:127.0.0.1,DNS:localhost"],
        capture_output=True, text=True, timeout=60)
    if done.returncode != 0 or not cert.is_file() or not key.is_file():
        raise RuntimeError(f"το openssl απέτυχε: {(done.stderr or '').strip()[-200:]}")
    try:
        key.chmod(0o600)
    except OSError:
        pass
    return cert, key


def prepare() -> dict | None:
    """What the server needs to listen on HTTPS, or None with the reason printed.

    Local HTTPS is for the phone on the same network. It is skipped when the server only listens on this machine,
    when a tunnel already provides HTTPS (PUBLIC_URL), or when HTTPS_PORT=0.
    """
    if not config.HTTPS_PORT or config.PUBLIC_URL or config.HOST in ("127.0.0.1", "localhost"):
        return None
    ip = config.lan_ip()
    if not ip:
        return None
    if not port_free(config.HOST, config.HTTPS_PORT):
        print(f"  HTTPS:     η θύρα {config.HTTPS_PORT} είναι πιασμένη· όρισε άλλη με HTTPS_PORT στο .env")
        return None
    try:
        cert, key = ensure_cert(ip)
    except (RuntimeError, OSError, subprocess.SubprocessError) as e:
        print(f"  HTTPS:     δεν ξεκίνησε ({e}). Για την κάμερα του κινητού: python scripts/run_tunnel.py")
        return None
    return {"ip": ip, "port": config.HTTPS_PORT, "cert": cert, "key": key}
