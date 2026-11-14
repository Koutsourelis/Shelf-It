# Live παρακολούθηση ραφιού

Η κάμερα βλέπει το ράφι συνεχώς. Κάθε 30 δευτερόλεπτα στέλνεται ένα frame στο Gemini, ο κώδικας το συγκρίνει με το
πλανόγραμμα και ο αποθηκάριος παίρνει αναφορά **μόνο όταν κάτι αλλάξει**. Τελευταία ενημέρωση: 14 Νοε, βράδυ.

## Ροή

```
/live (browser, κάμερα)  ── frame κάθε LIVE_INTERVAL_SECONDS ──►  POST /api/shelf/frame
  agentkit/live.py
    1. αποθήκευση στο workspace/live/   (όχι στο workspace/photos, αλλιώς ο watcher ξεκινά agent σε κάθε frame)
    2. σχεδόν ίδιο με το προηγούμενο → skip, χωρίς κλήση στο μοντέλο
    3. agentkit/vision.read_photo → ανάγνωση (Gemini)
    4. occluded → skip
    5. findings(): λείπει / λίγες προσόψεις / λάθος ράφι / εκτός πλανογράμματος / παρουσίαση (κώδικας)
    6. ίδια ευρήματα σε LIVE_CONFIRM_FRAMES frames και διαφορετικά από την τελευταία αναφορά
         → αναφορά (κονσόλα + Telegram) και εκτέλεση του agent: αναπλήρωση, παραγγελία με έγκριση
```

## Ποιος κάνει τι

| | Άτομο Α: μοντέλο | Άτομο Β: ενσωμάτωση |
|---|---|---|
| Αρχεία | `agentkit/vision/` (`prompts.py`, `reader.py`, `schema.py`), `scripts/eval_vision.py`, `data/shelf/eval/`, `data/shelf/refs/` | `agentkit/live.py`, `console/live.html`, endpoints `/live` και `/api/shelf/frame` στο `server.py` |
| Πρώτο βήμα | Κλειδί Gemini στο `.env`, `eval_vision.py` στα 2 samples | `/live` με το mock: κουμπιά «χαλασμένο» / «σωστό» |
| Μετά | 10–15 φωτογραφίες του ραφιού μας στο eval, tuning του prompt ως sku_shelf ≥ 90% | Πραγματική κάμερα, Telegram, μηνύματα για τον αποθηκάριο, πόσο συχνά στο demo |
| Ανοιχτά | Native Gemini client με `response_schema` αν το `openai_compat` δίνει λάθος τύπους· φωτογραφία αναφοράς: βοηθάει; | Interval στο demo (30 s είναι αργό στη σκηνή· 8–10 s + «Scan τώρα»)· συγκρούσεις με εκτέλεση agent που τρέχει ήδη |

**Συμβόλαιο μεταξύ σας:** η έξοδος του `read_photo()`, όπως ορίζεται στο `agentkit/vision/schema.py`
(`occluded`, `items`, `gaps`, `visual_issues`). Ο Β δουλεύει με το mock μέχρι να είναι έτοιμος ο Α.

## Δοκιμή χωρίς κλειδί

```bash
python -m agentkit.server
```

Άνοιξε http://127.0.0.1:8000/live → «Έναρξη» → «mock: χαλασμένο» (2 frames = αναφορά) → «mock: σωστό».

## Με Gemini

Στο `.env`: `LLM_PROVIDER=openai_compat`, `OPENAI_COMPAT_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/`,
`OPENAI_COMPAT_MODEL=<id από το AI Studio>`. Μετά: `python scripts/eval_vision.py --runs 3`.
