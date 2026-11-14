"""Σενάρια: κάθε σενάριο = ρόλος (prompt) + λίστα εργαλείων + παραδείγματα στόχων.

Για νέο σενάριο στο hackathon: αντίγραψε ένα από τα παρακάτω, άλλαξε το prompt και τα
εργαλεία, πρόσθεσέ το στο SCENARIOS. Δεν χρειάζεται αλλαγή πουθενά αλλού.
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
- Μην κάνεις πράξεις νοερά. Κάθε αριθμός που δεν διάβασες αυτούσιο (διαφορά, ποσοστό, άθροισμα, επίπτωση) βγαίνει
  από SQL ή από το compute. Στοιχεία από έγγραφα τα παίρνεις με το extract_fields όπου είναι διαθέσιμο.
- Αν ένα εργαλείο αποτύχει, δοκίμασε άλλον δρόμο πριν τα παρατήσεις.
- Ενέργειες προς τα έξω (email, παραγγελία) περνούν από έγκριση ανθρώπου· ετοίμασέ τες πλήρως ώστε να αρκεί ένα «ναι».
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
Βάση δεδομένων (DuckDB) της «Αγορά Plus», αλυσίδας χονδρικής με 4 καταστήματα:
- sales(date, store_id, sku, qty, revenue, cost): ημερήσιες πωλήσεις. Περιθώριο = revenue - cost.
- products(sku, name, category, supplier_id, unit_cost, unit_price)
- suppliers(supplier_id, name, email, lead_days)
- stores(store_id, name, city)
- stock(store_id, sku, on_hand, reorder_point)
- supplier_prices(supplier_id, sku, price, min_qty, valid_from): τιμοκατάλογοι όλων των προμηθευτών.
- customer_weekly_needs(customer, sku, weekly_qty)
- invoices(...), bank_transactions(date, description, counterparty, amount)
"""

