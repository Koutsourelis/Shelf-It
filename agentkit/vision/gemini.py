"""Native Gemini client for shelf reading (generateContent with a response schema). Owner: Person A.

Why not the OpenAI-compatible endpoint: it only offers `json_object`, so the model may return wrong types or
miss fields. Here the schema is enforced by the API (`responseSchema`), the images go first, and temperature is 0.

Enabled with VISION_PROVIDER=gemini in .env. Uses plain REST over httpx, so there is no extra dependency.
The API key travels in a header, never in the URL, so it cannot leak into error messages or logs.
"""
import json
from pathlib import Path

import httpx

from .. import config
from ..llm.structured import image_b64

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"
_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}
_TYPES = {"object": "OBJECT", "array": "ARRAY", "string": "STRING", "integer": "INTEGER",
          "number": "NUMBER", "boolean": "BOOLEAN"}

_client: httpx.AsyncClient | None = None


class GeminiRetryable(ValueError):
    """Transient failure (rate limit, server error, truncated or empty answer): worth one more attempt."""


class GeminiError(RuntimeError):
    """Permanent failure (bad key, unknown model, rejected request): retrying will not help."""


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=httpx.Timeout(config.VISION_TIMEOUT_SECONDS, connect=10))
    return _client


def to_gemini_schema(schema: dict) -> dict:
    """JSON Schema → the OpenAPI subset that Gemini's `responseSchema` accepts.

    - types in upper case
    - `anyOf: [X, {"type": "null"}]` becomes X with `nullable: true`
    - `additionalProperties` is dropped (not supported)
    - `propertyOrdering` keeps the fields in the order we declared them
    """
    variants = schema.get("anyOf")
    if variants:
        real = [v for v in variants if v.get("type") != "null"]
        if len(real) != 1:
            raise ValueError("Only anyOf of one type plus null is supported in the vision schema.")
        out = to_gemini_schema({**{k: v for k, v in schema.items() if k != "anyOf"}, **real[0]})
        if len(real) < len(variants):
            out["nullable"] = True
        return out

    out: dict = {"type": _TYPES[schema["type"]]}
    for key in ("description", "enum", "required"):
        if key in schema:
            out[key] = schema[key]
    if "properties" in schema:
        out["properties"] = {name: to_gemini_schema(sub) for name, sub in schema["properties"].items()}
        out["propertyOrdering"] = list(schema["properties"])
    if "items" in schema:
        out["items"] = to_gemini_schema(schema["items"])
    return out


def build_request(system: str, user: str, schema: dict, pictures: list[str]) -> dict:
    """The generateContent body. `pictures` are base64 JPEGs; they go before the text, as Google recommends."""
    parts = [{"inlineData": {"mimeType": "image/jpeg", "data": b}} for b in pictures]
    parts.append({"text": user})
    generation: dict = {"temperature": 0, "responseMimeType": "application/json",
                        "responseSchema": to_gemini_schema(schema)}
    if config.GEMINI_MAX_OUTPUT_TOKENS:
        generation["maxOutputTokens"] = config.GEMINI_MAX_OUTPUT_TOKENS
    if config.GEMINI_MEDIA_RESOLUTION:
        generation["mediaResolution"] = "MEDIA_RESOLUTION_" + config.GEMINI_MEDIA_RESOLUTION.upper()
    if config.GEMINI_THINKING_LEVEL in ("low", "medium", "high"):
        # Χρόνος απόκρισης: το medium (προεπιλογή του μοντέλου) αργεί πολύ για ζωντανή κάμερα.
        generation["thinkingConfig"] = {"thinkingLevel": config.GEMINI_THINKING_LEVEL}
    return {"systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": generation}


def parse_response(data: dict) -> dict:
    """Pulls the JSON object out of a generateContent response, or raises with the reason it is missing."""
    candidates = data.get("candidates") or []
    if not candidates:
        reason = (data.get("promptFeedback") or {}).get("blockReason")
        if reason:
            raise GeminiError(f"Gemini blocked the request: {reason}")
        raise GeminiRetryable("Gemini returned no candidates.")
    cand = candidates[0]
    finish = cand.get("finishReason")
    if finish == "MAX_TOKENS":
        raise GeminiRetryable("Gemini answer was cut off (MAX_TOKENS). Raise or clear GEMINI_MAX_OUTPUT_TOKENS.")
    text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts") or []
                   if not p.get("thought"))
    if not text.strip():
        raise GeminiRetryable(f"Gemini returned an empty answer (finishReason={finish}).")
    try:
        result = json.loads(text)
    except json.JSONDecodeError as e:
        raise GeminiRetryable(f"Gemini returned invalid JSON: {e}") from None
    if not isinstance(result, dict):
        raise GeminiRetryable("Gemini returned JSON that is not an object.")
    return result


async def structured(system: str, user: str, schema: dict, images: list[Path] | None = None) -> dict:
    """Same contract as agentkit.llm.structured.structured, served by the native Gemini API."""
    if not config.GEMINI_API_KEY:
        raise GeminiError("GEMINI_API_KEY is empty. Put the key in your local .env (never in the repo).")
    if not config.GEMINI_MODEL:
        raise GeminiError("GEMINI_MODEL is empty. Set the model id from AI Studio in .env.")

    pictures = [image_b64(p, config.VISION_MAX_IMAGE_SIDE) for p in images or []]
    url = f"{API_ROOT}/models/{config.GEMINI_MODEL}:generateContent"
    try:
        response = await _get_client().post(url, json=build_request(system, user, schema, pictures),
                                            headers={"x-goog-api-key": config.GEMINI_API_KEY})
    except httpx.TimeoutException:
        raise GeminiRetryable("Gemini request timed out.") from None
    except httpx.TransportError as e:
        raise GeminiRetryable(f"Gemini connection failed: {type(e).__name__}") from None

    if response.status_code != 200:
        try:
            message = response.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = response.text[:200]
        kind = GeminiRetryable if response.status_code in _RETRYABLE_STATUS else GeminiError
        raise kind(f"Gemini HTTP {response.status_code}: {message}")
    return parse_response(response.json())
