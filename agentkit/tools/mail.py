"""Email. Αν δεν έχει ρυθμιστεί SMTP στο .env, το μήνυμα γράφεται στο workspace/outbox
(ώστε το demo να δουλεύει και χωρίς πραγματική αποστολή)."""
import asyncio
import json
import smtplib
import time
from email.message import EmailMessage

from .. import config
from . import tool


@tool(
    "send_email",
    "Στείλε email. Θέλει έγκριση ανθρώπου πριν φύγει. Γράψε πλήρες, ευγενικό μήνυμα έτοιμο για αποστολή.",
    {
        "to": {"type": "string", "description": "Διεύθυνση παραλήπτη"},
        "subject": {"type": "string", "description": "Θέμα"},
        "body": {"type": "string", "description": "Κείμενο του μηνύματος"},
    },
    needs_approval=True,
)
async def send_email(ctx, to: str, subject: str, body: str) -> str:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    record = config.OUTBOX / f"{stamp}_{to.replace('@', '_at_')}.json"
    record.write_text(json.dumps({"to": to, "subject": subject, "body": body}, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    ctx.artifact(record)

    if not config.SMTP_HOST:
        return f"(Προσομοίωση, δεν υπάρχει SMTP) Το email προς {to} αποθηκεύτηκε στο workspace/outbox/{record.name}."

    def work():
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = config.SMTP_FROM, to, subject
        msg.set_content(body)
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=20) as s:
            s.starttls()
            s.login(config.SMTP_USER, config.SMTP_PASSWORD)
            s.send_message(msg)

    await asyncio.to_thread(work)
    return f"Το email στάλθηκε στον {to}."


@tool("inbox_list", "Δείξε τα εισερχόμενα email (αποστολέας, θέμα, συνημμένα).", {})
async def inbox_list(ctx) -> str:
    folder = config.DATA_DIR / "inbox"
    if not folder.exists():
        return "Δεν υπάρχουν εισερχόμενα."
    rows = []
    for f in sorted(folder.glob("*.json")):
        m = json.loads(f.read_text(encoding="utf-8"))
        rows.append(f"{f.stem} | {m['date']} | {m['from']} | {m['subject']} | συνημμένα: {', '.join(m.get('attachments', [])) or '-'}")
    return "\n".join(rows) or "Κανένα μήνυμα."


@tool("inbox_read", "Διάβασε ένα εισερχόμενο email.", {"id": {"type": "string", "description": "Το id από το inbox_list"}})
async def inbox_read(ctx, id: str) -> str:
    f = config.DATA_DIR / "inbox" / f"{id.split('/')[-1]}.json"
    if not f.exists():
        return "Δεν βρέθηκε."
    m = json.loads(f.read_text(encoding="utf-8"))
    att = ", ".join(f"data/invoices/{a}" for a in m.get("attachments", [])) or "-"
    return f"Από: {m['from']}\nΗμερομηνία: {m['date']}\nΘέμα: {m['subject']}\nΣυνημμένα: {att}\n\n{m['body']}"
