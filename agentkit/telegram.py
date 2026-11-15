"""Telegram: ζωντανές ειδοποιήσεις ραφιού, φωτογραφίες, διαδραστικά κουμπιά και εντολές από το κινητό.

Χρησιμοποιεί long polling (getUpdates), άρα ΔΕΝ χρειάζεται δημόσια διεύθυνση ή tunnel.
Ενεργοποιείται αυτόματα μόλις οριστεί TELEGRAM_BOT_TOKEN στο .env.
"""
import asyncio
import hashlib
import json
import time
from pathlib import Path

import httpx

from . import config, events

_API = "https://api.telegram.org/bot{token}/{method}"
_FILE_API = "https://api.telegram.org/file/bot{token}/{file_path}"
_client: httpx.AsyncClient | None = None
_chat_scenario: dict[str, str] = {}
_CB_MAP: dict[str, tuple[str, str]] = {}

STATE_FILE = config.ROOT / "state" / "telegram_chats.json"
last_chat_id: str | None = None        # ο τελευταίος συνομιλητής (συμβατότητα με watchers)
bot_username: str | None = None        # συμπληρώνεται αυτόματα από getMe στην εκκίνηση


def _env_chat_ids() -> list[str]:
    raw = getattr(config, "TELEGRAM_CHAT_ID", "") or ""
    return [c.strip() for c in raw.split(",") if c.strip()]


def _load_saved_chats() -> list[str]:
    try:
        if STATE_FILE.is_file():
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("chats"), list):
                return [str(c).strip() for c in data["chats"] if str(c).strip()]
    except Exception:
        pass
    return []


def _remember_chat(chat_id: str) -> None:
    global last_chat_id
    cid = str(chat_id).strip()
    if not cid:
        return
    last_chat_id = cid
    chats = _load_saved_chats()
    if cid in chats:
        chats.remove(cid)
    chats.append(cid)
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps({"chats": chats[-20:], "last": cid}, indent=2), encoding="utf-8")
    except Exception:
        pass


def subscribers() -> list[str]:
    """Όλα τα ενεργά chat IDs (από .env TELEGRAM_CHAT_ID + όσους έστειλαν /start ή μήνυμα)."""
    seen: list[str] = []
    for cid in [*_env_chat_ids(), *_load_saved_chats(), *([last_chat_id] if last_chat_id else [])]:
        if cid and cid not in seen:
            if not config.TELEGRAM_ALLOWED_CHATS or cid in config.TELEGRAM_ALLOWED_CHATS:
                seen.append(cid)
    return seen


def bot_url() -> str | None:
    return f"https://t.me/{bot_username}?start=shelf" if bot_username else None


def _cb(kind: str, target_id: str) -> str:
    """Σύντομο callback_data (≤20 bytes) ώστε να μην ξεπερνά ποτέ το όριο 64 bytes του Telegram."""
    key = hashlib.sha1(f"{kind}:{target_id}".encode("utf-8")).hexdigest()[:12]
    _CB_MAP[key] = (kind, target_id)
    return f"cb:{key}"


def _markup(buttons: list[tuple[str, str]] | None = None,
            rows: list[list[tuple[str, str]]] | None = None) -> dict | None:
    grid = rows if rows is not None else ([buttons] if buttons else None)
    if not grid:
        return None
    return {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in row] for row in grid if row]}


async def _call(method: str, **payload) -> dict:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=40)
    r = await _client.post(_API.format(token=config.TELEGRAM_BOT_TOKEN, method=method), json=payload)
    return r.json()


async def _download_file(file_id: str) -> bytes:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=40)
    info = await _call("getFile", file_id=file_id)
    fp = (info.get("result") or {}).get("file_path")
    if not fp:
        raise RuntimeError("Αδυναμία ανάκτησης αρχείου από το Telegram")
    r = await _client.get(_FILE_API.format(token=config.TELEGRAM_BOT_TOKEN, file_path=fp))
    r.raise_for_status()
    return r.content


async def send(chat_id: str, text: str, buttons: list[tuple[str, str]] | None = None,
               rows: list[list[tuple[str, str]]] | None = None) -> dict:
    payload: dict = {"chat_id": chat_id, "text": text[:4000]}
    rm = _markup(buttons=buttons, rows=rows)
    if rm:
        payload["reply_markup"] = rm
    return await _call("sendMessage", **payload)


