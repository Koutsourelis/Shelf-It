"""Vercel entrypoint for the live demo (Vercel serves the FastAPI `app` found in this file).

On Vercel the file system is read-only except /tmp, while the app writes next to its code (data/demo.duckdb,
workspace/, runs/, state/). So on Vercel the code and data are copied once per instance to /tmp/shelf-it and imported
from there. Locally nothing changes: run `python -m agentkit.server` as before.
With no model keys set in the Vercel project, the demo runs with the offline mock model.
"""
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

if os.environ.get("VERCEL"):
    RUN_DIR = Path("/tmp/shelf-it")
    for name in ("agentkit", "console", "data", "scripts"):
        if (HERE / name).exists() and not (RUN_DIR / name).exists():
            shutil.copytree(HERE / name, RUN_DIR / name)
    sys.path.insert(0, str(RUN_DIR))
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
    public = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL") or os.environ.get("VERCEL_URL")
    if public:
        os.environ.setdefault("BASE_URL", f"https://{public}")
        os.environ.setdefault("PUBLIC_URL", f"https://{public}")

    from agentkit import config, demo_data  # noqa: E402  (imported from /tmp/shelf-it)

    if not config.DB_PATH.exists():
        demo_data.build()

from agentkit.server import app  # noqa: E402,F401
