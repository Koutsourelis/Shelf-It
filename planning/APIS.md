# APIs και credits του hackathon: τι είναι, πώς τα στήνουμε, πώς τα αξιοποιούμε

Έλεγχος: 14 Νοε 2026, απόγευμα. Πηγές: https://hackathon.polymath42.com/credits , `/prep`, #announcements και
#general του Discord, τα επίσημα docs κάθε παρόχου. [Ε] = επιβεβαιωμένο, [Σ] = εκτίμηση μας.

## Πρώτα απ' όλα: πώς ξεκλειδώνουν

- [Ε] Όλα τα links διεκδίκησης είναι στη σελίδα **https://hackathon.polymath42.com/credits** και ανοίγουν με τον
  **κωδικό συμμετεχόντων** που έδωσαν οι διοργανωτές (διαφάνεια kickoff / ρωτάμε στο Discord ή τον Abed).
  Ο κωδικός **δεν** γράφεται σε αρχείο ή στο chat.
- [Ε] Κάθε μέλος διεκδικεί **τα δικά του** credits (fal, treg ανά άτομο). 4 άτομα = 4× τα ποσά.
- [Ε] Στο #general κάποιος ρώτησε πώς διεκδικείται το Iris· δεν είχε απαντηθεί ως το μεσημέρι. Ρωτάμε στο τραπέζι της Oumi.
- [Ε] «Wonderful track has 4 open spots» (Philippos, #general, 14:21). Αν μας ενδιαφέρει, DM σε εκείνον. Προσοχή στους
  όρους: ό,τι χτίζεται στην πλατφόρμα της ανήκει στη Wonderful.

## Σύνοψη

| Πάροχος | Τι δίνει | Βραβείο χρήσης | Για εμάς |
|---|---|---|---|
| **Google AI (Gemini)** | Credits inference για όλους | – | **Κύριο LLM**. Μπαίνει στον κώδικα χωρίς αλλαγές |
| **Oumi – Iris** | Πρόωρη πρόσβαση σε «decision model» | **1.000 / 500 / 250 $** | Βήμα «ποια ενέργεια να κάνω» του agent. Μεγάλη ευκαιρία: λίγες ομάδες θα το δοκιμάσουν |
| **treg** | 20 $/άτομο (+1 $ δωρεάν σε νέο λογαριασμό) | **500 / 250 / 100 $** | Εργαλεία για τον agent (εμπλουτισμός εταιρειών, web, SEO, social) μέσω MCP ή HTTP |
| **fal** | 50 $/άτομο | 1.500 $ στο track fal | Εικόνα, βίντεο, φωνή. Για «wow» στο demo |
| **boxd** | **100 €** (Discord, πάνω από τα 50 € του site) | – | Linux VM για να τρέξει ο agent/το demo online, ή sandbox εκτέλεσης κώδικα |
| **Wonderful** | Μόνο επιλεγμένες ομάδες | – | Μόνο αν πάμε στο Voice track |

[Σ] **Στρατηγική:** Gemini για τον εγκέφαλο, Iris για μία ορατή απόφαση στο demo, treg για 1–2 εργαλεία με
πραγματικά δεδομένα. Έτσι διεκδικούμε δύο έξτρα βραβεία (Iris, treg) με την ίδια λύση, χωρίς να αλλάξουμε track.
Τα fal/boxd μόνο αν τα χρειάζεται το σενάριο.

## 1. Google AI Studio / Gemini

- Κλειδί: https://aistudio.google.com/apikey (λογαριασμός Google). Τα credits ενεργοποιούνται από το link της
  σελίδας credits· χωρίς αυτά δουλεύει το free tier (τα δεδομένα του free tier χρησιμοποιούνται από τη Google:
  μόνο συνθετικά δεδομένα).
- Στο `.env` (κανένας κώδικας δεν αλλάζει):

```
LLM_PROVIDER=openai_compat
OPENAI_COMPAT_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
OPENAI_COMPAT_API_KEY=<κλειδί AI Studio>
OPENAI_COMPAT_MODEL=<π.χ. Flash μοντέλο από τη λίστα του AI Studio>
```

- Μετά: `python scripts/check_setup.py`.
- [Σ] Flash για ανάπτυξη, το καλύτερο Pro για την εγγραφή του βίντεο. Ελέγχουμε όρια (RPM/RPD) μέσα στο AI Studio.
  Επίσης χρήσιμα αν το θέλει το σενάριο: όραση (PDF/φωτογραφίες), Live API για φωνή, Nano Banana για εικόνες.

## 2. Oumi – Iris (decision model)

- [Ε] Δεν υπάρχει δημόσια τεκμηρίωση· πρόσβαση μόνο από το link της σελίδας credits. Η Oumi έχει πλατφόρμα
  `platform.oumi.ai` και MCP server (`oumi-mcp`) σύμφωνα με τρίτους.
- [Σ] Αν είναι API τύπου OpenAI, προσθέτουμε δεύτερο πάροχο μόνο για ένα εργαλείο `decide(options, context)` που
  επιστρέφει επιλογή + αιτιολόγηση και το δείχνουμε στην κονσόλα. Αυτό αρκεί για «πραγματική χρήση».
- Ερωτήσεις για το τραπέζι της Oumi: endpoint και auth; μορφή εισόδου/εξόδου; όρια; πώς κρίνεται «η καλύτερη χρήση»;

## 3. treg (εργαλεία για agents)

- Εγγραφή/login: `curl -fsSL https://treg.to/install.sh | sh` → `treg login` → `treg` (δείχνει υπόλοιπο).
  Στα Windows χωρίς bash: απευθείας HTTP με token από το dashboard.
- Αναζήτηση εργαλείου: `treg catalog search "company enrichment"` → `treg catalog get <id>` → `treg call <id> --query k=v`.
- HTTP από τον κώδικα: `GET https://treg.to/call/<id>?key=value` με header `X-Treg-Token: <token>`
  (με προσωπικό token και `X-Treg-Org: <team-slug>`). Κόστος ανά κλήση στο header `X-Treg-Cost-Micro`.
- MCP: `https://treg.to/mcp/` (εργαλεία `catalog_search`, `call`, `balance` κ.ά.).
- [Σ] Ένα γενικό εργαλείο `treg_call(id, params)` στο `agentkit/tools` και ο agent βρίσκει μόνος του τι χρειάζεται.
  Κατηγορίες: SEO/SERP, social, εμπλουτισμός προσώπων/εταιρειών, διαφημίσεις, scraping, media.

## 4. fal (εικόνα, βίντεο, ήχος)

- Κλειδί: https://fal.ai/dashboard/keys → μεταβλητή `FAL_KEY`. `pip install fal-client`.

```python
import fal_client
r = fal_client.subscribe("fal-ai/nano-banana-2", arguments={"prompt": "..."})
print(r["images"][0]["url"])
```

- Κατάλογος μοντέλων: https://fal.ai/models. Ουρά: `https://queue.fal.run/<model-id>`.

## 5. boxd (Linux VM για agents)

- `curl -fsSL https://boxd.sh/downloads/install.sh | sh` → σύνδεση → `boxd m new` (2 vCPU, 8 GB).
  Δημόσιο URL για την κονσόλα: `boxd machine proxy add api --vm <name> --port 8000`. Μυστικά: `boxd env set KEY --secret`.
- Αδρανοποιείται μετά από 4 ώρες χωρίς κίνηση. Docs: https://docs.boxd.sh . Υπάρχει και MCP server.
- [Σ] Χρήσιμο για: demo σε δημόσιο URL (plan B αν πέσει το Wi-Fi στο laptop), ή για να τρέχει ο agent κώδικα με ασφάλεια.

## Σειρά εγγραφής (κάθε μέλος, ~20')

1. Κωδικός συμμετεχόντων → σελίδα credits.
2. Google AI Studio: κλειδί + credits → `.env` → `check_setup.py`.
3. treg: εγγραφή + credits.
4. Oumi Iris: link πρόσβασης· ερωτήσεις στο τραπέζι.
5. fal και boxd: διεκδίκηση τώρα (για να μη χαθούν), χρήση μόνο αν το θέλει το σενάριο.

Κλειδιά μόνο στο `.env` κάθε laptop. Ποτέ σε commit, Discord ή chat.