# ---------------------------------------------------------------------------
ANALYST = Scenario(
    name="analyst",
    title="Εμπορικός αναλυτής",
    description="Εντοπίζει μόνος του τι άλλαξε στα νούμερα, βρίσκει την αιτία και ετοιμάζει την ενέργεια.",
    prompt=f"""
Είσαι ο εμπορικός αναλυτής της «Αγορά Plus». Δεν γράφεις απλώς αναφορές: βρίσκεις την αιτία ενός
προβλήματος και ετοιμάζεις τη διορθωτική ενέργεια.
{SCHEMA_HINT}
Μέθοδος:
1. Μέτρησε το πρόβλημα (πόσο, από πότε, σε σχέση με τον μέσο όρο των προηγούμενων 14 ημερών).
2. Κατέβα επίπεδα μέχρι να βρεις την αιτία: κατηγορία → προϊόν → προμηθευτής → κατάστημα. Ξεχώρισε αν
   άλλαξε ο όγκος, η τιμή πώλησης ή το κόστος.
3. Υπολόγισε την επίπτωση σε ευρώ ανά ημέρα και ανά μήνα αν δεν γίνει τίποτα.
4. Πρότεινε συγκεκριμένη ενέργεια με αριθμούς (π.χ. νέα τιμή ανά προϊόν ή εναλλακτικός προμηθευτής από το supplier_prices).
5. Παράδωσε: (α) αναφορά μίας σελίδας «report.html» με 1-2 γραφήματα (make_chart) και πίνακα ενεργειών,
   (β) έτοιμο email προς τον προμηθευτή ή τη διοίκηση με send_email.
""",
    tools=COMMON_TOOLS + ["describe_data", "sql_query", "make_chart", "send_email", "web_search", "fetch_url"],
    examples=[
        "Γιατί έπεσε το περιθώριο χθες; Βρες την αιτία και ετοίμασε ό,τι χρειάζεται για να διορθωθεί.",
        "Ποια 5 προϊόντα αξίζει να αλλάξουν προμηθευτή; Υπολόγισε το ετήσιο όφελος.",
        "Ετοίμασε την εβδομαδιαία εμπορική αναφορά για τη διοίκηση.",
    ],
    mock_script=[
        ("Ξεκινάω με πλάνο.", [("update_plan", {"steps": [
            {"title": "Μέτρηση περιθωρίου ανά κατηγορία", "status": "in_progress"},
            {"title": "Εντοπισμός αιτίας", "status": "pending"},
            {"title": "Γράφημα και αναφορά", "status": "pending"},
            {"title": "Email στον προμηθευτή", "status": "pending"}]})]),
        ("Συγκρίνω την τελευταία ημέρα με τις προηγούμενες 14.", [("sql_query", {"sql":
            "with d as (select max(date) m from sales) select p.category, "
            "round(100*sum(case when s.date=d.m then s.revenue-s.cost end)/sum(case when s.date=d.m then s.revenue end),1) as margin_last, "
            "round(100*sum(case when s.date<d.m and s.date>=d.m-14 then s.revenue-s.cost end)/sum(case when s.date<d.m and s.date>=d.m-14 then s.revenue end),1) as margin_avg14 "
            "from sales s join products p using(sku), d group by 1 order by 2"})]),
        ("Φτιάχνω το γράφημα της τάσης.", [("make_chart", {"sql":
            "select strftime(s.date,'%d/%m') d, round(100*sum(s.revenue-s.cost)/sum(s.revenue),1) as margin_pct "
            "from sales s where s.date >= (select max(date) from sales) - 20 group by s.date order by s.date",
            "kind": "line", "title": "Περιθώριο % ανά ημέρα", "filename": "margin_trend.png"}),
            ("update_plan", {"steps": [
                {"title": "Μέτρηση περιθωρίου ανά κατηγορία", "status": "done"},
                {"title": "Εντοπισμός αιτίας", "status": "done"},
                {"title": "Γράφημα και αναφορά", "status": "in_progress"},
                {"title": "Email στον προμηθευτή", "status": "pending"}]})]),
        ("Γράφω την αναφορά.", [("write_file", {"path": "report.html", "content":
            "<html><meta charset='utf-8'><body style='font-family:Arial;max-width:800px;margin:40px auto'>"
            "<h1>Πτώση περιθωρίου: δοκιμαστική αναφορά</h1><p>Αναφορά από το ψεύτικο μοντέλο, για έλεγχο της ροής.</p>"
            "<img src='margin_trend.png' style='width:100%'></body></html>"})]),
        ("Ετοιμάζω το email.", [("send_email", {"to": "sales@galaktokomiki-ipeirou.example",
            "subject": "Αύξηση τιμών: αίτημα επανεξέτασης",
            "body": "Καλησπέρα σας,\n\nδιαπιστώσαμε αύξηση κόστους στα προϊόντα σας. Παρακαλούμε για επικοινωνία.\n\nΑγορά Plus"})]),
        ("Υπολογίζω την επίπτωση με κώδικα.", [("compute", {"label": "Απώλεια ανά μήνα (€)",
            "expression": "round(daily_loss * 26, 0)", "variables": {"daily_loss": 48.5}})]),
        ("Δηλώνω το βασικό αποτέλεσμα.", [("headline_result", {"value": "1.261 €", "label": "απώλεια ανά μήνα αν δεν γίνει τίποτα",
            "detail": "Δοκιμαστικός αριθμός από το ψεύτικο μοντέλο."}),
            ("update_plan", {"steps": [
                {"title": "Μέτρηση περιθωρίου ανά κατηγορία", "status": "done"},
                {"title": "Εντοπισμός αιτίας", "status": "done"},
                {"title": "Γράφημα και αναφορά", "status": "done"},
                {"title": "Email στον προμηθευτή", "status": "done"}]})]),
        ("Ολοκληρώθηκε η δοκιμαστική ροή: μέτρηση, γράφημα, αναφορά (report.html) και email προς έγκριση.", []),
    ],
)

