"""Ρυθμίσεις: όλα διαβάζονται από το .env ώστε να αλλάζουν χωρίς κώδικα."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


# --- Μοντέλο -----------------------------------------------------------
# LLM_PROVIDER: anthropic | openai_compat | mock
LLM_PROVIDER = _env("LLM_PROVIDER", "mock")
# Φθηνό μοντέλο για ανάπτυξη· για το demo άλλαξέ το σε claude-opus-5-5.
ANTHROPIC_MODEL = _env("ANTHROPIC_MODEL", "claude-haiku-5-5")
# Οποιοσδήποτε πάροχος με API συμβατό με OpenAI (OpenAI, Gemini, Groq, OpenRouter...).
OPENAI_COMPAT_BASE_URL = _env("OPENAI_COMPAT_BASE_URL")
OPENAI_COMPAT_API_KEY = _env("OPENAI_COMPAT_API_KEY")
OPENAI_COMPAT_MODEL = _env("OPENAI_COMPAT_MODEL")

MAX_STEPS = int(_env("MAX_STEPS", "30"))

# --- Όραση (agentkit/vision) -------------------------------------------
# Φωτογραφία του σωστού ραφιού που στέλνεται μαζί με κάθε frame (σχετική διαδρομή από τη ρίζα). Κενό = χωρίς.
VISION_REFERENCE = _env("VISION_REFERENCE")
VISION_TIMEOUT_SECONDS = int(_env("VISION_TIMEOUT_SECONDS", "40"))

# --- Live παρακολούθηση (agentkit/live.py, σελίδα /live) ------------------
LIVE_INTERVAL_SECONDS = int(_env("LIVE_INTERVAL_SECONDS", "30"))    # κάθε πόσο στέλνει frame η σελίδα /live
LIVE_CONFIRM_FRAMES = int(_env("LIVE_CONFIRM_FRAMES", "2"))         # ίδια ευρήματα σε τόσα συνεχόμενα frames → αναφορά
LIVE_DIFF_THRESHOLD = float(_env("LIVE_DIFF_THRESHOLD", "4.0"))     # μέση διαφορά pixel (0-255) κάτω από την οποία το frame θεωρείται ίδιο
LIVE_START_AGENT = _env("LIVE_START_AGENT", "1") == "1"             # νέα ευρήματα → πλήρης εκτέλεση του agent (αναπλήρωση, παραγγελία)

# --- Συμπεριφορά -------------------------------------------------------
DEFAULT_SCENARIO = _env("DEFAULT_SCENARIO", "shelf")
AUTO_APPROVE = _env("AUTO_APPROVE", "0") == "1"
WATCHERS_ENABLED = _env("WATCHERS_ENABLED", "1") == "1"
WATCH_INTERVAL_SECONDS = int(_env("WATCH_INTERVAL_SECONDS", "20"))
BROWSER_HEADLESS = _env("BROWSER_HEADLESS", "1") == "1"

# --- Κανάλια -----------------------------------------------------------
TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
# Κενό = δέχεται όλους. Αλλιώς λίστα chat id χωρισμένη με κόμμα.
TELEGRAM_ALLOWED_CHATS = {c for c in _env("TELEGRAM_ALLOWED_CHATS").split(",") if c}

SMTP_HOST = _env("SMTP_HOST")
SMTP_PORT = int(_env("SMTP_PORT", "587"))
SMTP_USER = _env("SMTP_USER")
SMTP_PASSWORD = _env("SMTP_PASSWORD")
SMTP_FROM = _env("SMTP_FROM") or SMTP_USER

# --- Ταυτότητα του project (φαίνεται στην κονσόλα) --------------------------
PROJECT_NAME = _env("PROJECT_NAME", "Agent Console")
PROJECT_TAGLINE = _env("PROJECT_TAGLINE")
# Αρχείο εικόνας μέσα στον φάκελο console/ (π.χ. logo.png). Κενό = χωρίς λογότυπο.
PROJECT_LOGO = _env("PROJECT_LOGO")

HOST = _env("HOST", "127.0.0.1")
PORT = int(_env("PORT", "8000"))
BASE_URL = _env("BASE_URL", f"http://{HOST}:{PORT}")

# --- Φάκελοι -----------------------------------------------------------
DATA_DIR = ROOT / "data"
DB_PATH = DATA_DIR / "demo.duckdb"
WORKSPACE = ROOT / "workspace"      # ό,τι παράγει ο agent (αναφορές, γραφήματα, στιγμιότυπα)
OUTBOX = WORKSPACE / "outbox"       # email που «στάλθηκαν» όταν δεν υπάρχει SMTP
RUNS_DIR = ROOT / "runs"            # ιστορικό κάθε εκτέλεσης (για replay)
for _d in (WORKSPACE, OUTBOX, RUNS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
