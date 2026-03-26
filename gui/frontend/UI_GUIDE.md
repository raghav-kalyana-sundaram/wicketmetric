# Cricket Metrics — UI guide (dark-first, monochrome)

This document is the **site-wide visual standard**, anchored on the **win probability** block: near-black surfaces, **white / zinc typography**, whisper-thin borders, and **colour only where data needs it** (series fills, grades, alerts). Use it when building or refactoring any page in `gui/frontend`.

**Bulk redesign:** Use the copy-paste agent prompt in [DARK_MODE_REDESIGN_PROMPT.md](./DARK_MODE_REDESIGN_PROMPT.md) to align the whole app with this guide.

---

## 1. North star

**Reference implementation:** `src/components/WinProbabilityMomentumChart.tsx` (the scorecard chart card).

**Intent:**

- The interface should feel like a **precision instrument**: calm, high contrast, no decorative noise.
- **Default chrome is monochrome** (zinc / white opacity on charcoal).
- **Hue is semantic**: **blue only via `primary`** (links, focus, active nav text, small CTAs) — never large `bg-primary/*` panel washes. Success/warning/danger for states; **chart series** for comparison — not for general boxes and labels.

If a new screen does not look at home next to the win probability card, realign it to this guide.

---

## 2. Colour system (dark mode = default)

### 2.1 Base canvas

| Role        | Token / value              | Use |
|------------|-----------------------------|-----|
| Page bg    | `bg-background` → `#030303` | Body; **solid** in dark (`globals.css` — no radial wash) |
| Panel / card | `bg-surface` → `#060606`  | Default content panels |
| Raised     | `bg-surface-elevated` → `#101010` | Inputs, table hover, secondary buttons |

**Win-probability “cinema” card** (step up from default `section-card`):

- Gradient: **opaque** neutral stops only, e.g. `from-[#121212] via-[#0a0a0a] to-[#060606]` — do **not** stack `/95` alpha gradients on top of `bg-surface-light` or the light canvas will show through.
- Border: `border-white/[0.08]`–`[0.1]` (not heavy `border-surface-elevated` alone)
- Highlight: `shadow-[0_24px_48px_-24px_rgba(0,0,0,0.85),inset_0_1px_0_rgba(255,255,255,0.06)]`
- Header divider: `border-b border-white/[0.07]`

Use this treatment for **hero data modules** (large charts, match narratives), not for every small widget.

### 2.2 Typography colours

| Role     | Token              | Hex (dark) |
|----------|--------------------|------------|
| Primary  | `text-text-primary` | `#e4e4e7`  |
| Secondary | `text-text-secondary` | `#c4c4cc` |
| Muted    | `text-text-muted`   | `#8f8f98`  |

**Win probability copy ladder:**

- Title: `text-zinc-100`, `font-semibold`, `tracking-wide`, `text-sm`
- Body / help: `text-zinc-500`, `text-xs`, `leading-relaxed`, `max-w-3xl`
- Inline code in empty states: `text-zinc-300` on `bg-zinc-950/80`

Align other dense explainers to this hierarchy: **one strong title, zinc-400/500 for de-emphasis**.

### 2.3 Accent (`primary`)

- Token: `text-primary` / `bg-primary` → accent blue (`#8cb4fc`) for **links, focus rings, active nav label, filled buttons** only.
- Do **not** use `bg-primary/5`–`/20` (etc.) for panels, strips, or table headers — use `bg-white/[0.04]`–`[0.08]` on dark instead.

### 2.4 Data-only colour

- **Charts:** prefer `CHART_COLOURS` / `chart.*` from `tailwind.config.ts` and `src/lib/colours.ts` — restrained saturation, distinct hues for series.
- **Grades / scores:** use existing `grade-*`, `score-color-*`, `score-bg-*` utilities — do not invent parallel palettes.
- **Neutrals in charts:** axis strokes ~ `rgba(161,161,170,0.35)`, ticks `#a1a1aa`, grid `rgba(255,255,255,0.045)`, **reference lines** subtle (e.g. even line: `rgba(251, 191, 36, 0.26)` only when it carries meaning).

### 2.5 Black-and-white line work

When showing a **primary curve** over tinted areas (win probability style):

- Curve: `rgba(252, 252, 253, 0.95)` or `rgba(248, 250, 252, 0.88)` with a faint under-glow stroke.
- Avoid rainbow strokes for the main series; let **fills** carry team / series identity.

---

## 3. Typography

Defined in `tailwind.config.ts`:

| Element | Class / family |
|---------|----------------|
| UI body | `font-sans` → **Manrope** |
| Headings | `font-heading` → **Bricolage Grotesque** (use `text-h1` / `text-h2` / `text-h3`) |
| Stats / tables | `font-mono` or `.font-score` / `.tabular-nums` for alignment |

**Rules:**

- Page titles: existing `.page-title` (`text-h2`, `text-text-primary`).
- Section labels: `.section-title` — `uppercase tracking-wide text-text-muted` (or win-prob style `text-sm font-semibold tracking-wide text-zinc-100` inside dark modules).
- Prefer **weight and zinc step** over new colours for hierarchy.

---

## 4. Layout & spacing

- Page shell: `.app-page`, `.page-stack`, `.page-header` (`globals.css`).
- **8-point rhythm:** CSS variables `--space-1` … `--space-6` in `globals.css`; Tailwind spacing as usual.
- Max content width: `max-w-7xl` (see `.app-page`); scorecard narrative text `max-w-3xl` so line length stays readable.

---

## 5. Components & patterns

### 5.1 Default card

- `.section-card` — `rounded-xl border border-surface-elevated bg-surface shadow-sm`
- `.section-card-body` — `p-4 md:p-6`

### 5.2 “Cinema” card (data hero)

Match win probability:

- `rounded-2xl`
- `border border-white/[0.08]`
- Gradient background (zinc-900 → zinc-950)
- Combined **outer shadow + inset top highlight** (see §2.1)
- Internal **header band** with bottom border `border-white/[0.07]`

### 5.3 Buttons, inputs, tables

Use existing classes: `.btn-primary`, `.btn-secondary`, `.btn-ghost`, `.filter-input`, `.sortable-table`, etc. (`globals.css`). Keep **borders cool grey**, not saturated outlines.

### 5.4 Tooltips & popovers

Win probability tooltip pattern:

- `rounded-lg border border-white/15 bg-zinc-950/95 backdrop-blur-sm shadow-xl`
- Text: white title, `text-zinc-400` meta, `tabular-nums` for numbers

Reuse for dark-mode floating UI where it fits; light mode may need a parallel recipe (see §8).

---

## 6. Motion

- Easing: `ease-out-quart` / `ease-out-quint` (theme + `--ease-*` in `globals.css`).
- **Respect `prefers-reduced-motion`** (already in `globals.css`).
- Win probability momentum markers: subtle CSS pulse in `src/styles/scorecards.css` — **decorative only**, low amplitude.

---

## 7. Accessibility

- Focus: `outline-2 outline-offset-2 outline-primary` on interactive elements (`globals.css`).
- Skip link: `.skip-link` pattern in layout.
- Do not rely on colour alone for meaning; pair with **labels, position, or pattern** (win prob uses territory copy + legend + tooltip).

---

## 8. Light mode

The product is **dark-first**. Light theme remaps tokens under `html:not(.dark)` in `globals.css`.

When adding UI:

- Prefer **semantic tokens** (`text-text-primary`, `bg-surface`) so light overrides apply.
- For **zinc-hardcoded** blocks (win probability card), add **explicit light variants** if those surfaces must appear in light mode — otherwise they may look out of place.

---

## 9. Checklist (new feature or page)

1. [ ] Background stack: `background` → `surface` → optional “cinema” gradient for hero data.
2. [ ] Text: primary/secondary/muted only; no random greys outside the zinc scale unless chart-internal.
3. [ ] Borders: `white/5–10%` on dark heroes; `border-surface-elevated` on standard cards.
4. [ ] Accent colour: sparing; data colours only in charts and grades.
5. [ ] Typography: heading font for titles, Manrope for UI, mono/tabular for numbers.
6. [ ] Spacing and `max-w-*` consistent with scorecard / rankings pages.
7. [ ] Focus and keyboard path verified.

---

## 10. File reference

| Concern | Location |
|---------|----------|
| Dark-mode redesign agent prompt | `DARK_MODE_REDESIGN_PROMPT.md` |
| Design tokens (colours, fonts, shadows) | `tailwind.config.ts` |
| Global rules, components, light overrides | `src/styles/globals.css` |
| Win probability (reference card + chart) | `src/components/WinProbabilityMomentumChart.tsx` |
| Scorecard-specific CSS | `src/styles/scorecards.css` |
| Score / chart hex helpers | `src/lib/colours.ts` |
| App shell / nav | `src/components/Layout.tsx` |

---

## 11. Summary sentence

**Build everything like the win probability module:** dark charcoal base, **white and zinc for structure and type**, **thin luminous borders**, shadows that lift without glow clutter, and **colour reserved for data and state** — that is the Cricket Metrics look.
