# Product spec: Team Builder, dual ratings & rankings

This document captures **product intent** and a **step-by-step implementation plan** for Cricket Metrics. It merges stakeholder Q&A with follow-up clarifications on UI (simple vs expanded), Dhoni-style examples, and the “can’t exceed what form ever was” rule.

---

## 1. Goals & principles

| Principle | Detail |
|-----------|--------|
| Trust / eye test | Ratings and positions should match how fans think about players; users should trust the data. |
| Real teams (autofill) | Autofill XIs must look like **coherent squads**, not arbitrary stat-max heaps. |
| Honesty | Where data is thin or inference is weak, **best-effort guess**; explain in **Glossary** where needed. |
| Scope | **T20I + IPL** now; **ODI + Test** in scope later—no implementation required for those formats yet. |

---

## 2. Team Builder

### 2.1 Two modes

| Aspect | **User-built XI** | **Autofill XI** |
|--------|-------------------|-----------------|
| Purpose | User experiments freely | **Best XI on paper** for the selected **time window** |
| Time window | N/A (user choice) | **Current year**, **user-filtered year range**, or **all-time** (2008–2024 IPL mix) |
| Positions | Any slotting; user can “mess with” order | Strict composition rules below |
| Flex | Allowed with **small penalty** + recommendation; **larger penalty** if slot is unfamiliar | **At most one** slot flex from natural position per player; beyond that pick **best at true position** |
| Spin / pace | No limits | ≤ **2** **pure** spinners (not all-rounders); ≤ **4** **pure** pacers (not all-rounders) |
| Phase tags | User choice | Prefer **powerplay / death** (etc.) tags to drive autofill specialist picks |
| Franchise IPL | N/A | Roster = players who **played for that franchise** in the **IPL dataset** only |
| Captain | Cosmetic | Cosmetic |

### 2.2 Position truth (pipeline)

- **Source of truth**: **Modal / inferred batting position** from **where the batter actually entered**:
  - First two batters in the innings → positions **1–2**
  - Innings starts after **one** wicket → **3**, and so on (encode explicitly from ball-by-ball / innings records).
- **Rare roles**: If a player opens e.g. **~1 in 100** innings, **autofill must not** assign them as opener.
- **Manual placement**: If user slots someone away from their usual position → **small notice**: “X is out of position.”
- **Finishers**: T20s are short; **do not** over-model “finisher” as a separate archetype for autofill—**batting position** is enough.

### 2.3 Flex penalty (conceptual)

- **User mode**: Small penalty; **minimal** if they’ve **played that position before** (data-backed).
- **Autofill mode**: Max **one** position step flex; then only **natural-position** picks.

### 2.4 All-rounders

- **Definition**: **Large volume** of both batting and bowling; need not be 50/50, but **both consistently**.

### 2.5 Year filter (autofill / franchise)

- Default mental model: **mix 2008–2024**.
- **UI**: Let user select **year range** over which stats inform the autofill XI.

---

## 3. Ratings: dual system

### 3.1 Definitions

| Rating | Meaning |
|--------|---------|
| **Current** | How good the player is **right now**, driven by **recent** performance (same family of “recent logic” for bat and bowl). |
| **Overall** | Career-style quality: blends **peak** and **sustained performance**; **not** automatically equal to peak. |

### 3.2 Peak and hard caps

- **Peak** = maximum of the **rolling / window composite** shown in the **form tracker** (same series the app already surfaces over time).
- **Rule**: **No displayed rating (overall or current) can exceed a value the player’s form composite has never reached.**  
  - If form has **never** hit 100, **overall cannot be 100** (same intuition for any ceiling).
- **Current** is additionally **hard-capped by peak** (as previously agreed).

### 3.3 Blending and volume

- **Overall** uses a **blend** of peak + body of work (exact weights TBD in implementation; stakeholder approved “blend for now”).
- **Earning** the headline: High **peak** alone does **not** grant full **overall**—need **good performances over a long enough span** to **earn** proximity to peak.
- **Recent window pull**: Need **≥ 10 innings** (enough variance) before recent performance can **materially** move the **current** rating (and influence blends where applicable).
- **Inactivity**: **No numerical decay** for time off—only **inactive** classification (separate from rating math).

