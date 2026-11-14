"""Το συμβόλαιο της εξόδου του μοντέλου όρασης. Το διαβάζουν το read_shelf και το live loop.

Αλλαγή εδώ = αλλαγή συμβολαίου: προσθέτουμε πεδία, δεν αφαιρούμε ούτε μετονομάζουμε χωρίς συνεννόηση.
"""

BOX = {"type": "array", "items": {"type": "integer"},
       "description": "[ymin, xmin, ymax, xmax], κανονικοποιημένο 0-1000 ως προς την εικόνα"}

READING_SCHEMA = {
    "type": "object",
    "properties": {
        "occluded": {"type": "boolean",
                     "description": "true αν άνθρωπος, χέρι ή αντικείμενο κρύβει μέρος του ραφιού"},
        "items": {
            "type": "array",
            "description": "Μία εγγραφή για κάθε ομάδα ίδιων προϊόντων που στέκονται δίπλα δίπλα.",
            "items": {
                "type": "object",
                "properties": {
                    "sku": {"anyOf": [{"type": "string"}, {"type": "null"}],
                            "description": "Κωδικός από τον κατάλογο, ή null αν το προϊόν δεν είναι στον κατάλογο"},
                    "label": {"type": "string", "description": "Τι γράφει η συσκευασία, όπως το διαβάζεις"},
                    "shelf": {"type": "integer", "description": "Αριθμός ραφιού, 1 = το πάνω"},
                    "position": {"type": "integer", "description": "Σειρά στο ράφι, 1 = αριστερά"},
                    "facings": {"type": "integer", "description": "Πόσα τεμάχια φαίνονται δίπλα δίπλα στην μπροστινή σειρά"},
                    "box_2d": BOX,
                },
                "required": ["sku", "label", "shelf", "position", "facings", "box_2d"],
                "additionalProperties": False,
            },
        },
        "gaps": {
            "type": "array",
            "description": "Εμφανή κενά στο ράφι, όπου χωράει τουλάχιστον ένα προϊόν.",
            "items": {"type": "object", "properties": {"shelf": {"type": "integer"}, "box_2d": BOX},
                      "required": ["shelf", "box_2d"], "additionalProperties": False},
        },
        "visual_issues": {
            "type": "array",
            "description": "Παραβάσεις παρουσίασης που φαίνονται μόνο με το μάτι.",
            "items": {"type": "object", "properties": {
                "shelf": {"type": "integer"},
                "type": {"type": "string", "enum": ["label_not_facing", "not_fronted", "messy", "other"]},
                "detail": {"type": "string"}},
                "required": ["shelf", "type", "detail"], "additionalProperties": False},
        },
    },
    "required": ["occluded", "items", "gaps", "visual_issues"],
    "additionalProperties": False,
}
