# ShelfSense (working name)

> A shelf agent for supermarket department managers: take a photo of a shelf, and the agent finds what is missing or
> misplaced, prepares the refill from the backroom, orders what the backroom does not have, and checks again once the
> shelf is fixed.

**Team: start with [START_HERE.md](START_HERE.md).**

Built at the Gen AI Summit Hackathon, Athens, 14–15 November 2026. Track: Open Track (the phone camera is the hardware).

## What it does

1. **Sees.** A vision model turns the photo into a table: shelf, position, product, facings, bounding box.
2. **Compares.** Code checks that table against the planogram: missing products, too few facings, wrong shelf, wrong
   order. It draws the findings on the photo and reports a compliance score.
3. **Computes.** Code works out how many units to bring from the backroom, what has to be ordered in cases, and the
   daily sales at risk from products with no facing at all.
4. **Acts.** The agent sends the task list to the shelf worker and places the order with the central warehouse, after
   a human approves it.
5. **Suggests.** Up to two layout suggestions from category-management rules: share of space against share of sales,
   and margin per facing at eye level.
6. **Checks again.** A second photo after the fix shows before and after.

The model only reads the photo. Every number comes from code and is written to an audit trail shown in the console.

## Status

- The whole flow runs end to end with the offline mock model on two drawn sample shelves.
- **Not tested yet:** reading a real shelf photo with a real vision model.
- Product names, brands and sales in `data/shelf/` are invented placeholders. The warehouse portal is a simulation.

## Demo

- Video: _TODO link_
- 90-second path: start the server, open the console, click the first example. With a phone on the same network, open
  `/capture`, take a photo and watch the console.

## What was built during the hackathon

Everything after the `boilerplate` tag:

- Shelf tools: `read_shelf`, `check_planogram`, `replenishment_plan`, `layout_suggestions`, `order_from_warehouse`
  (`agentkit/tools/shelf.py`)
- Image input for the model providers (`agentkit/llm/structured.py`)
- Phone capture page and photo upload that starts the agent (`console/capture.html`, `/api/shelf/photo`)
- Trigger on a new photo in `workspace/photos` (`agentkit/watchers.py`)
- The shelf scenario: role, method, tool list (`agentkit/scenarios.py`)
- Shelf data model: catalogue, planogram, backroom stock, sales (`agentkit/demo_data.py`, `data/shelf/`)
- Central-warehouse ordering portal (`agentkit/portal.py`)

## What existed before (declared boilerplate)

The commits up to the `boilerplate` tag are a generic agent skeleton prepared before the event (in a private repo,
imported here on 14 November so the team starts from a clean history), as the rules allow for tooling and boilerplate.
It contained no project-specific logic: an agent loop, model providers, general tools (files, SQL, web, browser,
email, extract/compute with audit trail), a console that shows the agent's steps, run recording/replay and an empty
pitch template. The sample scenarios and sample data that came with it (sales analyst, procurement, invoices) were
removed when the project was chosen. Details: [SKELETON.md](SKELETON.md).

`git log` shows the split: the commits up to the `boilerplate` tag, then the hackathon work.

## Run it

Python 3.10+. Full steps in [START_HERE.md](START_HERE.md#4-στήσιμο-σε-laptop-5-λεπτά).

```bash
pip install -r requirements.txt
```

```bash
python scripts/make_demo_data.py
```

```bash
python scripts/check_setup.py
```

```bash
python -m agentkit.server
```

Open http://127.0.0.1:8000. With `LLM_PROVIDER=mock` (the default) it runs with no API key.

## How it works

```
photo (phone, /capture)
   → read_shelf          vision model: photo → table of products, facings, boxes
   → check_planogram     code: findings per product, compliance %, annotated photo
   → replenishment_plan  code: units from the backroom, cases to order, sales at risk
   → notify_user         task list for the shelf worker
   → order_from_warehouse  human approval, then the order is placed
   → layout_suggestions  code: space vs sales, eye level
   → second photo        before / after
```

## Team

- _Name — role_

## Third-party tools and credits

- _TODO: models, sponsor tools, libraries worth naming_
