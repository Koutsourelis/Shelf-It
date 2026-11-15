"""Names and Open Food Facts identity on a shelf reading (agentkit/identity.py). No network, no model.

    python -m unittest tests.test_identity
"""
import asyncio
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentkit import config, demo_data, identity, live, off, portal, vision   # noqa: E402

config.SHELF_SET = ""
config.VISION_PROVIDER = "mock"
config.SHELF_DIR = config.DATA_DIR / "shelf"
demo_data.SHELF_DIR = config.SHELF_DIR
demo_data.PHOTOS_DIR = demo_data.SHELF_DIR / "photos"

MATCH = {"status": "matched", "score": 0.75, "match": {"barcode": "5449000133335", "name": "Coca Cola Zero Sugar",
                                                        "brand": "Coca-Cola", "quantity": "1.5l",
                                                        "url": "https://world.openfoodfacts.org/product/5449000133335"}}


class Base(unittest.TestCase):
    def setUp(self):
        self._saved = {k: getattr(config, k) for k in ("LLM_PROVIDER", "VISION_PROVIDER", "DB_PATH", "LIVE_START_AGENT",
                                                       "LIVE_CONFIRM_FRAMES", "OFF_LIVE_LOOKUP")}
        self._tmp = tempfile.TemporaryDirectory()
        config.DB_PATH = Path(self._tmp.name) / "test.duckdb"
        self._seen, identity.SEEN_PATH = identity.SEEN_PATH, Path(self._tmp.name) / "off_seen.json"
        demo_data.build()
        config.LLM_PROVIDER, config.VISION_PROVIDER, config.LIVE_START_AGENT = "mock", "mock", False
        portal.orders.clear()
        live.STATE.reset()
        vision.set_mock_assessment("sample_before")

    def tearDown(self):
        from agentkit.tools import data as data_tools
        if data_tools._con is not None:
            data_tools._con.close()
            data_tools._con = None
        for k, v in self._saved.items():
            setattr(config, k, v)
        identity.SEEN_PATH = self._seen
        live.STATE.reset()
        portal.orders.clear()
        self._tmp.cleanup()


class IdentityTest(Base):
    def test_key_does_not_repeat_the_brand(self):
        self.assertEqual(identity.key("Coca-Cola", "Coca-Cola Zero 1.5L"), "coca cola zero 1 5l")
        self.assertEqual(identity.key("Άλφα", "Μπίρα 330ml"), "alfa mpira 330ml")
        self.assertEqual(identity.key("", "ελαιόλαδο"), "elaiolado")

    def test_catalogue_items_take_the_catalogue_name(self):
        shelves = [{"level": "top", "items": [{"sku": "C02", "label": "Μπρίκι", "brand": "", "facings": 1}]}]
        identity.annotate(shelves)
        item = shelves[0]["items"][0]
        self.assertEqual(item["name"], "Μπρίκι Ελληνικός καφές 200g")     # brand in front: the name alone can repeat
        self.assertEqual(item["brand"], "Μπρίκι")
        self.assertIsNone(item["off"])                       # the coffee set has no saved lookup

    def test_items_outside_the_catalogue_keep_the_label_and_read_saved_lookups(self):
        shelves = [{"level": "bottom", "items": [
            {"sku": None, "label": "Coca-Cola Zero 1.5L", "brand": "Coca-Cola", "facings": 2},
            {"sku": None, "label": "ελαιόλαδο", "brand": "", "facings": 1}]}]
        self.assertEqual([p[0] for p in identity.pending(shelves)], ["coca cola zero 1 5l"])   # no brand → no lookup
        identity._save_seen({"coca cola zero 1 5l": MATCH})
        identity.annotate(shelves)
        cola, oil = shelves[0]["items"]
        self.assertEqual(cola["name"], "Coca-Cola Zero 1.5L")
        self.assertEqual(cola["off"]["barcode"], "5449000133335")
        self.assertEqual((oil["name"], oil["off"]), ("ελαιόλαδο", None))
        self.assertEqual(identity.pending(shelves), [])

    def test_weak_guesses_are_not_shown_as_identity(self):
        self.assertIsNone(identity.public({**MATCH, "status": "weak"}))
        self.assertIsNone(identity.public({"status": "not_found", "match": None}))
        self.assertEqual(identity.public({**MATCH, "status": "similar"})["status"], "similar")

    def test_live_match_needs_the_same_pack_size(self):
        self.assertTrue(identity.same_pack("Coca-Cola Zero 1.5L", MATCH))
        self.assertFalse(identity.same_pack("Coca-Cola Zero 330ml", MATCH))
        self.assertFalse(identity.same_pack("ΑΛΦΑ Μπύρα Φιάλη 500ml", {"match": {"name": "Μπύρα ΑΛΦΑ weiss", "quantity": ""}}))

    def test_no_lookup_when_switched_off(self):
        config.OFF_LIVE_LOOKUP = False
        shelves = [{"level": "top", "items": [{"sku": None, "label": "Fix Hellas 330ml", "brand": "Fix"}]}]
        self.assertEqual(identity.lookup_in_background(shelves), 0)

    def test_live_status_carries_names(self):
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (640, 360), (200, 0, 0)).save(buf, "JPEG")
        res = asyncio.run(live.process_frame(buf.getvalue(), force=True))
        items = [i for sh in res["shelves"] for i in sh["items"]]
        self.assertTrue(items)
        self.assertTrue(all(i["name"] for i in items if i["sku"]))
        self.assertIn("Αυγή Καφές φίλτρου 250g", {i["name"] for i in items})
        self.assertEqual(res["shelf_title"], "Καφές · Κακάο")