async def send_photo(chat_id: str, photo: Path | bytes, caption: str = "",
                     rows: list[list[tuple[str, str]]] | None = None) -> dict:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=40)
    raw = photo.read_bytes() if isinstance(photo, Path) else photo
    name = photo.name if isinstance(photo, Path) else "shelf.jpg"
    data: dict[str, str] = {"chat_id": str(chat_id)}
    if caption:
        data["caption"] = caption[:1024]
    rm = _markup(rows=rows)
    if rm:
        data["reply_markup"] = json.dumps(rm, ensure_ascii=False)
    r = await _client.post(
        _API.format(token=config.TELEGRAM_BOT_TOKEN, method="sendPhoto"),
        data=data,
        files={"photo": (name, raw, "image/jpeg")},
    )
    return r.json()


async def broadcast(text: str, rows: list[list[tuple[str, str]]] | None = None,
                    photo: Path | bytes | None = None) -> int:
    """Στέλνει ειδοποίηση σε όλα τα εγγεγραμμένα κινητά. Επιστρέφει πλήθος αποστολών."""
    if not config.TELEGRAM_BOT_TOKEN:
        return 0
    targets = subscribers()
    sent = 0
    for cid in targets:
        try:
            if photo is not None:
                res = await send_photo(cid, photo, caption=text, rows=rows)
            else:
                res = await send(cid, text, rows=rows)
            if res.get("ok", True):
                sent += 1
        except Exception as e:
            events.emit("system", "log", text=f"Telegram αποστολή ({cid}): {e}")
    return sent


def notifier_for(chat_id: str):
    async def notifier(kind: str, text: str) -> None:
        if kind.startswith("approval:"):
            approval_id = kind.split(":", 1)[1]
            await send(chat_id, text, [("Έγκριση", f"ok:{approval_id}"), ("Απόρριψη", f"no:{approval_id}")])
        elif kind == "final":
            await send(chat_id, "Ολοκληρώθηκε.\n\n" + text)
        else:
            await send(chat_id, text)
    return notifier


def default_notifier():
    """Για εκτελέσεις που ξεκινούν αυτόματα (watchers): ειδοποίηση στον τελευταίο ή προεπιλεγμένο συνομιλητή."""
    targets = subscribers()
    return notifier_for(targets[-1]) if (config.TELEGRAM_BOT_TOKEN and targets) else None


# --- Ζωντανές ειδοποιήσεις ραφιού & προτάσεων ---------------------------------

def _task_rows(task_list: list[dict]) -> list[list[tuple[str, str]]]:
    rows: list[list[tuple[str, str]]] = []
    for t in task_list[:4]:
        tid = t["id"]
        pr = t.get("priority", "")
        label = f"Αναλαμβάνω #{pr}" if pr else "Το αναλαμβάνω"
        if not t.get("claimed_by"):
            rows.append([(label, _cb("claim", tid))])
        if t.get("needs_approval"):
            pend = t["needs_approval"]
            rows.append([
                (f"Έγκριση {pend['sku']} ({pend['cases']} κιβ.)", _cb("ord_ok", tid)),
                ("Απόρριψη", _cb("ord_no", tid)),
            ])
    return rows


async def notify_shelf_change(changed: dict, frame: Path | None = None) -> None:
    """Ειδοποιεί στο Telegram όταν η κάμερα ανοίγει ή κλείνει εργασίες ραφιού."""
    if not config.TELEGRAM_BOT_TOKEN or not subscribers():
        return
    from . import tasks
    lines: list[str] = []
    for t in changed.get("new") or []:
        order = t.get("order") or {}
        ord_txt = f" · Παραγγελία {order['order_no']} ({order['eur']:.2f} €)" if order.get("order_no") else ""
        lines.append(f"{t['priority']}. {t['text']}{ord_txt}")
        if t.get("needs_approval"):
            lines.append(f"   — Αναμένει έγκριση παραγγελίας ({t['needs_approval']['why']})")
    for t in changed.get("resolved") or []:
        lines.append(f"✓ Αποκαταστάθηκε: {t['text']}")

    open_now = tasks.open_tasks()
    head = f"ShelfSense · {len(open_now)} εκκρεμείς εργασίες" if open_now else "ShelfSense · Το ράφι είναι σωστό ✓"
    caption = head + ("\n\n" + "\n".join(lines) if lines else "")
    rows = _task_rows(open_now)

    photo_path: Path | None = None
    if changed.get("new"):
        first_img = str((changed["new"][0] or {}).get("image") or "")
        rel_img = first_img.removeprefix("/files/").lstrip("/")
        if rel_img and (config.WORKSPACE / rel_img).is_file():
            photo_path = config.WORKSPACE / rel_img
        elif frame and frame.is_file():
            photo_path = frame

    await broadcast(caption, rows=rows or None, photo=photo_path)


