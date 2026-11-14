"""Όραση: φωτογραφία ραφιού → δομημένη ανάγνωση (JSON). Κάτοχος: Άτομο Α (μοντέλο).

Η μόνη συνάρτηση που χρειάζεται ο υπόλοιπος κώδικας:

    reading = await read_photo(path)      # {"items": [...], "gaps": [...], "occluded": bool}

Τη χρησιμοποιούν το εργαλείο read_shelf (agent) και το live loop (agentkit/live.py).
Το συμβόλαιο της εξόδου είναι το READING_SCHEMA στο schema.py. Αν αλλάξει, ενημερώνεται και το Άτομο Β.
"""
from .assessment import assess_photo, set_mock_assessment, mock_assessment
from .reader import read_photo, set_mock_reading, mock_reading

__all__ = ["assess_photo", "set_mock_assessment", "mock_assessment",
           "read_photo", "set_mock_reading", "mock_reading"]