### 3.4 Activity windows (unchanged rationale)

- **T20I** vs **IPL** use different **activity/recency windows** for “active player” (IPL short season vs T20I year-round)—**not** different peak/overall formulas per format beyond that.

### 3.5 UI: simple vs expanded (clarified)

| Surface | What to show |
|---------|----------------|
| **Simple view** | **Current** rating only (primary number users see at a glance). |
| **Expanded view** | **Overall** (and optionally breakdown / peak / glossary links). |

### 3.6 Sanity checks (calibration targets)

Use these as **regression targets** when tuning—not hard-coded constants:

| Player | Expectation |
|--------|-------------|
| **Dhoni** | Autofill / sensible XI: bats **~5**. **Overall** in high 90s **all-time** is acceptable as *ceiling narrative*, but **displayed overall** must reflect **recent reality**: poor batting over **~5 years**, composite **not above ~85** in that window → **overall shown** can sit **~70** if that’s what the model produces. **Current** lower if recent form is weak. |
| **Kohli** | **> Dhoni** in both **T20I** and **IPL** for the relevant ratings. Ballpark: T20I **~98–99**, IPL **~96** (tune to distribution). |

**Note:** Dhoni example ties **overall** to **multi-year underperformance** relative to peak—implementation should make **overall** responsive to sustained form, not just career peak.

---

## 4. Rankings

- **Retired / inactive**: Still appear on **all-time** style lists with **inactive** flag; default lists remain **active-only** where product already defines that.
- **Provisional**: **Hidden by default** (filter).
- **Layout**: **One** leaderboard table + **position filter** (not separate tabs per position for now).
- **Cross-position metrics**: Do **not** compare raw sub-scores (e.g. **power vs acceleration**) across **opener vs finisher** without **position-aware normalization**—a good opener innings (e.g. 70 off 40) is not comparable to a good finisher innings (e.g. 25 off 10) on the same raw scale.

---

## 5. Explainability

- Deep detail lives in **Glossary** (and expanded profile views).
- **Simple** surfaces stay minimal: **current** first.

---

## 6. Open implementation details (to lock in code)

1. **Overall formula**: Explicit weights (peak vs career length vs recent tail); document in `src/` or this doc once chosen.
2. **“Never exceeded in form” cap**: Apply to **overall** and **current**, or **overall only**? Spec reads as **both** display numbers capped by historical max of form composite—confirm in code review.
3. **Position from entry order**: Exact mapping table (wicket index → batting position 1–11) and edge cases (retired hurt, supersub, missing data).
4. **Pure spinner / pacer**: Definition from pipeline (e.g. primary bowling type + innings share thresholds).

---

# Part B — Step-by-step implementation plan

Phases are ordered so **data layer → API → UI** stays consistent. Parallel tracks are marked.

### Phase 0 — Document & audit (1–2 days)

1. [ ] Add this file to repo (`docs/product-spec-team-ratings.md`) — **done when merged**.
2. [ ] **Audit** current fields: `overall_score`, form series / `peak_window_composite`, `position_group`, bowling style columns, franchise IDs in IPL data.
3. [ ] List **gaps**: innings-level batting position, year on match, “pure” vs “all-rounder” flags for autofill caps.

### Phase 1 — Batting position from entry order (pipeline) (medium)

1. [ ] Define **batting position** per innings from **order of first appearance** (or wickets fallen at entry—align with spec §2.2).
2. [ ] Persist per innings in `batting_innings_detail` (or equivalent).
3. [ ] Recompute **modal position** and **position histogram** (share of innings per slot 1–11).
4. [ ] Add rule: **autofill eligibility** for slot S = player has ≥ **N** innings at S or **≥ X%** of career innings (tune N/X; spec says ~1/100 open → exclude from autofill opener).
5. [ ] Expose via API for Team Builder: `position_histogram`, `modal_position`, `eligible_slots`.

