# ShelfSense Design System (`DESIGN.md`)

**Design Authority:** Apple Human Interface Guidelines (macOS & iOS)
**Surface Mode:** `Operate` (Impeccable framework — Restrained semantic color, flat grouped hierarchy, native ergonomics)
**Implementation Files:** `console/ui/app.css`, `console/ui/shell.js`, `console/ui/logo.svg`

---

## 1. Visual Direction & Core Principles

1. **Clarity:** Shelf camera telemetry, open replenishment tasks, and numeric calculations take visual priority. Interactive controls use Apple System Blue (`#007AFF` / `#0A84FF`), while static SKU codes, quantities, currency figures, and timestamps remain in neutral `Secondary Label` `SF Mono` with `tabular-nums`.
2. **Deference:** No nested cards (`Card-inside-Card` ban), no decorative gradients, no left-border callout stripes, and no uppercase tracked section headers. Grouped content sits on flat surfaces (`--bg-primary`) separated by hairline `1px` `--separator` rules.
3. **Depth:** Functional vibrancy (`backdrop-filter: saturate(180%) blur(20px)`) is reserved strictly for the sticky `52px` macOS Unified Toolbar, `44px` iOS Navigation Bar, and `49px` iOS Bottom Tab Bar. Dark Mode replaces drop shadows with surface luminance steps (`#1E1E1E` → `#2C2C2E` → `#3A3A3C` on macOS; `#000000` → `#1C1C1E` → `#2C2C2E` on iOS OLED) and `1px` inner hairlines.

---

## 2. Typography & Platform Scale

* **UI Sans Stack (`--font-sans`):** `-apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display", system-ui, "Segoe UI", sans-serif`
* **Monospace Stack (`--font-mono`):** `"SF Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace` (`font-variant-numeric: tabular-nums`)

| Role | Desktop / macOS (`≥768px`) | Mobile / iOS (`<768px`) | Weight & Token |
|---|---|---|---|
| Page Title | `22px` (`-0.02em`) | `28px` (`-0.024em`) | `600` / `700`, `--label-primary` |
| Card / Row Headline | `15px` | `17px` | `600`, `--label-primary` |
| Body & Controls | `13px` | `16px` | `400` / `500`, `--label-primary` |
| Callout / Metadata | `12px` | `14px` | `400`, `--label-secondary` |
| Section Header | `11px` (sentence case) | `13px` (sentence case) | `500`, `--label-secondary` |
| Static Figures & SKUs | `12px` (`SF Mono`) | `13px` (`SF Mono`) | `400` / `500`, `--label-secondary` |
| Footnote / Citation | `11px` | `12px` | `400`, `--label-tertiary` |

---

## 3. Color & Semantic Tokens

| Token | Light Mode | Dark Mode | Purpose |
|---|---|---|---|
| `--sys-blue` | `#007AFF` | `#0A84FF` | Primary buttons, links, active tab/nav state, focus ring |
| `--sys-green` | `#34C759` | `#30D158` | Compliant shelf (`shelf_ok`), confirmed order, completed task |
| `--sys-orange` | `#FF9500` | `#FF9F0A` | Low facings, task in progress, foreign/occluded shelf |
| `--sys-red` | `#FF3B30` | `#FF453A` | Missing SKU, misplaced level, destructive/reject state |
| `--sys-indigo` | `#5856D6` | `#5E5CE6` | AI layout swap arrows and `propose_move` rule annotations |
| `--bg-canvas` | `#F5F5F7` (`#F2F2F7` iOS) | `#1E1E1E` (`#000000` iOS) | Window / screen background |
| `--bg-primary` | `#FFFFFF` | `#2C2C2E` (`#1C1C1E` iOS) | Inset grouped list & inspector sidebar surface |
| `--bg-secondary` | `#F5F5F7` | `#3A3A3C` (`#2C2C2E` iOS) | Inputs, code blocks, table column headers |
| `--label-primary` | `#1D1D1F` | `#F5F5F7` | Primary foreground copy (contrast `>14:1`) |
| `--label-secondary` | `rgba(60,60,67,0.62)` | `rgba(235,235,245,0.62)` | Section titles, descriptions, static figures |
| `--label-tertiary` | `rgba(60,60,67,0.42)` | `rgba(235,235,245,0.40)` | Timestamps, route hints, citations |
| `--separator` | `rgba(60,60,67,0.13)` | `rgba(84,84,88,0.62)` | `1px` internal row and pane dividers |
| `--focus-ring` | `rgba(0,122,255,0.32)` | `rgba(10,132,255,0.40)` | Unified `0 0 0 3px` keyboard focus ring |

---

## 4. Reusable Components & Navigation

* **Unified macOS Toolbar (`.topbar`):** `52px` sticky translucent bar on desktop with centered `.seg-nav` (`Αρχική` · `Ράφι` · `Εργασίες` · `Αποθήκη` · `Κονσόλα`) and `Auto / Light / Dark` theme switcher (`console/ui/shell.js`).
* **iOS Bottom Tab Bar (`.ios-tabbar`):** Automatically activates below `768px` (`49px + env(safe-area-inset-bottom)`) with `≥44×44pt` touch targets and live open-task badge (`[data-tab-tasks-badge]`).
* **Segmented Control (`.seg`):** `--control-track` well (`3px` padding, `8px` radius) with elevated `--control-thumb` pill (`6px` radius, `0 1px 3px rgba(0,0,0,0.08)`).
* **Inset Grouped Surface (`.group-surface` / `.group-row`):** Flat container (`10px` radius) with internal `--separator` rows, eliminating nested cards across `/`, `/tasks`, `/capture`, and `/portal`.
* **Two-Pane & Three-Pane Split Views:** `/shelf` pairs the `16:9` camera stage with a flat `376px` Inspector Sidebar; `/dev` pairs a `280px` run sidebar, center event stream, and `310px` metrics/audit inspector.
* **Accessibility:** WCAG AA contrast in both themes, `@media (prefers-contrast: more)` token boost, `@media (prefers-reduced-motion: reduce)` motion suppression, and unified `:focus-visible` ring.