async def notify_proposal(prop: dict) -> None:
    """Στέλνει πρόταση διάταξης (Κ3/Κ4/Κ5/Κ7) στο Telegram με κουμπιά Αποδοχής, Ταμπέλας PNG και Απόρριψης."""
    if not config.TELEGRAM_BOT_TOKEN or not subscribers():
        return
    rid = prop.get("recommendation_id") or ""
    lines = [
        f"Πρόταση διάταξης ({prop.get('rule', 'Κ')})",
        prop.get("text", ""),
        f"— {prop.get('reason', '')}",
        f"— {prop.get('numbers', '')}",
    ]
    rows: list[list[tuple[str, str]]] = []
    if rid:
        rows.append([
            ("✓ Αποδοχή", _cb("rec_ok", rid)),
            ("Ταμπελάκι PNG", _cb("talker", rid)),
            ("✗ Απόρριψη", _cb("rec_no", rid)),
        ])
    await broadcast("\n".join(x for x in lines if x), rows=rows or None)


async def send_test_ping() -> dict:
    """Δοκιμαστικό μήνυμα από την Κονσόλα (/dev -> Σύστημα)."""
    if not config.TELEGRAM_BOT_TOKEN:
        return {"ok": False, "text": "Δεν έχει οριστεί TELEGRAM_BOT_TOKEN στο .env."}
    subs = subscribers()
    if not subs:
        hint = f" Άνοιξε το @{bot_username} και πάτα /start." if bot_username else " Στείλε /start στο bot από το κινητό σου."
        return {"ok": False, "text": "Δεν υπάρχει συνδεδεμένο chat." + hint}
    n = await broadcast(f"ShelfSense · Δοκιμή σύνδεσης επιτυχής ({time.strftime('%H:%M:%S')}).")
    return {"ok": n > 0, "text": f"Στάλθηκε δοκιμαστικό μήνυμα σε {n} συνομιλία." if n else "Αποτυχία αποστολής στο Telegram."}


# --- Χειρισμός εισερχομένων (κουμπιά, φωτογραφίες, εντολές) -------------------

def _sender_name(obj: dict) -> str:
    u = obj.get("from") or {}
    return (u.get("first_name") or u.get("username") or "Υπάλληλος").strip()


async def _handle_callback(cq: dict) -> None:
    from . import agent, feedback_api, recommendations as rec_store, tasks
    data = cq.get("data") or ""
    chat_id = str(((cq.get("message") or {}).get("chat") or {}).get("id") or "")
    if chat_id:
        _remember_chat(chat_id)
    who = _sender_name(cq)

    if data.startswith("cb:"):
        mapped = _CB_MAP.get(data[3:])
        if not mapped:
            await _call("answerCallbackQuery", callback_query_id=cq["id"], text="Η ενέργεια έληξε")
            return
        kind, target = mapped
    else:
        kind, _, target = data.partition(":")

    if kind in ("ok", "no"):
        ok = agent.resolve_approval(target, kind == "ok")
        msg = ("Εγκρίθηκε" if kind == "ok" else "Απορρίφθηκε") if ok else "Έχει ήδη απαντηθεί"
        await _call("answerCallbackQuery", callback_query_id=cq["id"], text=msg)
        return

    if kind == "claim":
        t = tasks.claim(target, who=who)
        msg = f"Ανατέθηκε ({who})" if t else "Η εργασία έχει ήδη κλείσει"
        await _call("answerCallbackQuery", callback_query_id=cq["id"], text=msg)
        return

    if kind in ("ord_ok", "ord_no"):
        approved = kind == "ord_ok"
        t = await asyncio.to_thread(tasks.approve_order, target, approved)
        if not t:
            await _call("answerCallbackQuery", callback_query_id=cq["id"], text="Έχει ήδη απαντηθεί")
            return
        ord_info = t.get("order") or {}
        msg = f"Παραγγέλθηκε {ord_info.get('order_no', '')}" if approved else "Η παραγγελία απορρίφθηκε"
        await _call("answerCallbackQuery", callback_query_id=cq["id"], text=msg)
        if chat_id and approved and ord_info.get("order_no"):
            await send(chat_id, f"✓ Καταχωρήθηκε η παραγγελία {ord_info['order_no']} ({ord_info['eur']:.2f} €).")
        return

    if kind in ("rec_ok", "rec_no"):
        dec = "accepted" if kind == "rec_ok" else "rejected"
        try:
            await asyncio.to_thread(rec_store.record_feedback, target, {
                "submission_id": f"tg-{dec}-{cq['id']}",
                "decision": dec,
                "decided_by": who,
            })
            tasks.update_proposal_feedback(target, decision=dec, decided_by=who)
            await _call("answerCallbackQuery", callback_query_id=cq["id"],
                        text="Η πρόταση εγκρίθηκε" if dec == "accepted" else "Η πρόταση απορρίφθηκε")
        except Exception:
            await _call("answerCallbackQuery", callback_query_id=cq["id"], text="Αδυναμία καταχώρησης")
        return

    if kind == "talker":
        await _call("answerCallbackQuery", callback_query_id=cq["id"], text="Δημιουργώ το ταμπελάκι PNG…")
        try:
            prop = next((p for p in tasks.PROPOSALS if p.get("recommendation_id") == target), None)
            rec = await asyncio.to_thread(rec_store.get_recommendation, target)
            prod = ((rec or {}).get("recommendation") or {}).get("product") or {}
            sku = (prop or {}).get("featured_sku") or prod.get("sku")
            pname = (prop or {}).get("featured_name") or prod.get("name") or "Προϊόν"
            price = float((prop or {}).get("unit_price") or 2.50)
            await asyncio.to_thread(rec_store.record_feedback, target, {
                "submission_id": f"tg-corr-{cq['id']}",
                "decision": "corrected",
                "decided_by": who,
                "correction": {
                    "product": {"sku": sku, "name": pname},
                    "price": {"amount": price, "currency": "EUR", "source": "owner_confirmation"},
                },
            })
            tasks.update_proposal_feedback(target, decision="corrected", decided_by=who)
            res = await feedback_api.build_talker_for_recommendation(target, "fresh")
            png_path = config.WORKSPACE / res["file"]
            if chat_id and png_path.is_file():
                await send_photo(chat_id, png_path, caption=f"Ταμπελάκι ραφιού: {pname} · {res['price_text']}")
        except Exception as e:
            if chat_id:
                await send(chat_id, f"Σφάλμα δημιουργίας ταμπέλας: {e}")


