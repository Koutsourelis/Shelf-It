# Shelf-it

**Shelf-it** turns a phone or aisle camera into an autonomous shelf-monitoring and merchandising system for supermarket teams. Built at the **Gen AI Summit Hackathon (Athens, 14–15 November 2026 — Open Track)**.

- **Who it is for:** Supermarket department managers and aisle staff in small-to-mid grocery stores that lack expensive fixed shelf sensors.
- **Problem:** ~8% of grocery SKUs are out of stock at any hour, and 43% of shoppers do not substitute inside the store (Gruen, Corsten & Bharadwaj, 2002) — yet manual shelf walks are slow, stockouts sit unnoticed for hours, and eye-level space goes to low-margin items.
- **Solution:** Point a phone (`/cam`, `/capture`, or Telegram) at the bay. Gemini reads the shelf, deterministic SQL checks backroom stock, dispatches cropped tasks to staff, places bounded warehouse orders automatically, and proposes sourced K1–K7 layout moves with printable `fal` shelf talkers.

> **Design invariant:** The vision model reads the shelf image; **every number** (missing units, backroom refills, warehouse cases, order totals, sales at risk, and margin per facing) is computed deterministically by Python and DuckDB SQL and recorded in an inspectable audit trail.

---

## What It Does

1. **Reads the shelf (`agentkit/vision/`):** A single structured call to **`gemini-3.8-flash`** (`responseSchema`) extracts visible products per tier (`top`, `eye`, `bottom`), facings, `[y0, x0, y1, x1]` bounding boxes (`0–1000`), misplaced SKUs, and visual gaps. Includes pixel-diff gating, dark/occluded frame rejection, and out-of-catalog shelf detection.
2. **Dispatches floor tasks & bounded orders (`agentkit/live.py`, `agentkit/tasks.py`, `agentkit/portal.py`):**
   - Creates prioritized worker tasks with cropped highlight thumbnails on `/tasks` and Telegram.
   - Places central-warehouse orders automatically within store guardrails (`AUTO_ORDER_MAX_CASES`, `AUTO_ORDER_MAX_EUR`) and holds larger orders for human approval.
   - Closes tasks automatically **only** when a subsequent scan confirms the shelf is fixed.
3. **Proposes sourced layout moves (`agentkit/rules.py`, `agentkit/tools/shelf.py`):** Evaluates category-management rules **K1–K7** over 28-day DuckDB sales and margin data (`layout_suggestions`, `propose_move`) and draws swap/facing arrows directly over the shelf feed.
4. **Closes the merchandising loop (`agentkit/recommendations.py`, `agentkit/feedback_api.py`, `agentkit/shelf_talker.py`, `agentkit/tools/evidence.py`):**
   - Stores append-only owner decisions (`accepted`, `rejected`, `corrected`) in SQLite.
   - Pulls external market & category evidence via **`treg`** (with automatic DuckDuckGo fallback) and curated Greek retail sources.
   - Generates printable PNG shelf talkers from owner-confirmed product names and prices via **`fal` (`fal-ai/flux/schnell`)** or an offline Pillow renderer.

---

## Quickstart

Requires **Python 3.11 or 3.12**.

### 1. Install & seed demo data

```bash
python -m venv .venv

# Windows:
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m playwright install chromium

# macOS / Linux:
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Build the local DuckDB database and verify the setup:

```bash
python scripts/make_demo_data.py
python scripts/check_setup.py
```

### 2. Configure `.env` (optional for offline `mock` mode)

With no `.env`, the app runs 100% offline using `LLM_PROVIDER=mock`. For live Gemini vision, agent reasoning, and optional integrations, copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

```env
LLM_PROVIDER=openai_compat
VISION_PROVIDER=gemini
GEMINI_API_KEY=your_google_ai_studio_key
GEMINI_MODEL=gemini-3.8-flash
GEMINI_THINKING_LEVEL=low
VISION_MAX_IMAGE_SIDE=1152

LIVE_INTERVAL_SECONDS=5
LIVE_CONFIRM_FRAMES=1
AUTO_ORDER=1
AUTO_ORDER_MAX_CASES=3
AUTO_ORDER_MAX_EUR=50

HOST=0.0.0.0
PORT=8000

# Optional integrations (all degrade gracefully when empty):
TELEGRAM_BOT_TOKEN=
FAL_KEY=
TREG_TOKEN=
```

### 3. Run the server

**Local / LAN:**
```bash
python -m agentkit.server
```

**With automatic HTTPS tunnel for mobile cameras (4G/5G or isolated guest Wi-Fi):**
```bash
python scripts/run_tunnel.py
```
`run_tunnel.py` downloads `cloudflared` if missing, opens a `trycloudflare.com` HTTPS tunnel, injects `PUBLIC_URL` in memory, and updates the pairing QR codes automatically.

Open **`http://localhost:8000`**.

---

## Application Screens

| Route | Purpose |
|---|---|
| `/` | Home overview, live shelf status, and mobile pairing QR codes (`Tasks`, `Live Cam`, `Photo`, `Telegram`) |
| `/shelf` | Department stage: live webcam or wireless mobile mirror, AR bounding boxes & swap arrows, tasks, K3–K7 proposals, shelf talkers, and timeline (`/shelf?dev=1` enables test controls) |
| `/cam` | Continuous mobile viewfinder (`getUserMedia` + Wake Lock): streams 1 FPS preview to `/shelf` and runs diff-gated Gemini scans hands-free |
| `/capture` | Single-photo mobile scanner (`<input capture>`): works over plain HTTP without camera stream permissions |
| `/tasks` | Store worker queue: prioritized tasks with cropped shelf photos; tasks auto-resolve on rescan |
| `/portal/orders` | Central warehouse portal showing automated and approved replenishment orders |
| `/dev` | Agent console: step-by-step tool calls, SQL queries, audit trail, run replay, and system readiness (`/dev?present=1` for presentation mode) |

