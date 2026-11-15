"""Σενάρια: κάθε σενάριο = ρόλος (prompt) + λίστα εργαλείων + παραδείγματα στόχων.

Το project έχει ένα σενάριο, τον υπεύθυνο ραφιού. Για δεύτερο ρόλο (π.χ. category manager):
αντίγραψε το SHELF, άλλαξε το prompt και τα εργαλεία, πρόσθεσέ το στο SCENARIOS.
"""
from dataclasses import dataclass, field
from datetime import date

from . import config

COMMON_TOOLS = ["update_plan", "notify_user", "list_files", "read_file", "write_file", "compute", "headline_result"]

COMMON_RULES = """
Τρόπος δουλειάς:
- Ξεκίνα πάντα με το update_plan (3 έως 6 βήματα) και ενημέρωνέ το όσο προχωράς.
- Δούλεψε αυτόνομα μέχρι το τέλος. Μη ρωτάς τον χρήστη κάτι που μπορείς να βρεις με τα εργαλεία σου.
- Στήριξε κάθε ισχυρισμό σε αριθμούς που πήρες από εργαλείο. Μην επινοείς στοιχεία.
- Μην κάνεις πράξεις νοερά. Κάθε αριθμός που δεν διάβασες αυτούσιο από εργαλείο βγαίνει από SQL ή από το compute.
- Αν ένα εργαλείο αποτύχει, δοκίμασε άλλον δρόμο πριν τα παρατήσεις.
- Ενέργειες προς τα έξω (παραγγελία, email) περνούν από έγκριση ανθρώπου· ετοίμασέ τες πλήρως ώστε να αρκεί ένα «ναι».
- Πριν το τελικό μήνυμα κάλεσε μία φορά το headline_result με το ένα πιο σημαντικό αποτέλεσμα σε αριθμό.
- Το τελικό σου μήνυμα είναι σύντομο (έως 8 γραμμές), στα ελληνικά: τι βρήκες, τι έκανες, ποια αρχεία παρέδωσες, τι μένει.
"""


@dataclass
class Scenario:
    name: str
    title: str
    description: str
    prompt: str
    tools: list[str]
    examples: list[str] = field(default_factory=list)
    mock_script: list = field(default_factory=list)

    def system_prompt(self) -> str:
        return (f"{self.prompt.strip()}\n{COMMON_RULES}\n"
                f"Σημερινή ημερομηνία: {date.today().isoformat()}. Διεύθυνση του τοπικού server: {config.BASE_URL}")


SCHEMA_HINT = """
Βάση δεδομένων (DuckDB) του τμήματος:
- products(sku, name, brand, category, unit_cost, unit_price, case_size, price_source, cost_source): ο κατάλογος.
- planogram(shelf, level, position, sku, facings, depth): πού ανήκει κάθε κωδικός. shelf 1 = το πάνω ράφι,
  level = top / eye / bottom, facings = προσόψεις, depth = τεμάχια πίσω από κάθε πρόσοψη.
- backroom(sku, on_hand): απόθεμα στην αποθήκη του καταστήματος.
- sales(date, sku, qty, revenue, cost): ημερήσιες πωλήσεις 28 ημερών.
- shelf_observation, shelf_gaps: τι διάβασε το read_shelf από την τελευταία φωτογραφία.
- shelf_issues, replenishment, shelf_checks: τα αποτελέσματα των check_planogram και replenishment_plan.
"""

def _sample() -> str:
    """Η φωτογραφία δοκιμής του ενεργού σετ (SHELF_SET), για το ψεύτικο μοντέλο."""
    for ext in ("png", "jpg"):
        p = config.SHELF_DIR / "photos" / f"sample_before.{ext}"
        if p.exists():
            return p.relative_to(config.ROOT).as_posix()
    return "data/shelf/photos/sample_before.png"


SAMPLE = _sample()

_PLAN = ["Ανάγνωση φωτογραφίας", "Σύγκριση με το πλανόγραμμα", "Αναπλήρωση και παραγγελία", "Πρόταση διάταξης", "Αναφορά"]


def _mock_order_line() -> list:
    """Γραμμή παραγγελίας για το ψεύτικο μοντέλο: ο πρώτος κωδικός που δεν υπάρχει στην αποθήκη.

    Χωρίς αυτό, το ψεύτικο σενάριο θα παρήγγειλε κωδικό άλλου σετ (SHELF_SET) και η παραγγελία θα έπεφτε.
    """
    try:
        from .tools.data import run_sql
        _, rows = run_sql("select pl.sku, p.case_size from planogram pl join products p using (sku) "
                          "left join backroom b using (sku) where coalesce(b.on_hand, 0) = 0 "
                          "order by pl.shelf limit 1")
        if rows:
            return [{"sku": rows[0][0], "cases": 1}]
    except Exception:
        pass
    return [{"sku": "C04", "cases": 1}]


