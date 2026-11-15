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
    known = {d.sku for d in destinations(slots, rules)}      # Κ7: ο προορισμός δεν διεκδικεί το ύψος των ματιών
    known |= {s.sku for s in heavy(slots, rules)}            # Κ8: ούτε οι βαριές συσκευασίες
    eye = [s for s in slots if s.level == "eye"]
    rest = [s for s in slots if s.level != "eye" and s.sku not in known]
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
    known = {d.sku for d in destinations(slots, rules)}
    target = max((s for s in eye if s.sku not in known), key=lambda s: s.margin_per_facing, default=None)
    if target is None:
        return None
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


# --- Κ7 ------------------------------------------------------------------------------------------------

def unit_share(slots: list[Slot]) -> dict[str, float]:
    """Μερίδιο κάθε κωδικού στα τεμάχια που πουλά το ράφι την ημέρα (0 έως 1)."""
    total = sum(s.units_day for s in slots)
    return {s.sku: (s.units_day / total if total else 0.0) for s in slots}


def destinations(slots: list[Slot], rules: dict) -> list[Slot]:
    """Κωδικοί-προορισμός: ο πελάτης τους ψάχνει όπου κι αν είναι, άρα δεν χρειάζονται την καλή θέση.

    Προορισμός είναι ό,τι έχει μερίδιο τεμαχίων τουλάχιστον min_share_vs_average φορές το μέσο μερίδιο του
    ραφιού, ή μάρκα δηλωμένη στο destination_brands του rules.json. Πρώτος ο ισχυρότερος.
    """
    r = rules.get("K7")
    if not r or len(slots) < 2:
        return []
    share, limit = unit_share(slots), r["min_share_vs_average"] / len(slots)
    brands = {b.strip().lower() for b in r.get("destination_brands", [])}
    hits = [s for s in slots if s.brand.strip().lower() in brands or (share[s.sku] and share[s.sku] >= limit)]
    return sorted(hits, key=lambda s: -s.units_day)


def destination_corner(slots: list[Slot], rules: dict) -> Suggestion | None:
    """Ο ισχυρότερος προορισμός που δεν είναι ήδη εκεί πάει στο κάτω ράφι, δεξιά."""
    r = rules.get("K7")
    bottom = sorted((s for s in slots if s.level == "bottom"), key=lambda s: s.position)
    known = destinations(slots, rules)
    if not r or not bottom or not known:
        return None
    share, ids = unit_share(slots), {d.sku for d in known}
    spots = list(reversed(bottom))                       # από δεξιά προς τα αριστερά
    for d, spot in zip(known, spots):
        if d.sku == spot.sku:
            continue
        if spot.sku in ids and d.level == "bottom":      # δύο προορισμοί ήδη κάτω: η μεταξύ τους σειρά δεν αξίζει αλλαγή
            continue
        pct = lambda x: f"{100 * x:.1f}".replace(".", ",") + "%"
        return Suggestion(
            rule="Κ7", title=r["title"],
            what=f"Το {d.sku} ({d.name}) στο κάτω ράφι δεξιά, στη θέση του {spot.sku} ({spot.name}).",
            figure=f"το {d.sku} κάνει το {pct(share[d.sku])} των τεμαχίων του ραφιού (όριο προορισμού "
                   f"{pct(r['min_share_vs_average'] / len(slots))})· ο πελάτης το ψάχνει όπου κι αν είναι. "
                   "Δεν δίνεται ποσοστό αύξησης.",
            source=r["source"],
            expression="units_day / sum(units_day) >= min_share_vs_average / n_skus",
            variables={"share": round(share[d.sku], 3), "min_share_vs_average": r["min_share_vs_average"],
                       "n_skus": len(slots)},
            result=round(share[d.sku], 3), move={"sku": d.sku, "swap_with": spot.sku})
    return None


# --- Κ8 ------------------------------------------------------------------------------------------------

