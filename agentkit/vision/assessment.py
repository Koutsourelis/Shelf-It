"""Αξιολόγηση ραφιού από το μοντέλο όρασης. Μία κλήση: τι υπάρχει, τι λείπει, τι είναι σε λάθος ύψος, πώς πρέπει να στηθεί.

Σχεδιαστική αρχή: **καμία καρτεσιανή θέση**. Δεν λέμε στο μοντέλο «το C04 ανήκει στο ράφι 2, θέση 3».
Του δίνουμε τον κατάλογο των προϊόντων που πουλάει το τμήμα και τους κανόνες merchandising, και το μοντέλο
απαντά με ό,τι βλέπει: επίπεδο ραφιού (top / eye / bottom), σειρά από αριστερά, πόσες προσόψεις, τι λείπει,
τι είναι σε λάθος επίπεδο, και πώς θα έπρεπε να στηθεί. Ο κώδικας δεν συγκρίνει θέσεις· μετατρέπει μόνο
«λείπουν 3 προσόψεις» σε τεμάχια, κιβώτια και ευρώ (agentkit/tasks.py).

Το συμβόλαιο εξόδου είναι το ASSESS_SCHEMA παρακάτω. Το χρησιμοποιούν το read_shelf (σενάριο agent) και το
live loop (agentkit/live.py).

Mock (χωρίς κλειδί): διαβάζει το <photo>.assessment.json δίπλα στη φωτογραφία, αλλιώς του ενεργού δείγματος
(set_mock_assessment). Έτσι όλη η ροή δοκιμάζεται offline, με την ίδια έξοδο που θα έδινε το μοντέλο.
"""
import asyncio
import json
from collections import OrderedDict
from pathlib import Path

from .. import config
from .. import demo_data

LEVELS = ("top", "eye", "bottom")          # top = πάνω, eye = ύψος ματιών, bottom = κάτω
LEVEL_TO_SHELF = {"top": 1, "eye": 2, "bottom": 3}   # μόνο για εμφάνιση («ράφι 2»), όχι για έλεγχο θέσης

BOX = {"type": "array", "items": {"type": "integer"},
       "description": "[ymin, xmin, ymax, xmax], 0-1000 ως προς την εικόνα"}

