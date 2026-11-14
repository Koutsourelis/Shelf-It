# Instructions for AI coding assistants

For anyone on the team who works on this repo with an AI assistant (Claude, ChatGPT, Codex, Cursor or other).
Point your assistant at this file first.

## Read first

1. [`START_HERE.md`](START_HERE.md): map of the repo, open decisions, schedule.
2. [`planning/DECISIONS.md`](planning/DECISIONS.md): what the team has decided. Do not reopen a decision without asking.
3. [`SKELETON.md`](SKELETON.md): how the code is organised and how to extend it.

## Rules

- **Secrets:** API keys, passwords and tokens never go in a file in this repo, in a commit message or in an issue.
  They live only in each person's local `.env`, which `.gitignore` already excludes. Never print `.env`.
- **Data:** synthetic or public only. Never data from anyone's employer.
- **Git:** code reaches `main` only through a pull request with a green `check`; steps in
  [`planning/WORKFLOW.md`](planning/WORKFLOW.md). Work on a short branch named `p<role number>/<topic>` cut from fresh
  `main`, run `python scripts/check_setup.py` before each commit, keep commits small, merge every 1–2 hours. Notes
  (`.md` in `planning/` and `pitch/`) may go straight to `main` after `git pull --rebase`. Never `push --force`, never
  delete someone else's branch or the `boilerplate` tag. Do not commit the files `scripts/make_demo_data.py`
  regenerates in `data/`.
- **Numbers come from code:** the model extracts and plans; every figure is computed by SQL or the `compute` tool and
  shows up in the audit trail.
- **Outward actions need approval:** tools that send, order or pay use `needs_approval=True`.
- **Boilerplate:** everything up to the `boilerplate` tag was prepared before the event and is declared in the README.
  Hackathon work starts after it.
- **Language:** Greek for team notes in `planning/`, English for code, README and slides.

## Where things go

| What | Where |
|---|---|
| New tool | `agentkit/tools/`, registered with `@tool(...)`, imported in `load_all()` |
| Role prompt and tool list | `agentkit/scenarios.py` |
| Proactive trigger | `agentkit/watchers.py` |
| Demo data | `agentkit/demo_data.py` |
| Decisions | one line in `planning/DECISIONS.md`, at the moment they are made |
