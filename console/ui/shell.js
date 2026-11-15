/* ShelfSense Shared HIG Shell & Theme Controller
   - Immediate Light / Dark / Auto theme resolution (persisted in localStorage("shelfsense_theme"))
   - Syncs meta[name="theme-color"] for iOS Safari / macOS window chrome
   - Binds [data-theme-toggle] buttons across all screens
   - Updates mobile iOS Tab Bar active badge when task counts arrive */
(() => {
  const KEY = "shelfsense_theme";
  const root = document.documentElement;
  const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");

  function storedMode() {
    try { return localStorage.getItem(KEY) || "auto"; } catch { return "auto"; }
  }

  function effectiveTheme(mode) {
    if (mode === "light" || mode === "dark") return mode;
    return darkQuery.matches ? "dark" : "light";
  }

  function applyTheme(mode) {
    const eff = effectiveTheme(mode);
    root.setAttribute("data-theme", eff);
    root.setAttribute("data-theme-mode", mode);
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) {
      const isMobile = window.innerWidth < 768;
      meta.setAttribute("content", eff === "dark" ? (isMobile ? "#000000" : "#1e1e1e") : (isMobile ? "#f2f2f7" : "#f5f5f7"));
    }
    const labels = { auto: "Αυτόματο θέμα", light: "Φωτεινό θέμα", dark: "Σκοτεινό θέμα" };
    const short = { auto: "Auto", light: "Light", dark: "Dark" };
    document.querySelectorAll("[data-theme-toggle]").forEach(btn => {
      btn.setAttribute("aria-label", labels[mode] + " (εναλλαγή)");
      btn.setAttribute("title", labels[mode]);
      const lbl = btn.querySelector(".theme-lbl");
      if (lbl) lbl.textContent = short[mode];
    });
  }

  function cycleTheme() {
    const order = ["auto", "light", "dark"];
    const next = order[(order.indexOf(storedMode()) + 1) % order.length];
    try { localStorage.setItem(KEY, next); } catch {}
    applyTheme(next);
  }

  // Apply synchronously before first paint when loaded in <head>
  applyTheme(storedMode());

  darkQuery.addEventListener?.("change", () => {
    if (storedMode() === "auto") applyTheme("auto");
  });
  window.addEventListener("storage", e => {
    if (e.key === KEY) applyTheme(storedMode());
  });

  document.addEventListener("DOMContentLoaded", () => {
    applyTheme(storedMode());
    document.addEventListener("click", e => {
      const btn = e.target.closest("[data-theme-toggle]");
      if (btn) cycleTheme();
    });
  });

  /* ---------- Unified state vocabulary (presentation only) ----------
     Kinds: idle · loading · pending · info · success · warning · error · neutral · unknown.
     success means the specific action finished; it is never inferred from HTTP 200/201 alone. */
  const ICONS = {
    idle: '<circle cx="12" cy="12" r="8"/>',
    loading: '<path d="M12 4a8 8 0 1 1-8 8" stroke-linecap="round"/>',
    pending: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4.2l2.6 1.6" stroke-linecap="round" stroke-linejoin="round"/>',
    info: '<path d="M7 4h10v16l-5-3.6L7 20V4Z" stroke-linejoin="round"/>',
    success: '<circle cx="12" cy="12" r="8"/><path d="M8.6 12.3l2.3 2.3 4.6-5" stroke-linecap="round" stroke-linejoin="round"/>',
    warning: '<path d="M12 4.5l8.5 15h-17L12 4.5Z" stroke-linejoin="round"/><path d="M12 10.2v3.8M12 16.8v.01" stroke-linecap="round"/>',
    error: '<circle cx="12" cy="12" r="8"/><path d="M9.6 9.6l4.8 4.8M14.4 9.6l-4.8 4.8" stroke-linecap="round"/>',
    neutral: '<circle cx="12" cy="12" r="8"/><path d="M8.8 12h6.4" stroke-linecap="round"/>',
    unknown: '<circle cx="12" cy="12" r="8"/><path d="M10 10a2 2 0 1 1 2.9 1.8c-.6.3-.9.7-.9 1.3v.4M12 16.6v.01" stroke-linecap="round"/>'
  };
  const KINDS = Object.keys(ICONS);
  const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const kindOf = k => (KINDS.includes(k) ? k : "unknown");

  function stateIcon(kind) {
    const k = kindOf(kind);
    return `<svg class="state-ico${k === "loading" ? " spin" : ""}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">${ICONS[k]}</svg>`;
  }
  /* opts.box: block banner next to the component · opts.actionHTML: recovery control.
     User-facing only: technical detail never goes into this markup (no hover titles); use devLog(). */
  function stateHTML(kind, label, detail = "", opts = {}) {
    const k = kindOf(kind);
    return `<span class="state${opts.box ? " box" : ""}" data-kind="${k}">` +
      `${stateIcon(k)}<span class="state-txt"><span class="state-lbl">${esc(label)}</span>` +
      `${detail ? `<span class="state-det">${esc(detail)}</span>` : ""}${opts.actionHTML || ""}</span></span>`;
  }

  /* One polite live region per page; errors are announced assertively. */
  let liveEl = null, liveErr = null;
  function announce(text, urgent = false) {
    if (!document.body) return;
    if (!liveEl) {
      liveEl = Object.assign(document.createElement("div"), { className: "sr-only" });
      liveEl.setAttribute("aria-live", "polite"); liveEl.setAttribute("role", "status");
      liveErr = Object.assign(document.createElement("div"), { className: "sr-only" });
      liveErr.setAttribute("aria-live", "assertive"); liveErr.setAttribute("role", "alert");
      document.body.append(liveEl, liveErr);
    }
    const el = urgent ? liveErr : liveEl;
    el.textContent = "";
    setTimeout(() => { el.textContent = text; }, 40);
  }

  /* Busy button: disabled + aria-busy + specific label. Returns a restore function. */
  function busy(btn, label) {
    if (!btn) return () => {};
    const prev = btn.innerHTML;
    btn.disabled = true;
    btn.setAttribute("aria-busy", "true");
    btn.textContent = label;
    return (doneLabel) => {
      if (!btn.isConnected) return;
      btn.disabled = false;
      btn.removeAttribute("aria-busy");
      btn.innerHTML = prev;
      if (doneLabel) btn.textContent = doneLabel;
    };
  }

  /* fetch wrapper: throws an Error carrying status / detail / tech (raw text for secondary views). */
  async function api(url, opts) {
    let r;
    try { r = await fetch(url, opts); }
    catch (e) { const err = new Error("network"); err.network = true; err.tech = String(e && e.message || e); throw err; }
    let data = null;
    try { data = await r.json(); } catch { data = null; }
    if (!r.ok) {
      const detail = data && data.detail !== undefined ? data.detail : null;
      const err = new Error("http " + r.status);
      err.status = r.status; err.detail = detail; err.data = data;
      err.tech = `HTTP ${r.status}` + (detail ? ": " + (typeof detail === "string" ? detail : JSON.stringify(detail)) : "");
      throw err;
    }
    return { status: r.status, data };
  }

  const GREEK = /[Ͱ-Ͽἀ-῿]/;
  /* Raw diagnostics belong to developers only: the browser devtools console (and, on /shelf,
     the «Δοκιμές» panel). Never rendered into user-facing markup. */
  function devLog(scope, err) {
    if (!err) return;
    try { console.warn(`[ShelfSense ${scope}]`, err.tech || err.message || err); } catch {}
  }
  const TECHNICAL = /Error\b|Exception|Traceback|HTTP \d|\bpython\b|[\/\\][\w.-]+\.(py|js|duckdb|sqlite3|json|png)\b|[{}[\]]/i;
  /* Concise user-facing copy for a failed action; the raw text stays in err.tech (dev view only).
     A backend message passes through only for 4xx, only when it is short plain Greek with no technical tokens. */
  function errorCopy(err, fallback = "Δοκίμασε ξανά.") {
    if (!err) return fallback;
    if (err.network) return "Δεν υπάρχει σύνδεση με τον διακομιστή. Έλεγξε ότι τρέχει και δοκίμασε ξανά.";
    const d = err.detail;
    const msg = typeof d === "string" ? d : (d && typeof d.message === "string" ? d.message : "");
    if (msg && err.status < 500 && GREEK.test(msg) && msg.length <= 160 && !TECHNICAL.test(msg)) return msg;
    if (err.status >= 500) return "Σφάλμα διακομιστή. " + fallback;
    if (err.status === 404) return "Δεν βρέθηκε πλέον. Ανανέωσε τη σελίδα.";
    if (err.status === 409) return "Η κατάσταση άλλαξε στο μεταξύ. Ανανέωσε και δοκίμασε ξανά.";
    if (err.status === 413) return "Η εικόνα είναι πολύ μεγάλη.";
    if (err.status === 400 || err.status === 422) return "Το αίτημα δεν έγινε δεκτό. " + fallback;
    return fallback;
  }

  /* Owner decision on a recommendation. Saving a decision never means the move happened. */
  const DECISION = {
    accepted: ["info", "Απόφαση αποθηκεύτηκε: αποδοχή", "Η μετακίνηση δεν έχει επιβεβαιωθεί"],
    corrected: ["info", "Απόφαση αποθηκεύτηκε: με διόρθωση", "Η μετακίνηση δεν έχει επιβεβαιωθεί"],
    rejected: ["neutral", "Απορρίφθηκε από τον υπεύθυνο", ""]
  };
  function decisionState(dec) {
    if (!dec) return null;
    return DECISION[dec] || ["unknown", "Άγνωστη απόφαση", String(dec)];
  }

  /* Second-scan verification sessions (agentkit/verification.py). No state here is ever "verified":
     while vision_integration is pending, a received photo is only "received". */
  const VERIFICATION = {
    awaiting_rescan: ["pending", "Αναμονή νέας φωτογραφίας", "Τράβηξε φωτογραφία μετά τη μετακίνηση"],
    awaiting_vision: ["pending", "Η φωτογραφία ελήφθη", "Ο έλεγχος όρασης εκκρεμεί"],
    superseded: ["warning", "Η απόφαση άλλαξε", "Χρειάζεται νέος έλεγχος για την τρέχουσα απόφαση"]
  };
  function verificationState(session) {
    const st = session && session.status;
    const base = VERIFICATION[st];
    if (base) return base;
    return ["unknown", "Άγνωστη κατάσταση ελέγχου", st ? String(st) : ""];
  }

  /* Shelf talker results (agentkit/shelf_talker.py). "generated" counts only with a real file. */
  const TALKER = {
    missing_inputs: ["warning", "Λείπουν στοιχεία", "Επιβεβαίωσε όνομα και τιμή προϊόντος"],
    input_mismatch: ["warning", "Τα στοιχεία δεν ταιριάζουν", "Έλεγξε όνομα και τιμή"],
    invalid_input: ["warning", "Μη έγκυρα στοιχεία", "Έλεγξε όνομα και τιμή"],
    not_configured: ["warning", "Η υπηρεσία εικόνας δεν έχει ρυθμιστεί", "Λείπει ρύθμιση στο .env"],
    pending: ["pending", "Η δημιουργία συνεχίζεται", "Δοκίμασε ξανά σε λίγο"],
    submit_ambiguous: ["warning", "Άγνωστο αν στάλθηκε το αίτημα", "Δεν έγινε νέα αποστολή"],
    submit_failed: ["error", "Το ταμπελάκι δεν δημιουργήθηκε", "Δοκίμασε ξανά"],
    provider_failed: ["error", "Το ταμπελάκι δεν δημιουργήθηκε", "Η υπηρεσία εικόνας απέτυχε"],
    render_failed: ["error", "Το ταμπελάκι δεν δημιουργήθηκε", "Η απόδοση της εικόνας απέτυχε"],
    config_error: ["error", "Το ταμπελάκι δεν δημιουργήθηκε", "Σφάλμα ρύθμισης"],
    not_found: ["error", "Η πρόταση δεν βρέθηκε", "Ανανέωσε τη σελίδα"]
  };
  function talkerState(status) {
    return TALKER[status] || ["unknown", "Άγνωστη κατάσταση ταμπελακιού", status ? String(status) : ""];
  }

  window.ShelfSenseShell = {
    applyTheme,
    cycleTheme,
    esc,
    stateIcon,
    stateHTML,
    announce,
    busy,
    api,
    errorCopy,
    devLog,
    decisionState,
    verificationState,
    talkerState,
    setTaskBadge(count) {
      document.querySelectorAll("[data-tab-tasks-badge]").forEach(el => {
        const n = Number(count) || 0;
        el.textContent = n > 99 ? "99+" : String(n);
        el.hidden = n <= 0;
      });
    }
  };
})();