### Phase 2 — Dual ratings backend (large)

1. [x] **peak / ceiling** from form series: `form_composite_max` + `peak_window_composite` used in `rating_display.py` (API-layer caps).
2. [x] **current_rating** from latest rolling composite with **≥10 innings/spells** gate (else aligned with overall display).
3. [~] **overall_rating**: capped `min(overall_score, ceiling)`; full **sustained-performance blend** (Dhoni-style multi-year) still TBD vs spec §3.3.
4. [x] Cap **both** displayed ratings by historical max form composite (and current by ceiling).
5. [~] Parquet: rollups merged in loader from form series; optional materialised career columns still TBD.
6. [x] **Bowling**: mirrored in display helper + loader rollups.

### Phase 3 — API & schema (small–medium)

1. [x] `PlayerSummary` / profiles: `rating_current`, `rating_overall`; batters `modal_position`.
2. [x] Rankings: sort by **rating_current** / **rating_overall** (API + Cur/Ovl header); default **current** desc; pipeline `overall_score` still in sort dropdown.
3. [x] Frontend `primaryDisplayRating()` falls back to `overall_score`.

### Phase 4 — UI: simple vs expanded (medium)

1. [x] Rankings / Home / autocomplete / PlayerCard mini: **current** headline via `primaryDisplayRating`.
2. [x] Profile hero: **Current** + **Career overall** when `rating_overall` present.
3. [x] Rankings column **Current / Overall** together + tooltip / micro-copy on sort vs pipeline `overall_score`.
4. [x] Compare summary: **Current** + **Career overall** rows.

### Phase 5 — Team Builder: manual mode (medium)

1. [x] Existing slot model; modal position from API.
2. [~] **Out-of-position** hint vs `modal_position` (no penalty hook yet; no `eligible_slots` / histogram API).
3. [x] No spin/pace caps in manual mode.

### Phase 6 — Team Builder: autofill (large)

1. [ ] Inputs: franchise, **year range**, format IPL.
2. [ ] Filter players to franchise + matches in year range.
3. [ ] **ILP / greedy** skeleton: pick **WK** (if distinguished), **batters 1–11** by position eligibility, **bowlers** with caps: ≤2 pure spin, ≤4 pure pace, all-rounders exempt from caps.
4. [ ] Enforce **max 1 position flex** from modal slot; objective = maximize sum of **position-specific** ratings (use position-normalized scores when available).
5. [ ] Integrate **phase specialists** (PP/death) as bonus terms or hard constraints (start soft).
6. [ ] **Captain**: cosmetic picker only.

### Phase 7 — Rankings: position-aware display (medium)

1. [ ] **Position filter** already planned—wire to new `modal_position` / bucket.
2. [ ] **Metric tooltips**: warn when comparing across positions (or hide certain sorts when position = “all”).
3. [ ] Optional: **position-normalized** columns for cross-position “power” comparison—research task.

### Phase 8 — Glossary & QA (ongoing)

1. [~] Glossary: **Current vs career overall**, **Out of position** + FAQ; **Peak** / **Inactive** / **Provisional** largely covered elsewhere; **Autofill rules** when Phase 6 ships.
2. [ ] **Test suite** / notebooks: Dhoni (slot 5, overall ~70 recent-era), Kohli > Dhoni, cap-at-max-form examples.
3. [ ] **Distribution check**: no mass of players at 100 unless form supports it.

### Phase 9 — Future (ODI / Test)

1. [ ] Duplicate position + rating pipeline per format when data added.
2. [ ] Separate autofill caps (e.g. Test pace/spin) — new spec section later.

---

## Revision history

| Date | Change |
|------|--------|
| (initial) | Full spec + plan from stakeholder Q&A and clarifications on simple=current, expanded=overall, Dhoni 5y composite, cap by form history. |
| 2026-03 | Progress notes: API dual ratings + modal position; UI current headline; Team Builder OOP hint; Glossary/FAQ for current vs overall. |

---

*End of document.*