async def _handle_photo(chat_id: str, file_id: str) -> None:
    from . import live, tasks
    await send(chat_id, "Διαβάζω τη φωτογραφία του ραφιού…")
    raw = await _download_file(file_id)
    res = await live.process_frame(raw, force=True, single=True)
    if res.get("status") == "occluded":
        await send(chat_id, "Κάτι κρύβει το ράφι στη φωτογραφία· δοκίμασε ξανά καθαρή λήψη.")
        return
    last_info = res.get("last") or {}
    if last_info.get("status") != "acted":
        open_now = tasks.open_tasks()
        secs = last_info.get("seconds") or res.get("seconds")
        timing = f" ({secs}s)" if secs else ""
        if not open_now:
            await send(chat_id, f"✓ Το ράφι είναι σωστό{timing}.")
        else:
            listing = "\n".join(f"{t['priority']}. {t['text']}" for t in open_now)
            await send(chat_id, f"Εκκρεμούν {len(open_now)} εργασίες{timing}:\n\n{listing}", rows=_task_rows(open_now))


async def _handle(update: dict) -> None:
    from . import live, portal, tasks
    from .agent import start_run
    from .scenarios import SCENARIOS

    if "callback_query" in update:
        await _handle_callback(update["callback_query"])
        return

    msg = update.get("message") or {}
    chat_id = str(msg.get("chat", {}).get("id", ""))
    if not chat_id:
        return
    if config.TELEGRAM_ALLOWED_CHATS and chat_id not in config.TELEGRAM_ALLOWED_CHATS:
        await send(chat_id, f"Δεν έχεις πρόσβαση. Το chat ID σου είναι {chat_id}.")
        return
    _remember_chat(chat_id)

    photos = msg.get("photo") or []
    doc = msg.get("document") or {}
    photo_fid = photos[-1]["file_id"] if photos else (
        doc.get("file_id") if str(doc.get("mime_type") or "").startswith("image/") else None
    )
    if photo_fid:
        await _handle_photo(chat_id, photo_fid)
        return

    text = (msg.get("text") or "").strip()
    if not text:
        return

    cmd = text.split()[0].split("@")[0].lower()
    if cmd in ("/start", "/help"):
        names = "\n".join(f"  /mode {s.name} — {s.title}" for s in SCENARIOS.values())
        await send(
            chat_id,
            "Συνδέθηκες στο ShelfSense.\n"
            "Θα λαμβάνεις εδώ ζωντανές ειδοποιήσεις ραφιού, αυτόματες παραγγελίες και προτάσεις διάταξης.\n\n"
            "• Στείλε φωτογραφία ραφιού εδώ για άμεση σάρωση\n"
            "• /tasks — Εκκρεμείς εργασίες υπαλλήλου\n"
            "• /orders — Παραγγελίες αποθήκης\n"
            "• /status — Κατάσταση ραφιού & μοντέλου\n"
            "• /reset — Μηδενισμός εργασιών demo\n\n"
            f"Ή γράψε ελεύθερα στόχο στον agent:\n{names}",
        )
        return

    if cmd == "/tasks":
        open_now = tasks.open_tasks()
        if not open_now:
            await send(chat_id, "✓ Δεν υπάρχουν εκκρεμείς εργασίες. Το ράφι είναι σωστό.")
        else:
            lines = [f"{t['priority']}. {t['text']}" + (f" ({t['claimed_by']})" if t.get("claimed_by") else "")
                     for t in open_now]
            await send(chat_id, f"Εκκρεμείς εργασίες ({len(open_now)}):\n\n" + "\n".join(lines),
                       rows=_task_rows(open_now))
        return

    if cmd == "/orders":
        if not portal.orders:
            await send(chat_id, "Δεν έχουν καταχωρηθεί παραγγελίες στην αποθήκη ακόμη.")
        else:
            lines = [f"• {o['order_no']} · {o['total']:.2f} € ({o['created_at']})" for o in portal.orders[-8:]]
            await send(chat_id, f"Παραγγελίες αποθήκης ({len(portal.orders)}):\n\n" + "\n".join(lines))
        return

    if cmd == "/status":
        st = live.status()
        state_txt = "Σωστό ✓" if st["shelf_ok"] else f"{st['open']} εκκρεμείς εργασίες"
        await send(
            chat_id,
            f"Κατάσταση ShelfSense\n"
            f"• Ράφι: {state_txt}\n"
            f"• Μοντέλο όρασης: {st['model']}\n"
            f"• Σαρώσεις κάμερας: {st['frames']} frames ({st['model_calls']} κλήσεις μοντέλου)\n"
            f"• Αυτόματη παραγγελία: {'έως ' + str(st['max_cases']) + ' κιβ. / ' + str(st['max_eur']) + ' €' if st['auto_order'] else 'με έγκριση'}",
        )
        return

    if cmd == "/reset":
        live.STATE.reset()
        portal.orders.clear()
        await send(chat_id, "Έγινε επαναφορά εργασιών, προτάσεων και παραγγελιών.")
        return

    if cmd == "/mode":
        name = text.split(maxsplit=1)[1].strip() if " " in text else ""
        if name in SCENARIOS:
            _chat_scenario[chat_id] = name
            await send(chat_id, f"Ενεργός ρόλος: {SCENARIOS[name].title}")
        else:
            await send(chat_id, "Διαθέσιμοι ρόλοι: " + ", ".join(SCENARIOS))
        return

    run_id = start_run(text, _chat_scenario.get(chat_id), source="telegram", notifier=notifier_for(chat_id))
    await send(chat_id, f"Το ανέλαβα (εκτέλεση {run_id}). Θα σε ενημερώνω.")


