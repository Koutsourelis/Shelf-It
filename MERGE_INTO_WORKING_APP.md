# Merge into a working ShelfSense AR app

## What this branch contains

`demo-shelf-jpeg` is based on local `main` commit `fa61e87` and adds commit
`1e51ed5` (`Use demo_shelf.jpg for cached demo`).

The branch changes four paths:

- `frontend/index.html`: removes the Screenshot PNG selector.
- `frontend/app.js`: loads exactly `/demo_shelf.jpg` for Cached Demo mode and
  displays `Demo image failed to load` when that asset cannot be loaded.
- `frontend/demo_shelf.jpg`: the single cached-demo shelf image.
- `backend/mock_server.py`: accepts `demo_shelf.jpg` as the cached dataset key
  so the frontend and backend use the same demo asset.

The old `Screenshot*.png` files are intentionally outside the repository in
`~/private-shots/`.

## Merge the branch

From a clean checkout of the target repository:

```bash
git fetch origin
git switch main
git pull --ff-only origin main
git switch -c demo-shelf-jpeg
git merge --no-ff origin/demo-shelf-jpeg
```

If the branch should be merged directly into the existing local branch:

```bash
git switch main
git pull --ff-only origin main
git merge --no-ff origin/demo-shelf-jpeg
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
4. Cached Demo does not claim that a physical move was verified. Use live Gemini
   mode with a new post-move image for physical placement verification.

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

## Repository comparison note

The local full comparison against `main` contains only the four paths listed
above. `git diff --check main...HEAD` produced no output. A fresh
`git fetch --all --prune` could not be completed in the original environment
because GitHub HTTPS credentials were unavailable; the branch had already been
confirmed pushed to `origin/demo-shelf-jpeg`.
