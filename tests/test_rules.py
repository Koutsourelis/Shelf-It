"""Έλεγχοι των κανόνων απόφασης. Τρέχουν χωρίς βάση, μοντέλο ή δίκτυο:

    python -m unittest tests.test_rules
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agentkit import rules  # noqa: E402
from agentkit.rules import Slot  # noqa: E402

R = rules.load()


def slot(sku, shelf, level, position, facings=2, margin=10.0, revenue=30.0, units=3.0, brand="Μάρκα", category="Καφές", depth=4):
    return Slot(sku, f"Προϊόν {sku}", brand, category, shelf, level, position, facings, depth, units, revenue, margin)


class LostSales(unittest.TestCase):
    def test_forty_percent_of_daily_revenue(self):
        self.assertEqual(rules.lost_sales(100.0, R), 40.0)


class FacingTransfer(unittest.TestCase):
    def test_elasticity_numbers_match_the_note(self):
        e = R["K3"]["space_elasticity"]
        self.assertAlmostEqual(rules.facing_gain(100, 2, e), 7.14, places=2)     # 2 → 3 προσόψεις: +7,1%
        self.assertAlmostEqual(rules.facing_loss(100, 2, e), 11.12, places=2)    # 2 → 1 προσόψεις: −11,1%

    def test_moves_a_facing_from_the_weak_to_the_strong(self):
        hit = rules.facing_transfer([slot("A", 1, "top", 1, margin=1.0), slot("B", 1, "top", 2, margin=30.0)], R)
        self.assertEqual(hit.rule, "Κ3")
        self.assertIn("από το A", hit.what)
        self.assertGreater(hit.result, 0)

    def test_no_transfer_between_equals(self):
        self.assertIsNone(rules.facing_transfer([slot("A", 1, "top", 1), slot("B", 1, "top", 2)], R))

    def test_donor_keeps_a_day_of_sales(self):
        # Ο Α πουλά 9 τεμάχια την ημέρα· με μία πρόσοψη βάθους 4 δεν χωρά μία ημέρα, άρα δεν δίνει πρόσοψη.
        hit = rules.facing_transfer([slot("A", 1, "top", 1, margin=1.0, units=9.0), slot("B", 1, "top", 2, margin=30.0, facings=1)], R)
        self.assertIsNone(hit)

    def test_single_facing_is_never_taken(self):
        hit = rules.facing_transfer([slot("A", 1, "top", 1, facings=1, margin=1.0), slot("B", 1, "top", 2, facings=1, margin=30.0)], R)
        self.assertIsNone(hit)


class EyeLevel(unittest.TestCase):
    def test_swap_when_advantage_is_clear(self):
        hit = rules.eye_level_swap([slot("LOW", 3, "bottom", 1, margin=20.0), slot("EYE", 2, "eye", 1, margin=5.0)], R)
        self.assertEqual(hit.rule, "Κ4")
        self.assertIn("LOW", hit.what)
        self.assertIn("Δεν δίνεται ποσοστό αύξησης", hit.figure)

    def test_no_swap_below_threshold(self):
        self.assertIsNone(rules.eye_level_swap([slot("LOW", 3, "bottom", 1, margin=11.0), slot("EYE", 2, "eye", 1, margin=10.0)], R))


class Centre(unittest.TestCase):
    def test_best_item_moves_to_the_middle(self):
        hit = rules.centre_position([slot("A", 2, "eye", 1, margin=30.0), slot("B", 2, "eye", 2), slot("C", 2, "eye", 3)], R)
        self.assertEqual(hit.rule, "Κ5")
        self.assertIn("στη θέση του B", hit.what)

    def test_quiet_when_already_central(self):
        self.assertIsNone(rules.centre_position([slot("A", 2, "eye", 1), slot("B", 2, "eye", 2, margin=30.0), slot("C", 2, "eye", 3)], R))

    def test_needs_three_positions(self):
        self.assertIsNone(rules.centre_position([slot("A", 2, "eye", 1, margin=30.0), slot("B", 2, "eye", 2)], R))


class PrivateLabel(unittest.TestCase):
    OWN = R["K6"]["private_label_brands"][0]

    def test_far_from_leader(self):
        hits = rules.private_label_adjacency([slot("PL", 3, "bottom", 3, brand=self.OWN), slot("LEAD", 1, "top", 2, revenue=90.0),
                                              slot("OTHER", 1, "top", 1, revenue=10.0)], R)
        self.assertEqual(len(hits), 1)
        self.assertIn("δίπλα στο LEAD", hits[0].what)

    def test_quiet_when_adjacent(self):
        hits = rules.private_label_adjacency([slot("PL", 1, "top", 3, brand=self.OWN), slot("LEAD", 1, "top", 2, revenue=90.0)], R)
        self.assertEqual(hits, [])

    def test_other_category_is_not_a_rival(self):
        hits = rules.private_label_adjacency([slot("PL", 3, "bottom", 3, brand=self.OWN), slot("TEA", 1, "top", 2, category="Τσάι")], R)
        self.assertEqual(hits, [])


class Destination(unittest.TestCase):
    """Κ7: ο κωδικός που ο πελάτης ψάχνει έτσι κι αλλιώς πάει κάτω δεξιά, όχι στο ύψος των ματιών."""

    def shelf(self):
        return [slot("T1", 1, "top", 1), slot("STAR", 1, "top", 2, units=30.0, margin=60.0), slot("T3", 1, "top", 3),
                slot("E1", 2, "eye", 1, margin=12.0), slot("E2", 2, "eye", 2, margin=20.0), slot("E3", 2, "eye", 3, margin=14.0),
                slot("B1", 3, "bottom", 1, margin=4.0), slot("B2", 3, "bottom", 2, margin=5.0), slot("B3", 3, "bottom", 3, margin=6.0)]

    def test_top_unit_seller_is_a_destination(self):
        self.assertEqual([d.sku for d in rules.destinations(self.shelf(), R)], ["STAR"])

    def test_equal_sellers_have_no_destination(self):
        self.assertEqual(rules.destinations([slot("A", 1, "top", 1), slot("B", 2, "eye", 1), slot("C", 3, "bottom", 1)], R), [])

    def test_declared_brand_is_a_destination(self):
        declared = {**R, "K7": {**R["K7"], "destination_brands": ["Γνωστή"]}}
        slots = [slot("A", 1, "top", 1, brand="Γνωστή"), slot("B", 2, "eye", 1), slot("C", 3, "bottom", 1)]
        self.assertEqual([d.sku for d in rules.destinations(slots, declared)], ["A"])

    def test_destination_goes_bottom_right_not_to_eye_level(self):
        hits, _ = rules.evaluate(self.shelf(), R)
        self.assertNotIn("STAR", [h.move.get("sku") for h in hits if h.rule in ("Κ4", "Κ5")])
        k7 = next(h for h in hits if h.rule == "Κ7")
        self.assertEqual(k7.move, {"sku": "STAR", "swap_with": "B3"})

    def test_no_suggestion_when_already_bottom_right(self):
        slots = [slot("E1", 2, "eye", 1), slot("B1", 3, "bottom", 1), slot("STAR", 3, "bottom", 2, units=30.0)]
        self.assertIsNone(rules.destination_corner(slots, R))

    def test_layout_puts_margin_in_the_middle_and_destination_bottom_right(self):
        layout = {l["level"]: l for l in rules.target_layout(self.shelf(), R)}
        self.assertTrue(layout["bottom"]["order"][-1].startswith("STAR"))
        self.assertTrue(layout["eye"]["order"][1].startswith("E2"))            # το μεγαλύτερο περιθώριο στο κέντρο
        self.assertEqual(sum(len(l["order"]) for l in layout.values()), 9)     # κανένας κωδικός δεν χάνεται
        self.assertIn("Κ7", layout["bottom"]["why"])

    def test_layout_is_empty_without_sales(self):
        self.assertEqual(rules.target_layout([slot("A", 2, "eye", 1, units=0), slot("B", 3, "bottom", 1, units=0)], R), [])

    def test_heavy_packs_stay_on_the_bottom_shelf(self):
        """Κ8: μια φιάλη 1,5 λίτρου δεν ανεβαίνει στο ύψος των ματιών, όσο περιθώριο κι αν αφήνει."""
        from dataclasses import replace
        self.assertEqual(rules.pack_grams("Cola 1,5lt"), 1500)
        self.assertEqual(rules.pack_grams("Ελαιόλαδο 1L"), 1000)
        self.assertEqual(rules.pack_grams("Καφές 500g"), 500)
        self.assertIsNone(rules.pack_grams("Τσάι x20"))
        shelf = self.shelf()
        best = max((s for s in shelf if s.level == "bottom"), key=lambda s: s.margin_per_facing)
        rich = replace(best, name="Cola 1,5lt", margin_day=best.margin_day * 50)      # by far the best margin on the shelf
        shelf = [rich if s.sku == best.sku else s for s in shelf]
        layout = {l["level"]: l for l in rules.target_layout(shelf, R)}
        where = {i["sku"]: (lv, i) for lv, l in layout.items() for i in l["items"]}
        self.assertEqual(where[rich.sku][0], "bottom")
        self.assertEqual(where[rich.sku][1]["role"], "heavy")
        self.assertIn("Κ8", where[rich.sku][1]["why"])
        self.assertEqual(sum(len(l["order"]) for l in layout.values()), len(shelf))
        without = {k: v for k, v in R.items() if k != "K8"}                            # the rule can be switched off
        self.assertEqual({i["sku"]: l["level"] for l in rules.target_layout(shelf, without) for i in l["items"]}[rich.sku], "eye")


class Evaluate(unittest.TestCase):
    def test_says_so_when_sales_are_missing(self):
        hits, skipped = rules.evaluate([slot("A", 1, "top", 1, margin=0, revenue=0, units=0)], R)
        self.assertEqual(hits, [])
        self.assertIn("δεν υπάρχουν επαρκή δεδομένα", skipped[0].lower())

    def test_position_rules_come_before_facings(self):
        hits, _ = rules.evaluate([slot("LOW", 3, "bottom", 1, margin=40.0), slot("E1", 2, "eye", 1, margin=2.0),
                                  slot("E2", 2, "eye", 2, margin=6.0), slot("E3", 2, "eye", 3, margin=5.0)], R)
        order = [h.rule for h in hits]
        self.assertEqual(order[0], "Κ4")
        self.assertEqual(order[-1], "Κ3")

    def test_rules_do_not_fight_over_the_same_spot(self):
        # Το LOW ανεβαίνει στο κέντρο του ύψους ματιών (Κ4)· ο Κ5 δεν πρέπει μετά να ζητά την ίδια θέση για άλλον.
        hits, _ = rules.evaluate([slot("LOW", 3, "bottom", 1, margin=40.0), slot("E1", 2, "eye", 1, margin=6.0),
                                  slot("E2", 2, "eye", 2, margin=2.0), slot("E3", 2, "eye", 3, margin=5.0)], R)
        self.assertEqual([h.rule for h in hits if h.rule in ("Κ4", "Κ5")], ["Κ4"])

    def test_every_suggestion_has_four_parts(self):
        hits, _ = rules.evaluate([slot("LOW", 3, "bottom", 1, margin=40.0), slot("E1", 2, "eye", 1, margin=2.0)], R)
        for h in hits:
            self.assertTrue(h.what and h.title and h.figure and h.source)
            self.assertEqual(h.as_text().count("\n"), 3)


if __name__ == "__main__":
    unittest.main()