ASSESS_SCHEMA = {
    "type": "object",
    "properties": {
        "shelf_ok": {"type": "boolean",
                     "description": "true μόνο αν το ράφι είναι όπως πρέπει: τίποτα δεν λείπει, τίποτα δεν είναι σε λάθος επίπεδο, τίποτα ξένο"},
        "occluded": {"type": "boolean", "description": "true αν άνθρωπος, χέρι ή αντικείμενο κρύβει μέρος του ραφιού"},
        "shelves": {
            "type": "array",
            "description": "Ένα στοιχείο για κάθε επίπεδο που φαίνεται, από πάνω προς τα κάτω.",
            "items": {
                "type": "object",
                "properties": {
                    "level": {"type": "string", "enum": list(LEVELS)},
                    "items": {
                        "type": "array",
                        "description": "Οι ομάδες ίδιων προϊόντων που στέκονται δίπλα δίπλα, από αριστερά.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string",
                                          "description": "Μάρκα, προϊόν και συσκευασία όπως γράφει η ετικέτα, π.χ. «Amstel Radler 330ml»"},
                                "brand": {"type": "string",
                                          "description": "Μόνο η μάρκα όπως είναι τυπωμένη· κενό αν δεν διαβάζεται"},
                                "sku": {"anyOf": [{"type": "string"}, {"type": "null"}],
                                        "description": "Κωδικός του καταλόγου αν ταιριάζει με βεβαιότητα, αλλιώς null"},
                                "facings": {"type": "integer", "description": "Πόσα τεμάχια φαίνονται δίπλα δίπλα"},
                                "target_facings": {"type": "integer",
                                                   "description": "Πόσες προσόψεις θα είχε η ομάδα με το ράφι γεμάτο: όσες φαίνονται συν όσες χωράνε στο άδειο διάστημα που της ανήκει. Χωρίς κενό δίπλα της, ίσο με το facings"},
                                "best_level": {"type": "string", "enum": list(LEVELS),
                                               "description": "Το επίπεδο όπου πρέπει να στέκει με τους κανόνες· ίδιο με το τωρινό αν είναι καλά εκεί"},
                                "move_why": {"type": "string",
                                             "description": "Αν το best_level διαφέρει από το τωρινό: γιατί, σε μία πρόταση. Αλλιώς κενό"},
                                "placement_ok": {"type": "boolean",
                                                 "description": "false αν το προϊόν δεν ταιριάζει στο επίπεδο που στέκει (κανόνες παρακάτω)"},
                                "box_2d": BOX,
                            },
                            "required": ["label", "brand", "sku", "facings", "target_facings", "best_level", "move_why",
                                         "placement_ok", "box_2d"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["level", "items"],
                "additionalProperties": False,
            },
        },
        "missing": {
            "type": "array",
            "description": "Προϊόντα του καταλόγου που δεν φαίνονται καθόλου στο ράφι.",
            "items": {"type": "object", "properties": {
                "sku": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "product": {"type": "string"},
                "target_facings": {"type": "integer"},
                "why": {"type": "string", "description": "Γιατί πρέπει να είναι εδώ (π.χ. κύριος κωδικός της κατηγορίας)"}},
                "required": ["sku", "product", "target_facings", "why"], "additionalProperties": False},
        },
        "misplaced": {
            "type": "array",
            "description": "Προϊόντα που υπάρχουν αλλά σε λάθος επίπεδο για τους κανόνες.",
            "items": {"type": "object", "properties": {
                "sku": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "product": {"type": "string"},
                "from_level": {"type": "string", "enum": list(LEVELS)},
                "to_level": {"type": "string", "enum": list(LEVELS)},
                "why": {"type": "string"},
                "box_2d": BOX},
                "required": ["sku", "product", "from_level", "to_level", "why", "box_2d"], "additionalProperties": False},
        },
        "gaps": {
            "type": "array",
            "description": "Άδειος χώρος πάνω στο ράφι όπου χωράει τουλάχιστον ένα προϊόν: το ράφι δεν είναι γεμάτο εκεί.",
            "items": {"type": "object", "properties": {
                "level": {"type": "string", "enum": list(LEVELS)},
                "sku": {"anyOf": [{"type": "string"}, {"type": "null"}],
                        "description": "Ο κωδικός που ανήκει στο κενό, αν φαίνεται από την ετικέτα τιμής ή τη διπλανή ομάδα· αλλιώς null"},
                "product": {"type": "string",
                            "description": "Το προϊόν που ανήκει στο κενό, όπως το γράφεις στο label της ομάδας του· κενό αν δεν φαίνεται"},
                "units": {"type": "integer", "description": "Πόσα τεμάχια χωράνε δίπλα δίπλα στο κενό"},
                "box_2d": BOX},
                "required": ["level", "sku", "product", "units", "box_2d"], "additionalProperties": False},
        },
        "foreign": {
            "type": "array",
            "description": "Αντικείμενα που δεν είναι προϊόν αυτού του είδους ραφιού (π.χ. απορρυπαντικό ανάμεσα σε ποτά, κάτι που άφησε πελάτης). Άλλη μάρκα ή άλλο ποτό ΔΕΝ είναι ξένο.",
            "items": {"type": "object", "properties": {
                "label": {"type": "string"}, "level": {"type": "string", "enum": list(LEVELS)}, "box_2d": BOX},
                "required": ["label", "level", "box_2d"], "additionalProperties": False},
        },
        "visual_issues": {
            "type": "array",
            "description": "Παραβάσεις παρουσίασης που φαίνονται μόνο με το μάτι.",
            "items": {"type": "object", "properties": {
                "level": {"type": "string", "enum": list(LEVELS)},
                "type": {"type": "string", "enum": ["label_not_facing", "not_fronted", "messy", "damaged", "other"]},
                "detail": {"type": "string"}},
                "required": ["level", "type", "detail"], "additionalProperties": False},
        },
        "suggested_layout": {
            "type": "array",
            "description": "Πώς θα έπρεπε να στηθεί το ράφι. Ένα στοιχείο ανά επίπεδο, με τη σειρά από αριστερά.",
            "items": {"type": "object", "properties": {
                "level": {"type": "string", "enum": list(LEVELS)},
                "order": {"type": "array", "items": {"type": "string"},
                          "description": "Ονόματα/κωδικοί προϊόντων με τη σειρά που προτείνεις"},
                "why": {"type": "string"}},
                "required": ["level", "order", "why"], "additionalProperties": False},
        },
        "summary": {"type": "string", "description": "Δύο προτάσεις: τι βλέπεις και τι πρέπει να γίνει."},
    },
    "required": ["shelf_ok", "occluded", "shelves", "missing", "misplaced", "gaps", "foreign", "visual_issues",
                 "suggested_layout", "summary"],
    "additionalProperties": False,
}

SYSTEM = (
    "Είσαι merchandiser καταστήματος και κοιτάς φωτογραφία ραφιού. Περιγράφεις μόνο ό,τι φαίνεται: δεν μαντεύεις "
    "προϊόντα που δεν βλέπεις και δεν συμπληρώνεις τον κατάλογο από συνήθεια. Κρίνεις τη διάταξη με κανόνες "
    "κατηγορίας, όχι με προκαθορισμένες θέσεις: δεν υπάρχει σωστή «θέση 3» — υπάρχει σωστό επίπεδο, σωστή γειτονιά "
    "και σωστός αριθμός προσόψεων."
)

RULES = [
    "Το ύψος των ματιών (eye) είναι το πολυτιμότερο. Εκεί πάνε οι κωδικοί με το μεγαλύτερο περιθώριο σε ΕΥΡΩ "
    "ανά πρόσοψη ανά ημέρα: (τιμή − κόστος) × ημερήσιες πωλήσεις ÷ προσόψεις. Μη συγκρίνεις μόνο ποσοστά "
    "περιθωρίου — ένα φθηνό προϊόν με υψηλό ποσοστό μπορεί να αποδίδει λιγότερα ευρώ από ένα ακριβότερο.",
    "Εξαίρεση, ο προϊόν-προορισμός: η πασίγνωστη μάρκα ή ο πρώτος σε τεμάχια κωδικός, που ο πελάτης ψάχνει όπου "
    "κι αν είναι (π.χ. το γνωστότερο αναψυκτικό). Δεν χρειάζεται την καλή θέση: πάει στο κάτω επίπεδο, δεξιά. "
    "Το ύψος των ματιών και το κέντρο του μένουν για ό,τι θέλουμε να πουληθεί και αφήνει μεγάλο περιθώριο.",
    "Τα βαριά ή ογκώδη πάνε κάτω (bottom), τα ελαφριά και μικρά πάνω (top). Το βάρος όμως έρχεται δεύτερο: "
    "αν ένα βαρύ προϊόν αποδίδει πολύ περισσότερα ευρώ ανά πρόσοψη, μένει στα μάτια.",
    "Ίδια μάρκα μαζί, κάθετα αν γίνεται· μην ανακατεύεις ανταγωνιστές στο ίδιο μπλοκ.",
    "Κάθε κωδικός θέλει τουλάχιστον δύο προσόψεις· ο ηγέτης της κατηγορίας περισσότερες.",
    "Οι ετικέτες κοιτάνε προς τα έξω και τα προϊόντα είναι τραβηγμένα στην άκρη του ραφιού.",
    "Ράφι που δεν είναι γεμάτο θέλει γέμισμα. Κάθε άδειο διάστημα όπου χωράει προϊόν το γράφεις στο gaps, με το "
    "προϊόν στο οποίο ανήκει (η ομάδα δίπλα του ή η ετικέτα τιμής από κάτω) και πόσα τεμάχια χωράνε. Αν το κενό είναι "
    "η θέση κωδικού του καταλόγου που λείπει εντελώς, γράψε τον κωδικό και στο missing. Μην το γράφεις στο "
    "visual_issues.",
    "Ξένο (foreign) είναι μόνο ό,τι δεν πουλιέται σε τέτοιο ράφι. Ένα ποτό, ένας καφές ή μια μάρκα που δεν έχει ο "
    "κατάλογος ΔΕΝ είναι ξένο και ΔΕΝ βγαίνει από το ράφι: το γράφεις στο items με sku null και το όνομά του.",
    "Στο misplaced βάλε ΜΟΝΟ προϊόντα σε επίπεδο που δεν βγάζει νόημα: πολύ βαρύ ή ογκώδες πάνω, ή προϊόν έξω "
    "από την κατηγορία του. Η καλύτερη θέση για περισσότερο κέρδος ΔΕΝ είναι misplaced· γι' αυτήν υπάρχει το "
    "suggested_layout.",
    "Στο visual_issues βάλε μόνο πραγματικά ελαττώματα παρουσίας: ετικέτα γυρισμένη, προϊόν πίσω από την άκρη, "
    "σπασμένη συσκευασία, ανακατεμένα διαφορετικά προϊόντα.",
]


def user_prompt(catalog: list[dict], has_reference: bool) -> str:
    rows = []
    for p in catalog:
        margin = ""
        if p.get("unit_price") and p.get("unit_cost") is not None:
            try:
                margin = f", περιθώριο {100 * (float(p['unit_price']) - float(p['unit_cost'])) / float(p['unit_price']):.0f}%"
            except (TypeError, ValueError, ZeroDivisionError):
                margin = ""
        try:
            per_day = (float(p["unit_price"]) - float(p["unit_cost"])) * float(p.get("daily_units") or 0)
            margin += f", {per_day:.2f} € περιθώριο/ημέρα"
        except (TypeError, ValueError, KeyError):
            pass
        rows.append(f"- {p['sku']} | {p['name']} | {p['brand']} | {p.get('category') or 'χωρίς κατηγορία'}{margin}")
    ref = ("Η ΠΡΩΤΗ εικόνα δείχνει το ίδιο ράφι σε καλή κατάσταση (αναφορά). Η ΔΕΥΤΕΡΗ είναι η σημερινή. "
           "Σύγκρινε νοητά, αλλά αξιολόγησε μόνο τη δεύτερη.\n\n" if has_reference else "")
    rules = "\n".join(f"- {r}" for r in RULES)
    if not catalog:
        return (f"{ref}ΔΕΝ έχεις κατάλογο: το ράφι μπορεί να είναι άλλου τμήματος ή άγνωστο.\n\n"
                "Διάβασε τη φωτογραφία και πες τι βλέπεις:\n"
                "1. Για κάθε επίπεδο (top/eye/bottom) τις ομάδες ίδιων προϊόντων από αριστερά, με προσόψεις και "
                "box_2d. Στο sku βάλε πάντα null. Στο label γράψε μάρκα, προϊόν και συσκευασία όπως τα διαβάζεις "
                "(π.χ. «Coca-Cola Zero 1.5L», «Amstel Radler 330ml») και στο brand μόνο τη μάρκα· αν η μάρκα δεν "
                "διαβάζεται, άφησε το brand κενό και γράψε στο label τον τύπο προϊόντος (π.χ. «ελαιόλαδο»). "
                "Άλλη συσκευασία ή παραλλαγή της ίδιας μάρκας είναι ξεχωριστή ομάδα.\n"
                "   ΓΕΜΙΣΜΑ: στο target_facings γράψε πόσες προσόψεις θα είχε η ομάδα γεμάτη. Κοίτα κάθε ομάδα: αν δίπλα "
                "της υπάρχει άδειος χώρος ή μισοάδειο δισκάκι όπου φανερά λείπουν τεμάχιά της, αν έχει λιγότερα "
                "τεμάχια από τις γειτονικές της ίδιας σειράς, ή αν έχει μείνει μία μόνο πρόσοψη, βάλε target_facings "
                "μεγαλύτερο από το facings κατά όσα τεμάχια χωράνε στο κενό. Αλλιώς ίσο με το facings. Ένα κενό που "
                "ανήκει σε ομάδα το γράφεις ΕΔΩ και όχι στο visual_issues.\n"
                "   ΘΕΣΗ: στο best_level γράψε το επίπεδο όπου πρέπει να στέκει κάθε ομάδα με τους κανόνες παρακάτω, και στο "
                "move_why τον λόγο όταν διαφέρει από το τωρινό, ονομάζοντας τον κανόνα· π.χ. «πασίγνωστη μάρκα που ο "
                "πελάτης ψάχνει έτσι κι αλλιώς: κάτω, για να μείνει το ύψος των ματιών σε ό,τι θέλει προβολή» ή «βαριά "
                "φιάλη 1.5L: κάτω». Δεν έχεις πωλήσεις ούτε περιθώρια: μη γράφεις αριθμούς, ποσοστά ή ποσά. Πρότεινε "
                "αλλαγή μόνο όπου ο κανόνας είναι καθαρός· οι περισσότερες ομάδες μένουν εκεί που είναι.\n"
                "2. Στο missing ΜΗΝ βάλεις τίποτα: χωρίς κατάλογο δεν ξέρουμε τι θα έπρεπε να υπάρχει.\n"
                "3. Στο foreign ΜΗΝ βάλεις προϊόντα του ραφιού: όλα είναι άγνωστα, όχι ξένα.\n"
                "4. Στο misplaced ό,τι πρέπει να αλλάξει επίπεδο με βάση τους κανόνες (π.χ. πολύ βαρύ πάνω, προϊόν "
                "μακριά από την υπόλοιπη μάρκα ή κατηγορία του), με το όνομά του στο product όπως στο label.\n"
                "5. Στο gaps κάθε άδειο διάστημα του ραφιού. Στο visual_issues μόνο τις παραβάσεις παρουσίασης.\n"
                "6. Στο suggested_layout πώς θα στήσιμο το ράφι με κανόνες κατηγορίας, με βάση τα προϊόντα που "
                "βλέπεις. Στη σύνοψη πες τι κατηγορία είναι το ράφι και ό,τι αξίζει να προσέξει ο υπεύθυνος.\n"
                "7. shelf_ok = true αν το ράφι είναι γεμάτο και δεν υπάρχει πραγματικό ελάττωμα παρουσίασης.\n\n"
                "Κανόνες κατηγορίας:\n" + rules)
    return (
        f"{ref}Κατάλογος του τμήματος (κωδικός | προϊόν | μάρκα | κατηγορία):\n" + "\n".join(rows) + "\n\n"
        "Ο κατάλογος λέει ΠΟΙΑ προϊόντα πουλάμε, όχι σε ποια θέση πρέπει να είναι. Αξιολόγησε τη φωτογραφία:\n"
        "1. Για κάθε επίπεδο (top/eye/bottom) γράψε τις ομάδες ίδιων προϊόντων από αριστερά, με προσόψεις, το "
        "box_2d τους και αν το επίπεδο τους ταιριάζει (placement_ok). Στο brand γράψε τη μάρκα που διαβάζεις, και "
        "για ό,τι δεν ταιριάζει σε κωδικό γράψε στο label μάρκα και προϊόν όπως στην ετικέτα. Για ομάδες με κωδικό βάλε "
        "στο best_level το τωρινό επίπεδο και άφησε το move_why κενό, εκτός αν το προϊόν μπαίνει στο misplaced: τη "
        "θέση τους τη βγάζει ο κώδικας από τις πωλήσεις. Για ομάδες χωρίς κωδικό δεν υπάρχουν πωλήσεις: γράψε στο "
        "best_level το επίπεδο που τους ταιριάζει με τους κανόνες και στο move_why τον λόγο αν διαφέρει από το "
        "τωρινό, χωρίς αριθμούς (π.χ. «βαριά φιάλη 1.5L: κάτω», «πασίγνωστη μάρκα που ο πελάτης ψάχνει έτσι κι "
        "αλλιώς: κάτω»).\n"
        "2. Στο missing βάλε κωδικούς του καταλόγου που δεν φαίνονται καθόλου.\n"
        "3. Στο misplaced ό,τι είναι σε λάθος επίπεδο, με το επίπεδο που του ταιριάζει.\n"
        "4. Στο gaps κάθε άδειο διάστημα του ραφιού. Στο foreign μόνο ό,τι δεν πουλιέται σε τέτοιο ράφι· προϊόν "
        "εκτός καταλόγου μένει στο items με sku null. Στο visual_issues τις παραβάσεις παρουσίασης.\n"
        "5. Στο suggested_layout δώσε τη διάταξη που προτείνεις, ανά επίπεδο, με σειρά από αριστερά, και το γιατί.\n"
        "6. shelf_ok = true αν (α) δεν λείπει κανένας κωδικός, (β) δεν υπάρχει ξένο προϊόν, (γ) δεν υπάρχει "
        "πραγματικό ελάττωμα παρουσίας και (δ) δεν υπάρχει προϊόν σε επίπεδο που δεν βγάζει νόημα. Τα κενά του gaps "
        "και το «θα ήταν καλύτερα αλλού για κέρδος» ΔΕΝ κάνουν το ράφι λάθος εδώ: αν ένα κενό σημαίνει έλλειψη το "
        "κρίνει ο κώδικας με το πλανόγραμμα, και τη θέση τη λέει το suggested_layout.\n\n"
        "Κανόνες κατηγορίας:\n" + rules
    )


_cache: "OrderedDict[tuple, dict]" = OrderedDict()
_CACHE_SIZE = 16
_mock_name = "sample_before"


def set_mock_assessment(name: str) -> None:
    """Mock: ποια κατάσταση «βλέπει» το ψεύτικο μοντέλο (π.χ. sample_before, sample_after, newim1)."""
    global _mock_name
    if not (demo_data.PHOTOS_DIR / f"{name}.assessment.json").exists():
        raise FileNotFoundError(f"Λείπει το {demo_data.PHOTOS_DIR / (name + '.assessment.json')}")
    _mock_name = name


def mock_assessment() -> str:
    return _mock_name


def _clamp_box(value) -> list[int] | None:
    try:
        ymin, xmin, ymax, xmax = (max(0, min(1000, int(v))) for v in value)
    except (TypeError, ValueError):
        return None
    return [ymin, xmin, ymax, xmax] if ymax > ymin and xmax > xmin else None


def _int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize(raw: dict, known: set[str]) -> dict:
    """Καθαρίζει την έξοδο του μοντέλου: άγνωστοι κωδικοί → null, κουτιά σε 0-1000, αριθμοί ≥ 0."""
    shelves = []
    for sh in raw.get("shelves") or []:
        level = sh.get("level") if sh.get("level") in LEVELS else "top"
        items = []
        for it in sh.get("items") or []:
            if not isinstance(it, dict):
                continue
            items.append({"label": str(it.get("label") or ""), "brand": str(it.get("brand") or "").strip(),
                          "sku": it.get("sku") if it.get("sku") in known else None,
                          "facings": max(_int(it.get("facings")), 0),
                          "target_facings": max(_int(it.get("target_facings")), 0),
                          "best_level": it.get("best_level") if it.get("best_level") in LEVELS else level,
                          "move_why": str(it.get("move_why") or "").strip(),
                          "placement_ok": bool(it.get("placement_ok", True)),
                          "box_2d": _clamp_box(it.get("box_2d"))})
        shelves.append({"level": level, "items": items})

    def level(value, default="top"):
        return value if value in LEVELS else default

    missing = [{"sku": m.get("sku") if m.get("sku") in known else None, "product": str(m.get("product") or ""),
                "target_facings": max(_int(m.get("target_facings")), 1), "why": str(m.get("why") or "")}
               for m in raw.get("missing") or [] if isinstance(m, dict)]
    misplaced = [{"sku": m.get("sku") if m.get("sku") in known else None, "product": str(m.get("product") or ""),
                  "from_level": level(m.get("from_level")), "to_level": level(m.get("to_level")),
                  "why": str(m.get("why") or ""), "box_2d": _clamp_box(m.get("box_2d"))}
                 for m in raw.get("misplaced") or [] if isinstance(m, dict)]
    gaps = [{"level": level(g.get("level")), "sku": g.get("sku") if g.get("sku") in known else None,
             "product": str(g.get("product") or "").strip(), "units": max(_int(g.get("units")), 1),
             "box_2d": _clamp_box(g.get("box_2d"))} for g in raw.get("gaps") or [] if isinstance(g, dict)]
    foreign = [{"label": str(f.get("label") or ""), "level": level(f.get("level")),
                "box_2d": _clamp_box(f.get("box_2d"))} for f in raw.get("foreign") or [] if isinstance(f, dict)]
    visual = [{"level": level(v.get("level")), "type": str(v.get("type") or "other"), "detail": str(v.get("detail") or "")}
              for v in raw.get("visual_issues") or [] if isinstance(v, dict)]
    layout = [{"level": level(s.get("level")), "order": [str(x) for x in s.get("order") or []],
               "why": str(s.get("why") or "")} for s in raw.get("suggested_layout") or [] if isinstance(s, dict)]
    # Το shelf_ok του μοντέλου δεν μπορεί να είναι true όταν το ίδιο δήλωσε πρόβλημα: το κρατάει ο κώδικας συνεπές.
    shelf_ok = bool(raw.get("shelf_ok")) and not (missing or misplaced or foreign or visual)
    return {"shelf_ok": shelf_ok, "occluded": bool(raw.get("occluded")), "shelves": shelves,
            "missing": missing, "misplaced": misplaced, "gaps": gaps, "foreign": foreign, "visual_issues": visual,
            "suggested_layout": layout, "summary": str(raw.get("summary") or "")}


def unknown_ratio(verdict: dict) -> float:
    """Πόσο μεγάλο μέρος του ραφιού δεν ταιριάζει με τον κατάλογο (0 = όλα γνωστά, 1 = κανένα)."""
    items = [i for sh in verdict.get("shelves") or [] for i in sh["items"]]
    # Το μοντέλο μερικές φορές γράφει ό,τι δεν ξέρει μόνο στο foreign και αφήνει το shelves άδειο. Χωρίς αυτά ένα
    # ράφι ποτών μετρούσε ως «όλα γνωστά» και έβγαιναν 32 εργασίες «βγάλε από το ράφι».
    listed = {i.get("label") for i in items}
    extra = [f for f in verdict.get("foreign") or [] if f.get("label") not in listed]
    total = len(items) + len(extra)
    if not total:
        return 0.0
    return (sum(1 for i in items if not i.get("sku")) + len(extra)) / total


def _catalog() -> list[dict]:
    from ..tools.data import run_sql
    _, rows = run_sql("select sku, name, brand, unit_cost, unit_price, category from products order by sku")
    # Ημερήσιες πωλήσεις από τις συνθετικές πωλήσεις 28 ημερών (ο μέσος όρος ανά ημέρα).
    _, daily = run_sql("select sku, sum(qty) / count(distinct date) from sales group by 1")
    units = {r[0]: r[1] for r in daily}
    return [{"sku": r[0], "name": r[1], "brand": r[2], "unit_cost": r[3], "unit_price": r[4], "category": r[5],
             "daily_units": units.get(r[0]) or 0} for r in rows]


def _reference() -> Path | None:
    if not config.VISION_REFERENCE:
        return None
    p = (config.ROOT / config.VISION_REFERENCE).resolve()
    return p if p.is_file() else None


def _provider():
    from . import gemini
    from ..llm.structured import structured
    return gemini.structured if config.vision_provider() == "gemini" else structured


async def assess_photo(path: Path, catalog: list[dict] | None = None) -> dict:
    """Φωτογραφία → αξιολόγηση κατά ASSESS_SCHEMA. Καμία σύγκριση με θέσεις· όλα από το μοντέλο.

    catalog=None → κανονική λειτουργία (ο κατάλογος του τμήματος). catalog=[] → «άγνωστο ράφι»: το μοντέλο
    περιγράφει μόνο ό,τι βλέπει, χωρίς «λείπει» και χωρίς παραγγελίες, γιατί δεν ξέρουμε τι θα έπρεπε να έχει.
    """
    from . import prompts
    path = Path(path)
    catalog = await asyncio.to_thread(_catalog) if catalog is None else catalog
    known = {c["sku"] for c in catalog}

    if config.vision_provider() == "mock":
        side = path.with_suffix(".assessment.json")
        if not side.exists():
            side = demo_data.PHOTOS_DIR / f"{_mock_name}.assessment.json"
        return normalize(json.loads(side.read_text(encoding="utf-8")), known)

    ref = _reference()
    key = (str(path.resolve()), path.stat().st_mtime_ns, config.vision_provider(), config.vision_model(),
           prompts.PROMPT_VERSION, str(ref), config.SHELF_SET, len(catalog) or "unknown")
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]

    call = _provider()
    last = None
    for _ in range(2):                      # μία επανάληψη σε timeout ή χαλασμένο JSON
        try:
            raw = await asyncio.wait_for(
                call(SYSTEM, user_prompt(catalog, ref is not None), ASSESS_SCHEMA,
                     images=[ref, path] if ref else [path]),
                timeout=config.VISION_TIMEOUT_SECONDS)
            break
        except (asyncio.TimeoutError, ValueError, json.JSONDecodeError) as e:
            last = e
    else:
        raise RuntimeError(f"Το μοντέλο όρασης απέτυχε δύο φορές: {type(last).__name__}: {last}")

    verdict = normalize(raw, known)
    _cache[key] = verdict
    if len(_cache) > _CACHE_SIZE:
        _cache.popitem(last=False)
    return verdict
