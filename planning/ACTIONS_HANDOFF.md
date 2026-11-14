# Ενέργειες μετά τη σύσταση: παράδοση

Τι υπάρχει στο `feat/shelfsense-actions` για ό,τι γίνεται **μετά** από μια σύσταση τοποθέτησης: feedback του
υπεύθυνου, ταμπελάκι ραφιού, δεύτερη φωτογραφία. Λεπτομέρειες για τη δεύτερη φωτογραφία:
[`VERIFICATION.md`](VERIFICATION.md).

## Κατάσταση

| Τι | Κατάσταση |
|---|---|
| Υλοποίηση και τοπικοί έλεγχοι (test fixtures, προσωρινή αποθήκευση, χωρίς δίκτυο) | Έγινε |
| Πραγματική παραγωγή εικόνας από το fal | Εκκρεμεί (οι έλεγχοι χρησιμοποιούν mock· δεν έχει χρεωθεί καμία κλήση) |
| Σύνδεση με τον producer (ο agent γράφει πραγματικές συστάσεις) | Εκκρεμεί |
| Ενσωμάτωση όρασης (`vision_integration`) | Εκκρεμεί |
| Έλεγχος από άκρη σε άκρη (`end_to_end_validation`) | Εκκρεμεί |

Τίποτα από τα παραπάνω δεν έχει συμφωνηθεί με τις άλλες ομάδες. Το συμβόλαιο συστάσεων είναι `0-provisional`.

## 1. Συστάσεις και feedback

Κώδικας: [`agentkit/recommendations.py`](../agentkit/recommendations.py) (αποθήκη, συμβόλαιο),
[`agentkit/feedback_api.py`](../agentkit/feedback_api.py) (HTTP).

- **Καταχώριση:** μόνο από κώδικα, `recommendations.register_recommendation(payload)`. Δεν υπάρχει endpoint.
  Υποχρεωτικά: `recommendation_id`, `product` (`sku` ή/και `name`), `placement.to`. Η σύσταση αποθηκεύεται όπως ήρθε
  και δεν αλλάζει ποτέ.
- **`GET /api/recommendations/{id}`**: αρχική σύσταση, ιστορικό feedback, τρέχουσα απόφαση.
- **`POST /api/recommendations/{id}/feedback`**: `{"submission_id", "decision": "accepted"|"rejected"|"corrected",
  "correction"?, "note"?, "decided_by"?}`. 201 νέο, 200 επανάληψη ίδιου `submission_id`, 404, 409, 422.
  Το `correction` (μόνο στο `corrected`) δέχεται `product`, `price`, `placement`.
- Αποθήκευση ιδιωτική στο `state/recommendations.sqlite3` (gitignored, δεν σερβίρεται).

## 2. Ταμπελάκι ραφιού

Κώδικας: [`agentkit/shelf_talker.py`](../agentkit/shelf_talker.py), εργαλείο
[`agentkit/tools/talker.py`](../agentkit/tools/talker.py) (`make_shelf_talker`).

- **Κλήση:** εργαλείο `make_shelf_talker(recommendation_id, product_name, price_amount, currency, theme?)`.
  Φορτώνεται στο `load_all()`, αλλά **δεν είναι σε κανένα σενάριο** ακόμα.
- **Επιβεβαιωμένα στοιχεία:** όνομα και τιμή μόνο από feedback `corrected` του υπεύθυνου
  (`correction.product.name`, `correction.price` με `amount`, `currency`, `source`). Το απλό `accepted` δεν
  επιβεβαιώνει όνομα ή τιμή. Η τελευταία απόφαση δεν πρέπει να είναι `rejected`. Τα ορίσματα πρέπει να ταιριάζουν
  ακριβώς. Αλλιώς `missing_inputs` / `input_mismatch` και δεν στέλνεται τίποτα. Έλεγχος από το UI:
  `shelf_talker.confirmed_inputs(recommendation_id)`.
- **Έγκριση:** `needs_approval=True`. Η κάρτα έγκρισης δείχνει τα ορίσματα πριν από τη χρεωμένη κλήση στο fal.
- **Έξοδος:** στο `generated`, PNG στο `workspace/talkers/` (σερβίρεται στο `/files/talkers/...`) ως artifact.
  Το φόντο είναι από το fal (`fal-ai/flux/schnell`, χωρίς κείμενο)· όνομα και τιμή γράφονται τοπικά με Pillow.
  Ιδιωτική εγγραφή εργασίας στο `state/talkers/`. Στο `pending` ξανακαλείς με τα ίδια στοιχεία (συνεχίζει, όχι νέα
  χρέωση). Στο `submit_ambiguous` δεν ξαναστέλνει: κάποιος ελέγχει το fal dashboard και σβήνει την εγγραφή.
