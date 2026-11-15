"""Sales from ELSTAT household purchases (agentkit/market.py) and the identity column of read_shelf."""
import unittest

from agentkit import market
from agentkit.tools.products import short_identity

HBS = {"0115101": {"per_household_month": 1766.27}, "0111501": {"per_household_month": 2292.35}}
MODEL = {"households": 2000, "store_share": 0.3, "days_per_month": 30.4, "categories": {
    "Ελαιόλαδο": {"coicop": ["0115101"], "shelf_share": 0.25, "grams_per_ml": 0.916},
    "Ζυμαρικά": {"coicop": ["0111501"], "shelf_share": 0.1},
    "Ταχίνι": None}}


def row(sku, name, category, daily="9", **extra):
    return {"sku": sku, "name": name, "category": category, "daily_units": daily, **extra}


class Sales(unittest.TestCase):
    def test_pack_size_in_grams(self):
        self.assertAlmostEqual(market.pack_grams("Ελαιόλαδο 1L", 0.916), 916)
        self.assertEqual(market.pack_grams("Κριθαράκι 500g"), 500)
        self.assertEqual(market.pack_grams("Κριθαράκι 1kg", 0.916), 1000)    # weight: density not applied

    def test_olive_oil_from_elstat(self):
        plan = market.plan([row("T03", "Ελαιόλαδο 1L", "Ελαιόλαδο")], MODEL, HBS)
        expected = 1766.27 * 2000 * 0.3 * 0.25 / 30.4 / 916            # 9.5 bottles a day
        self.assertAlmostEqual(plan[0]["daily_units"], round(expected, 1))
        self.assertIn("ΕΛΣΤΑΤ", plan[0]["sales_source"])
        self.assertIn("0115101", plan[0]["sales_source"])

    def test_equal_grams_split_and_weights(self):
        rows = [row("A", "Κριθαράκι 500g", "Ζυμαρικά"), row("B", "Κριθαράκι 1kg", "Ζυμαρικά")]
        a, b = market.plan(rows, MODEL, HBS)
        self.assertAlmostEqual(a["daily_units"], 2 * b["daily_units"], delta=0.1)   # same grams, half the pack
        rows[1]["sales_weight"] = "3"
        a, b = market.plan(rows, MODEL, HBS)
        self.assertGreater(b["daily_units"], a["daily_units"])

    def test_category_without_elstat_item_keeps_its_number(self):
        plan = market.plan([row("T06", "Ταχίνι 400g", "Ταχίνι", daily="2.5")], MODEL, HBS)
        self.assertEqual(plan[0]["daily_units"], 2.5)
        self.assertTrue(plan[0]["sales_source"].startswith("υπόθεση"))

    def test_real_extract_has_the_items_we_map(self):
        hbs = market.load_hbs()
        self.assertGreater(hbs["0115101"]["per_household_month"], 0)      # olive oil
        self.assertIn("0111501", hbs)                                      # pasta


class IdentityColumn(unittest.TestCase):
    CACHE = {
        "T03": {"status": "matched", "match": {"barcode": "5201106128482", "brand": "Minerva",
                                                "name": "Greek extra virgin olive oil", "quantity": ""}},
        "T01": {"status": "similar", "match": {"barcode": "5201216002252", "brand": "xenia",
                                                "name": "xenia έξτρα παρθένο ελαιόλαδο", "quantity": "1L"}},
        "T09": {"status": "weak", "match": {"barcode": "1", "brand": "x", "name": "y", "quantity": ""}},
    }

    def test_matched_similar_weak(self):
        self.assertEqual(short_identity("T03", self.CACHE), "5201106128482 · Minerva Greek extra virgin olive oil")
        self.assertEqual(short_identity("T01", self.CACHE), "≈ xenia έξτρα παρθένο ελαιόλαδο 1L (5201216002252)")
        self.assertEqual(short_identity("T09", self.CACHE), "-")
        self.assertEqual(short_identity(None, self.CACHE), "-")


if __name__ == "__main__":
    unittest.main()
