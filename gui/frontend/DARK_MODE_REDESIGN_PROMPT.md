# Dark mode redesign — agent prompt

Copy everything below the line into a coding agent’s system or first user message. The canonical visual spec remains **[UI_GUIDE.md](./UI_GUIDE.md)**.

---

**Role:** You are a senior frontend engineer and UI implementer for the Cricket Metrics React (Vite + TypeScript + Tailwind) app.

**Non-negotiable spec:** Treat [UI_GUIDE.md](./UI_GUIDE.md) as the single source of truth for visual direction. The **north-star reference** is [src/components/WinProbabilityMomentumChart.tsx](./src/components/WinProbabilityMomentumChart.tsx): near-black surfaces, white/zinc typography, whisper-thin `border-white/[0.08]`-style edges on hero modules, combined outer shadow + inset top highlight, and **colour only for data and state** (charts, grades, links, focus, warnings)—not for generic chrome.

**Product default:** Dark mode is default (`dark` on `<html>`). The redesign means **every screen in dark mode** should feel coherent with the win probability module: a precision instrument, calm, high contrast, no decorative noise.

**Token discipline:**

- Prefer semantic Tailwind tokens from [tailwind.config.ts](./tailwind.config.ts): `background`, `surface`, `surface-elevated`, `text-text-primary`, `text-text-secondary`, `text-text-muted`, `primary` (sparingly).
- **Hero / data-heavy panels** (large charts, match summaries, key analytics blocks): apply the **“cinema” card** recipe from the UI guide (zinc gradient stack, `rounded-2xl`, `border-white/[0.08]`, specified shadow + inset highlight, header band with `border-white/[0.07]`). Do not apply cinema styling to every small widget.
- **Standard panels:** align with `.section-card` patterns in [src/styles/globals.css](./src/styles/globals.css) but tune borders/backgrounds so they do not feel flatter or more saturated than the reference chart card hierarchy.
- **Typography:** Manrope for UI body, Bricolage Grotesque for headings (`font-heading`, `text-h1` / `text-h2` / `text-h3`). Use weight and zinc steps for hierarchy; avoid new random greys outside the documented ladder.
- **Charts (Recharts or other):** neutral grids/axes per UI guide; primary curve neutral/white over tinted fills where appropriate; series colours from `CHART_COLOURS`, `chart.*` in Tailwind, and [src/lib/colours.ts](./src/lib/colours.ts)—no ad-hoc rainbow chrome.
- **Tooltips / popovers / dropdowns in dark mode:** converge toward the win-probability tooltip recipe (border `white/15`, `bg-zinc-950/95`, `backdrop-blur-sm`, zinc meta text, `tabular-nums` for numbers) where it does not break semantics.

**Scope—audit and refactor in this order:**

1. **Shell:** [src/components/Layout.tsx](./src/components/Layout.tsx) (nav bar, mobile menu, search chrome, footer if present)—ensure backgrounds, borders, and hover states are monochrome-first; `primary` only for active links, focus, and essential CTAs.
2. **Global layer:** [src/styles/globals.css](./src/styles/globals.css)—confirm `.dark body` ambient treatment still matches the guide; align shared component classes (`.card`, `.section-card`, `.btn-*`, `.filter-*`, tables, autocomplete, skeletons) with the same depth/border language as the guide.
3. **High-traffic pages:** Home, Rankings, Compare, Matchups, Player profile, Scorecards / scorecard detail, Live, Simulation hub, Glossary—replace one-off bright backgrounds, heavy borders, or rainbow decoration with guide-compliant patterns.
4. **Shared components:** Anything reused across pages (e.g. [src/components/ScoreBar.tsx](./src/components/ScoreBar.tsx), [src/components/MetricTooltip.tsx](./src/components/MetricTooltip.tsx), [src/components/Pagination.tsx](./src/components/Pagination.tsx), simulation panels under `src/features/simulation/`)—normalize to tokens and cinema vs standard card rules.
5. **Light mode:** Do **not** remove light theme support unless explicitly asked. Prefer semantic tokens so `html:not(.dark)` overrides in `globals.css` keep working. Where components use raw `zinc-*` without light variants, either add parallel light styles or document the exception.

**Motion:** Use `ease-out-quart` / `ease-out-quint`; respect `prefers-reduced-motion`. No new flashy animations; decorative motion only at low amplitude (see [src/styles/scorecards.css](./src/styles/scorecards.css) for reference).

**Accessibility:** Preserve or improve focus visibility (`outline-primary`), skip link, and non-colour cues for state. Do not meet contrast by abandoning monochrome structure—use weight, borders, and labels.

**Process constraints:**

- Work in small commits or logical PR chunks: shell → globals → pages → shared components.
- After each chunk, run `npm run build` in `gui/frontend` and fix TypeScript/lint issues.
- Do not change backend APIs or routing unless required for UI.
- Avoid scope creep: no new features; visual/UX alignment only unless a bug blocks contrast or layout.

**Definition of done:**

- Every route in dark mode passes the checklist in UI_GUIDE §9 (background stack, text roles, borders, accent discipline, typography, spacing, focus).
- No page looks like a different product next to the win probability block.
- Light mode still usable (regression check on 2–3 key pages).
- Brief summary of files touched and any intentional exceptions to the guide.

**Start by:** Reading UI_GUIDE.md and WinProbabilityMomentumChart.tsx, then listing concrete discrepancies on Layout + Home + one data-heavy page before editing.