def pack_grams(name: str) -> float | None:
    """Μέγεθος συσκευασίας από το όνομα, σε γραμμάρια ή ml: '1,5lt' → 1500, '500g' → 500, 'x20' → None."""
    import re
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(kg|g|gr|ml|l|lt)\b", (name or "").lower())
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    return value * 1000 if m.group(2) in ("kg", "l", "lt") else value


def heavy(slots: list[Slot], rules: dict) -> list[Slot]:
    """Βαριές ή ογκώδεις συσκευασίες (από min_grams και πάνω): μένουν στο κάτω ράφι όσο κι αν αποδίδουν."""
    r = rules.get("K8")
    if not r:
        return []
    return [s for s in slots if (pack_grams(s.name) or 0) >= r["min_grams"]]


def _centre_out(ranked: list[Slot]) -> list[Slot]:
    """Ο πρώτος στο κέντρο, ο δεύτερος δεξιά του, ο τρίτος αριστερά του κ.ο.κ. (Κ5)."""
    out: list[Slot] = []
    for i, s in enumerate(ranked):
        if i and i % 2 == 0:
            out.insert(0, s)
        else:
            out.append(s)
    return out


def target_layout(slots: list[Slot], rules: dict | None = None) -> list[dict]:
    """Η διάταξη που βγαίνει από τις πωλήσεις: ένα στοιχείο ανά επίπεδο, με σειρά από αριστερά.

    Κάθε επίπεδο κρατά όσους κωδικούς έχει σήμερα. Οι προορισμοί (Κ7) πάνε κάτω δεξιά. Από τους υπόλοιπους, όσοι
    έχουν το μεγαλύτερο περιθώριο ανά πρόσοψη την ημέρα πάνε στο ύψος των ματιών με τον πρώτο στο κέντρο (Κ4, Κ5),
    οι επόμενοι πάνω και οι τελευταίοι κάτω αριστερά. Επιστρέφει [] όταν λείπουν πωλήσεις ή επίπεδα.
    """
    rules = rules or load()
    size = {lv: sum(1 for s in slots if s.level == lv) for lv in ("top", "eye", "bottom")}
    if not size["eye"] or not size["bottom"] or not any(s.units_day for s in slots):
        return []
    share = unit_share(slots)
    known = destinations(slots, rules)[:size["bottom"]]
    ids = {d.sku for d in known}
    bulky = [s for s in heavy(slots, rules) if s.sku not in ids]          # Κ8: δεν διεκδικούν ύψος ματιών ή πάνω ράφι
    ids |= {s.sku for s in bulky}
    ranked = sorted((s for s in slots if s.sku not in ids), key=lambda s: -s.margin_per_facing)
    eye, ranked = ranked[:size["eye"]], ranked[size["eye"]:]
    top, low = ranked[:size["top"]], ranked[size["top"]:]
    eye, top = _centre_out(eye), _centre_out(top)
    bulky.sort(key=lambda s: s.margin_per_facing)
    bottom = low[::-1] + bulky + known[::-1]             # ο ισχυρότερος προορισμός τέρμα δεξιά

    name = lambda s: f"{s.sku} {s.name}"
    per = lambda group: ", ".join(f"{s.sku} {_eur(s.margin_per_facing)}" for s in
                                  sorted(group, key=lambda s: -s.margin_per_facing))
    pct = lambda s: f"{100 * share[s.sku]:.1f}".replace(".", ",") + "%"
    units = lambda s: f"{s.units_day:.1f}".replace(".", ",")
    # Ο λόγος για κάθε κωδικό χωριστά: η οθόνη τον δείχνει δίπλα στο βέλος «πήγαινέ το σε αυτό το ράφι».
    reason = {s.sku: f"{_eur(s.margin_per_facing)} περιθώριο ανά πρόσοψη την ημέρα, από τα υψηλότερα του ραφιού· "
                     "στο ύψος των ματιών το βλέπουν οι περισσότεροι πελάτες (Κ4)" for s in eye}
    reason.update({s.sku: f"{_eur(s.margin_per_facing)} περιθώριο ανά πρόσοψη την ημέρα· το ύψος των ματιών το "
                          "παίρνουν κωδικοί που αποδίδουν περισσότερο (Κ4)" for s in top})
    reason.update({s.sku: f"{_eur(s.margin_per_facing)} περιθώριο ανά πρόσοψη την ημέρα, από τα χαμηλότερα του "
                          "ραφιού· αφήνει την καλή θέση σε ό,τι αποδίδει περισσότερο (Κ4)" for s in low})
    reason.update({d.sku: f"πουλάει πολύ: {units(d)} τεμάχια την ημέρα, το {pct(d)} του ραφιού· ο πελάτης το ψάχνει "
                          "όπου κι αν είναι, άρα δεν χρειάζεται την καλή θέση (Κ7)" for d in known})
    if bulky:
        reason.update({s.sku: f"βαριά συσκευασία ({pack_grams(s.name) / 1000:g} κιλά ή λίτρα): στο κάτω ράφι σηκώνεται "
                              f"πιο εύκολα και δεν πέφτει από ψηλά, όσο κι αν αποδίδει ({_eur(s.margin_per_facing)} ανά "
                              "πρόσοψη την ημέρα) (Κ8)" for s in bulky})
    role = {**{s.sku: "eye" for s in eye}, **{s.sku: "top" for s in top}, **{s.sku: "low" for s in low},
            **{s.sku: "heavy" for s in bulky}, **{d.sku: "destination" for d in known}}
    items = lambda group: [{"sku": s.sku, "name": s.name, "from_level": s.level, "why": reason[s.sku],
                            "role": role[s.sku], "margin_per_facing": round(s.margin_per_facing, 2),
                            "units_day": round(s.units_day, 1)} for s in group]
    out = []
    if top:
        out.append({"level": "top", "order": [name(s) for s in top], "items": items(top),
                    "why": f"Οι επόμενοι σε περιθώριο ανά πρόσοψη την ημέρα: {per(top)}."})
    out.append({"level": "eye", "order": [name(s) for s in eye], "items": items(eye),
                "why": f"Το μεγαλύτερο περιθώριο ανά πρόσοψη την ημέρα, ο πρώτος στο κέντρο: {per(eye)} (Κ4, Κ5)."})
    why = []
    if known:
        why.append("Δεξιά " + ", ".join(f"{d.sku} με {pct(d)} των τεμαχίων του ραφιού" for d in known)
                   + ": ο πελάτης τους ψάχνει όπου κι αν είναι (Κ7).")
    if bulky:
        why.append("Οι βαριές συσκευασίες μένουν κάτω: " + ", ".join(s.sku for s in bulky) + " (Κ8).")
    if low:
        why.append(f"Αριστερά το χαμηλότερο περιθώριο ανά πρόσοψη: {per(low)}.")
    out.append({"level": "bottom", "order": [name(s) for s in bottom], "items": items(bottom), "why": " ".join(why)})
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
    """Τρέχει τους κανόνες διάταξης. Η θέση (Κ4, Κ5, Κ7, Κ6) προηγείται των προσόψεων (Κ3). Επιστρέφει και τι παραλείφθηκε."""
    rules = rules or load()
    skipped = []
    if not slots:
        return [], ["Δεν υπάρχει πλανόγραμμα."]
    if not any(s.revenue_day for s in slots):
        return [], ["Δεν υπάρχουν επαρκή δεδομένα για τους Κ3, Κ4, Κ5, Κ6: λείπουν οι πωλήσεις."]
    out: list[Suggestion] = []
    # Κάθε ανταλλαγή εφαρμόζεται πριν τρέξει ο επόμενος κανόνας, ώστε οι προτάσεις να μη διεκδικούν την ίδια θέση.
    for fn in (eye_level_swap, centre_position, destination_corner):
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

