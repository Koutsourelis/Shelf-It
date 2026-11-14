"""Δομημένη εξαγωγή: το μοντέλο διαβάζει κείμενο ή εικόνες και επιστρέφει JSON με συγκεκριμένα πεδία.

Χρησιμοποιείται από τα εργαλεία extract_fields και read_shelf. Το μοντέλο ΜΟΝΟ διαβάζει· οι
υπολογισμοί γίνονται με κανονικό κώδικα.
"""
import base64
import io
import json
import re
from pathlib import Path

from .. import config

MAX_IMAGE_SIDE = 1600      # οι φωτογραφίες κινητού μικραίνουν πριν σταλούν (ταχύτητα, κόστος, όρια μεγέθους)


def _parse_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("Το μοντέλο δεν επέστρεψε JSON.")
    return json.loads(match.group(0))


def image_b64(path: Path) -> str:
    """Η εικόνα ως JPEG σε base64, με σωστό προσανατολισμό και μέγιστη πλευρά MAX_IMAGE_SIDE."""
    from PIL import Image, ImageOps
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode("ascii")


async def structured(system: str, user: str, schema: dict, images: list[Path] | None = None) -> dict:
    """Επιστρέφει dict που ακολουθεί το JSON schema (όλα τα πεδία υποχρεωτικά, null αν δεν βρεθούν).

    Με `images` οι εικόνες στέλνονται στο μοντέλο μαζί με το κείμενο.
    """
    provider = config.LLM_PROVIDER
    fallback_note = ("\n\nΑπάντησε ΜΟΝΟ με ένα αντικείμενο JSON που ακολουθεί αυτό το schema, χωρίς άλλο κείμενο:\n"
                     + json.dumps(schema, ensure_ascii=False))
    pictures = [image_b64(p) for p in images or []]

    if provider == "mock":
        return {name: None for name in schema.get("properties", {})}

    if provider == "anthropic":
        import anthropic
        from .anthropic_llm import _get_client
        client = _get_client()

        def content(text: str) -> list[dict]:
            return ([{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b}}
                     for b in pictures] + [{"type": "text", "text": text}])
        try:
            response = await client.messages.create(
                model=config.ANTHROPIC_MODEL, max_tokens=8000, system=system,
                messages=[{"role": "user", "content": content(user)}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.BadRequestError:
            # Αν το schema δεν γίνει δεκτό, ζητάμε απλό JSON μέσα στο κείμενο.
            response = await client.messages.create(
                model=config.ANTHROPIC_MODEL, max_tokens=8000, system=system,
                messages=[{"role": "user", "content": content(user + fallback_note)}],
            )
        return _parse_json("".join(b.text for b in response.content if b.type == "text"))

    if provider == "openai_compat":
        from .openai_llm import _get_client
        parts = [{"type": "text", "text": user + fallback_note}]
        parts += [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b}"}} for b in pictures]
        response = await _get_client().chat.completions.create(
            model=config.OPENAI_COMPAT_MODEL,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": parts if pictures else user + fallback_note}],
            response_format={"type": "json_object"},
        )
        return _parse_json(response.choices[0].message.content or "")

    raise ValueError(f"Άγνωστο LLM_PROVIDER: {provider!r}")
