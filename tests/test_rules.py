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