# ---------------------------------------------------------------------------
PROCUREMENT = Scenario(
    name="procurement",
    title="Υπάλληλος προμηθειών",
    description="Παίρνει έναν στόχο αγορών, συγκρίνει προμηθευτές και καταχωρεί την παραγγελία.",
    prompt=f"""
Είσαι ο υπάλληλος προμηθειών ενός μικρού εστιατορίου («Ταβέρνα Το Λιμανάκι»). Ο ιδιοκτήτης σου δίνει έναν
στόχο και εσύ παραδίδεις έτοιμη παραγγελία.
{SCHEMA_HINT}
Μέθοδος:
1. Βρες τι χρειάζεται (customer_weekly_needs) και τι προσφέρει κάθε προμηθευτής (supplier_prices· πρόσεξε το min_qty).
2. Διάλεξε τον φθηνότερο συνδυασμό μέσα στο όριο δαπάνης. Υπολόγισε πόσα γλιτώνει σε σχέση με την αγορά όλων
   από τον κύριο προμηθευτή.
3. Για τα ποτά υπάρχει το portal του προμηθευτή στο {config.BASE_URL}/portal (σύνδεση: demo / demo). Μπες με τα
   browser_*, βάλε τα προϊόντα στο καλάθι και υπέβαλε την παραγγελία. Κράτησε τον αριθμό παραγγελίας.
4. Για τους υπόλοιπους προμηθευτές στείλε αίτημα παραγγελίας με send_email (ένα email ανά προμηθευτή).
5. Γράψε «order_summary.md» με πίνακα: προϊόν, ποσότητα, προμηθευτής, τιμή, σύνολο, εξοικονόμηση.
""",
    tools=COMMON_TOOLS + ["describe_data", "sql_query", "send_email", "browser_open", "browser_click",
                          "browser_type", "browser_download", "read_pdf", "web_search", "fetch_url"],
    examples=[
        "Γέμισέ μου το μαγαζί για την εβδομάδα, μέχρι 800 €.",
        "Παράγγειλε μόνο τα ποτά της εβδομάδας από το portal.",
    ],
    mock_script=[
        ("Πλάνο.", [("update_plan", {"steps": [
            {"title": "Ανάγκες εβδομάδας", "status": "in_progress"},
            {"title": "Παραγγελία ποτών στο portal", "status": "pending"},
            {"title": "Σύνοψη", "status": "pending"}]})]),
        ("Βλέπω τις ανάγκες.", [("sql_query", {"sql": "select n.sku, p.name, n.weekly_qty from customer_weekly_needs n join products p using(sku)"})]),
        ("Μπαίνω στο portal.", [("browser_open", {"url": f"{config.BASE_URL}/portal/login"})]),
        ("", [("browser_type", {"selector": "#username", "text": "demo"})]),
        ("", [("browser_type", {"selector": "#password", "text": "demo", "press_enter": True})]),
        ("Πάω στον κατάλογο.", [("browser_open", {"url": f"{config.BASE_URL}/portal/catalog"})]),
        ("Προσθέτω νερά.", [("browser_type", {"selector": "#qty-P011", "text": "20"})]),
        ("", [("browser_click", {"target": "#add-P011"})]),
        ("Υποβάλλω.", [("browser_open", {"url": f"{config.BASE_URL}/portal/cart"})]),
        ("", [("browser_click", {"target": "#checkout"})]),
        ("Γράφω σύνοψη.", [("write_file", {"path": "order_summary.md", "content": "# Παραγγελία (δοκιμή)\n\n| Προϊόν | Ποσότητα |\n|---|---|\n| Νερό 1.5L x6 | 20 |\n"})]),
        ("Ολοκληρώθηκε η δοκιμαστική ροή: σύνδεση στο portal, καλάθι, υποβολή παραγγελίας και σύνοψη.", []),
    ],
)

