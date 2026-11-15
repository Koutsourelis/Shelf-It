"""Δημιουργία της «διορθωμένης / ιδανικής» εικόνας του ραφιού μετά την ανάλυση.

Παίρνει την πραγματική φωτογραφία του ραφιού μαζί με τα ντετερμινιστικά ευρήματα (ελλείψεις, κενά, λάθος ράφι,
ξένα αντικείμενα, προτεινόμενες μετακινήσεις Κ1–Κ8) και παράγει με το Gemini Image Editing (`gemini-3.1-flash-image`)
μια καθαρή, ρεαλιστική προεπισκόπηση του πώς πρέπει να φαίνεται το ράφι αφού τακτοποιηθεί και γεμίσει.

Σε offline / `mock` λειτουργία παράγει ντετερμινιστική προεπισκόπηση χωρίς κλήση δικτύου.
"""
from __future__ import annotations

import asyncio
import base64
import io
import shutil
from pathlib import Path

import httpx

from .. import config, events

_GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/models"
_LEVEL_EN = {
    "top": "top shelf",
    "eye": "middle (eye-level) shelf",
    "bottom": "bottom shelf",
}


def build_prompt(verdict: dict, findings: list[dict], moves: list[dict]) -> str:
    """Μετατρέπει τα ακριβή ευρήματα και τις μετακινήσεις σε σαφείς οδηγίες επεξεργασίας της φωτογραφίας."""
    steps: list[str] = []

    for f in findings:
        ftype = f.get("type")
        name = f.get("name") or f.get("label") or f.get("sku") or "matching adjacent product"
        lvl = _LEVEL_EN.get(str(f.get("level") or ""), f"shelf {f.get('shelf', '')}".strip())
        need = f.get("need")
        if ftype in ("missing", "low", "gap"):
            qty = f" ({need} facings)" if need else ""
            steps.append(f"- Fill the empty gap on the {lvl} with neat forward-facing packages of '{name}'{qty}, matching the exact style and Greek label of the shelf.")
        elif ftype == "misplaced":
            to_lvl = _LEVEL_EN.get(str(f.get("to_level") or ""), "its proper shelf")
            steps.append(f"- Move '{name}' to the {to_lvl} neatly aligned.")
        elif ftype == "unknown":
            steps.append(f"- Remove the foreign non-belonging item '{name}' from the {lvl} and fill its space cleanly with adjacent shelf products.")
        elif ftype == "visual":
            detail = f.get("detail") or f.get("text") or "straighten crooked or fallen packages"
            steps.append(f"- Tidy presentation: {detail}.")

    for m in moves[:4]:
        name = m.get("name") or m.get("label") or m.get("sku") or ""
        to_lvl = _LEVEL_EN.get(str(m.get("to_level") or ""), "")
        if name and to_lvl:
            steps.append(f"- Ensure '{name}' is positioned cleanly on the {to_lvl}.")

    if not steps:
        steps.append("- Fill any visible empty gaps on each shelf with the matching adjacent packages and straighten all items neatly facing forward.")

    joined = "\n".join(steps)
    return (
        "Edit this exact supermarket shelf image to show how this exact shelf looks AFTER it has been properly "
        "restocked, tidied, and corrected according to planogram:\n"
        f"{joined}\n\n"
        "CRITICAL RULES:\n"
        "1. Keep the EXACT same shelf structure, number of shelves, camera angle, background, lighting, price rails, and exact Greek product brand names/labels.\n"
        "2. All packages/bottles/cans must stand upright, neatly aligned front-facing with zero empty gaps.\n"
        "3. Do NOT draw any bounding boxes, arrows, badges, or UI overlays — output a clean, natural, realistic image of the corrected shelf."
    )


def _mock_corrected(frame_path: Path, out_path: Path) -> Path:
    """Offline fallback για το mock provider (χρησιμοποιεί το sample_after αν υπάρχει, αλλιώς αντιγράφει καθαρά)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "jpeg", "jpg"):
        cand = config.SHELF_DIR / "photos" / f"sample_after.{ext}"
        if cand.is_file():
            shutil.copyfile(cand, out_path)
            return out_path
    shutil.copyfile(frame_path, out_path)
    return out_path


def _prepare_jpeg(frame_path: Path) -> tuple[str, tuple[int, int]]:
    from PIL import Image, ImageOps
    with Image.open(frame_path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        orig_size = im.size
        im.thumbnail((1152, 1152))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=86)
    return base64.b64encode(buf.getvalue()).decode("ascii"), orig_size


async def generate_corrected_shelf(
    frame_path: Path,
    verdict: dict,
    findings: list[dict],
    moves: list[dict],
    *,
    force_regenerate: bool = False,
) -> Path | None:
    """Παράγει το `workspace/live/corrected_<stem>.png` και το επιστρέφει (ή None σε αποτυχία)."""
    out_dir = config.WORKSPACE / "live"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"corrected_{frame_path.stem}.png"

    if out_path.is_file() and not force_regenerate:
        return out_path

    if config.vision_provider() == "mock" or not config.GEMINI_API_KEY:
        return await asyncio.to_thread(_mock_corrected, frame_path, out_path)

    # Αν το ράφι είναι ήδη 100% σωστό χωρίς ευρήματα/μετακινήσεις και δεν ζητήθηκε ρητά αναδημιουργία,
    # η ίδια η φωτογραφία είναι ήδη η σωστή εικόνα του ραφιού.
    if verdict.get("shelf_ok") and not findings and not moves and not force_regenerate:
        await asyncio.to_thread(shutil.copyfile, frame_path, out_path)
        return out_path

    try:
        b64, _ = await asyncio.to_thread(_prepare_jpeg, frame_path)
    except Exception as e:
        events.emit("system", "log", text=f"Ανάγνωση εικόνας για διόρθωση: {e}")
        return None

    prompt = build_prompt(verdict, findings, moves)
    models = [config.GEMINI_IMAGE_MODEL]
    if "gemini-2.5-flash-image" not in models:
        models.append("gemini-2.5-flash-image")

    payload = {
        "contents": [{
            "parts": [
                {"inlineData": {"mimeType": "image/jpeg", "data": b64}},
                {"text": prompt},
            ]
        }],
        "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]},
    }

    async with httpx.AsyncClient(timeout=75.0) as client:
        for model in models:
            try:
                r = await client.post(
                    f"{_GEMINI_API}/{model}:generateContent",
                    params={"key": config.GEMINI_API_KEY},
                    json=payload,
                )
                if r.status_code != 200:
                    events.emit("system", "log", text=f"Εικόνα διόρθωσης ({model}): HTTP {r.status_code}")
                    continue
                parts = r.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
                for pt in parts:
                    inline = pt.get("inlineData") or pt.get("inline_data")
                    if inline and inline.get("data"):
                        raw = base64.b64decode(inline["data"])
                        await asyncio.to_thread(out_path.write_bytes, raw)
                        return out_path
            except Exception as e:
                events.emit("system", "log", text=f"Εικόνα διόρθωσης ({model}): {type(e).__name__}: {e}")
    return None