---

## Architecture & Decision Rules

```text
Phone (/cam, /capture, Telegram) or Aisle Webcam (/shelf)
  │
  ├─► Live Fast Path (agentkit/live.py + agentkit/tasks.py)
  │     1. Luminance & 64×48 pixel-diff gate (skips unchanged / covered frames)
  │     2. Gemini structured shelf assessment (agentkit/vision/assessment.py)
  │     3. Deterministic SQL stock check → worker tasks + bounded warehouse orders
  │     4. Push alerts + inline action buttons on Web SSE & Telegram
  │
  └─► Merchandising Agent (agentkit/agent.py + agentkit/tools/)
        1. check_planogram & layout_suggestions (rules K1–K7 in DuckDB SQL)
        2. propose_move → SQLite recommendation store (agentkit/recommendations.py)
        3. Owner confirmation → product_evidence (treg/DDG) & PNG shelf talker (fal/Pillow)
```

### Category-Management Rules (`agentkit/rules.py`, `data/shelf/rules.json`)

| Rule | Principle | Grounding |
|---|---|---|
| **K1–K2** | Out-of-stock priority & backroom-first replenishment in full warehouse cases | Gruen, Corsten & Bharadwaj (2002) |
| **K3** | Facing transfer using space elasticity (`0.17`) when net daily margin > 0 | Eisend (2014) meta-analysis |
| **K4** | Highest daily euro margin per facing placed at eye level | Drèze, Hoch & Purk (1994); Chandon et al. (2009) |
| **K5** | Highest-margin eye-level SKU placed at horizontal center | Atalay, Bodur & Rasolofoarison (2012) |
| **K6** | Private-label SKU placed adjacent to the category brand leader | Sayman, Hoch & Raju (2002) |
| **K7** | High-velocity destination SKUs (`≥ 1.8×` mean unit share) placed bottom-right to free eye level | Merchandising destination rule |

### Shelf Datasets (`SHELF_SET`)

Switch datasets via `SHELF_SET` in `.env` (each builds its own `data/demo_<set>.duckdb`):
- **`""` (default — `data/shelf/`):** 9-SKU Greek coffee bay (`C01–C09`) with photorealistic before/after scenes.
- **`trad` (`data/shelf/sets/trad/`):** Real supermarket shelf photo paired with **Open Food Facts** barcode/brand metadata (`off_products.json`).
- **`drinks` (`data/shelf/sets/drinks/`):** 37-SKU Greek beer & soft-drink bay (`D01–D37`) with an 18-photo evaluation suite (`eval/`).

---

## Verification & Tests

All test suites run offline without API keys and leave runtime state untouched:

```bash
python -m unittest discover tests          # 63 unit & integration tests
python scripts/check_setup.py              # End-to-end mock agent, DuckDB, evidence & Playwright check
python scripts/check_recommendations.py    # 28 SQLite recommendation & feedback contract checks
python scripts/check_shelf_talker.py       # 41 shelf-talker composition & fal contract checks
python scripts/check_verification.py       # 88 rescan verification state-machine checks
```

To benchmark real Gemini vision accuracy against ground-truth `.truth.json` labels:
```bash
python scripts/eval_vision.py --runs 1
```

---

## Hackathon Scope & Boilerplate Disclosure

- **Declared pre-event boilerplate (up to git tag `boilerplate`):** Generic agent loop, provider wrappers, generic file/SQL/web/audit tools, `/dev` trace viewer, and empty pitch templates ([`SKELETON.md`](SKELETON.md)). All sample non-retail scenarios were removed at kickoff.
- **Built during the 36-hour hackathon (`boilerplate..HEAD`):** Native Gemini vision client & single-call shelf assessment (`agentkit/vision/`), live camera loop & wireless mobile mirror (`agentkit/live.py`, `console/cam.html`, `console/shelf.html`), worker task engine & bounded auto-ordering (`agentkit/tasks.py`, `agentkit/portal.py`), rules K1–K7 (`agentkit/rules.py`), Open Food Facts & multi-dataset support (`agentkit/off.py`, `data/shelf/sets/`), market evidence packs (`agentkit/tools/evidence.py`), append-only recommendation store & printable shelf talkers (`agentkit/recommendations.py`, `agentkit/feedback_api.py`, `agentkit/shelf_talker.py`), interactive Telegram bot (`agentkit/telegram.py`), Apple HIG Light/Dark UI (`console/`, `DESIGN.md`), and Cloudflare HTTPS launcher (`scripts/run_tunnel.py`).

---

## Third-Party Tools & Credits

- **Google AI (`gemini-3.8-flash`)** — Structured multimodal shelf perception, `0–1000` spatial bounding boxes, and agent tool reasoning.
- **`treg` & DuckDuckGo** — Category demand trends and Greek grocery trade press evidence.
- **`fal` (`fal-ai/flux/schnell`) & Pillow** — Decorative shelf-talker background generation composed locally with confirmed product copy and prices.
- **Open Food Facts** — Real barcode, brand, and pack-size metadata (`ODbL`).
- **FastAPI, DuckDB, SQLite, Playwright & Cloudflared** — Backend runtime, SQL analytics, append-only state, browser automation, and mobile HTTPS tunneling.
