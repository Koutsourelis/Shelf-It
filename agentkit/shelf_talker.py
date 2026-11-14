"""Shelf talker: decorative artwork from fal, exact product name and price rendered locally with Pillow.

Used by the make_shelf_talker tool (agentkit/tools/talker.py). Nothing here runs on its own.

Flow (generate()):
  1. confirmed_inputs(): load the stored recommendation (agentkit/recommendations.py) and take the product name
     and price ONLY from owner feedback with correction_source "owner_input". The producer's own name/price and a
     plain "accepted" decision do not count as confirmation. The latest decision must not be "rejected".
     The caller's product_name / price_amount / currency must match those values exactly.
  2. A private job record is written to state/talkers/<talker_id>.json BEFORE the billable request.
  3. fal queue API (https://fal.ai/docs/model-apis/model-endpoints/queue), model fal-ai/flux/schnell:
     POST https://queue.fal.run/fal-ai/flux/schnell, then poll the returned status_url, then GET response_url.
     The provider request_id is saved as soon as the submit response arrives.
  4. The image is downloaded from its own host with a separate client that has NO auth header.
  5. Pillow composes the final PNG: artwork on top, the confirmed name and price in a text panel below.
     The artwork prompt never contains the product name, a price, a brand or any text.
  6. The PNG is written to workspace/talkers/ (served at /files/talkers/...) and verified by re-opening it.

No blind resubmission: if a submit may have reached fal but no request_id came back (timeout after sending,
5xx), the record stays "submit_ambiguous" and every later call for the same inputs refuses to submit again.
A human checks https://fal.ai/dashboard and then deletes that record file to allow a new attempt.
A record with a request_id that has not finished is RESUMED (polled again), never resubmitted.
Only a request that fal itself reported as failed (or returned an unusable image) allows a new submission.

The private record (state/ is gitignored and not served) holds: recommendation_id, the inputs used, the fal
arguments, the model ID the request was submitted to, the provider request_id, the timings, generated_at and
the PNG's sha256. Tool results and the public audit trail carry no request_id and no URLs with credentials.
FAL_KEY is read from the environment (agentkit/config.py loads .env); it is never logged or returned.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import httpx
from PIL import Image, ImageDraw, ImageFont, ImageStat

from . import config
from . import recommendations as store

MODEL_ID = "fal-ai/flux/schnell"
QUEUE_HOST = "queue.fal.run"
SUBMIT_URL = f"https://{QUEUE_HOST}/{MODEL_ID}"
# Status/result URLs use owner/app only ("fal-ai/flux"), not the full model ID (fal queue docs).
_APP_BASE = f"https://{QUEUE_HOST}/fal-ai/flux/requests"

# Time budget. The agent wraps every tool call in a 120 s timeout (agentkit/agent.py); stay well inside it.
TOTAL_BUDGET_S = 100.0
SUBMIT_TIMEOUT_S = 20.0
POLL_TIMEOUT_S = 10.0
POLL_INTERVAL_S = 1.5
RESULT_TIMEOUT_S = 20.0
DOWNLOAD_TIMEOUT_S = 30.0
MAX_IMAGE_BYTES = 25 * 1024 * 1024

ART_REQUEST = {"width": 1024, "height": 768}
CANVAS = (1200, 1600)
ART_HEIGHT = 1000

STATE_DIR: Optional[Path] = None        # None = <repo>/state/talkers (private, gitignored)
OUTPUT_SUBDIR = "talkers"               # under config.WORKSPACE, published at /files/talkers/

THEMES = {
    "fresh": "soft flowing organic shapes in fresh green, lime and cream tones, delicate leaf silhouettes near the edges",
    "warm": "soft flowing abstract shapes in warm terracotta, honey and cream tones, gentle sunlight gradients",
    "cool": "soft flowing abstract waves in calm blue, teal and white tones, light watercolor texture",
    "festive": "soft abstract confetti dots and ribbons in red, gold and cream tones, subtle sparkle",
    "minimal": "very simple abstract geometric shapes in pastel tones on an off-white background, lots of empty space",
}
_NO_TEXT = ("Pure decorative pattern only. Absolutely no text, no letters, no numbers, no words, no typography, "
            "no logos, no brand marks, no packaging, no products, no bottles, no boxes, no price tags, no labels, "
            "no signs, no discount badges, no people.")

FONT_CANDIDATES = [
    os.environ.get("TALKER_FONT", "").strip(),
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/noto/NotoSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/arial.ttf",
]

_TALKER_ID = re.compile(r"^[0-9a-f]{20}$")
_locks: dict[str, asyncio.Lock] = {}


class TalkerError(Exception):
    """An honest, explicit refusal or failure. `status` is the machine-readable outcome."""

    def __init__(self, status: str, message: str, **extra: Any):
        super().__init__(message)
        self.status = status
        self.message = message
        self.extra = extra

    def result(self) -> dict:
        return {"status": self.status, "message": self.message, **self.extra}


# --- confirmed inputs --------------------------------------------------------

@dataclass(frozen=True)
class ConfirmedInputs:
    recommendation_id: str
    product_name: str
    amount: Decimal
    currency: str
    name_feedback_id: int
    price_feedback_id: int
    price_source: str


def _cents(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise TalkerError("invalid_input", "price_amount must be a number")
    try:
        d = Decimal(str(value))
    except Exception:
        raise TalkerError("invalid_input", "price_amount must be a number") from None
    if not d.is_finite() or d <= 0:
        raise TalkerError("invalid_input", "price_amount must be greater than 0")
    q = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if q != d:
        raise TalkerError("invalid_input", f"price_amount {value} has more than 2 decimals; refusing to round a price")
    return q


def confirmed_inputs(recommendation_id: str) -> tuple[Optional[ConfirmedInputs], list[str], dict]:
    """What the owner has confirmed for this recommendation. Returns (inputs or None, missing[], summary).

    Raises TalkerError("not_found") for an unknown ID. Pure read; never writes.
    """
    try:
        rec = store.get_recommendation(recommendation_id)
    except store.RecommendationNotFound:
        raise TalkerError("not_found", f"No stored recommendation with id {recommendation_id!r}.") from None
    history = rec["feedback_history"]
    current = rec["current_feedback"]
    missing: list[str] = []
    summary = {"recommendation_id": recommendation_id,
               "current_decision": current["decision"] if current else None,
               "producer_product": rec["recommendation"].get("product"),
               "producer_price": rec["recommendation"].get("price")}
    if current is None:
        missing.append("owner decision (no feedback recorded for this recommendation)")
    elif current["decision"] == "rejected":
        missing.append("a non-rejected owner decision (the latest owner decision is 'rejected')")

    name_row = price_row = None
    for row in history:                    # oldest first, so the latest owner input wins
        corr = row.get("correction") or {}
        if row.get("correction_source") != "owner_input":
            continue
        product = corr.get("product") or {}
        if isinstance(product.get("name"), str) and product["name"].strip():
            name_row = row
        price = corr.get("price") or {}
        if price.get("amount") is not None and price.get("currency"):
            price_row = row
    if name_row is None:
        missing.append("owner-confirmed product name (feedback correction.product.name from the owner; "
                       "the producer's name and a plain 'accepted' decision do not count)")
    if price_row is None:
        missing.append("owner-confirmed price and currency (feedback correction.price {amount, currency, source} "
                       "from the owner; the producer's price and a plain 'accepted' decision do not count)")
    if missing:
        return None, missing, summary
    price = price_row["correction"]["price"]
    inputs = ConfirmedInputs(
        recommendation_id=recommendation_id,
        product_name=name_row["correction"]["product"]["name"],
        amount=_cents(price["amount"]),
        currency=price["currency"],
        name_feedback_id=name_row["feedback_id"],
        price_feedback_id=price_row["feedback_id"],
        price_source=str(price.get("source") or ""),
    )
    return inputs, [], summary


def check_request(recommendation_id: str, product_name: Any, price_amount: Any, currency: Any) -> ConfirmedInputs:
    """Validate the caller's values against the owner-confirmed ones. Raises TalkerError on any gap."""
    if not isinstance(recommendation_id, str) or not recommendation_id.strip():
        raise TalkerError("missing_inputs", "recommendation_id is required", missing=["recommendation_id"])
    asked_missing = [k for k, v in (("product_name", product_name), ("price_amount", price_amount),
                                    ("currency", currency)) if v is None or (isinstance(v, str) and not v.strip())]
    conf, missing, summary = confirmed_inputs(recommendation_id)
    if conf is None or asked_missing:
        raise TalkerError("missing_inputs", "Shelf talker not generated: confirmed inputs are missing.",
                          missing=asked_missing + missing, recommendation=summary)
    mismatches = []
    if product_name != conf.product_name:
        mismatches.append(f"product_name {product_name!r} differs from the owner-confirmed {conf.product_name!r}")
    if _cents(price_amount) != conf.amount:
        mismatches.append(f"price_amount {price_amount} differs from the owner-confirmed {conf.amount}")
    if currency != conf.currency:
        mismatches.append(f"currency {currency!r} differs from the owner-confirmed {conf.currency!r}")
    if mismatches:
        raise TalkerError("input_mismatch", "Shelf talker not generated: values do not match what the owner confirmed.",
                          mismatches=mismatches)
    return conf