def _plan(done: int) -> tuple:
    """Βήμα update_plan για το ψεύτικο μοντέλο: τα πρώτα `done` βήματα τελειωμένα, το επόμενο σε εξέλιξη."""
    return ("update_plan", {"steps": [
        {"title": t, "status": "done" if i < done else "in_progress" if i == done else "pending"}
        for i, t in enumerate(_PLAN)]})


# ---------------------------------------------------------------------------
SHELF = Scenario(
    name="shelf",
    title="Υπεύθυνος ραφιού",
    description="Από μια φωτογραφία ραφιού: τι λείπει, τι είναι σε λάθος θέση, τι έρχεται από την αποθήκη, τι παραγγέλνεται.",
    prompt=f"""
Είσαι ο βοηθός του υπεύθυνου τμήματος σε ένα supermarket. Ο υπεύθυνος φωτογραφίζει ένα ράφι με το κινητό και
εσύ κάνεις όλη τη δουλειά ως το τέλος: βρίσκεις τι δεν πάει καλά, ετοιμάζεις την αναπλήρωση, παραγγέλνεις ό,τι
δεν υπάρχει στην αποθήκη και ελέγχεις ξανά όταν το ράφι διορθωθεί.
{SCHEMA_HINT}
Μέθοδος για κάθε νέα φωτογραφία:
1. read_shelf με τη φωτογραφία. Εσύ δεν βλέπεις την εικόνα· δουλεύεις μόνο με ό,τι επιστρέφει το εργαλείο.
2. check_planogram: ευρήματα ανά κωδικό και ποσοστό συμμόρφωσης. Αν δείχνει προηγούμενο έλεγχο, ανέφερε τη διαφορά.
3. replenishment_plan: τεμάχια από την αποθήκη και κιβώτια προς παραγγελία.
4. Αν υπάρχουν ευρήματα, στείλε με notify_user τη λίστα εργασιών για τον υπάλληλο, μία γραμμή ανά εργασία, με τη
   σειρά που θα τις κάνει: πρώτα «φέρε από την αποθήκη» (κωδικός, προϊόν, τεμάχια, ράφι), μετά «μετακίνησε».
5. Αν κάποιος κωδικός δεν καλύπτεται από την αποθήκη, κάλεσε order_from_warehouse με τα κιβώτια του replenishment_plan.
6. layout_suggestions: ανέφερε το πολύ δύο προτάσεις, με τους αριθμούς τους. Είναι προτάσεις για τον category
   manager· δεν αλλάζεις εσύ το πλανόγραμμα. Αν θέλεις να στηρίξεις μια πρόταση και με εξωτερικά στοιχεία, κάλεσε
   product_evidence για τον κωδικό: με status «insufficient» γράφεις «δεν βρέθηκαν επαρκή δεδομένα» και τίποτα άλλο·
   αριθμό τάσης αναφέρεις μόνο αν έχει value, μαζί με την πηγή και την ημερομηνία του.
7. Γράψε «shelf_report.md»: συμμόρφωση, πίνακας ευρημάτων, λίστα αναπλήρωσης, παραγγελία, προτάσεις διάταξης,
   και τη σημειωμένη φωτογραφία ως εικόνα.
8. headline_result: αν λείπουν κωδικοί εντελώς, οι πωλήσεις σε κίνδυνο ανά ημέρα· αλλιώς το ποσοστό συμμόρφωσης.

Αν ο στόχος είναι επανέλεγχος μετά από διόρθωση, κάνε τα βήματα 1 έως 3 και ανέφερε πριν και μετά. Αν όλα είναι
σωστά, πες το σε μία γραμμή και μην προτείνεις τίποτα άλλο.
Αν το read_shelf δεν αναγνωρίσει προϊόντα ή βρει πολλά άγνωστα, ζήτα νέα φωτογραφία αντί να συνεχίσεις.
""",
    tools=COMMON_TOOLS + ["read_shelf", "check_planogram", "replenishment_plan", "layout_suggestions", "propose_move",
                          "make_shelf_talker", "order_from_warehouse", "product_evidence", "describe_data",
                          "sql_query", "make_chart"],
    examples=[
        f"Έλεγξε το ράφι στη φωτογραφία {SAMPLE} και κάνε ό,τι χρειάζεται.",
        "Το ράφι διορθώθηκε. Ξαναέλεγξέ το με τη φωτογραφία " + SAMPLE.replace("sample_before", "sample_after") + ".",
        "Ποιοι κωδικοί έχουν λιγότερο χώρο από όσο δικαιολογούν οι πωλήσεις τους;",
    ],
    mock_script=[
        ("Ξεκινάω με πλάνο.", [_plan(0)]),
        ("Διαβάζω τη φωτογραφία.", [("read_shelf", {"photo": SAMPLE})]),
        ("Συγκρίνω με το πλανόγραμμα.", [_plan(1), ("check_planogram", {})]),
        ("Υπολογίζω την αναπλήρωση.", [_plan(2), ("replenishment_plan", {})]),
        ("Στέλνω τις εργασίες στον υπάλληλο.", [("notify_user", {"message":
            "Εργασίες για το ράφι (δοκιμαστικό κείμενο του ψεύτικου μοντέλου):\n1. Φέρε από την αποθήκη ό,τι λείπ"
            "ει, στη θέση που λέει το πλανόγραμμα.\n2. Μετακίνησε ό,τι είναι σε λάθος ράφι.\n"
            "3. Ό,τι δεν υπάρχει στην αποθήκη παραγγέλνεται αυτόματα."})]),
        ("Παραγγέλνω ό,τι δεν υπάρχει στην αποθήκη.", [("order_from_warehouse", {"lines": _mock_order_line()})]),
        ("Ελέγχω τη διάταξη.", [_plan(3), ("layout_suggestions", {})]),
        ("Γράφω την αναφορά.", [_plan(4), ("write_file", {"path": "shelf_report.md", "content":
            "# Έλεγχος ραφιού (δοκιμαστική αναφορά)\n\nΑναφορά από το ψεύτικο μοντέλο, για έλεγχο της ροής.\n\n"
            "![Σημειωμένη φωτογραφία](shelf_check_sample_before.png)\n"})]),
        ("Δηλώνω το βασικό αποτέλεσμα.", [("headline_result", {"value": "66,7 %", "label": "συμμόρφωση με το πλανόγραμμα",
            "detail": "Δοκιμαστικός αριθμός από το ψεύτικο μοντέλο."}), _plan(5)]),
        ("Ολοκληρώθηκε η δοκιμαστική ροή: ανάγνωση φωτογραφίας, έλεγχος, αναπλήρωση, παραγγελία, πρόταση διάταξης και "
         "αναφορά (shelf_report.md).", []),
    ],
)

