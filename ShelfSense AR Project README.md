# ShelfSense AR — Autonomous Retail Merchandising Agent

> **Gen AI Summit Hackathon (Athens, Nov 14–15, 2026)**  
> **Deadline:** Sunday, Nov 15 at 7:00 PM EET (Finalists pitch Monday on the SNFCC stage)  
> **Core Mandate:** *"One user. One job, end to end. One wow moment."* — *Not a pitching competition, it's an agent at work.*

---

## 1. The Problem & Core Idea

Independent café, kiosk, and pharmacy owners lose up to **20% in impulse sales** because high-margin, trending items sit buried on bottom shelves while slow movers hog prime eye-level space (*"eye level is buy level"*). Unlike major supermarket chains, small shop owners do not have category managers watching daily consumer trends.

**ShelfSense AR** turns a standard `localhost` web browser and camera into an autonomous retail merchandiser:
1. **Perceive:** The owner selects a **Target Audience** (e.g., *Morning Commuters*, *Tourists*, *Students*) and captures a live shelf photo.
2. **Reason & Check Trends:** **Google Gemini** detects every product and its shelf height tier, while **`treg` / Firecrawl Search** checks live demand trends for those categories (no fragile website scraping).
3. **Guide in AR:** Using Gemini's normalized `0–1000` spatial coordinates, the app draws an **amber bounding box** around the misplaced product, a **pulsing green target circle** at eye level, and a **directional arrow** explaining why moving it boosts revenue.
4. **Act & Improve:** **`fal`** generates a print-ready promotional shelf talker for the newly featured product, and **`Oumi`** logs owner accept/override decisions to continuously improve store recommendations.

---

## 2. Sponsor Tool Architecture

```text
[Localhost Browser: Webcam + Split-Screen UI]
       │  (JPEG Frame + Target Audience)
       ▼
[FastAPI Backend + SSE Live Event Stream]
       ├──► 1. Google AI (Gemini Multimodal): Identifies SKUs, shelf tiers & 0–1000 spatial coords
       ├──► 2. treg / Firecrawl Search: Fetches live category demand & seasonal trends
       ├──► 3. Google AI (Planogram Planner): Selects optimal swap & calculates projected lift
       ├──► 4. fal: Generates a print-ready eye-level promo shelf-talker graphic
       └──► 5. Oumi Trace Logger: Saves placement + owner feedback for post-training/evals
```

| Sponsor Tool | Role in ShelfSense AR |
| :--- | :--- |
| **Google AI (Gemini)** | Multimodal shelf perception, shelf-tier classification, and structured `0–1000` spatial coordinates (`box_2d` + target `point`). |
| **treg / Firecrawl** | Live demand and trend lookup via search/trend endpoints (eliminates brittle e-commerce domain scraping). |
| **fal** | Fast generation of a customized, print-ready promo shelf tag / QR card for the recommended eye-level product. |
| **Oumi** | Captures human-in-the-loop accept/reject feedback traces to fine-tune merchandising accuracy over time. |

---

## 3. The 3-Minute Pitch Script (Kickoff Format)

We build **only** what supports these three exact beats:

* **`0:00` — The Person (1 sentence, no market-size slides):**
  > *"Independent café and kiosk owners lose up to 20% in impulse sales because high-margin, trending items sit buried on bottom shelves while slow movers hog eye level."*
* **`0:20` — The Live Demo (Trigger the agent, then stop talking while it works):**
  1. Point the webcam at our 2-tier physical product display on the table, select **Morning Commuters**, and click **Scan Shelf**.
  2. **Left Pane ("Show the work"):** Streams live agent steps—detected SKUs, `treg` trend spikes, and spatial reasoning traces.
  3. **Right Pane ("The Wow Moment"):** Snaps an **amber box** around the trending item on the lower tier, draws a **green target circle** and **curved arrow** to the prime eye-level spot, and renders the **`fal` promo shelf talker**.
* **`2:30` — What's Next (1 more week):**
  > *"Connecting checkout POS logs so Oumi automatically reinforces shelf placements that lift real daily revenue."*

---

## 4. Shared API & JSON Contract (Lock This First)

Backend and Frontend work in parallel against this exact payload structure. All coordinates use Gemini's native **`0–1000` normalized scale** (`[y_min, x_min, y_max, x_max]` and `[y, x]`) so canvas overlays scale cleanly across any screen resolution.