def price_text(amount: Decimal, currency: str) -> str:
    """Greek formatting: 1.234,50 € for EUR, 12,00 USD for other ISO codes."""
    whole, cents = f"{amount:.2f}".split(".")
    groups = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    number = ".".join(groups) + "," + cents
    return f"{number} €" if currency == "EUR" else f"{number} {currency}"


# --- private job records ---------------------------------------------------------

def state_dir() -> Path:
    d = Path(STATE_DIR) if STATE_DIR is not None else config.ROOT / "state" / "talkers"
    d = d.resolve()
    public = config.WORKSPACE.resolve()
    if d == public or public in d.parents:
        raise TalkerError("config_error", "talker metadata must not be stored under workspace/ (served at /files)")
    d.mkdir(parents=True, exist_ok=True, mode=0o700)
    return d


def talker_id(conf: ConfirmedInputs, theme: str) -> str:
    key = json.dumps([conf.recommendation_id, conf.product_name, str(conf.amount), conf.currency, theme, MODEL_ID],
                     ensure_ascii=False)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]


def _record_path(tid: str) -> Path:
    if not _TALKER_ID.match(tid):
        raise TalkerError("config_error", "invalid talker id")
    return state_dir() / f"{tid}.json"


def load_record(tid: str) -> Optional[dict]:
    p = _record_path(tid)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def _save_record(rec: dict) -> None:
    p = _record_path(rec["talker_id"])
    rec["updated_at"] = _now()
    tmp = p.with_name(f".{p.name}.{uuid.uuid4().hex[:6]}.tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


# --- fal queue client ---------------------------------------------------------------

def art_prompt(theme: str) -> str:
    return ("Decorative background artwork for a printed supermarket shelf sign, flat illustration, high quality: "
            f"{THEMES[theme]}. The center of the image is calm and uncluttered. {_NO_TEXT}")


def fal_arguments(theme: str) -> dict:
    return {"prompt": art_prompt(theme), "image_size": dict(ART_REQUEST), "num_inference_steps": 4,
            "num_images": 1, "enable_safety_checker": True, "output_format": "png"}


def _fal_key() -> str:
    key = os.environ.get("FAL_KEY", "").strip()
    if not key:
        raise TalkerError("not_configured", "FAL_KEY is not set in the environment (.env); no request was sent.")
    return key


def _queue_url(url: Any, fallback: str) -> str:
    """Only ever send the key to https://queue.fal.run. Anything else falls back to the documented URL."""
    if isinstance(url, str):
        u = urlparse(url)
        if u.scheme == "https" and u.hostname == QUEUE_HOST and not u.username and not u.password:
            return url
    return fallback


class _Clock:
    def __init__(self, budget: float):
        self.deadline = time.monotonic() + budget

    def left(self) -> float:
        return self.deadline - time.monotonic()

    def timeout(self, step: float) -> float:
        return max(0.5, min(step, self.left()))


async def _submit(client: httpx.AsyncClient, key: str, args: dict, clock: _Clock) -> dict:
    """POST the job. Returns the submit JSON, or raises TalkerError with status
    'submit_failed' (definitely not accepted) or 'submit_ambiguous' (may have been accepted)."""
    try:
        r = await client.post(SUBMIT_URL, json=args, timeout=clock.timeout(SUBMIT_TIMEOUT_S),
                              headers={"Authorization": f"Key {key}", "Content-Type": "application/json"})
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.UnsupportedProtocol) as e:
        raise TalkerError("submit_failed", f"Could not connect to fal; nothing was submitted ({type(e).__name__}).")
    except httpx.HTTPError as e:
        raise TalkerError("submit_ambiguous", f"The submit to fal may or may not have been accepted "
                                              f"({type(e).__name__}); not resubmitting.")
    if 400 <= r.status_code < 500:
        raise TalkerError("submit_failed", f"fal rejected the submit with HTTP {r.status_code}: {_detail(r)}")
    if r.status_code >= 500:
        raise TalkerError("submit_ambiguous", f"fal answered the submit with HTTP {r.status_code}; "
                                              "it may have been queued, not resubmitting.")
    try:
        body = r.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or not isinstance(body.get("request_id"), str) or not body["request_id"]:
        raise TalkerError("submit_ambiguous", f"fal answered HTTP {r.status_code} without a request_id; "
                                              "not resubmitting.")
    return body


