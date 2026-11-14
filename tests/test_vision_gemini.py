"""Tests for the native Gemini vision client. No key and no network: HTTP is served by httpx.MockTransport.

    python -m unittest discover tests
"""
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentkit import config, demo_data                      # noqa: E402

# Τα tests τρέχουν πάντα στο βασικό σετ (data/shelf), ό,τι SHELF_SET κι αν έχει το τερματικό.
config.SHELF_SET = ""
config.SHELF_DIR = config.DATA_DIR / "shelf"
demo_data.SHELF_DIR = config.SHELF_DIR
demo_data.PHOTOS_DIR = demo_data.SHELF_DIR / "photos"
from agentkit.vision import gemini, prompts, reader         # noqa: E402
from agentkit.vision.schema import READING_SCHEMA           # noqa: E402

SAMPLE = demo_data.PHOTOS_DIR / "sample_before.png"
FAKE_KEY = "test-key-not-real"
READING = {"occluded": False,
           "items": [{"sku": "C01", "label": "Καφές 200g", "shelf": 1, "position": 1, "facings": 2,
                      "box_2d": [10, 20, 300, 400]},
                     {"sku": "NOPE", "label": "άγνωστο", "shelf": 2, "position": 1, "facings": 1,
                      "box_2d": [310, 20, 600, 200]}],
           "gaps": [{"shelf": 2, "box_2d": [310, 500, 600, 700]}],
           "visual_issues": [{"shelf": 1, "type": "messy", "detail": "ανακατεμένα"}]}


def answer(payload, finish="STOP") -> dict:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return {"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": finish}]}


def keys_in(node) -> set:
    if isinstance(node, dict):
        return set(node) | {k for v in node.values() for k in keys_in(v)}
    if isinstance(node, list):
        return {k for v in node for k in keys_in(v)}
    return set()


class SchemaTest(unittest.TestCase):
    def test_reading_schema_converts_to_gemini_subset(self):
        out = gemini.to_gemini_schema(READING_SCHEMA)
        self.assertEqual(out["type"], "OBJECT")
        self.assertEqual(out["propertyOrdering"], ["occluded", "items", "gaps", "visual_issues"])
        item = out["properties"]["items"]["items"]
        self.assertEqual(item["properties"]["sku"], {
            "type": "STRING", "nullable": True, "description": READING_SCHEMA["properties"]["items"]["items"]
            ["properties"]["sku"]["description"]})
        self.assertEqual(item["properties"]["box_2d"]["items"], {"type": "INTEGER"})
        self.assertEqual(item["required"], ["sku", "label", "shelf", "position", "facings", "box_2d"])
        self.assertIn("messy", out["properties"]["visual_issues"]["items"]["properties"]["type"]["enum"])
        self.assertFalse({"additionalProperties", "anyOf"} & keys_in(out))

    def test_unsupported_union_is_rejected(self):
        with self.assertRaises(ValueError):
            gemini.to_gemini_schema({"anyOf": [{"type": "string"}, {"type": "integer"}]})


class ParseTest(unittest.TestCase):
    def test_good_answer(self):
        self.assertEqual(gemini.parse_response(answer(READING)), READING)

    def test_thought_parts_are_ignored(self):
        data = answer(READING)
        data["candidates"][0]["content"]["parts"].insert(0, {"text": "thinking...", "thought": True})
        self.assertEqual(gemini.parse_response(data), READING)

    def test_transient_problems_are_retryable(self):
        for data in ({"candidates": []}, answer("{not json"), answer(""), answer(READING, finish="MAX_TOKENS"),
                     answer("[1, 2]")):
            with self.assertRaises(gemini.GeminiRetryable):
                gemini.parse_response(data)

    def test_blocked_prompt_is_permanent(self):
        with self.assertRaises(gemini.GeminiError):
            gemini.parse_response({"promptFeedback": {"blockReason": "SAFETY"}})


