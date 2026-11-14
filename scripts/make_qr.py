"""Make the QR code that points to the project page (docs/index.html on GitHub Pages).

Needs one extra package that is not in requirements.txt:  pip install segno

    python scripts/make_qr.py                 # default URL below
    python scripts/make_qr.py https://...     # another URL, e.g. a custom domain

Writes docs/qr.svg (for slides, scales to any size) and docs/qr.png (for anything else).
The QR is static: it encodes the URL itself, so it never expires and needs no service.
"""
import sys
from pathlib import Path

import segno

DEFAULT_URL = "https://koutsourelis.github.io/Gen-AI-Hackathon-Agent/"
OUT = Path(__file__).resolve().parent.parent / "docs"


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    # Error correction "M" keeps the code coarse enough to scan from the back of a room.
    qr = segno.make(url, error="m")
    qr.save(str(OUT / "qr.svg"), scale=10, border=4, dark="#000000", light="#ffffff")
    qr.save(str(OUT / "qr.png"), scale=20, border=4, dark="#000000", light="#ffffff")
    print(f"QR for {url}")
    print(f"  {OUT / 'qr.svg'}")
    print(f"  {OUT / 'qr.png'}  ({qr.symbol_size(scale=20, border=4)[0]} px)")


if __name__ == "__main__":
    main()