# ---------------------------------------------------------------------------
INVOICES = Scenario(
    name="invoices",
    title="Υπάλληλος τιμολογίων",
    description="Μαζεύει τα τιμολόγια από email και portal, βρίσκει ποια λείπουν και τα ζητάει.",
    prompt=f"""
Είσαι ο υπάλληλος λογιστηρίου της «Αγορά Plus». Στόχος σου είναι ο πλήρης μηνιαίος φάκελος για τον λογιστή:
κάθε πληρωμή της τράπεζας να έχει το τιμολόγιό της.
{SCHEMA_HINT}
Πηγές:
- Κινήσεις τράπεζας: data/bank_statement.csv (ή ο πίνακας bank_transactions). Η περιγραφή έχει τον αριθμό τιμολογίου.
- Τιμολόγια που ήρθαν με email: inbox_list / inbox_read, τα PDF βρίσκονται στο data/invoices (read_pdf).
- Τιμολόγια του προμηθευτή «Ποτά Αιγαίου»: μόνο από το portal {config.BASE_URL}/portal (σύνδεση: demo / demo),
  κατέβασέ τα με browser_download.
Μέθοδος:
1. Διάβασε κάθε τιμολόγιο και κράτησε αριθμό, προμηθευτή, ημερομηνία, καθαρή αξία, ΦΠΑ, σύνολο.
2. Αντιστοίχισε με τις πληρωμές. Σημείωσε διαφορές ποσών.
3. Για κάθε πληρωμή χωρίς τιμολόγιο, στείλε email στον προμηθευτή (η διεύθυνση είναι στον πίνακα suppliers) και ζήτα το.
4. Παράδωσε «invoice_register.csv» (όλα τα τιμολόγια) και «reconciliation.md» (τι ταιριάζει, τι λείπει, τι ζητήθηκε).
""",
    tools=COMMON_TOOLS + ["describe_data", "sql_query", "read_pdf", "extract_fields", "inbox_list", "inbox_read", "send_email",
                          "browser_open", "browser_click", "browser_type", "browser_download"],
    examples=[
        "Ετοίμασε τον φάκελο τιμολογίων του μήνα για τον λογιστή και κυνήγησε ό,τι λείπει.",
        "Κατέβασε τα νέα τιμολόγια από το portal των Ποτών Αιγαίου και αρχειοθέτησέ τα.",
    ],
    mock_script=[
        ("Πλάνο.", [("update_plan", {"steps": [
            {"title": "Ανάγνωση εισερχομένων", "status": "in_progress"},
            {"title": "Αντιστοίχιση με τράπεζα", "status": "pending"},
            {"title": "Αίτημα για όσα λείπουν", "status": "pending"}]})]),
        ("Διαβάζω τα εισερχόμενα.", [("inbox_list", {})]),
        ("Διαβάζω τις κινήσεις.", [("read_file", {"path": "data/bank_statement.csv"})]),
        ("Διαβάζω ένα τιμολόγιο.", [("list_files", {"folder": "data/invoices"})]),
        ("Ελέγχω ένα ποσό με κώδικα.", [("compute", {"label": "Σύνολο με ΦΠΑ 24%", "expression": "round(net * 1.24, 2)", "variables": {"net": 1000}})]),
        ("Ζητάω αυτό που λείπει.", [("send_email", {"to": "info@katharistika-notou.example",
            "subject": "Αίτημα αποστολής τιμολογίου",
            "body": "Καλησπέρα σας,\n\nδεν έχουμε λάβει το τιμολόγιο για την πληρωμή μας. Παρακαλούμε στείλτε το.\n\nΑγορά Plus"})]),
        ("Ολοκληρώθηκε η δοκιμαστική ροή: εισερχόμενα, κινήσεις τράπεζας και αίτημα για τιμολόγιο που λείπει.", []),
    ],
)

# ---------------------------------------------------------------------------
BLANK = Scenario(
    name="blank",
    title="Κενό σενάριο (για το challenge)",
    description="Γενικός agent με όλα τα εργαλεία. Αφετηρία για ό,τι ανακοινωθεί στο hackathon.",
    prompt="Είσαι ένας ικανός, αυτόνομος βοηθός που φέρνει σε πέρας τον στόχο του χρήστη από την αρχή ως το τέλος.",
    tools=COMMON_TOOLS + ["describe_data", "sql_query", "make_chart", "read_pdf", "extract_fields", "inbox_list", "inbox_read",
                          "send_email", "web_search", "fetch_url", "browser_open", "browser_click",
                          "browser_type", "browser_download"],
    examples=["Βρες τι είναι το GenAI Summit 5 και γράψε μου σύνοψη μίας σελίδας."],
    mock_script=[("Το κενό σενάριο δεν έχει δοκιμαστική ροή. Όρισε LLM_PROVIDER στο .env.", [])],
)

SCENARIOS: dict[str, Scenario] = {s.name: s for s in (ANALYST, PROCUREMENT, INVOICES, BLANK)}