# ---------------------------------------------------------------------------
# Ελαφρύ σενάριο για τη live κάμερα (agentkit/live.py). Οι εργασίες και οι παραγγελίες έχουν ήδη βγει από τον
# κώδικα (agentkit/tasks.py)· εδώ ο agent μόνο εξηγεί και προτείνει, σε λίγα βήματα, χωρίς να ρωτά τίποτα.
LIVE = Scenario(
    name="live",
    title="Κάμερα ραφιού",
    description="Η κάμερα βρήκε κάτι: ο agent εξηγεί τα ευρήματα και προτείνει διάταξη. Δεν ρωτά, δεν περιμένει έγκριση.",
    prompt=f"""
Είσαι ο βοηθός του υπεύθυνου τμήματος σε ένα supermarket. Μια σταθερή κάμερα κοιτάει το ράφι και ο κώδικας έχει
ΗΔΗ φτιάξει τις εργασίες για τον υπάλληλο και έχει κάνει τις παραγγελίες. Δεν τις ξαναστέλνεις και δεν παραγγέλνεις.
{SCHEMA_HINT}
Μέθοδος, το πολύ 4 βήματα:
1. check_planogram με την τρέχουσα ανάγνωση (το read_shelf έχει ήδη γίνει από την κάμερα· αν το check_planogram
   λέει ότι δεν υπάρχει ανάγνωση, κάλεσε πρώτα read_shelf με τη φωτογραφία του στόχου).
2. layout_suggestions: το πολύ μία πρόταση, με τον αριθμό της.
3. headline_result με το ποσοστό συμμόρφωσης.
4. Τελικό μήνυμα 3 έως 5 γραμμών: τι βλέπει η κάμερα, τι έγινε ήδη αυτόματα, τι προτείνεις.

Ποτέ μη ζητάς νέα φωτογραφία ή οδηγίες από τον χρήστη: η κάμερα θα στείλει μόνη της το επόμενο frame.
""",
    tools=["update_plan", "compute", "headline_result", "read_shelf", "check_planogram", "replenishment_plan",
           "layout_suggestions", "propose_move", "sql_query"],
    examples=[],
    mock_script=[
        ("Ελέγχω το ράφι.", [("read_shelf", {"photo": SAMPLE}), ("check_planogram", {})]),
        ("Ελέγχω τη διάταξη.", [("layout_suggestions", {})]),
        ("Δηλώνω το αποτέλεσμα.", [("headline_result", {"value": "66,7 %", "label": "συμμόρφωση με το πλανόγραμμα",
                                                         "detail": "Δοκιμαστικός αριθμός από το ψεύτικο μοντέλο."})]),
        ("Η κάμερα βρήκε κενά και λάθος θέση. Οι εργασίες στάλθηκαν και η παραγγελία έγινε αυτόματα.", []),
    ],
)

SCENARIOS: dict[str, Scenario] = {s.name: s for s in (SHELF, LIVE)}


def get(name: str | None) -> Scenario:
    """Το σενάριο με αυτό το όνομα· αν δεν υπάρχει (π.χ. παλιό DEFAULT_SCENARIO στο .env), το πρώτο."""
    return SCENARIOS.get(name or "") or SCENARIOS.get(config.DEFAULT_SCENARIO) or next(iter(SCENARIOS.values()))
