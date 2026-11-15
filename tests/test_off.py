"""Open Food Facts matching (agentkit/off.py) and the product_identity tool. No network: search is replaced."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agentkit import off
from agentkit.tools import products


def rec(code, name, brand, quantity="", cats=(), countries=("greece",)):
    return off.record({"code": code, "product_name": name, "brands": brand, "quantity": quantity,
                       "categories_tags": [f"en:{c}" for c in cats], "countries_tags": [f"en:{c}" for c in countries]})


MINERVA = rec("5201106128482", "Greek extra virgin olive oil", "Minerva", "1 l", ["olive-oils", "virgin-olive-oils"])
BENECOL = rec("5201106168204", "Benecol", "Minerva", "225 g", ["spreads"])
DELPHI_GREEN = rec("5201306817025", "Griechische Grüne Oliven", "Delphi", "200 g", ["olives", "green-olives"])
DELPHI_KALAMATA = rec("5201306811481", "Kalamata olives in brine", "Delphi", "180 g", ["olives", "kalamata-olives"])
XENIA = rec("5201216002252", "xenia έξτρα παρθένο ελαιόλαδο 1L", "xenia", "1L", ["olive-oils"])
CRETAN = rec("5214002248093", "Barley Rusk", "Cretan", "", ["rusks"])


class Normalise(unittest.TestCase):
    def test_greek_and_latin_meet(self):
        self.assertEqual(off.norm("Αγρινό"), off.norm("AGRINO"))
        self.assertEqual(off.norm("Μίσκο"), "misko")

    def test_pack_size(self):
        self.assertEqual(off._grams("Ελαιόλαδο 1L"), 1000)
        self.assertEqual(off._grams("Κριθαράκι 500g"), 500)
        self.assertIsNone(off._grams("Τσάι x20"))


class Matching(unittest.TestCase):
    def test_brand_must_match_every_word(self):
        self.assertTrue(off.brand_matches(MINERVA, "Minerva"))
        self.assertFalse(off.brand_matches(CRETAN, "Cretan Gold"))

    def test_same_brand_other_category_is_not_a_match(self):
        self.assertEqual(off.verdict(MINERVA, "Ελαιόλαδο 1L", "Minerva", "Ελαιόλαδο"), "matched")
        self.assertEqual(off.verdict(BENECOL, "Ελαιόλαδο 1L", "Minerva", "Ελαιόλαδο"), "weak")

    def test_greek_words_find_english_names(self):
        green = off.score(DELPHI_GREEN, "Πράσινες ελιές 370g", "Delphi", "Ελιές")
        kalamata = off.score(DELPHI_KALAMATA, "Πράσινες ελιές 370g", "Delphi", "Ελιές")
        self.assertGreater(green, kalamata)

    def test_other_brand_same_product_is_similar(self):
        self.assertEqual(off.verdict(XENIA, "Εξαιρετικό παρθένο ελαιόλαδο 1L", "Αγρινό", "Ελαιόλαδο"), "similar")

    def test_queries_most_precise_first(self):
        q = off.queries("Κριθαράκι 1kg", "Misko", "Ζυμαρικά")
        self.assertEqual(q[0], 'misko AND categories_tags:"en:pastas"')
        self.assertIn('countries_tags:"en:greece"', q[-1])


class Identify(unittest.TestCase):
    def test_picks_best_and_stops_at_first_match(self):
        calls = []

        async def fake_search(query, size=20):
            calls.append(query)
            return [BENECOL, MINERVA]
        with mock.patch.object(off, "search", fake_search):
            res = asyncio.run(off.identify("Ελαιόλαδο 1L", "Minerva", "Ελαιόλαδο"))
        self.assertEqual(res["status"], "matched")
        self.assertEqual(res["match"]["barcode"], MINERVA["barcode"])
        self.assertEqual(len(calls), 1)

    def test_nothing_found(self):
        async def empty(query, size=20):
            return []
        with mock.patch.object(off, "search", empty):
            self.assertEqual(asyncio.run(off.identify("Κάτι", "Καμία", "Ελαιόλαδο"))["status"], "not_found")


class Tool(unittest.TestCase):
    def test_reads_saved_lookup_without_network(self):
        saved = {"T03": {"status": "matched", "score": 0.9, "how": "search", "match": MINERVA, "candidates": []}}
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "off_products.json"
            path.write_text(json.dumps({"products": saved}, ensure_ascii=False), encoding="utf-8")

            async def no_network(*a, **k):
                raise AssertionError("must not search when the sku is saved")
            with mock.patch.object(off, "cache_path", lambda: path), mock.patch.object(off, "identify", no_network):
                text = asyncio.run(products.product_identity(None, sku="T03"))
        self.assertIn("5201106128482", text)
        self.assertIn("Βρέθηκε το ίδιο προϊόν", text)
        self.assertIn("ODbL", text)


if __name__ == "__main__":
    unittest.main()
