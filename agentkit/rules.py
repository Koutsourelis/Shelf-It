"""Κανόνες απόφασης του agent (Κ1 έως Κ6). Καθαρός κώδικας: χωρίς μοντέλο, χωρίς βάση, χωρίς δίκτυο.

Οι παράμετροι και οι πηγές τους ζουν στο data/shelf/rules.json, ώστε να αλλάζουν χωρίς κώδικα. Η εξήγηση και η
βιβλιογραφία είναι στο planning/DECISION_RULES.md.

Κάθε πρόταση έχει τέσσερα μέρη: τι, κανόνας, αριθμός, πηγή. Όταν λείπει στοιχείο, ο κανόνας δεν βγάζει πρόταση
αλλά γράφει τον λόγο στο `skipped`.
"""
import json
from dataclasses import asdict, dataclass, field, replace

from . import config

RULES_FILE = config.DATA_DIR / "shelf" / "rules.json"


def load() -> dict:
    return json.loads(RULES_FILE.read_text(encoding="utf-8"))


@dataclass
class Slot:
    """Μία θέση του πλανογράμματος μαζί με τις πωλήσεις του κωδικού της."""
    sku: str
    name: str
    brand: str
    category: str
    shelf: int
    level: str            # top / eye / bottom
    position: int         # 1 = αριστερά
    facings: int
    depth: int
    units_day: float      # μέσα τεμάχια την ημέρα
    revenue_day: float    # μέσες πωλήσεις την ημέρα (€)
    margin_day: float     # μέσο περιθώριο την ημέρα (€)

    @property
    def margin_per_facing(self) -> float:
        return self.margin_day / self.facings if self.facings else 0.0


@dataclass
class Suggestion:
    rule: str                      # Κ3, Κ4...
    title: str
    what: str                      # η πρόταση σε μία φράση
    figure: str                    # ο αριθμός που τη στηρίζει
    source: str
    expression: str = ""           # ο τύπος, για το ίχνος ελέγχου
    variables: dict = field(default_factory=dict)
    result: float | None = None
    move: dict = field(default_factory=dict)   # για την οθόνη: {"sku", "swap_with"} ή {"from_sku", "to_sku"}

    def as_dict(self) -> dict:
        return asdict(self)

    def as_text(self) -> str:
        return (f"Τι:      {self.what}\nΚανόνας: {self.rule}, {self.title}.\n"
                f"Αριθμός: {self.figure}\nΠηγή:    {self.source}")


def _eur(x: float) -> str:
    return f"{x:.2f}".replace(".", ",") + " €"


# --- Κ1 ------------------------------------------------------------------------------------------------

def lost_sales(revenue_day: float, rules: dict) -> float:
    """Πωλήσεις που χάνει το κατάστημα την ημέρα όταν ο κωδικός λείπει εντελώς από το ράφι."""
    return round(revenue_day * rules["K1"]["lost_share"], 2)


# --- Κ3 ------------------------------------------------------------------------------------------------

def facing_gain(margin_day: float, facings: int, elasticity: float) -> float:
    return margin_day * (((facings + 1) / facings) ** elasticity - 1)


def facing_loss(margin_day: float, facings: int, elasticity: float) -> float:
    return margin_day * (1 - ((facings - 1) / facings) ** elasticity)


def facing_transfer(slots: list[Slot], rules: dict) -> Suggestion | None:
    """Η μία μεταφορά πρόσοψης με το μεγαλύτερο καθαρό όφελος. Ο δότης κρατά χωρητικότητα για min_cover_days."""
    r = rules["K3"]
    e, cover = r["space_elasticity"], r["min_cover_days"]
    best = None
    for donor in slots:
        if donor.facings < 2 or (donor.facings - 1) * donor.depth < donor.units_day * cover:
            continue
        loss = facing_loss(donor.margin_day, donor.facings, e)
        for taker in slots:
            if taker.sku == donor.sku:
                continue
            net = facing_gain(taker.margin_day, taker.facings, e) - loss
            if net > 0 and (best is None or net > best[0]):
                best = (net, donor, taker, loss)
    if best is None:
        return None
    _, donor, taker, loss = best
    gain, loss = round(facing_gain(taker.margin_day, taker.facings, e), 2), round(loss, 2)
    net = round(gain - loss, 2)
    return Suggestion(
        rule="Κ3", title=r["title"],
        what=f"Μία πρόσοψη από το {donor.sku} ({donor.name}) στο {taker.sku} ({taker.name}).",
        figure=f"κέρδος {_eur(gain)} την ημέρα − απώλεια {_eur(loss)} = +{_eur(net)} περιθώριο την ημέρα.",
        source=r["source"],
        expression="m_to * (((n_to + 1) / n_to) ** e - 1) - m_from * (1 - ((n_from - 1) / n_from) ** e)",
        variables={"m_to": round(taker.margin_day, 2), "n_to": taker.facings, "m_from": round(donor.margin_day, 2),
                   "n_from": donor.facings, "e": e},
        result=net, move={"from_sku": donor.sku, "to_sku": taker.sku})


# --- Κ4 ------------------------------------------------------------------------------------------------