def _detail(r: httpx.Response) -> str:
    try:
        body = r.json()
        text = body.get("detail") or body.get("error") or body if isinstance(body, dict) else body
    except ValueError:
        text = r.text
    return str(text)[:300]


async def _poll(client: httpx.AsyncClient, key: str, rec: dict, clock: _Clock) -> Optional[dict]:
    """Poll until COMPLETED. Returns the final status JSON, or None if the time budget ran out."""
    url = _queue_url(rec.get("status_url"), f"{_APP_BASE}/{rec['request_id']}/status")
    while clock.left() > 1.0:
        try:
            r = await client.get(url, timeout=clock.timeout(POLL_TIMEOUT_S), headers={"Authorization": f"Key {key}"})
            if r.status_code in (200, 202):
                body = r.json()
                status = body.get("status")
                rec["provider_status"] = status
                if status == "COMPLETED":
                    return body
            else:
                rec["last_error"] = f"status HTTP {r.status_code}"
        except (httpx.HTTPError, ValueError) as e:
            rec["last_error"] = f"status poll {type(e).__name__}"
        await asyncio.sleep(min(POLL_INTERVAL_S, max(0.0, clock.left() - 1.0)))
    return None


async def _result(client: httpx.AsyncClient, key: str, rec: dict, clock: _Clock) -> Optional[dict]:
    url = _queue_url(rec.get("response_url"), f"{_APP_BASE}/{rec['request_id']}")
    try:
        r = await client.get(url, timeout=clock.timeout(RESULT_TIMEOUT_S), headers={"Authorization": f"Key {key}"})
    except httpx.HTTPError as e:
        rec["last_error"] = f"result fetch {type(e).__name__}"
        return None
    if r.status_code != 200:
        rec["last_error"] = f"result HTTP {r.status_code}: {_detail(r)}"
        return None
    try:
        return r.json()
    except ValueError:
        rec["last_error"] = "result was not JSON"
        return None


