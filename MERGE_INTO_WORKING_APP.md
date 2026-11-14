# Merge into a working ShelfSense AR app

## What this branch contains

`demo-shelf-jpeg` contains the cached-demo image fix, the merge guide, and the
README alignment audit.

The branch changes four paths:

- `frontend/index.html`: removes the Screenshot PNG selector.
- `frontend/app.js`: loads exactly `/demo_shelf.jpg` for Cached Demo mode and
  displays `Demo image failed to load` when that asset cannot be loaded.
- `frontend/demo_shelf.jpg`: the single cached-demo shelf image.
- `backend/mock_server.py`: accepts `demo_shelf.jpg` as the cached dataset key
  so the frontend and backend use the same demo asset.
- `MERGE_INTO_WORKING_APP.md`: documents the merge, run, verification, and
  README-alignment steps.

The old `Screenshot*.png` files are intentionally outside the repository in
`~/private-shots/`.

## Merge the branch

From a clean checkout of the target repository:

```bash
git fetch origin
git switch main
git pull --ff-only origin main
git merge --no-ff origin/demo-shelf-jpeg
git push origin main
```

If the branch should be merged directly into the existing local branch:

```bash
git switch main
git pull --ff-only origin main
git merge --no-ff origin/demo-shelf-jpeg
git push origin main
```

Review the result before pushing:

```bash
git diff --check
git status
```

## Run the app

Keep API keys server-side. Do not commit `.env`; it is ignored by `.gitignore`.

```bash
set -a
source .env
set +a
.venv/bin/uvicorn backend.mock_server:app --port 8000
```

Open these URLs:

- `http://127.0.0.1:8000/` for the application.
- `http://127.0.0.1:8000/demo_shelf.jpg` to verify the cached image directly.

In the application:

1. Enable **Use cached demo (Plan B)**.
2. Click **Scan Shelf**.
3. Confirm the image is `/demo_shelf.jpg`, the trace reaches `step 8 of max 8`,
   and the overlay shows the source box and eye-level target.
4. Cached Demo displays the placement guide but intentionally does not claim
   that a physical move was verified. Use live Gemini mode with a new
   post-move image for physical placement verification.

## Verification performed for this branch

The following checks passed before committing:

```text
asset_status=200 content_type=image/jpeg bytes=188257
/tmp/demo-shelf.jpg: JPEG image data ... 738x718
product_to_move": "Blue and white canned goods"
```

Browser result:

```json
{
  "image": "/demo_shelf.jpg",
  "status": "Awaiting Product Move — AR Active",
  "steps": "step 8 of max 8",
  "rescanDisabled": false
}
```

Backend syntax validation:

```bash
python3 -m py_compile backend/mock_server.py
```

## Branches compared with the README

The available refs were audited against the architecture, API contract,
repository structure, and quickstart in
`ShelfSense AR Project README.md` (the repository does not contain a file named
`README.md`):

| Branch | README alignment |
| --- | --- |
| `main` (`fa61e87`) | Contains the working FastAPI/SSE frontend and backend, but still references the old Screenshot PNG selector. The README quickstart is stale: it names `backend.main:app`, while the repository uses `backend.mock_server:app`. The README's `treg`, `fal`, and `Oumi` integrations are represented by local/mock behavior rather than external service calls. |
| `demo-shelf-jpeg` (`b57ed28` locally) | Adds the single `frontend/demo_shelf.jpg` cached asset, removes the PNG selector, and documents the actual `backend.mock_server:app` startup. Gemini live detection, SSE tracing, feedback logging, and the cached fallback are present. The README still overstates external sponsor integrations and still describes the removed animated arrow. |
| `origin/demo-shelf-jpeg` (`1e51ed5` locally) | Same functional demo-image branch before the merge-guide commits. Its local remote-tracking ref is stale; run `git fetch origin` before relying on its commit ID. |

Important README mismatches that remain after merging:

- The README says the arrow is rendered in AR; the current branch intentionally
  shows a static source box and destination target instead of a fake animated
  arrow.
- The README describes separate `backend/main.py`, `vision_agent.py`, and
  `tools.py` modules; the actual implementation is consolidated in
  `backend/mock_server.py`.
- `treg`/Firecrawl, `fal`, and Oumi are currently simulated/local integrations;
  only Gemini live vision is an external provider.
- The README's sample result uses Organic Matcha Latte, while the verified
  cached dataset uses Blue and white canned goods.

The available remote branch was already present locally, but refreshing all
remote refs was not possible in the original environment because GitHub HTTPS
credentials were unavailable. No claim is made here about branches not listed
by `git branch -a`.
