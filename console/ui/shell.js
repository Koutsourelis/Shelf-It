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

  window.ShelfSenseShell = {
    applyTheme,
    cycleTheme,
    setTaskBadge(count) {
      document.querySelectorAll("[data-tab-tasks-badge]").forEach(el => {
        const n = Number(count) || 0;
        el.textContent = n > 99 ? "99+" : String(n);
        el.hidden = n <= 0;
      });
    }
  };
})();