class MovesAndRefillsTest(Base):
    """What changes shelf and what needs refilling (agentkit/live.py), with the reason for each."""

    def test_department_shelf_moves_come_from_sales_with_a_number(self):
        from agentkit.tools.shelf import stats_layout
        layout = stats_layout()
        self.assertTrue(all(lay["items"] for lay in layout))
        shelves = [{"level": "top", "items": [{"sku": "C02", "label": "Μπρίκι", "name": "Ελληνικός καφές 200g",
                                               "facings": 3, "box_2d": [60, 364, 300, 636]}]},
                   {"level": "eye", "items": [{"sku": "C04", "label": "Νότα", "facings": 2, "box_2d": None}]}]
        moves = live.layout_moves({"shelves": shelves, "suggested_layout": layout, "misplaced": []})
        self.assertEqual([(m["sku"], m["from_level"], m["to_level"], m["source"]) for m in moves],
                         [("C02", "top", "bottom", "rules")])       # C04 is already at eye level: no arrow
        self.assertIn("πουλάει πολύ", moves[0]["why"])               # the best seller goes down, and says why
        self.assertIn("Κ7", moves[0]["why"])
        self.assertRegex(moves[0]["why"], r"\d")

    def test_a_product_with_a_task_gets_no_second_arrow(self):
        from agentkit.tools.shelf import stats_layout
        shelves = [{"level": "top", "items": [{"sku": "C02", "label": "Μπρίκι", "facings": 3, "box_2d": None}]}]
        verdict = {"shelves": shelves, "suggested_layout": stats_layout(), "misplaced": [{"sku": "C02"}]}
        self.assertEqual(live.layout_moves(verdict), [])

    def test_unknown_shelf_moves_are_the_models_and_say_so(self):
        shelves = [{"level": "eye", "items": [
            {"sku": None, "label": "Coca-Cola 1.5L", "facings": 2, "best_level": "bottom",
             "move_why": "βαριά φιάλη και πασίγνωστη μάρκα: κάτω", "box_2d": [10, 10, 90, 90]},
            {"sku": None, "label": "Amstel 330ml", "facings": 2, "best_level": "eye", "move_why": "", "box_2d": None}]}]
        moves = live.layout_moves({"shelves": shelves, "unknown_shelf": True, "suggested_layout": [], "misplaced": []})
        self.assertEqual([(m["name"], m["to_level"], m["source"]) for m in moves], [("Coca-Cola 1.5L", "bottom", "model")])
        # a product without a catalogue code is judged by the model on any shelf: there are no sales for it
        self.assertEqual(len(live.layout_moves({"shelves": shelves, "suggested_layout": [], "misplaced": []})), 1)

    def test_unknown_shelf_refill_is_a_task_and_never_an_order(self):
        from agentkit import tasks
        verdict = {"unknown_shelf": True, "missing": [], "misplaced": [], "foreign": [], "visual_issues": [],
                   "shelves": [{"level": "bottom", "items": [
                       {"sku": None, "label": "Λουξ Πορτοκαλάδα 1.5L", "facings": 1, "target_facings": 3, "box_2d": None},
                       {"sku": None, "label": "ΗΒΗ Λεμονάδα 1.5L", "facings": 2, "target_facings": 2, "box_2d": None}]}]}
        found = live.to_findings(verdict)
        self.assertEqual([(f["type"], f["label"], f["need"], f["seen"], f["target"]) for f in found],
                         [("low", "Λουξ Πορτοκαλάδα 1.5L", 2, 1, 3)])
        changed = tasks.sync(found, Path(self._tmp.name) / "none.jpg")
        task = changed["new"][0]
        self.assertEqual(task["text"], "Γέμισε το ράφι 3 (κάτω): Λουξ Πορτοκαλάδα 1.5L, λείπουν 2 προσόψεις")
        self.assertIsNone(task["numbers"])
        self.assertEqual(portal.orders, [])
        # a drink the catalogue does not have is a product of the shelf, not something to remove
        self.assertEqual([f["type"] for f in live.to_findings({**verdict, "unknown_shelf": False})], ["low"])
        # only what the model calls foreign (not sold on such a shelf) is removed, and it is not refilled
        stray = {**verdict, "foreign": [{"label": "Λουξ Πορτοκαλάδα 1.5L", "level": "bottom", "box_2d": None}]}
        self.assertEqual([f["type"] for f in live.to_findings(stray)], ["unknown"])

    def test_full_shelf_comes_from_the_planogram_not_from_the_model(self):
        verdict = {"missing": [], "misplaced": [], "foreign": [], "visual_issues": [], "gaps": [], "shelves": [
            {"level": "top", "items": [
                {"sku": "C02", "label": "Μπρίκι", "facings": 1, "target_facings": 1, "box_2d": [1, 1, 9, 9]},
                {"sku": "C01", "label": "Αυγή", "facings": 1, "target_facings": 1, "box_2d": None},
                {"sku": "C01", "label": "Αυγή", "facings": 1, "target_facings": 1, "box_2d": None}]}]}
        found = live.to_findings(verdict, live._planned())
        # C02 has 3 facings when full, the photo shows 1. C01 is split in two groups: 1 + 1 = its 2 facings, full.
        self.assertEqual([(f["type"], f["sku"], f["seen"], f["target"], f["need"]) for f in found],
                         [("low", "C02", 1, 3, 2)])
        self.assertEqual(live.to_findings(verdict), [])              # without a planogram the model's count stands

    def test_one_facing_short_needs_the_model_to_see_a_gap(self):
        def shelf(seen, model_target, gaps=()):
            return {"missing": [], "misplaced": [], "foreign": [], "visual_issues": [], "gaps": list(gaps), "shelves": [
                {"level": "top", "items": [{"sku": "C02", "label": "Μπρίκι", "facings": seen,
                                            "target_facings": model_target, "box_2d": None}]}]}
        planned = live._planned()                                    # C02: 3 facings when full
        self.assertEqual(live.to_findings(shelf(2, 2), planned), [])                       # counting error, no task
        self.assertEqual(len(live.to_findings(shelf(2, 3), planned)), 1)                   # the model sees the gap too
        gap = [{"level": "top", "sku": "C02", "product": "Μπρίκι", "units": 1, "box_2d": None}]
        self.assertEqual([f["type"] for f in live.to_findings(shelf(2, 2, gap), planned)], ["low"])
        self.assertEqual(len(live.to_findings(shelf(1, 1), planned)), 1)                   # two short always counts

    def test_regroup_finds_the_physical_shelves_and_names_the_gaps(self):
        from agentkit import shelfsets
        real_db = shelfsets.db_path
        shelfsets.db_path = lambda name: Path(self._tmp.name) / f"demo_{name or 'base'}.duckdb"
        saved = (config.SHELF_SET, config.SHELF_DIR, demo_data.SHELF_DIR, demo_data.PHOTOS_DIR)
        try:
            shelfsets.activate("drinks")
            planned = live._planned()
            it = lambda sku, y, x, n, label="": {"sku": sku, "label": label or sku, "facings": n, "target_facings": n,
                                                  "box_2d": [y, x, y + 100, x + 90]}
            # the model put shelves 2, 3 and 4 in one "eye" level, as it does on the real photos
            verdict = {"missing": [], "misplaced": [], "foreign": [], "visual_issues": [], "shelves": [
                {"level": "top", "items": [it("D01", 50, 100, 4), it("D02", 50, 300, 4)]},
                {"level": "eye", "items": [it("D11", 250, 100, 5), it("D13", 250, 300, 3),
                                           it("D21", 450, 100, 5), it("D23", 450, 300, 4),
                                           it("D36", 650, 100, 3), it("D37", 650, 400, 4),
                                           it(None, 650, 700, 2, "Red Bull 250ml")]},
                {"level": "bottom", "items": [it("D41", 850, 100, 3), it("D42", 850, 300, 3)]}],
                "gaps": [{"level": "eye", "sku": None, "product": "", "units": 1, "box_2d": [650, 195, 750, 290]}]}
            live.regroup(verdict, planned)
            self.assertEqual([(sh["shelf"], sh["level"], [i["label"] for i in sh["items"]]) for sh in verdict["shelves"]],
                             [(1, "top", ["D01", "D02"]), (2, "eye", ["D11", "D13"]), (3, "eye", ["D21", "D23"]),
                              (4, "bottom", ["D36", "D37", "Red Bull 250ml"]), (5, "bottom", ["D41", "D42"])])
            # the gap sits between D36 (3 of its 4 facings) and D37 (full): it is D36's, on shelf 4
            gap = verdict["gaps"][0]
            self.assertEqual((gap["sku"], gap["shelf"], gap["level"]), ("D36", 4, "bottom"))
            found = live.to_findings(verdict, planned)
            self.assertEqual([(f["type"], f["sku"], f["shelf"], f["need"]) for f in found], [("low", "D36", 4, 1)])
        finally:
            shelfsets.db_path = real_db
            from agentkit.tools import data as data_tools
            if data_tools._con is not None:
                data_tools._con.close()
                data_tools._con = None
            config.SHELF_SET, config.SHELF_DIR, demo_data.SHELF_DIR, demo_data.PHOTOS_DIR = saved

    def test_spare_room_next_to_a_fully_faced_code_is_not_a_task(self):
        verdict = {"missing": [], "misplaced": [], "foreign": [], "visual_issues": [], "shelves": [
            {"level": "eye", "items": [{"sku": "C06", "label": "Ρεύμα", "facings": 2, "target_facings": 2, "box_2d": None}]}],
            "gaps": [{"level": "eye", "sku": "C06", "product": "Ρεύμα", "units": 3, "box_2d": [1, 1, 9, 9]}]}
        self.assertEqual(live.to_findings(verdict, live._planned()), [])       # C06 has its 2 facings: free end of the shelf
        self.assertEqual([f["type"] for f in live.to_findings(verdict)], ["gap"])   # no planogram: the gap is all we know

    def test_missing_code_is_sent_to_its_own_shelf(self):
        verdict = {"misplaced": [], "foreign": [], "visual_issues": [], "gaps": [], "shelves": [],
                   "missing": [{"sku": "C09", "product": "Ελληνικός καφές 500g", "target_facings": 1, "why": ""}]}
        f = live.to_findings(verdict, live._planned())[0]
        self.assertEqual((f["shelf"], f["level"], f["need"]), (3, "bottom", 3))            # from the planogram
        self.assertEqual((live.to_findings(verdict)[0]["shelf"]), 2)                       # unknown: as before

    def test_moves_are_ranked_and_the_best_seller_comes_first(self):
        from agentkit.tools.shelf import stats_layout
        layout = stats_layout()
        now = {"C02": "top", "C03": "top", "C05": "eye", "C06": "eye", "C09": "bottom"}
        shelves = [{"level": lv, "items": [{"sku": s, "label": s, "facings": 2, "box_2d": None}
                                           for s, at in now.items() if at == lv]} for lv in ("top", "eye", "bottom")]
        moves = live.layout_moves({"shelves": shelves, "suggested_layout": layout, "misplaced": []})
        self.assertEqual([m["sku"] for m in moves][:3], ["C02", "C09", "C03"])   # destination, then eye level by margin
        self.assertNotIn("rank", moves[0])

    def test_gaps_become_fill_tasks_unless_already_explained(self):
        from agentkit import tasks
        base = {"missing": [], "misplaced": [], "foreign": [], "visual_issues": [], "shelves": [
            {"level": "eye", "items": [{"sku": "C02", "label": "Μπρίκι", "facings": 1, "target_facings": 3, "box_2d": None},
                                       {"sku": None, "label": "Coca-Cola 330ml", "facings": 4, "target_facings": 4,
                                        "box_2d": None}]}]}
        gaps = [{"level": "eye", "sku": "C02", "product": "Μπρίκι", "units": 2, "box_2d": [1, 1, 9, 9]},      # = the low C02
                {"level": "eye", "sku": None, "product": "Coca-Cola 330ml", "units": 2, "box_2d": [1, 20, 9, 30]},
                {"level": "eye", "sku": None, "product": "Coca-Cola 330ml", "units": 1, "box_2d": [1, 40, 9, 50]},
                {"level": "bottom", "sku": None, "product": "", "units": 3, "box_2d": None}]
        found = live.to_findings({**base, "gaps": gaps})
        self.assertEqual([(f["type"], f["label"], f["level"], f["need"]) for f in found],
                         [("low", "Μπρίκι", "eye", 2), ("gap", "Coca-Cola 330ml", "eye", 3), ("gap", "", "bottom", 3)])
        texts = [t["text"] for t in tasks.sync(found, Path(self._tmp.name) / "none.jpg")["new"]]
        self.assertIn("Γέμισε το ράφι 2 (ύψος ματιών): κενό στο Coca-Cola 330ml, χωράνε 3 τεμάχια", texts)
        self.assertIn("Γέμισε το ράφι 3 (κάτω): υπάρχει κενό, χωράνε 3 τεμάχια", texts)
        # a nameless gap on a shelf where a catalogue code is missing is the place of that code: one task, not two
        missing = {**base, "gaps": gaps[3:], "missing": [{"sku": "C04", "product": "Κάψουλες", "target_facings": 2, "why": ""}]}
        self.assertEqual([f["type"] for f in live.to_findings(missing)], ["missing", "low"])


