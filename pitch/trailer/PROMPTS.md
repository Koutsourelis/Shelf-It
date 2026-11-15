# Trailer: καρέ, prompts και μοντάζ

Υλικά για το [`TRAILER.md`](../TRAILER.md). Όλα γίνονται στο playground του fal στον browser (fal.ai/models/…): ανεβάζεις
τις εικόνες, επικολλάς το prompt, πατάς Run. Τα prompts είναι στα αγγλικά γιατί έτσι δουλεύουν καλύτερα τα μοντέλα.

## Τι χρειάζεσαι πριν

- **Μια αληθινή φωτογραφία ραφιού** με άδεια αναδημοσίευσης. Για τη δοκιμή υπάρχει ήδη η
  [`shelf_rice_tawalker.jpg`](shelf_rice_tawalker.jpg) (στοιχεία και άδεια πιο κάτω). Το
  `data/shelf/photos/sample_before.png` είναι σχέδιο, όχι φωτογραφία· κάνει μόνο για να δοκιμάσεις το script.
- **Το τελικό καρέ**, από τη φωτογραφία με το script:

  ```bash
  python scripts/make_trailer_frame.py pitch/trailer/shelf_rice_tawalker.jpg
  ```

  Βγαίνει `pitch/trailer/end_frame.png` (1920×1080): το κινητό οριζόντια, η κάμερα ανοιχτή με τη φωτογραφία και
  κουμπί λήψης, πίσω του το ίδιο ράφι θολό. Δεν το φτιάχνει μοντέλο, άρα το ράφι στην οθόνη είναι ακριβώς αυτό που
  αναλύει μετά ο agent. Το [`end_frame.png`](end_frame.png) από τη φωτογραφία της δοκιμής υπάρχει ήδη.

## Φωτογραφία της δοκιμής