async def _init_bot_metadata() -> None:
    global bot_username
    try:
        me = await _call("getMe")
        if me.get("ok") and me.get("result"):
            bot_username = me["result"].get("username")
            events.emit("system", "log", text=f"Telegram bot ενεργό: @{bot_username}")
        await _call("setMyCommands", commands=[
            {"command": "tasks", "description": "Εκκρεμείς εργασίες ραφιού"},
            {"command": "orders", "description": "Παραγγελίες αποθήκης"},
            {"command": "status", "description": "Κατάσταση ραφιού & συστήματος"},
            {"command": "reset", "description": "Επαναφορά εργασιών demo"},
            {"command": "help", "description": "Οδηγίες χρήσης"},
        ])
    except Exception as e:
        events.emit("system", "log", text=f"Telegram init: {e}")


async def poll_loop() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        return
    await _init_bot_metadata()
    offset = 0
    events.emit("system", "log", text="Το Telegram bot ακούει.")
    while True:
        try:
            data = await _call("getUpdates", offset=offset, timeout=25,
                               allowed_updates=["message", "callback_query"])
            for update in data.get("result", []):
                offset = update["update_id"] + 1
                try:
                    await _handle(update)
                except Exception as e:
                    events.emit("system", "log", text=f"Σφάλμα Telegram: {e}")
        except asyncio.CancelledError:
            raise
        except Exception:
            await asyncio.sleep(3)      # προσωρινό πρόβλημα δικτύου: ξαναδοκιμάζουμε
