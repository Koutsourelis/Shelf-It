# agentkit

A small, generic skeleton for building an agent that takes a goal, plans, uses tools and delivers
real work, with a live console that shows every step. This is the boilerplate the project started
from (the commits up to the `boilerplate` tag). See the README for what was built on top of it.

Code comments and agent prompts are in Greek. The structure is small enough to follow regardless.

## Run it in 5 minutes

Needs Python 3.10+.

```bash
python -m venv .venv
```

```bash
.venv\Scripts\activate
```

(macOS/Linux: `source .venv/bin/activate`)

```bash
pip install -r requirements.txt
```

```bash
python -m playwright install chromium
```

```bash
copy .env.example .env
```

(macOS/Linux: `cp .env.example .env`)

```bash
python scripts/make_demo_data.py
```

```bash
python scripts/check_setup.py
```

```bash
python -m agentkit.server
```

Open http://127.0.0.1:8000. With `LLM_PROVIDER=mock` (the default) everything runs with no API key
and no internet, using scripted steps. Set a real provider in `.env` to use a real model.

## What is in the box

| Piece | File | What it does |
|---|---|---|
| Agent loop | `agentkit/agent.py` | goal → plan → tool calls → result, with human approval gates |
| Model providers | `agentkit/llm/` | Claude, any OpenAI-compatible API (Gemini, Groq, OpenRouter…), offline mock; switch in `.env` |
| Tools | `agentkit/tools/` | files, SQL + charts, web search/fetch, browser (Playwright), email, PDF |
| Extract, then compute | `agentkit/tools/verify.py` | the model only extracts fields from documents; every number is computed by code; both are logged to an audit trail shown in the console and saved as `audit_<run>.json` |
| Scenarios | `agentkit/scenarios.py` | a role prompt + a tool list + example goals; add one for the challenge |
| Proactive triggers | `agentkit/watchers.py` | cheap checks that start the agent on their own when something changes |
| Channels | `agentkit/telegram.py` | send a goal from a phone, approve actions with buttons (long polling, no tunnel) |
| Console | `console/index.html` | live plan, steps, screenshots, approvals, deliverables; one static file, no build |
| Replay | `runs/*.jsonl` | every run is recorded and can be replayed in the console if the network dies |
| Presentation mode | `console/index.html` | key `P` or `?present=1`: larger type, less noise, for the projector; project name, tagline and logo come from `.env` |
| Headline result | `headline_result` tool | the agent states its one key number; the console shows it as a large card at the end of the run |
| Pitch kit | `pitch/` | slide template (`pitch.pptx`, rebuilt by `build_deck.py`), demo script and stage checklist, judge Q&A prep |
| Demo video | `scripts/record_demo.py` | records the console to a .webm while a run (live or replayed) plays |
| Demo material | `agentkit/demo_data.py`, `agentkit/portal.py` | synthetic wholesale data, invoices, bank statement, a fake supplier portal at `/portal` |

All demo data is synthetic. No real company, price or customer.

## Extending it

**New tool** — one function in `agentkit/tools/`, registered with `@tool(...)`, then add its name to a scenario:

```python
@tool("say_hi", "Greets someone.", {"name": {"type": "string", "description": "Name"}})
async def say_hi(ctx, name: str) -> str:
    return f"Hi {name}"
```

Use `needs_approval=True` for anything that acts on the outside world. New tool files must be
imported in `load_all()` in `agentkit/tools/__init__.py`.

**New scenario** — copy one in `agentkit/scenarios.py`, change the prompt and tool list, add it to `SCENARIOS`.

**New proactive trigger** — a function in `agentkit/watchers.py` returning `None` or `(key, goal)`, added to `WATCHERS`.

## Layout

```
agentkit/     core package (agent loop, llm providers, tools, server)
console/      the web console
scripts/      make_demo_data.py, check_setup.py
data/         demo inputs (generated; PDFs are committed, the database is rebuilt locally)
workspace/    what the agent produces (not committed)
runs/         recorded runs for replay (not committed)
```