| | |
|---|---|
| Αρχείο | `shelf_rice_tawalker.jpg`, 2048×1536 (το μέγεθος «Large 2048» του Flickr· το πρωτότυπο είναι 4032×3024) |
| Τίτλος | «2017 (Day 177 - 26th Jun): Change of plan on the rice-buying front...» |
| Δημιουργός | Tim Walker (tawalker) |
| Πηγή | https://www.flickr.com/photos/timjoyfamily/35424909051/ |
| Άδεια | [CC BY 2.0](https://creativecommons.org/licenses/by/2.0/): επιτρέπει αναδημοσίευση και αλλαγές, με αναφορά στον δημιουργό |
| Τι φαίνεται | Αληθινό ράφι supermarket (Ηνωμένο Βασίλειο, 2017), τρία ράφια μετωπικά, ετικέτες τιμών, εμφανή κενά κάτω δεξιά και στη μέση αριστερά |
| Προσοχή | Φαίνονται το λογότυπο ιδιωτικής ετικέτας της αλυσίδας πάνω στα πακέτα, η ταμπέλα τιμής της και ένα ταμπελάκι «Roll Back» |

Αναφορά που μπαίνει στο βίντεο (κάτω αριστερά, όσο φαίνεται το ράφι) και στις διαφάνειες, αν μπει εκεί η φωτογραφία:

```text
Shelf photo: Tim Walker (tawalker), CC BY 2.0, flickr.com/photos/timjoyfamily/35424909051, placed on a phone frame
```

## Τα τέσσερα καρέ και τα δύο κλιπ

```
Καρέ Α (υπάλληλος, κινητό κάτω) ──κλιπ 1──► Καρέ Β (κινητό σηκωμένο) ──κλιπ 2──► Τελικό καρέ (οθόνη κινητού)
```

Τα δύο κλιπ μοιράζονται το καρέ Β, οπότε κολλάνε χωρίς κόψιμο.

### Καρέ Α · `fal-ai/nano-banana-2/edit`

Εικόνα αναφοράς: η φωτογραφία του ραφιού. Αναλογία 16:9.

```text
Photorealistic photo, 16:9, inside a bright modern supermarket aisle. In the foreground, a store employee seen
from behind and slightly to the right, over-the-shoulder view, face not visible, wearing a plain dark green polo
shirt with no logo, holding a smartphone lowered at waist height. In front of them is the shelf from the reference
image: same products, same arrangement and the same empty gaps, filling most of the frame. Even fluorescent
lighting, natural colours, shallow depth of field, eye-level camera, 35mm lens. No store signs, no chain logos,
no added text.
```

### Καρέ Β · `fal-ai/nano-banana-2/edit`

Εικόνες αναφοράς: το καρέ Α και η φωτογραφία του ραφιού.

```text
Same scene, same person and same shelf as the first image. The employee has now raised the smartphone with both
hands, held horizontally in landscape at chest height, pointing at the shelf. Over their shoulder the phone screen
shows the camera viewfinder framing the shelf. Keep everything else identical: lighting, clothes, products, empty
gaps, camera position. Photorealistic, 16:9.
```

### Κλιπ 1 · `fal-ai/kling-video/o1/image-to-video`, 5″

Αρχικό καρέ (`start_image_url`): Α. Τελικό (`end_image_url`): Β.

```text
@Image1 to @Image2. The store employee notices the empty gap on the shelf, pauses for a moment, then calmly raises
the smartphone with both hands and holds it horizontally to photograph the shelf. Static over-the-shoulder camera
with a very slight handheld drift. Realistic supermarket lighting, natural movement, documentary style. No text,
no logos.
```

### Κλιπ 2 · `fal-ai/kling-video/o1/image-to-video`, 5″

Αρχικό καρέ: Β. Τελικό: `end_frame.png`.

```text
@Image1 to @Image2. Smooth slow push-in over the employee's shoulder towards the smartphone screen, until the phone
fills the frame and its screen shows the camera viewfinder of the shelf. The shelf on the screen stays sharp, the
aisle behind goes softly out of focus. Steady, cinematic, realistic. No text, no extra interface elements.
```

### Γρήγορη πρώτη δοκιμή: ένα κλιπ αντί για δύο

Πριν φτιάξεις το καρέ Β: ένα κλιπ 8″ από το Α κατευθείαν στο τελικό καρέ. Αν βγει καθαρό, δεν χρειάζεται τίποτε άλλο.

```text
@Image1 to @Image2. The employee notices the empty gap, raises the smartphone horizontally to photograph the shelf,
and the camera slowly pushes in over their shoulder until the phone screen fills the frame. Realistic lighting,
natural movement, documentary style. No text, no logos.
```

Αν το Kling δεν βγάζει καλό αποτέλεσμα: ίδια prompts στο `fal-ai/veo3.1/first-last-frame-to-video`, χωρίς ήχο.

## Πότε κρατάμε ένα κλιπ

Το κλιπ μπαίνει μόνο αν ισχύουν **όλα**:

- [ ] Χέρια με πέντε δάχτυλα, που δεν λιώνουν πάνω στο κινητό.
- [ ] Το κινητό κρατά σχήμα και μέγεθος σε όλη τη διάρκεια.
- [ ] Τα προϊόντα και τα κενά του ραφιού δεν αλλάζουν θέση ούτε μορφή.
- [ ] Κανένα κείμενο-σκουπίδι, λογότυπο αλυσίδας ή ταμπέλα καταστήματος.
- [ ] Η κίνηση είναι ομαλή, χωρίς τρέμουλο ή απότομο άλμα στο τέλος.

Τρεις αποτυχημένες προσπάθειες ανά κλιπ σημαίνει ότι το trailer δεν μπαίνει (βλ. `TRAILER.md`).

## Κόστος

| Τι | Περίπου |
|---|---|
| Καρέ Α ή Β (Nano Banana 2) | λίγα σεντς το καθένα |
| Κλιπ 5″ στο Kling O1 | 0,56 $ |
| Γρήγορη δοκιμή 8″ | 0,90 $ |
| Όλο το trailer με 2–3 προσπάθειες ανά κλιπ | 3–6 $ |

## Μοντάζ (Clipchamp)

1. Κλιπ 1 και κλιπ 2 στη σειρά (ή η γρήγορη δοκιμή, αν βγήκε καθαρή).
2. Στο τελικό καρέ: κράτημα 0,3″, σύντομο λευκό φλας (η λήψη της φωτογραφίας).
3. Η σελίδα «Φωτογραφία ραφιού» σε μορφή κινητού: η ίδια φωτογραφία στην προεπισκόπηση, πάτημα του «Στείλε στον agent»,
   «Στάλθηκε» (περίπου 2″). Εγγραφή οθόνης από το κινητό, ή από τον browser του laptop σε πλάτος κινητού.
4. Συνέχεια στην εγγραφή της κονσόλας από την ίδια εκτέλεση.
5. Ένδειξη «AI-generated scene · fal» κάτω δεξιά, μόνο στα κλιπ 1–2. Κάτω αριστερά η αναφορά της φωτογραφίας (πιο
   πάνω), όσο φαίνεται το ράφι.
6. Αφήγηση: η φράση του `TRAILER.md`.

## Πηγές

- [Kling O1 First Frame Last Frame to Video](https://fal.ai/models/fal-ai/kling-video/o1/image-to-video/llms.txt): παράμετροι, 0,112 $ ανά δευτερόλεπτο, `@Image1` και `@Image2` στο prompt
- [Nano Banana 2 Edit](https://fal.ai/models/fal-ai/nano-banana-2/edit): έως 14 εικόνες αναφοράς
- [Veo 3.1 first-last-frame](https://fal.ai/explore/image-to-video-apis)
