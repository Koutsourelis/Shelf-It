# Shelf-It deck

A self-contained slide deck (one `index.html`, no build step) that reads without a presenter.

- **Navigate:** ← → (or Space, Page Up/Down, Home/End), the round buttons, or swipe on a phone. Each slide has its own URL (`#1` … `#12`).
- **Motion:** each slide animates when it opens (scan and detection boxes, tool calls typing out, counters, a live agent network in the background). Press **R** to replay a slide. Viewers with reduced motion turned on get the same slides without animation.
- **PDF:** open the page in Chrome, Print, "Save as PDF". Every slide prints as one 1600×900 page.
- **Edit links, video and team:** the `DECK` object at the top of the `<script>` in `index.html`. An empty `video` hides the demo buttons.
- **Run locally:** `python -m http.server 8040 --directory slides`, then open `http://localhost:8040`.

## Deploy on Vercel

The deck lives on the branch `p3/slides`, folder `slides/`. Either way below works.

**A. From the command line (no GitHub connection needed, works for any team member):**

```bash
git fetch origin
git switch p3/slides
npx vercel deploy slides --prod
```

The first run asks you to log in and to create a project; accept the defaults (no build command, no output directory).

**B. From the Vercel dashboard (needs the Vercel GitHub app on the repo owner's account):**

1. Add New → Project → import the GitHub repo.
2. Framework Preset: **Other**. Root Directory: **`slides`**.
3. Settings → Git → Production Branch: **`p3/slides`** (until the branch is merged into `main`). Otherwise only a
   preview deployment is built, and Vercel may put previews behind a login.
