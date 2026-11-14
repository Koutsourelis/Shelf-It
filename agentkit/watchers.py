"""Προληπτική λειτουργία: έλεγχοι που τρέχουν μόνοι τους και ξεκινούν τον agent όταν κάτι αλλάξει.

Κάθε watcher είναι μια φθηνή συνάρτηση (χωρίς μοντέλο) που επιστρέφει None ή (κλειδί, στόχος).
Το κλειδί εμποδίζει να ξεκινήσει δεύτερη εκτέλεση για το ίδιο συμβάν.

Για νέο watcher στο hackathon: γράψε μια συνάρτηση και πρόσθεσέ τη στο WATCHERS.
"""
import asyncio

from . import config, events
from .tools.data import run_sql

_seen: set[str] = set()


def margin_drop():
    """Περιθώριο κατηγορίας την τελευταία ημέρα έναντι μέσου όρου 14 ημερών."""
    _, rows = run_sql("""
        with d as (select max(date) m from sales), t as (
          select p.category, d.m,
            100 * sum(case when s.date = d.m then s.revenue - s.cost end) / sum(case when s.date = d.m then s.revenue end) as last_pct,
            100 * sum(case when s.date < d.m and s.date >= d.m - 14 then s.revenue - s.cost end)
                / sum(case when s.date < d.m and s.date >= d.m - 14 then s.revenue end) as avg_pct
          from sales s join products p using (sku), d
          group by 1, 2)
        select * from t order by last_pct - avg_pct limit 1""")
    if not rows:
        return None
    category, day, last_pct, avg_pct = rows[0]
    if last_pct is None or avg_pct is None or avg_pct - last_pct < 4:
        return None
    return (f"margin:{category}:{day}",
            f"[Αυτόματος έλεγχος] Το περιθώριο της κατηγορίας «{category}» έπεσε στο {last_pct:.1f}% στις {day} "
            f"από {avg_pct:.1f}% μέσο όρο 14 ημερών. Βρες την αιτία, υπολόγισε την επίπτωση και ετοίμασε τη διορθωτική ενέργεια.")


def stock_low():
    """Προϊόν κάτω από το μισό του ορίου αναπαραγγελίας."""
    _, rows = run_sql("""
        select st.sku, p.name, s.name, st.on_hand, st.reorder_point
        from stock st join products p using (sku) join stores s using (store_id)
        where st.on_hand < st.reorder_point * 0.5 order by st.on_hand * 1.0 / st.reorder_point limit 1""")
    if not rows:
        return None
    sku, name, store, on_hand, reorder = rows[0]
    return (f"stock:{sku}:{store}",
            f"[Αυτόματος έλεγχος] Το «{name}» ({sku}) στο κατάστημα {store} έχει απόθεμα {on_hand} με όριο αναπαραγγελίας "
            f"{reorder}. Υπολόγισε πόσες ημέρες αντέχει, βρες τον καλύτερο προμηθευτή και ετοίμασε την παραγγελία.")


# (συνάρτηση ελέγχου, σενάριο που θα αναλάβει)
WATCHERS = [(margin_drop, "analyst"), (stock_low, "analyst")]


async def check_once(notifier_factory=None) -> list[str]:
    """Τρέχει όλους τους ελέγχους μία φορά. Επιστρέφει τα run_id που ξεκίνησαν."""
    from .agent import start_run
    started = []
    for fn, scenario in WATCHERS:
        try:
            hit = await asyncio.to_thread(fn)
        except Exception as e:
            events.emit("system", "log", text=f"Ο έλεγχος {fn.__name__} απέτυχε: {e}")
            continue
        if not hit or hit[0] in _seen:
            continue
        _seen.add(hit[0])
        notifier = notifier_factory() if notifier_factory else None
        if notifier:
            await notifier("notify", "Εντόπισα κάτι και το αναλαμβάνω:\n" + hit[1])
        started.append(start_run(hit[1], scenario, source="watcher", notifier=notifier))
    return started


def reset() -> None:
    _seen.clear()


async def loop(notifier_factory=None) -> None:
    while True:
        await asyncio.sleep(config.WATCH_INTERVAL_SECONDS)
        if config.WATCHERS_ENABLED:
            await check_once(notifier_factory)