class ClientTest(unittest.TestCase):
    """End to end through read_photo, with the HTTP layer replaced."""

    def setUp(self):
        self._saved = {k: getattr(config, k) for k in (
            "LLM_PROVIDER", "VISION_PROVIDER", "GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_MEDIA_RESOLUTION",
            "GEMINI_MAX_OUTPUT_TOKENS", "VISION_REFERENCE", "DB_PATH")}
        self._tmp = tempfile.TemporaryDirectory()
        config.DB_PATH = Path(self._tmp.name) / "test.duckdb"       # never touch the real demo database
        demo_data.build()
        config.LLM_PROVIDER, config.VISION_PROVIDER = "mock", "gemini"
        config.GEMINI_API_KEY, config.GEMINI_MODEL = FAKE_KEY, "gemini-test-model"
        config.GEMINI_MEDIA_RESOLUTION, config.GEMINI_MAX_OUTPUT_TOKENS, config.VISION_REFERENCE = "", 0, ""
        reader._cache.clear()
        self.requests: list[httpx.Request] = []

    def tearDown(self):
        from agentkit.tools import data as data_tools
        if data_tools._con is not None:
            data_tools._con.close()
            data_tools._con = None
        for k, v in self._saved.items():
            setattr(config, k, v)
        gemini._client = None
        reader._cache.clear()
        self._tmp.cleanup()

    def serve(self, *responses):
        queue = list(responses)

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            status, body = queue.pop(0) if len(queue) > 1 else queue[0]
            return httpx.Response(status, json=body)
        gemini._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    def read(self) -> dict:
        return asyncio.run(reader.read_photo(SAMPLE))

    def test_request_shape_and_normalized_reading(self):
        self.serve((200, answer(READING)))
        reading = self.read()

        req = self.requests[0]
        self.assertEqual(str(req.url), f"{gemini.API_ROOT}/models/gemini-test-model:generateContent")
        self.assertEqual(req.headers["x-goog-api-key"], FAKE_KEY)
        self.assertNotIn(FAKE_KEY, str(req.url))
        body = json.loads(req.content)
        parts = body["contents"][0]["parts"]
        self.assertEqual(parts[0]["inlineData"]["mimeType"], "image/jpeg")       # image first, then text
        self.assertIn("Κατάλογος προϊόντων", parts[-1]["text"])
        self.assertEqual(body["systemInstruction"]["parts"][0]["text"], prompts.SYSTEM)
        gen = body["generationConfig"]
        self.assertEqual(gen["responseMimeType"], "application/json")
        self.assertEqual(gen["responseSchema"], gemini.to_gemini_schema(READING_SCHEMA))
        self.assertEqual(gen["temperature"], 0)
        self.assertNotIn("mediaResolution", gen)
        self.assertNotIn("maxOutputTokens", gen)

        self.assertEqual(set(reading), {"occluded", "items", "gaps", "visual_issues"})
        self.assertEqual(reading["items"][0]["sku"], "C01")
        self.assertIsNone(reading["items"][1]["sku"])                              # unknown sku → null
        self.assertEqual(reading["gaps"], READING["gaps"])

    def test_optional_generation_settings(self):
        config.GEMINI_MEDIA_RESOLUTION, config.GEMINI_MAX_OUTPUT_TOKENS = "high", 4096
        self.serve((200, answer(READING)))
        self.read()
        gen = json.loads(self.requests[0].content)["generationConfig"]
        self.assertEqual(gen["mediaResolution"], "MEDIA_RESOLUTION_HIGH")
        self.assertEqual(gen["maxOutputTokens"], 4096)

    def test_second_read_of_same_file_uses_cache(self):
        self.serve((200, answer(READING)))
        self.assertEqual(self.read(), self.read())
        self.assertEqual(len(self.requests), 1)

    def test_rate_limit_is_retried_once(self):
        self.serve((429, {"error": {"message": "quota"}}), (200, answer(READING)))
        self.assertEqual(len(self.read()["items"]), 2)
        self.assertEqual(len(self.requests), 2)

    def test_two_failures_raise(self):
        self.serve((503, {"error": {"message": "overloaded"}}))
        with self.assertRaises(RuntimeError):
            self.read()
        self.assertEqual(len(self.requests), 2)

    def test_bad_key_fails_at_once_without_leaking_it(self):
        self.serve((400, {"error": {"message": "API key not valid."}}))
        with self.assertRaises(gemini.GeminiError) as caught:
            self.read()
        self.assertEqual(len(self.requests), 1)
        self.assertNotIn(FAKE_KEY, str(caught.exception))

    def test_missing_key_is_reported_before_any_request(self):
        config.GEMINI_API_KEY = ""
        self.serve((200, answer(READING)))
        with self.assertRaises(gemini.GeminiError):
            self.read()
        self.assertEqual(self.requests, [])

    def test_mock_provider_still_reads_the_sidecar_file(self):
        config.VISION_PROVIDER = ""
        self.serve((200, answer(READING)))
        reading = self.read()
        self.assertEqual(self.requests, [])
        self.assertTrue(reading["items"])


if __name__ == "__main__":
    unittest.main()