class ShelfSetsTest(unittest.TestCase):
    """The catalogue follows the photo (agentkit/shelfsets.py)."""

    def setUp(self):
        self._saved = (config.SHELF_SET, config.SHELF_DIR, config.DB_PATH, demo_data.SHELF_DIR, demo_data.PHOTOS_DIR)
        self._tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        from agentkit.tools import data as data_tools
        if data_tools._con is not None:
            data_tools._con.close()
            data_tools._con = None
        config.SHELF_SET, config.SHELF_DIR, config.DB_PATH, demo_data.SHELF_DIR, demo_data.PHOTOS_DIR = self._saved
        self._tmp.cleanup()

    def test_drinks_labels_pick_the_drinks_set(self):
        from agentkit import shelfsets
        read = ["ΑΛΦΑ Μπύρα Φιάλη 500ml", "Mythos Μπύρα Κουτί 500ml", "Βεργίνα Radler Κουτί 330ml", "Λουξ Cola 1.5L",
                "ΕΨΑ Λεμονάδα 1.5L", "Ήβη Πορτοκαλάδα 1.5L", "Coca-Cola Zero 330ml", " Μπύρα Φιάλη 330ml"]
        self.assertIn("drinks", shelfsets.names())
        self.assertEqual(shelfsets.guess(read, active=""), "drinks")
        self.assertIsNone(shelfsets.guess(read, active="drinks"))            # already tried with that catalogue
        self.assertEqual(shelfsets.guess(["Αυγή Καφές φίλτρου 250g", "Μπρίκι Ελληνικός καφές", "Νότα Espresso"],
                                         active="drinks"), "")
        self.assertIsNone(shelfsets.guess(["Dr. Oetker Paradies Creme", "RUF Schlagcreme", "Mondamin"], active=""))
        self.assertIsNone(shelfsets.guess(["Mythos 330ml"] + ["Dr. Oetker Pudding"] * 9, active=""))   # one beer is not a beer shelf

    def test_foreign_only_readings_count_as_unknown(self):
        from agentkit.vision.assessment import unknown_ratio
        foreign = [{"label": f"Μπίρα {i}"} for i in range(8)]
        self.assertEqual(unknown_ratio({"shelves": [], "foreign": foreign}), 1.0)
        known = [{"level": "top", "items": [{"sku": "C01", "label": "Αυγή"}, {"sku": "C02", "label": "Μπρίκι"}]}]
        self.assertEqual(unknown_ratio({"shelves": known, "foreign": foreign[:2]}), 0.5)
        self.assertEqual(unknown_ratio({"shelves": known, "foreign": [{"label": "Αυγή"}]}), 0.0)   # not counted twice

    def test_activate_switches_catalogue_planogram_and_database(self):
        from agentkit import shelfsets
        from agentkit.tools.data import run_sql
        real_db = shelfsets.db_path
        shelfsets.db_path = lambda name: Path(self._tmp.name) / f"demo_{name or 'base'}.duckdb"
        try:
            info = shelfsets.activate("drinks")
            self.assertEqual(info["title"], "Μπίρα · Αναψυκτικά")
            self.assertEqual(run_sql("select count(*) from products")[1][0][0], 37)
            self.assertEqual(live._planned()["D12"], {"facings": 5, "shelf": 2, "level": "eye"})
            self.assertEqual(live._planned()["D43"]["shelf"], 5)
            self.assertEqual(demo_data.PHOTOS_DIR, config.DATA_DIR / "shelf" / "sets" / "drinks" / "photos")
            shelfsets.activate("")
            self.assertEqual(run_sql("select count(*) from products")[1][0][0], 9)
            with self.assertRaises(ValueError):
                shelfsets.activate("nope")
        finally:
            shelfsets.db_path = real_db


class TradSetTest(unittest.TestCase):
    def test_saved_lookup_of_the_trad_set_is_shown(self):
        saved, config.SHELF_DIR = config.SHELF_DIR, config.DATA_DIR / "shelf" / "sets" / "trad"
        try:
            self.assertEqual(identity.for_sku("T03")["barcode"], "5201106128482")      # Minerva, matched
            self.assertIsNone(identity.for_sku("T13"))                                 # weak: not shown
        finally:
            config.SHELF_DIR = saved


if __name__ == "__main__":
    unittest.main()
