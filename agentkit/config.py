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
# VISION_PROVIDER: empty = same as LLM_PROVIDER | gemini = native Gemini API with an enforced response schema
# (agentkit/vision/gemini.py). The agent itself keeps using LLM_PROVIDER.
VISION_PROVIDER = _env("VISION_PROVIDER").lower()
_GOOGLE_COMPAT = "generativelanguage.googleapis.com" in OPENAI_COMPAT_BASE_URL
# If the OpenAI-compatible provider already points at Google, its key and model are reused.
GEMINI_API_KEY = _env("GEMINI_API_KEY") or (OPENAI_COMPAT_API_KEY if _GOOGLE_COMPAT else "")
GEMINI_MODEL = _env("GEMINI_MODEL") or (OPENAI_COMPAT_MODEL if _GOOGLE_COMPAT else "")
GEMINI_MEDIA_RESOLUTION = _env("GEMINI_MEDIA_RESOLUTION")          # empty (model default) | low | medium | high
GEMINI_MAX_OUTPUT_TOKENS = int(_env("GEMINI_MAX_OUTPUT_TOKENS", "0"))   # 0 = model default
# low | medium | high · low = γρήγορο (για ζωντανή κάμερα), high = πιο προσεκτικό αλλά αργό
GEMINI_THINKING_LEVEL = _env("GEMINI_THINKING_LEVEL", "low").lower()
GEMINI_IMAGE_MODEL = _env("GEMINI_IMAGE_MODEL", "gemini-3.1-flash-image")
VISION_MAX_IMAGE_SIDE = int(_env("VISION_MAX_IMAGE_SIDE", "1600"))  # longest side in pixels sent to Gemini


# Αν έχει μπει μόνο κλειδί Gemini (GEMINI_API_KEY / GEMINI_MODEL), χρησιμοποίησέ το και για τον agent.
# Αλλιώς κάθε κλήση πέφτει με άδειο base url, ενώ στο .env φαίνεται σωστό κλειδί.
if LLM_PROVIDER in ("openai_compat", "gemini") and not OPENAI_COMPAT_API_KEY and GEMINI_API_KEY:
    OPENAI_COMPAT_BASE_URL = OPENAI_COMPAT_BASE_URL or "https://generativelanguage.googleapis.com/v1beta/openai/"
    OPENAI_COMPAT_API_KEY = GEMINI_API_KEY
    OPENAI_COMPAT_MODEL = OPENAI_COMPAT_MODEL or GEMINI_MODEL


def vision_provider() -> str:
    """Ποιος διαβάζει τις φωτογραφίες: VISION_PROVIDER αν έχει οριστεί. Αλλιώς, αν υπάρχει κλειδί Gemini,
    η native Gemini API με επιβεβαιωμένο schema· σε κάθε άλλη περίπτωση ό,τι ορίζει το LLM_PROVIDER."""
    if VISION_PROVIDER:
        return VISION_PROVIDER
    return "gemini" if GEMINI_API_KEY else LLM_PROVIDER


def vision_model() -> str:
    return {"gemini": GEMINI_MODEL, "openai_compat": OPENAI_COMPAT_MODEL,
            "anthropic": ANTHROPIC_MODEL}.get(vision_provider(), "mock")

# --- Live παρακολούθηση (agentkit/live.py, σελίδα /live) ------------------
LIVE_INTERVAL_SECONDS = int(_env("LIVE_INTERVAL_SECONDS", "30"))    # κάθε πόσο στέλνει frame η σελίδα /live
LIVE_CONFIRM_FRAMES = int(_env("LIVE_CONFIRM_FRAMES", "2"))         # ίδια ευρήματα σε τόσα συνεχόμενα frames → αναφορά
LIVE_DIFF_THRESHOLD = float(_env("LIVE_DIFF_THRESHOLD", "4.0"))     # μέση διαφορά pixel (0-255) κάτω από την οποία το frame θεωρείται ίδιο
LIVE_START_AGENT = _env("LIVE_START_AGENT", "1") == "1"
# Πάνω από αυτό το ποσοστό άγνωστων προϊόντων, το ράφι θεωρείται άλλου τμήματος και αξιολογείται χωρίς κατάλογο
LIVE_UNKNOWN_RATIO = float(_env("LIVE_UNKNOWN_RATIO", "0.6"))             # νέα ευρήματα → πλήρης εκτέλεση του agent (αναπλήρωση, παραγγελία)

# 1 = προϊόντα εκτός καταλόγου αναζητούνται στο Open Food Facts στο παρασκήνιο (agentkit/identity.py). 0 = ποτέ δίκτυο.
OFF_LIVE_LOOKUP = _env("OFF_LIVE_LOOKUP", "1") == "1"

# --- Αυτονομία (agentkit/tasks.py) ---------------------------------------
# Παραγγελία χωρίς έγκριση μέσα σε αυτά τα όρια. Πάνω από αυτά, ο υπεύθυνος εγκρίνει με ένα πάτημα.
AUTO_ORDER = _env("AUTO_ORDER", "1") == "1"
AUTO_ORDER_MAX_CASES = int(_env("AUTO_ORDER_MAX_CASES", "3"))
AUTO_ORDER_MAX_EUR = float(_env("AUTO_ORDER_MAX_EUR", "50"))
TASK_REMINDER_MINUTES = int(_env("TASK_REMINDER_MINUTES", "10"))    # 0 = χωρίς υπενθυμίσεις