- Χρειάζεται `FAL_KEY` στο τοπικό `.env`.

## 3. Δεύτερη φωτογραφία

Κώδικας: [`agentkit/verification.py`](../agentkit/verification.py),
[`agentkit/verification_api.py`](../agentkit/verification_api.py). Πλήρης περιγραφή: [`VERIFICATION.md`](VERIFICATION.md).

- **`POST /api/verifications`** `{"recommendation_id", "expected_feedback_id"?}`: συνεδρία για την τρέχουσα έκδοση
  feedback, μόνο αν είναι `accepted`/`corrected`. 201 νέα, 200 υπάρχουσα.
- **`POST /api/verifications/{session_id}/scans`** multipart `file`, `upload_id`: αποθηκεύει την εικόνα,
  κατάσταση `awaiting_vision`. Καμία κλήση όρασης.
- **`GET /api/verifications/{session_id}`**: κατάσταση, προσπάθειες, και `target` (θέση προς έλεγχο).
- **Σωρευτικές διορθώσεις θέσης:** ο στόχος βγαίνει από την αρχική σύσταση και όλο το feedback με τη σειρά, μέχρι και
  το `feedback_id` της συνεδρίας. Κάθε διόρθωση αλλάζει μόνο τα πεδία που δίνει· `accepted`, `rejected` και διόρθωση
  μόνο ονόματος/τιμής δεν μηδενίζουν τίποτα. Μεταγενέστερο feedback δεν μετράει. Το `target.provenance` λέει ποια
  έκδοση έδωσε κάθε πεδίο.
- Νέο feedback κάνει τις ανοιχτές συνεδρίες `superseded`· κρατούν τον στόχο της δικής τους έκδοσης.
- Τα `verified` / `not_done` / `inconclusive` δεν υλοποιούνται και δεν υπάρχει endpoint για αποτέλεσμα.

## 4. Τι χρειάζεται από κάθε ομάδα

**Agent (producer):**
- Να καλεί `recommendations.register_recommendation(payload)` για κάθε πραγματική σύσταση, με σταθερό
  `recommendation_id` (συμβόλαιο στο docstring του `recommendations.py`).
- Να προσθέσει `"make_shelf_talker"` στα `tools` του σεναρίου ραφιού στο `agentkit/scenarios.py`.

**Όραση:**
- Να διαβάζει από `GET /api/verifications/{session_id}`: `status` (μόνο `awaiting_vision`), `target`,
  `scan_attempts[-1]`, `original_image_ref`. Bytes μέσα στη διεργασία: `verification.scan_image_path(session_id, attempt_no)`.
- Το συμβόλαιο αποτελέσματος δεν υπάρχει ακόμα (ενότητα «Ανοιχτό» στο `VERIFICATION.md`). Δεν υπάρχει τρόπος να
  γραφτεί αποτέλεσμα σήμερα.

**UI:**
- Feedback: νέο `submission_id` ανά ενέργεια χρήστη· στο retry το ίδιο. Επιβεβαίωση ονόματος/τιμής ως `corrected`.
- Έγκριση του `make_shelf_talker` από την υπάρχουσα κάρτα έγκρισης.
- Δεύτερη φωτογραφία: `expected_feedback_id` στην έναρξη, νέο `upload_id` ανά πάτημα. Στο `awaiting_vision`
  «ελήφθη, δεν έχει ελεγχθεί»· ποτέ «επιβεβαιώθηκε». Στο `superseded` «ξεκίνα νέο έλεγχο».

## 5. Έλεγχοι

Με το τοπικό `.venv-actions` (Python 3.11). Όλοι τρέχουν σε προσωρινή αποθήκευση, χωρίς δίκτυο:

```bash
.venv-actions/bin/python scripts/check_recommendations.py
```

```bash
.venv-actions/bin/python scripts/check_shelf_talker.py
```

```bash
.venv-actions/bin/python scripts/check_verification.py
```

## 6. Ανοιχτά ερωτήματα (χωρίς απόφαση)

- **Προτεραιότητα συντεταγμένων:** διόρθωση `shelf`/`position` πάνω σε `box_2d`/`point` (ή το αντίστροφο) αφήνει και
  τα δύο στον στόχο. Ποιο υπερισχύει;
- **Ταυτότητα προϊόντος σε διόρθωση:** το `correction.product` δεν αλλάζει τον στόχο της όρασης. Επιτρέπεται μια
  διόρθωση να αλλάξει το προϊόν, και τι ψάχνει τότε η όραση;
- **`null` σε ολόκληρη πλευρά:** το `correction.placement.from: null` σήμερα σημαίνει «δεν δόθηκε», όχι «σβήσε το
  `from`». Τι εννοεί το UI;

Άλλα ανοιχτά για το συμβόλαιο συστάσεων: docstring του `agentkit/recommendations.py`.