### `POST /api/analyze-shelf` (or SSE Stream `/api/analyze-stream`)
**Request (`multipart/form-data` or JSON):**
```json
{
  "image_base64": "<base64_jpeg>",
  "target_audience": "Morning Commuters",
  "use_cached_demo": false
}
```

**Streamed Trace Events (SSE):**
```json
{"step": "vision", "status": "done", "detail": "Detected 6 products across 2 shelf tiers"}
{"step": "trends", "status": "done", "detail": "Matcha Latte trending +38% for Morning Commuters"}
{"step": "planogram", "status": "done", "detail": "Recommended bottom-to-eye-level swap"}
{"step": "creative", "status": "done", "detail": "Generated print-ready shelf talker via fal"}
```

**Final Result Payload:**
```json
{
  "detected_items": [
    {
      "name": "Organic Matcha Latte Can",
      "shelf_tier": "bottom",
      "box_2d": [680, 140, 910, 290],
      "trend_score": 92
    },
    {
      "name": "Plain Sparkling Water",
      "shelf_tier": "eye_level",
      "box_2d": [210, 410, 450, 560],
      "trend_score": 34
    }
  ],
  "recommendation": {
    "product_to_move": "Organic Matcha Latte Can",
    "move_from_box": [680, 140, 910, 290],
    "move_to_point": [330, 485],
    "displaced_item": "Plain Sparkling Water",
    "reason": "High commuter morning demand (+38%) and higher margin; currently hidden on bottom tier.",
    "projected_sales_lift": "+18% to +24%"
  },
  "shelf_talker_image_url": "https://fal.media/files/...",
  "trace_id": "run_20261115_001"
}
```

---

## 5. 5-Person Team Division

| Role | Owner | Responsibilities & Deliverables |
| :--- | :--- | :--- |
| **1. Vision & Spatial Agent** | Backend Dev 1 | FastAPI server, Gemini multimodal prompt + structured JSON schema returning accurate `box_2d` and `move_to_point` coordinates. |
| **2. Trends, `fal` & `Oumi`** | Backend Dev 2 | `treg` / Firecrawl search trend lookup, `fal` shelf-talker image generation, and `Oumi` JSONL feedback logging endpoint (`/api/feedback`). |
| **3. Live Trace & Plan B UI** | Frontend Dev 1 | Split-screen dashboard streaming SSE reasoning steps in real time + **Demo Preset (Plan B)** cached toggle for Wi-Fi insurance. |
| **4. Camera & AR `<canvas>`** | Frontend Dev 2 | `localhost` webcam capture (`getUserMedia`) + file upload fallback + HTML5 `<canvas>` renderer drawing the amber box, green circle, and Bézier arrow. |
| **5. Demo Director & QA** | Product / Pitch Lead | Stages 5–6 physical products on a 2-tier riser, stress-tests lighting/angles, enforces the 3-minute script, and records the backup video by Sunday 5:30 PM. |

---

## 6. Repository Structure

```text
GenAI-Hackathon/
├── .devcontainer/          # Podman/VS Code Fedora container setup
├── backend/
│   ├── main.py             # FastAPI app + SSE streaming endpoints
│   ├── vision_agent.py     # Google Gemini spatial detection & planogram logic
│   ├── tools.py            # treg/Firecrawl trends, fal creative gen, Oumi trace logger
│   └── cached_demo.json    # Plan B verified stage run
├── frontend/
│   ├── index.html          # Single-page split-screen UI + AR canvas overlay
│   └── app.js              # Webcam capture, SSE listener & 0–1000 canvas drawing
├── .env                    # API keys (gitignored)
├── .env.example            # Template for team API keys
└── README.md
```

---

## 7. Quickstart (Localhost Setup)

1. **Configure API Keys:**
   ```bash
   cp .env.example .env
   # Add GEMINI_API_KEY, TREG_API_KEY, FIRECRAWL_API_KEY, FAL_KEY, OUMI_API_KEY
   ```
2. **Activate Environment & Run Backend:**
   ```bash
   source .venv/bin/activate
   uvicorn backend.main:app --reload --port 8000
   ```
3. **Open in Browser:**
   Navigate to `http://localhost:8000` (secure context enabled automatically for webcam access).

---

## 8. Hackathon Survival Rules (From Kickoff)
- **Demo First:** Test real physical table items early—never use *lorem ipsum*.
- **Show the Work:** Keep tool calls and reasoning visible on screen while the agent runs.
- **Have a Plan B:** Cache one verified run in `cached_demo.json` and record a clean screen capture by **Sunday 5:30 PM** before the 7:00 PM submission cutoff.