# --- Συμπεριφορά -------------------------------------------------------
DEFAULT_SCENARIO = _env("DEFAULT_SCENARIO", "shelf")
AUTO_APPROVE = _env("AUTO_APPROVE", "0") == "1"
WATCHERS_ENABLED = _env("WATCHERS_ENABLED", "1") == "1"
WATCH_INTERVAL_SECONDS = int(_env("WATCH_INTERVAL_SECONDS", "20"))
BROWSER_HEADLESS = _env("BROWSER_HEADLESS", "1") == "1"

# --- Κανάλια -----------------------------------------------------------
TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
# Προαιρετικό προεπιλεγμένο chat id (ή λίστα με κόμμα) για ειδοποιήσεις από την εκκίνηση.
TELEGRAM_CHAT_ID = _env("TELEGRAM_CHAT_ID")
# Κενό = δέχεται όλους. Αλλιώς λίστα chat id χωρισμένη με κόμμα.
TELEGRAM_ALLOWED_CHATS = {c.strip() for c in _env("TELEGRAM_ALLOWED_CHATS").split(",") if c.strip()}

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
TREG_SEARCH_TOOL = _env("TREG_SEARCH_TOOL") or "treg.web.search"
TREG_NEWS_TOOL = _env("TREG_NEWS_TOOL") or "treg.web.search.news"
TREG_TRENDS_TOOL = _env("TREG_TRENDS_TOOL") or "treg.google.keywords.trends"
TREG_QUERY_PARAM = _env("TREG_QUERY_PARAM") or "q"     # όνομα του πεδίου του ερωτήματος στα εργαλεία αναζήτησης
TREG_TRENDS_EXTRA = _env("TREG_TRENDS_EXTRA")         # προαιρετικά επιπλέον πεδία σε JSON, π.χ. {"location_name": "Greece"}
EVIDENCE_REGION = _env("EVIDENCE_REGION", "Ελλάδα")
EVIDENCE_COUNTRY = _env("EVIDENCE_COUNTRY") or "gr"      # κωδικός χώρας ISO για το εργαλείο τάσεων
EVIDENCE_MIN_SOURCES = int(_env("EVIDENCE_MIN_SOURCES", "2"))

# --- Ταυτότητα του project (φαίνεται στην κονσόλα) --------------------------
PROJECT_NAME = _env("PROJECT_NAME") or "Shelf-it"
PROJECT_TAGLINE = _env("PROJECT_TAGLINE") or "Έλεγχος ραφιού & αυτόματη αναπλήρωση"
# Αρχείο εικόνας μέσα στον φάκελο console/ (π.χ. ui/logo.svg).
PROJECT_LOGO = _env("PROJECT_LOGO") or "ui/logo.svg"

HOST = _env("HOST", "127.0.0.1")
PORT = int(_env("PORT", "8000"))
def lan_ip() -> str | None:
    """Η IP του laptop στο τοπικό δίκτυο (χωρίς να στέλνει πακέτο)."""
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return s.getsockname()[0]
    except OSError:
        return None


# Με HOST=0.0.0.0 ο server ακούει σε όλο το δίκτυο· το BASE_URL όμως δεν μπορεί να είναι 0.0.0.0,
# γιατί αυτή η διεύθυνση δεν ανοίγει από κινητό (τη χρησιμοποιούν τα μηνύματα του agent).
_BROWSE_HOST = (lan_ip() or "localhost") if HOST in ("0.0.0.0", "::") else HOST
BASE_URL = _env("BASE_URL", f"http://{_BROWSE_HOST}:{PORT}")
# Διεύθυνση για το κινητό αν μπαίνει από tunnel (π.χ. https://xxxx.trycloudflare.com). Κενό = η IP του laptop.
PUBLIC_URL = _env("PUBLIC_URL")

# --- Φάκελοι -----------------------------------------------------------
DATA_DIR = ROOT / "data"
# SHELF_SET: κενό = data/shelf (το ράφι του καφέ) · αλλιώς data/shelf/sets/<set>, με δική του βάση.
# Ισχύει για server, make_demo_data, eval_vision: SHELF_SET=trad python ...
SHELF_SET = _env("SHELF_SET")
SHELF_DIR = DATA_DIR / ("shelf/sets/" + SHELF_SET if SHELF_SET else "shelf")
DB_PATH = DATA_DIR / (f"demo_{SHELF_SET}.duckdb" if SHELF_SET else "demo.duckdb")
WORKSPACE = ROOT / "workspace"      # ό,τι παράγει ο agent (αναφορές, γραφήματα, στιγμιότυπα)
OUTBOX = WORKSPACE / "outbox"       # email που «στάλθηκαν» όταν δεν υπάρχει SMTP
RUNS_DIR = ROOT / "runs"            # ιστορικό κάθε εκτέλεσης (για replay)
for _d in (WORKSPACE, OUTBOX, RUNS_DIR):
    _d.mkdir(parents=True, exist_ok=True)
