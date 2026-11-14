"""Telegram: ο χρήστης στέλνει στόχο από το κινητό, ο agent απαντά και ζητά εγκρίσεις με κουμπιά.

Χρησιμοποιεί long polling (getUpdates), άρα ΔΕΝ χρειάζεται δημόσια διεύθυνση ή tunnel.
Ενεργοποιείται μόνο αν υπάρχει TELEGRAM_BOT_TOKEN στο .env.
"""
import asyncio

import httpx

from . import config, events

_API = "https://api.telegram.org/bot{token}/{method}"
_client: httpx.AsyncClient | None = None
_chat_scenario: dict[str, str] = {}
last_chat_id: str | None = None        # ο τελευταίος συνομιλητής: εκεί πάνε οι προληπτικές ειδοποιήσεις


async def _call(method: str, **payload):
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=40)
    r = await _client.post(_API.format(token=config.TELEGRAM_BOT_TOKEN, method=method), json=payload)
    return r.json()


async def send(chat_id: str, text: str, buttons: list[tuple[str, str]] | None = None) -> None:
    payload = {"chat_id": chat_id, "text": text[:4000]}
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in buttons]]}
    await _call("sendMessage", **payload)


def notifier_for(chat_id: str):
    async def notifier(kind: str, text: str) -> None:
        if kind.startswith("approval:"):
            approval_id = kind.split(":", 1)[1]
            await send(chat_id, text, [("Έγκριση", f"ok:{approval_id}"), ("Απόρριψη", f"no:{approval_id}")])
        elif kind == "final":
            await send(chat_id, "Τελείωσα.\n\n" + text)
        else:
            await send(chat_id, text)
    return notifier


def default_notifier():
    """Για εκτελέσεις που ξεκινούν μόνες τους (watchers): ειδοποίηση στον τελευταίο συνομιλητή."""
    return notifier_for(last_chat_id) if last_chat_id else None


async def _handle(update: dict) -> None:
    global last_chat_id
    from .agent import resolve_approval, start_run
    from .scenarios import SCENARIOS

    if "callback_query" in update:
        cq = update["callback_query"]
        action, _, approval_id = cq.get("data", "").partition(":")
        ok = resolve_approval(approval_id, action == "ok")
        await _call("answerCallbackQuery", callback_query_id=cq["id"],
                    text=("Εγκρίθηκε" if action == "ok" else "Απορρίφθηκε") if ok else "Έχει ήδη απαντηθεί")
        return

    msg = update.get("message") or {}
    text = (msg.get("text") or "").strip()
    chat_id = str(msg.get("chat", {}).get("id", ""))
    if not text or not chat_id:
        return
    if config.TELEGRAM_ALLOWED_CHATS and chat_id not in config.TELEGRAM_ALLOWED_CHATS:
        await send(chat_id, f"Δεν έχεις πρόσβαση. Το chat id σου είναι {chat_id}.")
        return
    last_chat_id = chat_id

    if text.startswith("/start") or text.startswith("/help"):
        names = "\n".join(f"/mode {s.name} — {s.title}" for s in SCENARIOS.values())
        await send(chat_id, "Γράψε μου έναν στόχο και τον αναλαμβάνω.\n\nΡόλοι:\n" + names)
        return
    if text.startswith("/mode"):
        name = text.split(maxsplit=1)[1].strip() if " " in text else ""
        if name in SCENARIOS:
            _chat_scenario[chat_id] = name
            await send(chat_id, f"Ρόλος: {SCENARIOS[name].title}")
        else:
            await send(chat_id, "Διαθέσιμοι ρόλοι: " + ", ".join(SCENARIOS))
        return

    run_id = start_run(text, _chat_scenario.get(chat_id), source="telegram", notifier=notifier_for(chat_id))
    await send(chat_id, f"Το ανέλαβα (εκτέλεση {run_id}). Θα σε ενημερώνω.")


async def poll_loop() -> None:
    if not config.TELEGRAM_BOT_TOKEN:
        return
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
