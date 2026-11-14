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

# --- Τεκμήρια από το διαδίκτυο (agentkit/tools/evidence.py) -----------------
# Χωρίς token treg η αναζήτηση γίνεται με DuckDuckGo, χωρίς κλειδί.
TREG_TOKEN = _env("TREG_TOKEN")
TREG_ORG = _env("TREG_ORG")
# Εργαλεία του treg (ids από τον δημόσιο κατάλογο, https://treg.to/catalog). Καλούνται με POST και σώμα JSON.
TREG_SEARCH_TOOL = _env("TREG_SEARCH_TOOL", "treg.web.search")
TREG_NEWS_TOOL = _env("TREG_NEWS_TOOL", "treg.web.search.news")
TREG_TRENDS_TOOL = _env("TREG_TRENDS_TOOL", "treg.google.keywords.trends")
TREG_QUERY_PARAM = _env("TREG_QUERY_PARAM", "q")     # όνομα του πεδίου του ερωτήματος στα εργαλεία αναζήτησης
TREG_TRENDS_EXTRA = _env("TREG_TRENDS_EXTRA")         # προαιρετικά επιπλέον πεδία σε JSON, π.χ. {"location_name": "Greece"}
EVIDENCE_REGION = _env("EVIDENCE_REGION", "Ελλάδα")
EVIDENCE_MIN_SOURCES = int(_env("EVIDENCE_MIN_SOURCES", "2"))

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