async def _download(url: str, clock: _Clock, transport: Optional[httpx.AsyncBaseTransport]) -> bytes:
    """Fetch the image from its own host. Fresh client, NO auth header, https only, size-capped."""
    u = urlparse(url)
    if u.scheme != "https" or not u.hostname:
        raise TalkerError("provider_failed", "fal returned an image URL that is not https; not downloading it.")
    async with httpx.AsyncClient(transport=transport, follow_redirects=True, max_redirects=3) as anon:
        async with anon.stream("GET", url, timeout=clock.timeout(DOWNLOAD_TIMEOUT_S)) as r:
            if r.status_code != 200:
                raise httpx.HTTPStatusError(f"image HTTP {r.status_code}", request=r.request, response=r)
            buf = bytearray()
            async for chunk in r.aiter_bytes():
                buf.extend(chunk)
                if len(buf) > MAX_IMAGE_BYTES:
                    raise TalkerError("provider_failed", "fal image is larger than the size cap; not using it.")
    return bytes(buf)


# --- local renderer ---------------------------------------------------------------------

def _glyph_pixels(font: ImageFont.FreeTypeFont, ch: str) -> bytes:
    img = Image.new("L", (font.size * 2, font.size * 2), 0)
    ImageDraw.Draw(img).text((font.size // 2, font.size // 2), ch, font=font, fill=255)
    return img.tobytes()


def _missing_glyph(font: ImageFont.FreeTypeFont, ch: str) -> bool:
    """True if `ch` renders like the font's .notdef box (a private-use code point no font maps)."""
    if ch.isspace():
        return False
    return _glyph_pixels(font, ch) == _glyph_pixels(font, "\ue000")


def pick_font(text: str, size: int = 64) -> str:
    """First candidate font file that has a glyph for every character in `text` (Greek included)."""
    for path in FONT_CANDIDATES:
        if not path or not Path(path).is_file():
            continue
        try:
            font = ImageFont.truetype(path, size)
        except OSError:
            continue
        if not any(_missing_glyph(font, ch) for ch in set(text)):
            return path
    raise TalkerError("render_failed", "No installed font covers every character of the product name and price; "
                                       "set TALKER_FONT to a .ttf with Greek glyphs.")


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_w: int) -> Optional[list[str]]:
    lines, line = [], ""
    for word in text.split():
        if draw.textlength(word, font=font) > max_w:
            return None                     # never split a word or cut text; caller shrinks the font
        trial = f"{line} {word}" if line else word
        if draw.textlength(trial, font=font) <= max_w:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _fit_lines(draw, text, font_path, max_w, max_h, start, stop, max_lines):
    for size in range(start, stop - 1, -2):
        font = ImageFont.truetype(font_path, size)
        lines = _wrap(draw, text, font, max_w)
        if lines is None or len(lines) > max_lines:
            continue
        line_h = int(size * 1.18)
        if line_h * len(lines) <= max_h:
            return font, lines, line_h
    return None


def render(art_png: bytes, product_name: str, price: str) -> Image.Image:
    """Compose the final talker. The text is exactly `product_name` and `price`, never altered or truncated."""
    try:
        art = Image.open(io.BytesIO(art_png))
        art.load()
    except Exception:
        raise TalkerError("provider_failed", "fal returned image bytes that Pillow cannot decode.") from None
    if art.width < 256 or art.height < 256:
        raise TalkerError("provider_failed", f"fal image is too small ({art.width}x{art.height}).")
    art = art.convert("RGB")
    W, H = CANVAS
    scale = max(W / art.width, ART_HEIGHT / art.height)
    art = art.resize((round(art.width * scale), round(art.height * scale)), Image.LANCZOS)
    left, top = (art.width - W) // 2, (art.height - ART_HEIGHT) // 2
    art = art.crop((left, top, left + W, top + ART_HEIGHT))
    mean = ImageStat.Stat(art).mean[:3]
    luma = 0.299 * mean[0] + 0.587 * mean[1] + 0.114 * mean[2]
    accent = tuple(int(c * min(0.55, 80 / max(luma, 1))) for c in mean)   # dark enough to read on the panel

    canvas = Image.new("RGB", CANVAS, (250, 248, 244))
    canvas.paste(art, (0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, ART_HEIGHT, W, ART_HEIGHT + 14), fill=accent)

    margin = 60
    max_w = W - 2 * margin
    font_path = pick_font(product_name + price)
    name_top, name_h = ART_HEIGHT + 50, 270
    fit = _fit_lines(draw, product_name, font_path, max_w, name_h, 96, 40, 3)
    if fit is None:
        raise TalkerError("render_failed", "The confirmed product name does not fit on the talker at a readable "
                                           "size (min 40 px, 3 lines); not truncating it.")
    font, lines, line_h = fit
    y = name_top + (name_h - line_h * len(lines)) // 2
    for line in lines:
        draw.text((W // 2, y), line, font=font, fill=(26, 26, 26), anchor="ma")
        y += line_h

    price_top, price_h = ART_HEIGHT + 340, 230
    pfit = _fit_lines(draw, price, font_path, max_w, price_h, 200, 60, 1)
    if pfit is None:
        raise TalkerError("render_failed", "The price does not fit on the talker; not truncating it.")
    pfont, _, _ = pfit
    draw.text((W // 2, price_top + price_h // 2), price, font=pfont, fill=accent, anchor="mm")
    return canvas


def _write_png(img: Image.Image, path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.stem}.{uuid.uuid4().hex[:6]}.tmp.png")
    img.save(tmp, format="PNG", optimize=True)
    with Image.open(tmp) as check:          # integrity: must decode back to the expected size
        check.load()
        if check.size != img.size:
            raise TalkerError("render_failed", "PNG check failed after writing.")
    os.replace(tmp, path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


# --- orchestration --------------------------------------------------------------------------

async def generate(recommendation_id: str, product_name: Any, price_amount: Any, currency: Any,
                   theme: str = "fresh", *, log: Callable[[str], None] = lambda _t: None,
                   transport: Optional[httpx.AsyncBaseTransport] = None,
                   download_transport: Optional[httpx.AsyncBaseTransport] = None) -> dict:
    """Returns a result dict. status "generated" only after the final PNG exists and re-opens.

    Other statuses: missing_inputs, input_mismatch, not_found, invalid_input, not_configured, submit_failed,
    submit_ambiguous, pending, provider_failed, render_failed, config_error.
    `transport` / `download_transport` exist for isolated tests only.
    """
    try:
        if theme not in THEMES:
            raise TalkerError("invalid_input", f"theme must be one of: {', '.join(THEMES)}")
        conf = await asyncio.to_thread(check_request, recommendation_id, product_name, price_amount, currency)
        text_price = price_text(conf.amount, conf.currency)
        pick_font(conf.product_name + text_price)        # fail before paying if the name cannot be rendered
        tid = talker_id(conf, theme)
        lock = _locks.setdefault(tid, asyncio.Lock())
        async with lock:
            return await _generate_locked(conf, theme, tid, text_price, log, transport, download_transport)
    except TalkerError as e:
        return e.result()


async def _generate_locked(conf, theme, tid, text_price, log, transport, download_transport) -> dict:
    out_path = config.WORKSPACE / OUTPUT_SUBDIR / f"talker_{_safe(conf.recommendation_id)}_{tid[:8]}.png"
    rel = out_path.relative_to(config.WORKSPACE).as_posix()
    base = {"recommendation_id": conf.recommendation_id, "talker_id": tid, "product_name": conf.product_name,
            "price_text": text_price, "model_id": MODEL_ID}
    rec = load_record(tid)

    if rec and rec.get("status") == "generated" and out_path.exists() \
            and hashlib.sha256(out_path.read_bytes()).hexdigest() == rec.get("png_sha256"):
        return {"status": "generated", "reused": True, "file": f"workspace/{rel}", "url": f"/files/{rel}",
                "message": "Already generated for these exact confirmed inputs; no new fal request was made.", **base}
    if rec and rec.get("status") in ("submitting", "submit_ambiguous"):
        return {"status": "submit_ambiguous", **base,
                "message": "An earlier submit for these inputs may have reached fal without a request_id coming "
                           "back. Not resubmitting. Check the fal dashboard, then remove "
                           f"state/talkers/{tid}.json to allow a new attempt."}

    key = _fal_key()
    clock = _Clock(TOTAL_BUDGET_S)
    async with httpx.AsyncClient(transport=transport, follow_redirects=False) as client:
        if not rec or not rec.get("request_id") or rec.get("status") in ("failed", "submit_failed"):
            attempts = (rec or {}).get("attempts", [])
            if rec and rec.get("status") in ("failed", "submit_failed"):
                attempts = attempts + [{k: rec.get(k) for k in ("status", "request_id", "error", "updated_at")}]
            args = fal_arguments(theme)
            rec = {"talker_id": tid, "status": "submitting", "recommendation_id": conf.recommendation_id,
                   "inputs": {"product_name": conf.product_name, "price_amount": str(conf.amount),
                              "currency": conf.currency, "price_text": text_price, "theme": theme,
                              "name_feedback_id": conf.name_feedback_id,
                              "price_feedback_id": conf.price_feedback_id, "price_source": conf.price_source},
                   "model_id": MODEL_ID, "fal_arguments": args, "attempts": attempts,
                   "created_at": _now(), "submit_started_at": _now()}
            _save_record(rec)                     # written BEFORE the billable request
            log("Υποβολή αιτήματος εικόνας στο fal…")
            try:
                sub = await _submit(client, key, args, clock)
            except TalkerError as e:
                rec.update(status=e.status, error=e.message)
                _save_record(rec)
                return {**e.result(), **base}
            rec.update(status="submitted", request_id=sub["request_id"], submitted_at=_now(),
                       status_url=_queue_url(sub.get("status_url"), f"{_APP_BASE}/{sub['request_id']}/status"),
                       response_url=_queue_url(sub.get("response_url"), f"{_APP_BASE}/{sub['request_id']}"))
            _save_record(rec)                     # request_id retained immediately
        else:
            log("Συνέχεια προηγούμενου αιτήματος fal (χωρίς νέα υποβολή)…")

        final = await _poll(client, key, rec, clock)
        if final is None:
            rec["status"] = "pending"
            _save_record(rec)
            return {"status": "pending", **base,
                    "message": "fal has not finished within the time limit. The request is kept; calling the tool "
                               "again with the same inputs resumes it without a new submission."}
        if final.get("error") or final.get("error_type"):
            rec.update(status="failed", error=f"{final.get('error_type') or ''} {final.get('error') or ''}".strip(),
                       completed_at=_now())
            _save_record(rec)
            return {"status": "provider_failed", **base, "message": f"fal reported a failure: {rec['error'][:300]}"}
        rec["metrics"] = final.get("metrics")
        output = await _result(client, key, rec, clock)
    if output is None:
        rec["status"] = "pending"
        _save_record(rec)
        return {"status": "pending", **base, "message": "fal finished but the result could not be fetched yet "
                "(" + str(rec.get("last_error")) + "). Calling again resumes without a new submission."}

    images = output.get("images") if isinstance(output, dict) else None
    nsfw = output.get("has_nsfw_concepts") if isinstance(output, dict) else None
    if not images or not isinstance(images[0], dict) or not isinstance(images[0].get("url"), str):
        rec.update(status="failed", error="result had no image")
        _save_record(rec)
        return {"status": "provider_failed", **base, "message": "fal's result contained no image."}
    if isinstance(nsfw, list) and nsfw and nsfw[0]:
        rec.update(status="failed", error="safety checker flagged the image (returned black)")
        _save_record(rec)
        return {"status": "provider_failed", **base, "message": "fal's safety checker blocked the artwork."}
    rec.update(timings=output.get("timings"), seed=output.get("seed"), image_url=images[0]["url"],
               provider_image={k: images[0].get(k) for k in ("width", "height", "content_type")})
    try:
        log("Λήψη της εικόνας…")
        art = await _download(images[0]["url"], clock, download_transport)
    except TalkerError as e:
        rec.update(status="failed", error=e.message)
        _save_record(rec)
        return {**e.result(), **base}
    except httpx.HTTPError as e:
        rec.update(status="pending", last_error=f"image download {type(e).__name__}")
        _save_record(rec)
        return {"status": "pending", **base, "message": "The image could not be downloaded yet; calling again "
                                                        "resumes without a new submission."}
    try:
        img = await asyncio.to_thread(render, art, conf.product_name, text_price)
        digest = await asyncio.to_thread(_write_png, img, out_path)
    except TalkerError as e:
        rec.update(status="failed" if e.status == "provider_failed" else "render_failed", error=e.message)
        _save_record(rec)
        return {**e.result(), **base}
    rec.update(status="generated", generated_at=_now(), png_path=f"workspace/{rel}", png_sha256=digest,
               png_size=list(img.size), last_error=None)
    _save_record(rec)
    return {"status": "generated", "reused": False, "file": f"workspace/{rel}", "url": f"/files/{rel}",
            "message": "Shelf talker generated.", **base}


def _safe(rec_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", rec_id)[:60]
