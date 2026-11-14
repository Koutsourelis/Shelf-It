"""Δομημένη εξαγωγή: το μοντέλο διαβάζει κείμενο και επιστρέφει JSON με συγκεκριμένα πεδία.

Χρησιμοποιείται από το εργαλείο extract_fields. Το μοντέλο ΜΟΝΟ διαβάζει· οι υπολογισμοί
γίνονται με κανονικό κώδικα (εργαλείο compute).
"""
import json
import re

from .. import config


def _parse_json(text: str) -> dict:
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("Το μοντέλο δεν επέστρεψε JSON.")
    return json.loads(match.group(0))


async def structured(system: str, user: str, schema: dict) -> dict:
    """Επιστρέφει dict που ακολουθεί το JSON schema (όλα τα πεδία υποχρεωτικά, null αν δεν βρεθούν)."""
    provider = config.LLM_PROVIDER
    fallback_note = ("\n\nΑπάντησε ΜΟΝΟ με ένα αντικείμενο JSON που ακολουθεί αυτό το schema, χωρίς άλλο κείμενο:\n"
                     + json.dumps(schema, ensure_ascii=False))

    if provider == "mock":
        return {name: None for name in schema.get("properties", {})}

    if provider == "anthropic":
        import anthropic
        from .anthropic_llm import _get_client
        client = _get_client()
        try:
            response = await client.messages.create(
                model=config.ANTHROPIC_MODEL, max_tokens=8000, system=system,
                messages=[{"role": "user", "content": user}],
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.BadRequestError:
            # Αν το schema δεν γίνει δεκτό, ζητάμε απλό JSON μέσα στο κείμενο.
            response = await client.messages.create(
                model=config.ANTHROPIC_MODEL, max_tokens=8000, system=system,
                messages=[{"role": "user", "content": user + fallback_note}],
            )
        return _parse_json("".join(b.text for b in response.content if b.type == "text"))

    if provider == "openai_compat":
        from .openai_llm import _get_client
        response = await _get_client().chat.completions.create(
            model=config.OPENAI_COMPAT_MODEL,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user + fallback_note}],
            response_format={"type": "json_object"},
        )
        return _parse_json(response.choices[0].message.content or "")

    raise ValueError(f"Άγνωστο LLM_PROVIDER: {provider!r}")