def eye_level_swap(slots: list[Slot], rules: dict) -> Suggestion | None:
    r = rules["K4"]
    eye = [s for s in slots if s.level == "eye"]
    rest = [s for s in slots if s.level != "eye"]
    if not eye or not rest:
        return None
    best = max(rest, key=lambda s: s.margin_per_facing)
    worst = min(eye, key=lambda s: s.margin_per_facing)
    if best.margin_per_facing <= r["min_advantage"] * worst.margin_per_facing:
        return None
    return Suggestion(
        rule="Κ4", title=r["title"],
        what=f"Το {best.sku} ({best.name}) από το ράφι {best.shelf} στο ύψος των ματιών, στη θέση του {worst.sku} ({worst.name}).",
        figure=f"{_eur(best.margin_per_facing)} περιθώριο ανά πρόσοψη την ημέρα έναντι {_eur(worst.margin_per_facing)}. "
               "Δεν δίνεται ποσοστό αύξησης.",
        source=r["source"],
        expression="margin_day / facings",
        variables={best.sku: round(best.margin_per_facing, 2), worst.sku: round(worst.margin_per_facing, 2),
                   "min_advantage": r["min_advantage"]},
        result=round(best.margin_per_facing - worst.margin_per_facing, 2), move={"sku": best.sku, "swap_with": worst.sku})


# --- Κ5 ------------------------------------------------------------------------------------------------

def centre_position(slots: list[Slot], rules: dict) -> Suggestion | None:
    """Στο ράφι του ύψους ματιών, ο κωδικός με το υψηλότερο περιθώριο ανά πρόσοψη πρέπει να είναι στο κέντρο."""
    r = rules["K5"]
    eye = sorted((s for s in slots if s.level == "eye"), key=lambda s: s.position)
    if len(eye) < 3:
        return None
    middle = {eye[(len(eye) - 1) // 2].sku, eye[len(eye) // 2].sku}
    target = max(eye, key=lambda s: s.margin_per_facing)
    if target.sku in middle:
        return None
    now = eye[len(eye) // 2]
    return Suggestion(
        rule="Κ5", title=r["title"],
        what=f"Το {target.sku} ({target.name}) στο κέντρο του ραφιού {target.shelf}, στη θέση του {now.sku} ({now.name}).",
        figure=f"είναι ο κωδικός με το υψηλότερο περιθώριο ανά πρόσοψη στο ράφι ({_eur(target.margin_per_facing)} την "
               f"ημέρα) και βρίσκεται στη θέση {target.position} από {len(eye)}. Δεν δίνεται ποσοστό αύξησης.",
        source=r["source"],
        expression="margin_day / facings",
        variables={s.sku: round(s.margin_per_facing, 2) for s in eye},
        result=round(target.margin_per_facing, 2), move={"sku": target.sku, "swap_with": now.sku})


# --- Κ6 ------------------------------------------------------------------------------------------------

def private_label_adjacency(slots: list[Slot], rules: dict) -> list[Suggestion]:
    r = rules["K6"]
    own = {b.strip().lower() for b in r.get("private_label_brands", [])}
    out = []
    for pl in (s for s in slots if s.brand.strip().lower() in own):
        rivals = [s for s in slots if s.category == pl.category and s.brand.strip().lower() not in own]
        if not rivals:
            continue
        leader = max(rivals, key=lambda s: s.revenue_day)
        if pl.shelf == leader.shelf and abs(pl.position - leader.position) == 1:
            continue
        out.append(Suggestion(
            rule="Κ6", title=r["title"],
            what=f"Το {pl.sku} ({pl.name}, {pl.brand}) δίπλα στο {leader.sku} ({leader.name}, {leader.brand}), "
                 f"στο ράφι {leader.shelf}.",
            figure=f"το {leader.sku} είναι ο ηγέτης της κατηγορίας «{pl.category}» με {_eur(leader.revenue_day)} πωλήσεις "
                   f"την ημέρα· η ιδιωτική ετικέτα είναι στο ράφι {pl.shelf}, θέση {pl.position}. Ισχύει μόνο αν η "
                   "ποιότητά της είναι συγκρίσιμη.",
            source=r["source"],
            expression="max(revenue_day) among national brands of the category",
            variables={s.sku: round(s.revenue_day, 2) for s in rivals},
            result=round(leader.revenue_day, 2), move={"sku": pl.sku, "next_to": leader.sku}))
    return out


def _swap(slots: list[Slot], a: str, b: str) -> list[Slot]:
    """Νέα λίστα όπου οι κωδικοί a και b έχουν ανταλλάξει ράφι, επίπεδο και θέση."""
    by = {s.sku: s for s in slots}
    sa, sb = by[a], by[b]
    by[a] = replace(sa, shelf=sb.shelf, level=sb.level, position=sb.position)
    by[b] = replace(sb, shelf=sa.shelf, level=sa.level, position=sa.position)
    return [by[s.sku] for s in slots]


# --- Όλοι μαζί -----------------------------------------------------------------------------------------

def evaluate(slots: list[Slot], rules: dict | None = None) -> tuple[list[Suggestion], list[str]]:
    """Τρέχει τους κανόνες διάταξης. Η θέση (Κ4, Κ5, Κ6) προηγείται των προσόψεων (Κ3). Επιστρέφει και τι παραλείφθηκε."""
    rules = rules or load()
    skipped = []
    if not slots:
        return [], ["Δεν υπάρχει πλανόγραμμα."]
    if not any(s.revenue_day for s in slots):
        return [], ["Δεν υπάρχουν επαρκή δεδομένα για τους Κ3, Κ4, Κ5, Κ6: λείπουν οι πωλήσεις."]
    out: list[Suggestion] = []
    # Κάθε ανταλλαγή εφαρμόζεται πριν τρέξει ο επόμενος κανόνας, ώστε οι προτάσεις να μη διεκδικούν την ίδια θέση.
    for fn in (eye_level_swap, centre_position):
        hit = fn(slots, rules)
        if hit:
            out.append(hit)
            slots = _swap(slots, hit.move["sku"], hit.move["swap_with"])
    if not rules["K6"].get("private_label_brands"):
        skipped.append("Κ6: δεν έχει δηλωθεί μάρκα ιδιωτικής ετικέτας στο rules.json.")
    out += private_label_adjacency(slots, rules)
    hit = facing_transfer(slots, rules)
    if hit:
        out.append(hit)
    return out, skipped

