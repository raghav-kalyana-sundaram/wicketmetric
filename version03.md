# Cricket Metrics — Version 0.3 Implementation Plan

> **Audience:** A single developer picking up this codebase for the first time.
> **Goal:** This document is self-contained. You should not need to read any other file to understand what needs to change, why, and how.

---

## Implementation Status

> **Last updated:** This section tracks which changes have been implemented and any deviations from the original plan.

| # | Change | Status | Notes |
|---|--------|--------|-------|
| 1 | Form Tracker Y-Axis Fix | ✅ Done | `PlayerProfile.tsx` — auto-scales Y-axis with 15% padding, min range of 5. |
| 2 | Bowling Median: Exclude Non-Bowlers | ✅ Done | `team.py` — archetype-based `_is_genuine_bowler()` with fallback heuristic (≥10 matches, ratio ≥0.40). Percentile computations now use genuine bowlers only. |
| 3 | Customisable Slot Positions | ✅ Done | `TeamBuilder.tsx` — `SLOT_TYPE_OPTIONS` with 6 types, click-to-cycle labels, persisted in localStorage and shared URLs. |
| 4 | Preserve Batting Order in Shared URLs | ✅ Done | `TeamBuilder.tsx` — `Promise.all` preserves order; URL encodes ordered IDs. |
| 5 | Exclude Tail-Enders from Batting Aggregates | ✅ Done | `team.py` — archetype-based `_is_genuine_batter()` with fallback (≥10 innings, composite ≥20). |
| 6 | Hover Tooltips on Compare Page | ✅ Done | `Compare.tsx` — `MetricLabel` component used in `StatTable`; `metricKey` on `StatRow` interface. |
| 7 | Era Timeline: Avg Run Rate & Predicted Score | ✅ Done | `Eras.tsx` — `METRIC_CONFIGS` includes `avg_rr` and `predicted_score` with toggle buttons. Frontend-only computation from existing baselines. |
| 8 | Compare Page: Show Predominant Role | ✅ Done | `Compare.tsx` — `viewMode` state (`auto`/`bat`/`bowl`), `effectiveView` logic, separate radar axes per role. |
| 9 | IPL Dataset Support & Format Toggle | ✅ Done | Pipeline run on `ipl_json/` → `output_ipl/` (703 batters, 551 bowlers). `data_loader.py` — `MultiDataStore` + `load_all_data()` auto-discovers `output_t20i/` and `output_ipl/`. `app.py` — `get_store(format=)` dependency selects dataset via `?format=` query param; `/api/formats` endpoint lists available formats. `FormatContext.tsx` — React context with localStorage persistence, syncs with `setClientFormat()` in `client.ts`. `client.ts` — `buildUrl()` auto-appends `?format=` to every request. `queries.ts` — every hook calls `useFormat()` and prefixes query keys with `format` for correct cache isolation. `FormatToggle.tsx` — pill-shaped T20I/IPL toggle in nav bar (desktop + mobile), only renders when >1 format available, invalidates all queries on switch. `Layout.tsx` — toggle added to nav bar and mobile menu. `App.tsx` — `FormatProvider` wraps router. |
| 10 | Multiple Archetypes (Top 3) | ✅ Done | `presentation.py` — `_match_archetypes()` returns up to 3 matches; `archetypes` column (comma-separated) + `archetype` (primary). `PlayerProfile.tsx` displays all with opacity fade. `ArchetypeBadge` component already supports lists. |
| 11 | Rating Rebalance | ✅ Done | `presentation.py` — superstar bonus capped at single best dimension (`max` instead of `sum`), weight reduced 0.15→0.10. `config.yaml` — control weights rebalanced (avg_proxy 0.20→0.22, scoring_consistency 0.10→0.14, dot_pct 0.12→0.08, survival_ratio 0.30→0.28). `batting.py` — responsibility multiplier on `raw_control` (up to 15% bonus for batters averaging 75+ balls/inn). Tests updated. |
| 12 | Team vs Team Comparison | ✅ Done | `team.py` — new `/team/compare` endpoint returning both analyses + edge indicators (batting/bowling/WAR/clutch). `client.ts` — `compareTeams()`. `queries.ts` — `useTeamCompare()`. `types.ts` — `TeamCompareResponse`/`TeamComparison`. `TeamBuilder.tsx` — compare mode toggle, Team B slots, `ComparisonPanel` with side-by-side aggregates, edge badges, and weakness comparison. |
| 13 | Chase Splits Tuning | ✅ Done | `batting.py` — `compute_chase_splits()` now computes actual SR and batting avg per split (not just differential indices). `main.py` — merges `setting_sr`, `setting_avg`, `chasing_sr`, `chasing_avg` into careers. `player.py` — `_build_batting_chase_splits()` populates `avg` and `sr` fields on `ChaseSplit`. |
| — | Role-Aware Team Builder (bonus) | ✅ Done | `team.py` — `_BATTING_ARCHETYPES` / `_BOWLING_ARCHETYPES` sets for archetype-first classification. `slot_types` param kept for URL compatibility but ignored for role classification. `TeamBuilder.tsx` — auto-assigns slot type from player archetype on add. |

### What Still Needs Doing

1. **Pipeline re-run complete** — Both `output_t20i/` (4,049 batters, 3,006 bowlers) and `output_ipl/` (703 batters, 551 bowlers) have been generated. The legacy `output/` directory is kept as a fallback.
2. **Bonus changes** (§ 15) — drag-and-drop, export as image, slot-type-aware search, year range filter, mobile responsive, bowling phase labels, IPL franchise names.

### New Ideas (discovered during implementation)

1. **Make archetype sets data-driven** — Currently `_BATTING_ARCHETYPES` and `_BOWLING_ARCHETYPES` in `team.py` are hardcoded sets that mirror `presentation.py`. Instead, export them from the pipeline as metadata (e.g., a JSON sidecar or a column in the Parquet) so the backend reads them at startup. This eliminates the need to keep two lists in sync.
2. **Team Builder: share both teams in URL** — When in compare mode, encode both Team A and Team B in the URL (e.g., `?a=id1,id2&b=id3,id4`) so the full comparison is shareable.
3. **Team Builder: overlay radars** — Show Team A and Team B radars overlaid on the same chart (different colours) for instant visual comparison, similar to the Compare page's player radar overlay.
4. **Archetype distribution chart** — On the Rankings page, add a small bar chart showing the distribution of archetypes in the top N players. This helps visualise whether the rating rebalance (Change 11) achieved a healthier mix.
5. **Chase split composite improvement** — Now that we have actual SR and avg per split, the composite could be a normalised blend (e.g., SR/130 × 50 + avg/30 × 50) instead of the raw differential index. This would give more intuitive numbers on the Player Profile page.
6. **"What-if" slot swaps** — In the Team Builder, allow the user to click a player and see how the team analysis would change if they swapped that player for another. Show delta values (e.g., "+3.2 ACC, −1.1 CTL") before confirming the swap.
7. **Team strength historical trend** — For a built team, show how the team's aggregate metrics would have looked in each year (using era multipliers). This visualises whether the team is built for modern T20 cricket or would have been better in an earlier era.

---

## Table of Contents

1. [Project Overview & Architecture Primer](#1-project-overview--architecture-primer)
2. [Change 1 — Form Tracker Y-Axis Fix](#2-change-1--form-tracker-y-axis-fix)
3. [Change 2 — Bowling Median: Exclude Non-Bowlers](#3-change-2--bowling-median-exclude-non-bowlers)
4. [Change 3 — Customisable WK / All-Rounder Slot Positions](#4-change-3--customisable-wk--all-rounder-slot-positions)
5. [Change 4 — Preserve Batting Order in Shared URLs](#5-change-4--preserve-batting-order-in-shared-urls)
6. [Change 5 — Exclude Tail-Enders from Batting Aggregates](#6-change-5--exclude-tail-enders-from-batting-aggregates)
7. [Change 6 — Hover Tooltips on Compare Page Advanced Stats](#7-change-6--hover-tooltips-on-compare-page-advanced-stats)
8. [Change 7 — Era Timeline: Add Avg Run Rate & Predicted Score](#8-change-7--era-timeline-add-avg-run-rate--predicted-score)
9. [Change 8 — Compare Page: Show Predominant Role](#9-change-8--compare-page-show-predominant-role)
10. [Change 9 — IPL Dataset Support & Format Toggle](#10-change-9--ipl-dataset-support--format-toggle)
11. [Change 10 — Multiple Archetypes (Top 3)](#11-change-10--multiple-archetypes-top-3)
12. [Change 11 — Rating Rebalance: Reduce Explosive Finisher Skew](#12-change-11--rating-rebalance-reduce-explosive-finisher-skew)
13. [Change 12 — Team vs Team Comparison](#13-change-12--team-vs-team-comparison)
14. [Change 13 — Chase Splits Tuning](#14-change-13--chase-splits-tuning)
15. [Bonus Changes — Additional Improvements](#15-bonus-changes--additional-improvements)
16. [Implementation Order & Dependency Graph](#16-implementation-order--dependency-graph)
17. [File Change Summary](#17-file-change-summary)
18. [Testing Strategy](#18-testing-strategy)

---

## 1. Project Overview & Architecture Primer

### Repository Layout

```
cricket_metrics/
├── src/                        # Python pipeline — processes raw Cricsheet JSON → Parquet
│   ├── parser.py               # Reads ball-by-ball JSON, produces DataFrames
│   ├── context.py              # Match context (par SR, targets, etc.)
│   ├── config.py               # YAML config loader (config.yaml)
│   ├── batting.py              # Batting component scores (acceleration, power, control)
│   ├── bowling.py              # Bowling component scores (accuracy, control, threat)
│   ├── expected_value.py       # xR / expected runs model
│   ├── rating.py               # Bayesian shrinkage rating system (0-100 scores)
│   ├── presentation.py         # Letter grades (S/A+/A/B+/…) and archetypes
│   ├── war.py                  # Wins Above Replacement
│   ├── clutch.py               # Pressure/clutch index
│   ├── form_tracker.py         # Rolling-window form time-series
│   ├── similarity.py           # Player similarity engine
│   ├── peak_ratings.py         # Peak vs current ratings
│   ├── venue.py                # Venue baselines & flat-track index
│   ├── matchups.py             # Batter vs bowler head-to-head
│   ├── condition.py            # Condition dependence (bat-first/chase)
│   ├── wpa.py                  # Win Probability Added
│   ├── era.py                  # Era adjustment multipliers
│   └── main.py                 # Pipeline orchestrator — runs everything
├── config.yaml                 # All tunable parameters
├── output/                     # Pipeline outputs (Parquet + CSV)
│   ├── batting_careers_full.parquet
│   ├── bowling_careers_full.parquet
│   ├── batting_innings_detail.parquet
│   ├── bowling_spells_detail.parquet
│   ├── batting_form_series.parquet
│   ├── bowling_form_series.parquet
│   ├── batting_similarities.parquet
│   ├── bowling_similarities.parquet
│   ├── matchups.parquet
│   ├── matchups_by_phase.parquet
│   └── venue_baselines.parquet
├── t20s_male_json/             # Cricsheet T20I ball-by-ball JSON files
├── ipl_json/                   # NEW: Cricsheet IPL ball-by-ball JSON (1,170 matches)
├── gui/
│   ├── backend/                # FastAPI backend — reads Parquet, serves JSON API
│   │   ├── app.py              # FastAPI app entry point, lifespan, CORS
│   │   ├── data_loader.py      # Loads all Parquet into DataStore dataclass
│   │   ├── search_index.py     # Trigram search over player names
│   │   ├── schemas.py          # Pydantic response models
│   │   └── routers/
│   │       ├── player.py       # GET /api/player/:id
│   │       ├── rankings.py     # GET /api/rankings
│   │       ├── compare.py      # GET /api/compare
│   │       ├── team.py         # GET /api/team/analyse, /api/team/auto-fill
│   │       ├── eras.py         # GET /api/eras
│   │       ├── matchups.py     # GET /api/matchups
│   │       ├── venues.py       # GET /api/venues
│   │       └── search.py       # GET /api/search
│   └── frontend/               # React + TypeScript + Vite + TailwindCSS
│       └── src/
│           ├── App.tsx          # Router config (react-router-dom)
│           ├── api/
│           │   ├── client.ts    # Axios/fetch wrapper
│           │   ├── queries.ts   # TanStack Query hooks (usePlayer, useTeamAnalysis, …)
│           │   └── types.ts     # TypeScript interfaces (PlayerSummary, TeamAnalysis, …)
│           ├── components/
│           │   ├── MetricTooltip.tsx   # Hover tooltip with metric definitions
│           │   ├── GradeBadge.tsx      # S/A+/A/B+ coloured badge
│           │   ├── ScoreBar.tsx        # Horizontal score bar
│           │   ├── PlayerAutocomplete.tsx # Searchable player picker
│           │   └── …
│           └── pages/
│               ├── PlayerProfile.tsx    # Individual player page with FormChart
│               ├── Compare.tsx          # Side-by-side player comparison
│               ├── TeamBuilder.tsx      # XI assembly + team analysis
│               ├── Eras.tsx             # Era timeline + par SR chart
│               ├── Rankings.tsx         # Leaderboard tables
│               ├── Matchups.tsx         # Head-to-head explorer
│               ├── Venues.tsx           # Venue analysis
│               └── Glossary.tsx         # Metric explanations
│           └── styles/                  # Tailwind config + global CSS
```

### Data Flow

```
Cricsheet JSON  →  src/main.py (pipeline)  →  output/*.parquet
                                                     ↓
                                            gui/backend/data_loader.py (loads into DataStore)
                                                     ↓
                                            gui/backend/app.py (FastAPI REST API)
                                                     ↓
                                            gui/frontend (React SPA, TanStack Query)
```

The pipeline runs **offline** and writes Parquet files. The FastAPI backend loads these into an
in-memory `DataStore` dataclass at startup and serves them as JSON. The React frontend
fetches data via TanStack Query hooks.

### Key Concepts

- **Batting scores** have three dimensions: `score_acceleration`, `score_power`, `score_control` (each 0–100 percentile).
- **Bowling scores** have three dimensions: `score_accuracy`, `score_control`, `score_threat` (each 0–100).
- **Archetypes** are rule-based labels derived from these scores (e.g., "Explosive Finisher" = acceleration ≥ 85 AND power ≥ 85). Defined in `src/presentation.py`.
- **WAR** (Wins Above Replacement) is a single-number value metric. Computed in `src/war.py`.
- **Form** is a rolling-window time-series of composite scores. Computed in `src/form_tracker.py`.
- **Team Analysis** (backend: `routers/team.py`) aggregates batting/bowling averages across selected players and detects weaknesses by comparing to dataset-wide percentiles.
- **Grade boundaries**: S ≥ 95, A+ ≥ 85, A ≥ 75, B+ ≥ 60, B ≥ 45, C+ ≥ 30, C ≥ 15, D < 15.
- **Bayesian shrinkage**: Raw per-innings metrics are shrunk toward population mean with k=12 sample weighting. More innings → less shrinkage. Implemented in `src/rating.py`.
- **Overall score**: NOT a simple average of the three dimensions. It uses a "superstar bonus" — if any dimension is above 85, the excess pulls the overall up non-linearly. See `src/presentation.py::_compute_overall_score`.

### How to Run

```bash
# 1. Pipeline (process Cricsheet JSON → output Parquet)
cd cricket_metrics
python -m src.main          # Reads t20s_male_json/ → writes output/

# 2. Backend (serves API on :8000)
cd gui/backend
pip install -r requirements.txt
uvicorn app:app --reload --port 8000

# 3. Frontend (Vite dev server on :5173)
cd gui/frontend
npm install
npm run dev
```

### Key TypeScript Interfaces (gui/frontend/src/api/types.ts)

- **`PlayerSummary`**: Compact player card data (id, name, country, role, archetype, 3 scores, grade).
- **`BatterProfile`** / **`BowlerProfile`**: Full player profile with all advanced metrics, phases, chase splits, matchups, similar players.
- **`TeamAnalysis`**: { player_count, batters[], bowlers[], avg_acceleration, avg_bat_power, avg_bat_control, avg_accuracy, avg_bowl_control, avg_threat, total_war_batting, total_war_bowling, avg_clutch, weaknesses[] }.
- **`EraBaseline`**: { year, par_sr, boundary_rate, dot_pct, multiplier }.
- **`FormPoint`**: { date, composite, ... rolling metrics }.

### Key Backend Schemas (gui/backend/schemas.py)

The Pydantic models mirror the TypeScript interfaces. Any new fields must be added in both.

### Config (config.yaml)

All tunable parameters live here. The `src/config.py` module provides `cfg("path.to.key", default=...)` for access. Key sections: `pipeline`, `rating`, `batting_*_weights`, `bowling_*_weights`, `presentation`, `clutch`, `chase_master`, `war`, `form_tracker`, `era_adjustment`, `condition_dependence`.

---

## 2. Change 1 — Form Tracker Y-Axis Fix

### Problem

The Form Tracker chart on the Player Profile page hard-codes `domain={[0, 100]}` for the Y-axis. Most players' composite scores cluster in a narrow range (e.g., 0–5 for tail-enders, or 40–70 for good batters), making the graph appear as a flat line squished at the bottom or middle. The user sees no meaningful variation.

### Root Cause

**File:** `gui/frontend/src/pages/PlayerProfile.tsx`, function `FormChart` (~L1376–1459).

The `<YAxis>` component has:
```tsx
<YAxis
  domain={[0, 100]}
  // ...
/>
```

This forces the axis from 0 to 100 regardless of actual data range.

### Solution

Auto-scale the Y-axis based on the actual data range with 15% padding on each side, clamped to `[0, 100]`.

### Implementation Steps

**File:** `gui/frontend/src/pages/PlayerProfile.tsx` — inside the `FormChart` component

1. After computing `chartData` (the `useMemo` that maps `series` → `{date, composite}`), add a derived min/max computation:

```tsx
const compositeValues = chartData
  .map((d) => d.composite)
  .filter((v): v is number => v != null);

const dataMin = compositeValues.length > 0 ? Math.min(...compositeValues) : 0;
const dataMax = compositeValues.length > 0 ? Math.max(...compositeValues) : 100;
const range = Math.max(dataMax - dataMin, 5); // Minimum range of 5 to avoid squished graphs
const pad = range * 0.15;
const yMin = Math.max(0, Math.floor(dataMin - pad));
const yMax = Math.min(100, Math.ceil(dataMax + pad));
```

2. Update the `<YAxis>` to use the dynamic domain:

```tsx
<YAxis
  domain={[yMin, yMax]}
  tick={{ fontSize: 10, fill: "#94A3B8" }}
  tickLine={false}
  axisLine={false}
  width={35}
/>
```

3. Conditionally render the `<ReferenceLine y={50}>` only if 50 falls within the visible range:

```tsx
{yMin <= 50 && yMax >= 50 && (
  <ReferenceLine y={50} stroke="#64748B" strokeDasharray="3 3" strokeOpacity={0.5} />
)}
```

### Testing

- Open a player with very low composite scores (e.g., a tail-ender or a seldom-used bowler where composites are near 0). Confirm the graph auto-scales and the line is visible with clear variation.
- Open a top batter with composites in the 60–90 range. Confirm the graph focuses on that range.
- Open a player whose composites span most of 0–100. Confirm no regression.
- Verify the reference line at y=50 only appears when 50 is within the visible range.

---

## 3. Change 2 — Bowling Median: Exclude Non-Bowlers

### Problem

In the Team Builder's Team Analysis panel, bowling weakness detection ("Bowling threat below average") compares the team's average bowling scores against the **50th percentile of the entire `bowl_careers` dataset**. But `bowl_careers` contains an entry for *every player who has ever bowled a single over*, including pure batters like Virat Kohli, Ishan Kishan, or even wicketkeepers who bowled 1–2 novelty overs. This drags the median way down, making the weakness detection give false positives ("Bowling threat below average") even for genuinely decent bowling attacks.

Similarly, when the "Selected Players" summary shows "Bowlers (9)" for a team with 11 players, it's including batters who have negligible bowling records. Those players would never actually bowl in a real match.

### Root Cause

**File:** `gui/backend/routers/team.py`

1. `_detect_weaknesses()` computes the 50th percentile from the raw `store.bowl_careers` DataFrame with no filtering:
```python
valid = pd.to_numeric(store.bowl_careers[col], errors="coerce").dropna()
p50 = float(valid.quantile(0.5))
```

2. `analyse_team()` adds every player who has *any* entry in `bowl_careers` to the bowler list, regardless of how little they bowl.

### Solution

Introduce a **"genuine bowler" heuristic** based on the ratio of bowling matches to batting innings. The idea: in real cricket, if a player bowls in at least 25% of the innings they bat in, they're a functional bowler (specialist or all-rounder). If they bowl in < 25%, they're a batter who occasionally sends down an over.

Additionally, require a minimum of 5 bowling matches to exclude fluky small-sample entries.

### Implementation Steps

**File:** `gui/backend/routers/team.py`

#### Step 1 — Add a genuine-bowler filter helper

Add this function after the existing helper functions:

```python
def _is_genuine_bowler(bowl_row: dict, store) -> bool:
    """Determine if a player is a genuine bowler (not a batter who occasionally bowls).

    Heuristic: a player is a genuine bowler if they bowled in at least 25%
    of the innings they batted in AND have at least 5 bowling matches.
    Players who only have bowling records (no batting) are always genuine.
    """
    bowl_matches = float(bowl_row.get("matches", 0) or 0)

    # Must have minimum bowling sample
    if bowl_matches < 5:
        return False

    # Cross-reference with batting careers
    bowler_id = str(bowl_row.get("bowler_id", ""))
    if not bowler_id or store.bat_careers.empty or "batter_id" not in store.bat_careers.columns:
        return True  # No batting record → pure bowler

    bat_mask = store.bat_careers["batter_id"] == bowler_id
    bat_matches = store.bat_careers.loc[bat_mask]

    if bat_matches.empty:
        return True  # No batting record → pure bowler

    bat_innings = float(bat_matches.iloc[0].get("innings_count", 0) or 0)
    if bat_innings <= 0:
        return True

    ratio = bowl_matches / bat_innings
    return ratio >= 0.25


def _get_genuine_bowlers_df(store) -> "pd.DataFrame":
    """Return a filtered copy of store.bowl_careers containing only genuine bowlers."""
    import pandas as pd

    if store.bowl_careers.empty:
        return pd.DataFrame()

    mask = []
    for _, row in store.bowl_careers.iterrows():
        mask.append(_is_genuine_bowler(row.to_dict(), store))

    return store.bowl_careers.loc[mask]
```

#### Step 2 — Update `_detect_weaknesses()` to use filtered bowlers for percentile computation

Replace the bowling dimension check section:

```python
# Bowling dimension checks — only compare against genuine bowlers
genuine_bowlers = _get_genuine_bowlers_df(store)

bowl_dimensions = [
    ("score_accuracy", "Bowling accuracy"),
    ("score_control", "Bowling control"),
    ("score_threat", "Bowling threat"),
]

for col, label in bowl_dimensions:
    team_avg = _avg_col(bowl_rows, col)
    if team_avg is None:
        continue

    if not genuine_bowlers.empty and col in genuine_bowlers.columns:
        valid = pd.to_numeric(genuine_bowlers[col], errors="coerce").dropna()
        if len(valid) > 0:
            p50 = float(valid.quantile(0.5))
            if team_avg < p50:
                weaknesses.append(
                    f"{label} below average (team avg {team_avg:.1f} vs median {p50:.1f})"
                )
```

#### Step 3 — Update `analyse_team()` to only include genuine bowlers in bowling aggregates

In the main loop where each player ID is looked up, add a genuine-bowler check before adding to `bowl_rows`:

```python
# Check bowlers (player can be both batter and bowler)
if not store.bowl_careers.empty and "bowler_id" in store.bowl_careers.columns:
    mask = store.bowl_careers["bowler_id"] == pid
    matches = store.bowl_careers.loc[mask]
    if not matches.empty:
        row = matches.iloc[0]
        row_dict = row.to_dict()
        # Only include in bowling aggregates if they're a genuine bowler
        if _is_genuine_bowler(row_dict, store):
            bowler_summaries.append(_row_to_player_summary(row_dict, "bowl"))
            bowl_rows.append(row_dict)
            found = True
        elif not found:
            # Player exists in bowling but isn't a genuine bowler
            # They'll still be found as a batter above; mark found if needed
            pass
```

#### Step 4 — Update the structural weakness checks

The existing check `if len(bowl_rows) < 4` should now correctly reflect genuine bowlers since non-genuine ones are filtered out. No change needed to the structural logic itself, but verify the threshold:

```python
if len(bowl_rows) < 4 and len(bowl_rows) > 0:
    weaknesses.append(f"Fewer than 4 specialist bowlers (have {len(bowl_rows)})")
```

### Testing

- Build a team with Abhishek Sharma, SV Samson, Ishan Kishan, SA Yadav (pure batters). The bowling panel should say "Bowlers (0)" or show only players who genuinely bowl.
- Add JJ Bumrah, Arshdeep Singh (pure bowlers). They should appear in bowlers.
- Add HH Pandya (all-rounder who bowls regularly). He should appear in both batters and bowlers.
- Verify the "Bowling threat below average" message now uses a realistic median based on genuine bowlers.

---

## 4. Change 3 — Customisable WK / All-Rounder Slot Positions

### Problem

The Team Builder has fixed slot labels: slots 1–4 are Opener/Top Order, 5–6 Middle Order, 7 is Finisher/WK, 8 is All-rounder, 9–11 are Bowlers. Users can't move the WK to slot 1 (e.g., Jos Buttler opens) or put an all-rounder at slot 5. The labels are purely cosmetic — any player can already go in any slot — but the labels mislead and don't reflect real team construction flexibility.

### Root Cause

**File:** `gui/frontend/src/pages/TeamBuilder.tsx`

The constants `SLOT_LABELS` and `SLOT_ICONS` are static arrays:
```tsx
const SLOT_LABELS: string[] = [
  "Opener", "Opener", "Top Order", "Top Order",
  "Middle Order", "Middle Order", "Finisher / WK",
  "All-rounder", "Bowler", "Bowler", "Bowler",
];
```

### Solution

Make slot labels editable via a click-to-cycle mechanism. Each slot's label can cycle through: Opener → Top Order → Middle Order → Finisher / WK → All-rounder → Bowler. The selection persists in localStorage and is included in shared URLs.

### Implementation Steps

**File:** `gui/frontend/src/pages/TeamBuilder.tsx`

#### Step 1 — Define slot type constants

Add at the top of the file, replacing or augmenting the existing `SLOT_LABELS` / `SLOT_ICONS`:

```tsx
const SLOT_TYPE_OPTIONS = [
  { key: "opener",       label: "Opener",         icon: "🏏" },
  { key: "top_order",    label: "Top Order",      icon: "🏏" },
  { key: "middle_order", label: "Middle Order",   icon: "🏏" },
  { key: "finisher_wk",  label: "Finisher / WK",  icon: "🧤" },
  { key: "allrounder",   label: "All-rounder",    icon: "⚡" },
  { key: "bowler",       label: "Bowler",         icon: "🎳" },
] as const;

type SlotTypeKey = typeof SLOT_TYPE_OPTIONS[number]["key"];

const DEFAULT_SLOT_TYPES: SlotTypeKey[] = [
  "opener", "opener", "top_order", "top_order",
  "middle_order", "middle_order", "finisher_wk",
  "allrounder", "bowler", "bowler", "bowler",
];
```

#### Step 2 — Add slot type state

```tsx
const [slotTypes, setSlotTypes] = useState<SlotTypeKey[]>(() => {
  // Try loading from localStorage (same SavedTeam object)
  const saved = loadTeamFromStorage();
  if (saved && saved.slotTypes) return saved.slotTypes;
  return [...DEFAULT_SLOT_TYPES];
});
```

#### Step 3 — Update `SavedTeam` interface and storage helpers

```tsx
interface SavedTeam {
  slots: (PlayerSummary | null)[];
  slotTypes?: SlotTypeKey[];  // NEW — backwards compatible with old saves
  savedAt: number;
}

function saveTeamToStorage(slots: (PlayerSummary | null)[], slotTypes: SlotTypeKey[]) {
  try {
    const data: SavedTeam = { slots, slotTypes, savedAt: Date.now() };
    localStorage.setItem(LOCALSTORAGE_KEY, JSON.stringify(data));
  } catch { /* ignore */ }
}
```

Update the `useEffect` that calls `saveTeamToStorage` to also pass `slotTypes`.

#### Step 4 — Update PlayerSlot component

Add `slotType` and `onSlotTypeChange` props:

```tsx
interface PlayerSlotProps {
  index: number;
  slotLabel: string;      // derived from slotType
  slotIcon: string;       // derived from slotType
  player: PlayerSummary | null;
  onSelect: (p: PlayerSummary) => void;
  onRemove: () => void;
  excludeIds: string[];
  onLabelClick: () => void;  // NEW: cycle the slot type on click
}
```

In the label area of `PlayerSlot`, make it clickable:

```tsx
<button
  onClick={onLabelClick}
  className="text-xs text-text-muted hover:text-primary transition-colors cursor-pointer select-none"
  title="Click to change slot role"
>
  {slotIcon} {slotLabel}
</button>
```

#### Step 5 — Wire it up in the main component

In the `slots.map(...)` JSX:

```tsx
{slots.map((player, i) => {
  const typeOption = SLOT_TYPE_OPTIONS.find((t) => t.key === slotTypes[i])
    ?? SLOT_TYPE_OPTIONS[0];
  return (
    <PlayerSlot
      key={i}
      index={i}
      slotLabel={typeOption.label}
      slotIcon={typeOption.icon}
      player={player}
      onSelect={(p) => handleAddPlayer(i, p)}
      onRemove={() => handleRemovePlayer(i)}
      excludeIds={excludeIds}
      onLabelClick={() => {
        setSlotTypes((prev) => {
          const next = [...prev];
          const curIdx = SLOT_TYPE_OPTIONS.findIndex((t) => t.key === next[i]);
          next[i] = SLOT_TYPE_OPTIONS[(curIdx + 1) % SLOT_TYPE_OPTIONS.length].key;
          return next;
        });
      }}
    />
  );
})}
```

#### Step 6 — Include slot types in shared URL

Encode slot types as a compact `types` query parameter:

```tsx
const TYPE_SHORT_CODES: Record<SlotTypeKey, string> = {
  opener: "o", top_order: "t", middle_order: "m",
  finisher_wk: "f", allrounder: "a", bowler: "b",
};
const SHORT_CODE_TO_TYPE: Record<string, SlotTypeKey> = Object.fromEntries(
  Object.entries(TYPE_SHORT_CODES).map(([k, v]) => [v, k as SlotTypeKey])
);

// In handleShare:
url.searchParams.set("types", slotTypes.map((t) => TYPE_SHORT_CODES[t]).join(""));

// In URL loading effect, decode:
const typesParam = searchParams.get("types");
if (typesParam) {
  const decoded = [...typesParam].map((c) => SHORT_CODE_TO_TYPE[c] ?? "bowler");
  // pad to MAX_PLAYERS
  while (decoded.length < MAX_PLAYERS) decoded.push(DEFAULT_SLOT_TYPES[decoded.length] ?? "bowler");
  setSlotTypes(decoded.slice(0, MAX_PLAYERS));
}
```

### Testing

- Default state: verify all 11 slots show the original default labels.
- Click the "Middle Order" label on slot 5 → it cycles to "Finisher / WK". Click again → "All-rounder". Keep cycling → wraps back to "Opener".
- Verify localStorage persists the slot types across page reload.
- Share URL → open in new tab → verify slot types are restored correctly.
- Verify the `handleClearAll` function also resets slot types to defaults.

---

## 5. Change 4 — Preserve Batting Order in Shared URLs

### Problem

When a user builds a team in a specific batting order and shares the URL, the recipient sees the players rearranged. Player 1 (the user's chosen opener) might appear at position 3 or 7 on the recipient's page. The batting order — which is the whole point of a team builder — is not preserved.

### Root Cause

**File:** `gui/frontend/src/pages/TeamBuilder.tsx` (~L700–775)

The URL loading uses `Promise.all(ids.map(...))` which **does** preserve the original order of promises. The actual issue is more subtle: the URL only stores `?ids=id1,id2,...` as a flat comma-separated list, but when loading, the code fills slots *contiguously starting from index 0*. If the user had players at specific slot positions (e.g., slot 0, slot 3, slot 7), the URL doesn't encode the slot positions — just the player IDs. So a team with a bowler at slot 1 and a batter at slot 2 could get swapped if the analysis endpoint reclassifies them.

Additionally, the analysis panel's "Selected Players" section groups players into "Batters" and "Bowlers", which visually reorders them away from the user's batting order.

### Solution

1. The URL already preserves the order of IDs (comma-separated = positional). The `Promise.all` approach already respects order. Verify this is working correctly.
2. The main fix: the URL should encode **which slot** each player occupies. Currently players are loaded into contiguous slots (0, 1, 2, ...) regardless of where they were originally placed.
3. In the "Selected Players" section, show players in **slot order** (1–11), not grouped by batting/bowling role.

### Implementation Steps

**File:** `gui/frontend/src/pages/TeamBuilder.tsx`

#### Step 1 — Verify Promise.all order preservation

The existing code already uses `Promise.all` which preserves order. The `results` array comes back in the same order as `ids`. The code iterates `results` and fills `newSlots[slotIdx++]`. This *does* preserve order if all succeed. Confirm there's no issue by adding an explicit positional fill:

```tsx
// Current code (correct — Promise.all preserves order):
const newSlots: (PlayerSummary | null)[] = Array(MAX_PLAYERS).fill(null);
for (let i = 0; i < results.length; i++) {
  if (results[i] && i < MAX_PLAYERS) {
    newSlots[i] = results[i];  // Use `i` directly, not `slotIdx++`
  }
}
```

The current code uses `slotIdx++` which skips failed fetches but still preserves relative order. If you want failed fetches to leave a gap (preserving the exact position), change to using `i` directly.

#### Step 2 — Show players in slot order in the analysis summary

Replace the current "Selected Players" section that groups by batters/bowlers with a single ordered list:

```tsx
{/* Player list summary — in batting order */}
{analysis && playerCount > 0 && (
  <div className="card p-4 mt-4 space-y-3">
    <h3 className="text-xs text-text-muted uppercase tracking-wider">
      Selected Players
    </h3>
    <div className="space-y-0.5">
      {slots.map((player, i) => {
        if (!player) return null;
        return (
          <div key={player.id} className="flex items-center justify-between text-xs py-0.5">
            <span className="text-text-muted w-5">{i + 1}</span>
            <span className="text-text-primary truncate flex-1 ml-1">
              {countryFlag(player.country)} {player.name}
            </span>
            <div className="flex items-center gap-2">
              <span className="text-text-muted">{player.archetype}</span>
              <GradeBadge grade={player.grade_overall} size="xs" />
            </div>
          </div>
        );
      })}
    </div>

    {/* Still show batting/bowling grouping below, but secondary */}
    {analysis.batters.length > 0 && (
      <div className="pt-2 border-t border-border/30">
        <span className="text-xs font-medium text-text-secondary">
          🏏 Batters ({analysis.batters.length})
        </span>
        {/* ...existing batter list... */}
      </div>
    )}
    {analysis.bowlers.length > 0 && (
      <div>
        <span className="text-xs font-medium text-text-secondary">
          🎳 Bowlers ({analysis.bowlers.length})
        </span>
        {/* ...existing bowler list... */}
      </div>
    )}
  </div>
)}
```

### Testing

- Build a team in a specific order: opener, opener, #3 batter, #4 batter, etc.
- Click "Share Team" → copy URL → open in a new incognito window.
- Verify the players appear in the exact same slot positions.
- Verify the "Selected Players" section shows them numbered 1–11 in the user's chosen order.

---

## 6. Change 5 — Exclude Tail-Enders from Batting Aggregates

### Problem

In the Team Builder's Team Analysis, **every player who has a `bat_careers` entry is included in the batting average calculations**. This means Arshdeep Singh (a #10/11 tail-ender with a career batting average of ~5 and scores of ACC: 22, POW: 30, CON: 10) drags down the team's batting acceleration, power, and control averages. In reality, players like Arshdeep would never be expected to bat — their batting stats are noise, not signal.

The "Batting Strength (11 Batters)" heading is also misleading — a team doesn't have 11 batters.

### Root Cause

Same pattern as Change 2 but for the batting side. The `analyse_team()` endpoint in `gui/backend/routers/team.py` adds *every* player found in `bat_careers` to `bat_rows`, with no quality filter.

### Solution

Mirror the bowling solution: use a **"genuine batter" heuristic**. A player is a genuine batter if:
- They have at least 10 batting innings, AND
- Their batting innings represent at least 40% of their bowling matches (i.e., they bat more than they purely bowl)
  — OR they have no significant bowling career (< 5 bowling matches, so they're a pure batter)
- Alternatively, a simpler and more robust heuristic: **exclude any player whose `overall_score` (batting composite) is below 20**. If a player's batting composite is below 20, they are effectively a tail-ender and should not count toward batting averages.

The simpler composite threshold approach is recommended because it directly captures "does this player contribute meaningfully with the bat?" regardless of role classification.

### Implementation Steps

**File:** `gui/backend/routers/team.py`

#### Step 1 — Add genuine-batter helper

```python
def _is_genuine_batter(bat_row: dict, store) -> bool:
    """Determine if a player contributes meaningfully with the bat.

    A player is a genuine batter if:
    1. They have at least 10 batting innings, AND
    2. Their batting composite score is >= 20 (above tail-ender level)

    This excludes #10/11 tail-enders whose batting stats are noise.
    """
    innings = float(bat_row.get("innings_count", 0) or 0)
    if innings < 10:
        return False

    composite = bat_row.get("overall_score") or bat_row.get("composite_batting")
    if composite is not None:
        try:
            if float(composite) < 20:
                return False
        except (TypeError, ValueError):
            pass

    return True
```

#### Step 2 — Filter batting rows in `analyse_team()`

In the player lookup loop, only add to `bat_rows` if genuine batter:

```python
if not store.bat_careers.empty and "batter_id" in store.bat_careers.columns:
    mask = store.bat_careers["batter_id"] == pid
    matches = store.bat_careers.loc[mask]
    if not matches.empty:
        row = matches.iloc[0]
        row_dict = row.to_dict()
        batter_summaries.append(_row_to_player_summary(row_dict, "bat"))
        if _is_genuine_batter(row_dict, store):
            bat_rows.append(row_dict)  # Only genuine batters affect averages
        found = True
```

Note: we still add the player to `batter_summaries` (for display in the "Selected Players" list) — we just don't include them in the `bat_rows` list used for computing batting averages.

#### Step 3 — Update the batting weakness detection similarly

In `_detect_weaknesses()`, use the full `bat_careers` filtered to genuine batters for percentile computation:

```python
# Filter to genuine batters for percentile computation
genuine_batters_mask = store.bat_careers.apply(
    lambda row: _is_genuine_batter(row.to_dict(), store), axis=1
)
genuine_batters = store.bat_careers.loc[genuine_batters_mask]
```

#### Step 4 — Update the batter count display

The frontend currently shows "Batting Strength (11 Batters)". This count should reflect only the genuine batters used for the average. Add a new field to the `TeamAnalysis` response:

**File:** `gui/backend/schemas.py` — add to TeamAnalysis:
```python
genuine_batter_count: int = 0
genuine_bowler_count: int = 0
```

**File:** `gui/backend/routers/team.py` — populate:
```python
return TeamAnalysis(
    # ...existing fields...
    genuine_batter_count=len(bat_rows),    # Only genuine batters
    genuine_bowler_count=len(bowl_rows),    # Only genuine bowlers
)
```

**File:** `gui/frontend/src/api/types.ts` — add:
```tsx
genuine_batter_count?: number;
genuine_bowler_count?: number;
```

**File:** `gui/frontend/src/pages/TeamBuilder.tsx` — update the heading:
```tsx
<h3 className="text-xs text-text-muted uppercase tracking-wider mb-2">
  Batting Strength ({analysis.genuine_batter_count ?? analysis.batters.length} batters)
</h3>
```

### Testing

- Build a team with Arshdeep Singh (tail-ender) and 5 strong batters. Verify Arshdeep does NOT drag down the batting averages. The heading should say "Batting Strength (5 batters)".
- Verify Arshdeep still appears in the "Selected Players" list but is just not counted in the batting average computation.
- Verify the batting radar chart reflects only genuine batters' scores.

---

## 7. Change 6 — Hover Tooltips on Compare Page Advanced Stats

### Problem

The Compare page shows advanced metrics like "Acceleration", "Power", "Control", "WAR", "Clutch Index", "Chase Master", "Peak Composite", "Avg Dominance" in the stat comparison table. New users have no idea what these mean. There's no hover tooltip or explanation.

### Existing Infrastructure

The codebase already has a comprehensive `MetricTooltip` component at `gui/frontend/src/components/MetricTooltip.tsx` with definitions for all major metrics (acceleration, power, control, war_batting, clutch_index, chase_master_index, flat_track_index, etc.). It's currently used on the Player Profile page but NOT on the Compare page.

### Solution

Wrap each metric label in the Compare page's `StatTable` with the existing `MetricLabel` component from `MetricTooltip.tsx`.

### Implementation Steps

**File:** `gui/frontend/src/pages/Compare.tsx`

#### Step 1 — Import MetricLabel

Add to the imports at the top:

```tsx
import { MetricLabel } from "@/components/MetricTooltip";
```

#### Step 2 — Add metricKey to StatRow interface

The existing `StatRow` interface:
```tsx
interface StatRow {
  label: string;
  values: (string | number | null)[];
  rawValues: (number | null)[];
  higherIsBetter: boolean;
  isGrade?: boolean;
}
```

Add an optional `metricKey`:
```tsx
interface StatRow {
  label: string;
  metricKey?: string;   // NEW: key into METRIC_DEFINITIONS for tooltip
  values: (string | number | null)[];
  rawValues: (number | null)[];
  higherIsBetter: boolean;
  isGrade?: boolean;
}
```

#### Step 3 — Add metricKey to buildBatterStatRows and buildBowlerStatRows

For each row in `buildBatterStatRows`, add the corresponding `metricKey`:

```tsx
{ label: "Acceleration", metricKey: "acceleration", values: ..., ... },
{ label: "Power", metricKey: "power", values: ..., ... },
{ label: "Control", metricKey: "control", values: ..., ... },
{ label: "WAR", metricKey: "war_batting", values: ..., ... },
{ label: "Clutch Index", metricKey: "clutch_index", values: ..., ... },
{ label: "Chase Master", metricKey: "chase_master_index", values: ..., ... },
{ label: "Peak Composite", metricKey: "overall_score", values: ..., ... },
{ label: "Avg Dominance", metricKey: "dominance_index", values: ..., ... },
```

Same for `buildBowlerStatRows`.

#### Step 4 — Use MetricLabel in StatTable rendering

In the `StatTable` component, where it renders each row's label:

```tsx
// Current:
<td className="...">{row.label}</td>

// New:
<td className="...">
  {row.metricKey ? (
    <MetricLabel metricKey={row.metricKey} label={row.label} />
  ) : (
    row.label
  )}
</td>
```

The `MetricLabel` component renders the label text with a small info icon; on hover, it shows a tooltip with the metric's description, interpretation, range, and high/low meanings.

### Testing

- Navigate to the Compare page with two batters (e.g., V Kohli and SPD Smith).
- Hover over "Acceleration" in the stat table → a tooltip should appear explaining what Acceleration is.
- Hover over "WAR" → tooltip should explain Wins Above Replacement.
- Hover over "Chase Master" → tooltip should explain the Chase Master Index.
- Verify tooltips don't obscure the stat values.
- Verify bowler comparison also has tooltips.

---

## 8. Change 7 — Era Timeline: Add Avg Run Rate & Predicted Score

### Problem

The Eras page currently shows three metrics over time: Par Strike Rate, Boundary Rate %, and Dot Ball %. Users want to also see:
- **Average Run Rate** (runs per over for the era)
- **Predicted Score** (projected 20-over total based on the era's run rate)

These are more intuitive measures of how the game has evolved.

### Solution

Add two new computed metrics to the era baseline data:
1. `avg_run_rate` = `par_sr / 100 * 6` (converting strike rate to runs per over)
2. `predicted_score` = `avg_run_rate * 20` (20-over projected total)

These can be computed **on the frontend** from the existing `par_sr` data without backend changes. Alternatively, compute them on the backend for cleanliness.

### Implementation Steps

#### Option A — Frontend-only (simpler, recommended)

**File:** `gui/frontend/src/pages/Eras.tsx`

1. Add new metric configs to `METRIC_CONFIGS`:

```tsx
const METRIC_CONFIGS: MetricConfig[] = [
  // ...existing three metrics...
  {
    key: "avg_rr",
    label: "Avg Run Rate",
    colour: "#8B5CF6",   // Purple
    yAxisId: "left",
    unit: " RPO",
    formatter: (v) => (v != null ? v.toFixed(2) + " RPO" : "—"),
  },
  {
    key: "predicted_score",
    label: "Predicted Score",
    colour: "#EC4899",   // Pink
    yAxisId: "left",
    unit: "",
    formatter: (v) => (v != null ? Math.round(v).toString() : "—"),
  },
];
```

2. Update `ChartMetric` type:

```tsx
type ChartMetric = "par_sr" | "boundary_rate" | "dot_pct" | "multiplier" | "avg_rr" | "predicted_score";
```

3. In the `chartData` computation, derive the new fields from `par_sr`:

```tsx
const chartData = useMemo(() => {
  if (!baselines) return [];
  return baselines.map((b) => ({
    year: b.year,
    par_sr: b.par_sr,
    boundary_rate: b.boundary_rate,
    dot_pct: b.dot_pct,
    multiplier: b.multiplier,
    avg_rr: b.par_sr != null ? Number((b.par_sr / 100 * 6).toFixed(2)) : null,
    predicted_score: b.par_sr != null ? Math.round(b.par_sr / 100 * 6 * 20) : null,
  }));
}, [baselines]);
```

4. The metric toggle buttons and chart lines will automatically work because they iterate over `METRIC_CONFIGS` and the `activeMetrics` set. Add the new metric keys as initially inactive:

```tsx
const [activeMetrics, setActiveMetrics] = useState<Set<ChartMetric>>(
  new Set(["par_sr", "boundary_rate", "dot_pct"]),
);
```

Users can toggle "Avg Run Rate" and "Predicted Score" on/off via the existing buttons.

5. Add the new `<Line>` components in the chart JSX — the existing code likely already iterates `METRIC_CONFIGS` and conditionally renders lines based on `activeMetrics`, so no extra JSX changes needed if that pattern is followed.

#### Option B — Backend (if you want the data to be canonical)

**File:** `gui/backend/routers/eras.py` — in `_compute_era_baselines()`:

```python
# After computing par_sr for each year:
if entry.get("par_sr") is not None:
    entry["avg_rr"] = round(entry["par_sr"] / 100 * 6, 2)
    entry["predicted_score"] = round(entry["avg_rr"] * 20, 0)
else:
    entry["avg_rr"] = None
    entry["predicted_score"] = None
```

Update the Pydantic model `EraBaseline` in `gui/backend/schemas.py`:
```python
class EraBaseline(BaseModel):
    year: int
    par_sr: float | None
    boundary_rate: float | None
    dot_pct: float | None
    multiplier: float | None
    avg_rr: float | None = None         # NEW
    predicted_score: float | None = None  # NEW
```

And the TypeScript type in `gui/frontend/src/api/types.ts`:
```tsx
export interface EraBaseline {
  year: number;
  par_sr: number | null;
  boundary_rate: number | null;
  dot_pct: number | null;
  multiplier: number | null;
  avg_rr?: number | null;
  predicted_score?: number | null;
}
```

### Stat Card Updates

The Eras page has summary stat cards at the top ("YEARS COVERED", "LATEST PAR SR", "SR GROWTH", "MAX ERA MULTIPLIER"). Add or modify:

- **Latest Avg RR**: Computed from latest par_sr.
- **Latest Predicted Score**: Computed from latest par_sr.

### Testing

- Load the Eras page. Verify par_sr, boundary_rate, dot_pct still display correctly.
- Click the "Avg Run Rate" toggle → a purple line appears showing RPO over time.
- Click the "Predicted Score" toggle → a pink line appears showing projected totals.
- Hover on the chart → tooltip shows all active metrics for that year.
- Verify the new lines make sense (e.g., if par_sr = 130 in 2024, avg_rr ≈ 7.8, predicted_score ≈ 156).

---

## 9. Change 8 — Compare Page: Show Predominant Role

### Problem

The Compare page currently shows players **only as bowlers** when comparing two bowlers (e.g., JJ Bumrah vs PJ Cummins). But it doesn't intelligently handle mixed comparisons or players who are strong in both roles. If you compare two all-rounders, it should show both their batting and bowling profiles. If you compare a batter vs a bowler, it should show each in their predominant role.

The current logic is:
```tsx
const radarAxes = useMemo(() => {
  if (hasBatters && !hasBowlers) return BATTER_RADAR_AXES;
  if (hasBowlers && !hasBatters) return BOWLER_RADAR_AXES;
  return BATTER_RADAR_AXES; // Mixed — defaults to batting
}, [hasBatters, hasBowlers]);
```

This means if both players have batting records, it always shows batting — even if they're both primarily bowlers. It also only ever shows ONE radar, not both.

### Solution

1. Determine each player's **predominant role** using the same bowling-to-batting ratio heuristic from Change 2.
2. If all compared players are predominantly batters → show batting comparison.
3. If all are predominantly bowlers → show bowling comparison.
4. If mixed → show **both** comparisons (batting radar + table AND bowling radar + table), with the predominant one first.
5. Alternatively, add a simple toggle at the top: "Compare as: Batters | Bowlers" so the user can switch.

### Implementation Steps

**File:** `gui/frontend/src/pages/Compare.tsx`

#### Step 1 — Add a role toggle

```tsx
const [viewMode, setViewMode] = useState<"auto" | "bat" | "bowl">("auto");
```

Add toggle buttons near the top of the comparison section:

```tsx
<div className="flex items-center gap-2">
  <span className="text-xs text-text-muted">Compare as:</span>
  {["auto", "bat", "bowl"].map((mode) => (
    <button
      key={mode}
      onClick={() => setViewMode(mode as typeof viewMode)}
      className={`btn-sm text-xs ${viewMode === mode ? "btn-primary" : "btn-ghost"}`}
    >
      {mode === "auto" ? "Auto" : mode === "bat" ? "🏏 Batters" : "🎳 Bowlers"}
    </button>
  ))}
</div>
```

#### Step 2 — Determine the effective view mode

```tsx
const effectiveView = useMemo(() => {
  if (viewMode !== "auto") return viewMode;

  // Auto: determine based on predominant roles
  // If more profiles are batters → show batting; if more are bowlers → show bowling
  if (hasBatters && !hasBowlers) return "bat";
  if (hasBowlers && !hasBatters) return "bowl";

  // Mixed: default to the role where more players have data
  return batters.length >= bowlers.length ? "bat" : "bowl";
}, [viewMode, hasBatters, hasBowlers, batters.length, bowlers.length]);
```

#### Step 3 — Use effectiveView throughout

Replace all instances where the code checks `hasBatters`/`hasBowlers` to decide which table/radar to show with `effectiveView`:

```tsx
const radarAxes = effectiveView === "bat" ? BATTER_RADAR_AXES : BOWLER_RADAR_AXES;

// For stat rows:
const statRows = effectiveView === "bat"
  ? buildBatterStatRows(batters)
  : buildBowlerStatRows(bowlers);
```

#### Step 4 — Backend: return both roles for each player

**File:** `gui/backend/routers/compare.py`

Currently `_parse_ids` classifies each player as either a batter or bowler. Modify it to check both tables and return the player in whichever table(s) they exist:

- If the player exists in both `bat_careers` and `bowl_careers`, include them in both `batters` and `bowlers` lists in the response.
- The frontend can then use `effectiveView` to decide which profile to display.

### Testing

- Compare JJ Bumrah vs PJ Cummins. Default ("Auto") should show bowling comparison since both are primarily bowlers.
- Click "🏏 Batters" → should show their (minimal) batting stats.
- Compare V Kohli vs JJ Bumrah. "Auto" should show batting (since Kohli is primarily a batter). Click "🎳 Bowlers" to see Bumrah's bowling vs Kohli's negligible bowling.
- Compare two all-rounders → "Auto" should pick the dominant role.

---

## 10. Change 9 — IPL Dataset Support & Format Toggle

### Problem

The app currently only supports T20 International data. There's now an `ipl_json/` directory with 1,170 IPL match JSON files. Users want to toggle between "T20I" and "IPL" at the top of each page.

### Solution

This is the **largest change** in this version. It requires:
1. Running the pipeline separately on IPL data to produce a separate output directory.
2. Loading both datasets into the backend.
3. Adding a format toggle to the frontend that switches all API calls between datasets.

### Implementation Steps

#### Phase 1 — Pipeline: Process IPL Data Separately

**File:** `src/main.py`

The pipeline's `main()` function currently reads from `t20s_male_json/`. Add a CLI argument or config option to specify the input directory and output directory:

```python
import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default="t20s_male_json", help="Directory of Cricsheet JSON files")
    parser.add_argument("--output-dir", default="output", help="Output directory for Parquet files")
    parser.add_argument("--format", default="t20i", choices=["t20i", "ipl"], help="Data format label")
    args = parser.parse_args()
    # ... use args.input_dir and args.output_dir throughout ...
```

Run the pipeline twice:
```bash
python -m src.main --input-dir t20s_male_json --output-dir output_t20i --format t20i
python -m src.main --input-dir ipl_json --output-dir output_ipl --format ipl
```

This produces `output_t20i/` and `output_ipl/` with identical file structures.

#### Phase 2 — Backend: Load Both Datasets

**File:** `gui/backend/data_loader.py`

Add a second `DataStore` instance for IPL:

```python
@dataclass
class MultiDataStore:
    t20i: DataStore = field(default_factory=DataStore)
    ipl: DataStore = field(default_factory=DataStore)

def load_all_data() -> MultiDataStore:
    store = MultiDataStore()
    store.t20i = load_data(Path("../../output_t20i"))
    store.ipl = load_data(Path("../../output_ipl"))
    return store
```

**File:** `gui/backend/app.py`

Replace the single `_store` with `_multi_store: MultiDataStore`. Update the dependency provider to accept a `format` query parameter:

```python
from fastapi import Query as FastAPIQuery

def get_store(format: str = FastAPIQuery("t20i", regex="^(t20i|ipl)$")) -> DataStore:
    if format == "ipl":
        return _multi_store.ipl
    return _multi_store.t20i
```

Since all routers use `Depends(_get_store)`, they automatically switch datasets based on the `?format=` query param. Every API call will need to include `?format=t20i` or `?format=ipl`.

#### Phase 3 — Frontend: Format Toggle

**File:** `gui/frontend/src/api/client.ts`

Add a global format state that all API calls include:

```tsx
// Create a simple reactive store for the current format
let currentFormat: "t20i" | "ipl" = "t20i";

export function setFormat(f: "t20i" | "ipl") {
  currentFormat = f;
}

export function getFormat(): "t20i" | "ipl" {
  return currentFormat;
}

// In the API client, automatically append ?format= to all requests:
const api = {
  async get<T>(url: string, params?: Record<string, any>): Promise<T> {
    const response = await fetch(`${BASE_URL}${url}?${new URLSearchParams({
      ...params,
      format: currentFormat,
    })}`);
    return response.json();
  },
};
```

Alternatively, use React Context for the format state:

**File:** `gui/frontend/src/api/FormatContext.tsx` (NEW)

```tsx
import { createContext, useContext, useState, ReactNode } from "react";

type Format = "t20i" | "ipl";

const FormatContext = createContext<{
  format: Format;
  setFormat: (f: Format) => void;
}>({ format: "t20i", setFormat: () => {} });

export function FormatProvider({ children }: { children: ReactNode }) {
  const [format, setFormat] = useState<Format>("t20i");
  return (
    <FormatContext.Provider value={{ format, setFormat }}>
      {children}
    </FormatContext.Provider>
  );
}

export function useFormat() {
  return useContext(FormatContext);
}
```

**File:** `gui/frontend/src/api/queries.ts`

Every TanStack Query hook must include `format` in its query key and pass it as a param:

```tsx
export function usePlayer(id: string) {
  const { format } = useFormat();
  return useQuery({
    queryKey: ["player", id, format],
    queryFn: () => api.getPlayer(id, format),
  });
}
```

**File:** `gui/frontend/src/components/Layout.tsx`

Add a format toggle in the navigation bar:

```tsx
import { useFormat } from "@/api/FormatContext";

function FormatToggle() {
  const { format, setFormat } = useFormat();
  return (
    <div className="flex items-center bg-surface-elevated rounded-lg p-0.5">
      <button
        onClick={() => setFormat("t20i")}
        className={`px-3 py-1 text-xs rounded-md transition-colors ${
          format === "t20i"
            ? "bg-primary text-white"
            : "text-text-muted hover:text-text-secondary"
        }`}
      >
        🌏 T20I
      </button>
      <button
        onClick={() => setFormat("ipl")}
        className={`px-3 py-1 text-xs rounded-md transition-colors ${
          format === "ipl"
            ? "bg-primary text-white"
            : "text-text-muted hover:text-text-secondary"
        }`}
      >
        🏆 IPL
      </button>
    </div>
  );
}
```

**File:** `gui/frontend/src/App.tsx`

Wrap the router with `FormatProvider`:

```tsx
export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <FormatProvider>
        <RouterProvider router={router} />
      </FormatProvider>
    </QueryClientProvider>
  );
}
```

### IPL-Specific Considerations

- IPL uses **4 overs per bowler** max (same as T20I), so bowling metrics translate directly.
- Player IDs in Cricsheet are the same across formats (they use player registry IDs), so the same player (e.g., V Kohli) will have the same ID in both datasets. This is convenient.
- IPL has **franchise teams** while T20I has **national teams**. The `country` field in IPL data will be the player's nationality, not their franchise. You may want to add a `team`/`franchise` field for IPL.
- Config settings (weights, thresholds) should be the same for both formats initially. If IPL-specific tuning is needed later, add a config section per format.

### Testing

- Run pipeline on IPL data. Verify `output_ipl/` has all expected Parquet files.
- Start the backend. Verify `/api/health` returns ok.
- Load the frontend. The default should be T20I. Click "IPL" → all data should refresh.
- Verify player counts differ between T20I and IPL.
- Verify a player like V Kohli shows different stats in T20I vs IPL.
- Toggle back to T20I → data should revert.

---

## 11. Change 10 — Multiple Archetypes (Top 3)

### Problem

Each player currently gets exactly one archetype (first-match-wins from the rule list in `src/presentation.py`). But many players fit multiple archetypes. For example, a player with ACC=88, POW=90, CTL=75 would match "Explosive Finisher" first, but they also fit "Aggressive Opener" and "All-Round Elite". Showing only one archetype loses information.

### Solution

Instead of stopping at the first matching archetype, evaluate ALL archetypes and assign the **top 3** that match. Store them as a comma-separated string or a JSON array in the Parquet output.

### Implementation Steps

#### Backend Pipeline

**File:** `src/presentation.py`

1. Modify the archetype assignment function. Currently there's a function like `_assign_archetype(row, archetypes)` that returns the first match. Change it to return up to 3 matches:

```python
def _match_archetypes(row: pd.Series, archetypes: list[tuple[str, dict[str, float]]], top_n: int = 3) -> list[str]:
    """Return up to top_n matching archetypes for a player.

    Each archetype has conditions like {"acceleration": 85, "power": 85}.
    A condition "foo": X means score_foo >= X.
    A condition "foo_max": X means score_foo <= X.
    """
    matched = []
    for name, conditions in archetypes:
        if _matches_conditions(row, conditions):
            matched.append(name)
            if len(matched) >= top_n:
                break
    if not matched:
        matched.append("Utility Player")
    return matched
```

2. Update `assign_batting_archetypes` and `assign_bowling_archetypes`:

```python
def assign_batting_archetypes(bat_careers: pd.DataFrame) -> pd.DataFrame:
    df = bat_careers.copy()
    # Primary archetype (first match) — kept for backward compatibility
    df["archetype"] = df.apply(
        lambda row: _match_archetypes(row, BATTING_ARCHETYPES, top_n=1)[0], axis=1
    )
    # All matching archetypes (top 3)
    df["archetypes"] = df.apply(
        lambda row: ", ".join(_match_archetypes(row, BATTING_ARCHETYPES, top_n=3)), axis=1
    )
    return df
```

Same for bowling.

#### Backend API

**File:** `gui/backend/routers/player.py`

When building the player profile response, include `archetypes` as a list:

```python
"archetypes": row.get("archetypes", row.get("archetype", "Utility Player")).split(", "),
```

#### Frontend

**File:** `gui/frontend/src/api/types.ts`

Add to both `BatterProfile` and `BowlerProfile`:
```tsx
archetypes?: string[];  // Top 3 matching archetypes
```

**File:** `gui/frontend/src/pages/PlayerProfile.tsx`

Display all archetypes:
```tsx
<div className="flex flex-wrap gap-1.5">
  {(profile.archetypes ?? [profile.archetype]).map((arch, i) => (
    <ArchetypeBadge key={arch} archetype={arch} isPrimary={i === 0} />
  ))}
</div>
```

**File:** `gui/frontend/src/components/ArchetypeBadge.tsx`

Add an `isPrimary` prop to visually distinguish the primary archetype (bolder/larger) from secondary ones (smaller/dimmer):

```tsx
function ArchetypeBadge({ archetype, isPrimary = true }: { archetype: string; isPrimary?: boolean }) {
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-xs ${
      isPrimary
        ? "bg-primary/20 text-primary font-medium"
        : "bg-surface-elevated text-text-muted"
    }`}>
      {archetype}
    </span>
  );
}
```

### Testing

- Run the pipeline. Verify the `archetypes` column in `batting_careers_full.parquet` contains comma-separated lists.
- Check a player like SA Yadav: should have "Explosive Finisher, Aggressive Opener, All-Round Elite" or similar.
- On the Player Profile page, verify all 3 archetypes are displayed with the primary one visually emphasized.
- Verify the Compare page shows the primary archetype (first one) in the stat table.

---

## 12. Change 11 — Rating Rebalance: Reduce Explosive Finisher Skew

### Problem

The current rating system over-rewards Explosive Finishers. The reason:
- The "superstar bonus" in `_compute_overall_score()` gives extra credit when any dimension is ≥ 85. Explosive Finishers tend to have acceleration AND power both ≥ 85, so they get a double superstar bonus.
- The acceleration and power weights reward high strike rates and boundary percentages, which naturally favor middle/lower-order batters who bat with freedom and low accountability. An opener who bats through and scores 45(38) in a successful chase is less rewarded than a #6 who smashes 25(10).
- The control dimension (which rewards anchors and accumulators) has lower variance in the population, so even a high control score doesn't compete with extreme acceleration+power scores.

### Solution

A multi-pronged rebalance:

1. **Cap the superstar bonus per player** — instead of summing (score - 85) for ALL dimensions above 85, cap the bonus at the single best dimension's excess. This prevents double/triple bonuses.

2. **Introduce a "responsibility multiplier"** for the control dimension — batters who bat more balls per innings should get a boost to their control score, reflecting the value of occupying the crease and building an innings.

3. **Adjust the overall score formula to use a geometric-mean-like combination** — this naturally penalises one-dimensional players more than the arithmetic mean + bonus approach.

4. **Increase weight of the `avg_proxy` component in control** — this rewards players who consistently score runs, not just rotate strike.

### Implementation Steps

#### Step 1 — Cap superstar bonus

**File:** `src/presentation.py` — `_compute_overall_score()`

Change:
```python
bonus = sum(max(s - superstar_threshold, 0.0) for s in valid)
```
To:
```python
# Cap bonus at the single best dimension's excess (no double/triple bonus)
individual_bonuses = [max(s - superstar_threshold, 0.0) for s in valid]
bonus = max(individual_bonuses) if individual_bonuses else 0.0
```

This means a player with ACC=95, POW=95, CTL=70 gets bonus = max(10, 10, 0) = 10, not 20.

#### Step 2 — Adjust the superstar bonus weight

Consider reducing `superstar_bonus_weight` from 0.15 to 0.10:

```python
def _compute_overall_score(
    scores: list[float],
    *,
    superstar_threshold: float = 85.0,
    superstar_bonus_weight: float = 0.10,  # Reduced from 0.15
) -> float:
```

#### Step 3 — Add a responsibility multiplier to control scoring

**File:** `src/batting.py` — in the control component computation

After computing raw control scores, apply a multiplier based on average balls faced per innings:

```python
# Responsibility multiplier: reward batters who face more balls
avg_balls = group["balls_faced"].mean()
if avg_balls >= 25:
    responsibility_mult = 1.0 + min((avg_balls - 25) / 50, 0.15)  # Up to 15% bonus
    raw_control *= responsibility_mult
```

This gives a 15% control boost to batters who average 75+ balls per innings (true anchors).

#### Step 4 — Increase `avg_proxy` weight in control

**File:** `config.yaml` — `batting_control_weights`

Current weights (summing to ~1.0):
```yaml
batting_control_weights:
  dot_pct_weighted: 0.15
  rotation: 0.15
  contribution: 0.15
  avg_proxy: 0.15
  dismissal_quality: 0.10
  scoring_consistency: 0.15
  survival_ratio: 0.15
```

Increase `avg_proxy` and `scoring_consistency`, decrease `dot_pct_weighted`:
```yaml
batting_control_weights:
  dot_pct_weighted: 0.10    # Reduced — dots are less valuable than scoring
  rotation: 0.12
  contribution: 0.15
  avg_proxy: 0.20            # Increased — batting average matters
  dismissal_quality: 0.10
  scoring_consistency: 0.18  # Increased — consistency matters
  survival_ratio: 0.15
```

### Impact Assessment

After these changes:
- Explosive Finishers will still be rated highly (they *are* valuable) but won't dominate the leaderboard.
- Classic Anchors and Accumulators will see a ratings boost (5–10 points on the overall score).
- The leaderboard should show a healthier mix of archetypes in the top 20.

### Testing

- Run pipeline before and after. Compare the top 20 batting leaderboard.
- Verify Explosive Finishers are still in the top tier (they should be) but that anchors/accumulators are also represented.
- Spot-check specific players:
  - V Kohli (control-focused): should see a ratings increase.
  - SA Yadav (explosive): should see a slight decrease but still high.
  - KL Rahul (anchor): should see an increase.
- Run the test suite (`pytest tests/`) and fix any test expectations that change.

---

## 13. Change 12 — Team vs Team Comparison

### Problem

The Team Builder lets you build a single XI and see its analysis. There's no way to compare two teams side-by-side to see which one is stronger in batting, bowling, and overall.

### Solution

Add a "Compare Teams" mode to the Team Builder page. The user can build two teams (Team A and Team B) and see a side-by-side comparison of their radar charts, aggregates, and weaknesses.

### Implementation Steps

#### Backend

**File:** `gui/backend/routers/team.py`

Add a new endpoint:

```python
@router.get("/team/compare", summary="Compare two teams")
async def compare_teams(
    team_a: str = Query(..., description="Comma-separated player IDs for Team A"),
    team_b: str = Query(..., description="Comma-separated player IDs for Team B"),
    store=Depends(_get_store),
):
    """Compare two team selections side-by-side."""
    # Reuse analyse_team logic for each team
    analysis_a = await analyse_team(ids=team_a, store=store)
    analysis_b = await analyse_team(ids=team_b, store=store)

    # Compute head-to-head matchup advantages if matchups data exists
    # (Optional: find shared matchup data between Team A batters and Team B bowlers)

    return {
        "team_a": analysis_a,
        "team_b": analysis_b,
        "comparison": {
            "batting_edge": "A" if (analysis_a.avg_acceleration or 0) + (analysis_a.avg_bat_power or 0) > (analysis_b.avg_acceleration or 0) + (analysis_b.avg_bat_power or 0) else "B",
            "bowling_edge": "A" if (analysis_a.avg_accuracy or 0) + (analysis_a.avg_threat or 0) > (analysis_b.avg_accuracy or 0) + (analysis_b.avg_threat or 0) else "B",
            "war_edge": "A" if ((analysis_a.total_war_batting or 0) + (analysis_a.total_war_bowling or 0)) > ((analysis_b.total_war_batting or 0) + (analysis_b.total_war_bowling or 0)) else "B",
        },
    }
```

#### Frontend

**File:** `gui/frontend/src/pages/TeamBuilder.tsx`

Add a "Compare" toggle that reveals a second set of 11 slots (Team B). When both teams have players, show a side-by-side layout:

```
┌─────────────────────────┐  ┌─────────────────────────┐
│       Team A (7/11)      │  │       Team B (8/11)      │
│  [slot1] [slot2] ...     │  │  [slot1] [slot2] ...     │
└─────────────────────────┘  └─────────────────────────┘
┌─────────────────────────────────────────────────────────┐
│                    Comparison Panel                       │
│  ┌──────────────┐  ┌──────────────┐                      │
│  │  Radar A      │  │  Radar B      │                    │
│  └──────────────┘  └──────────────┘                      │
│  Batting Edge: Team A (+5.2 avg ACC)                     │
│  Bowling Edge: Team B (+8.1 avg THR)                     │
│  WAR Edge: Team A (+3.2 total WAR)                       │
└─────────────────────────────────────────────────────────┘
```

Add state for the second team:
```tsx
const [isCompareMode, setIsCompareMode] = useState(false);
const [slotsB, setSlotsB] = useState<(PlayerSummary | null)[]>(
  () => Array(MAX_PLAYERS).fill(null)
);
```

Add a button to toggle compare mode:
```tsx
<button onClick={() => setIsCompareMode(!isCompareMode)} className="btn-secondary btn-sm">
  {isCompareMode ? "Single Team" : "⚔️ Compare Teams"}
</button>
```

### Testing

- Click "Compare Teams" → a second set of slots appears.
- Build both teams. The comparison panel should show side-by-side radars.
- Verify the "Batting Edge" / "Bowling Edge" / "WAR Edge" indicators are correct.
- Verify shared URL can encode both teams.

---

## 14. Change 13 — Chase Splits Tuning

### Problem

The Chase Splits section on the Player Profile page shows Setting vs Chasing splits but the data looks incomplete: "Innings" shows counts but "Avg", "SR", and "Composite" show dashes (—) for many players. The composite values are 0.0 or -0.0, suggesting the chase master calculation isn't working correctly.

### Root Cause

**File:** `src/clutch.py` — `compute_chase_splits` (or the chase master computation)

The chase split logic likely relies on columns like `innings_type` or `is_chasing` being present in the innings detail DataFrame. If the parser doesn't set these columns correctly (or at all), the splits can't be computed.

Additionally, the composite calculation for chase splits may use the same formula as the overall composite, which doesn't make sense for a small split — the z-scores are unstable with small samples.

### Investigation Steps

1. Check `src/parser.py` — verify that `innings_number` (1 = setting, 2 = chasing) is correctly parsed from the Cricsheet JSON and attached to each batter's innings.

2. Check `src/condition.py` — the `compute_batting_condition_dependence` function tags innings as bat-first vs chase. Verify the tagging logic is correct.

3. Check the chase master computation in the clutch module — verify it uses the correct column to split innings.

### Likely Fix

**File:** `src/clutch.py` or wherever `compute_chase_splits` lives

The function should:
1. Split batting innings into "setting" (innings_number == 1) and "chasing" (innings_number == 2).
2. For each split, compute the average SR, average batting average, and a composite score.
3. The composite should be a simple percentile or normalized value, NOT a z-score (which is unstable for small groups).

```python
def compute_chase_splits(bat_innings: pd.DataFrame) -> pd.DataFrame:
    """Compute batting-first vs chasing splits for each batter."""
    if bat_innings.empty:
        return pd.DataFrame()

    # Ensure innings_number exists
    if "innings_number" not in bat_innings.columns:
        return pd.DataFrame()

    results = []
    for batter_id, group in bat_innings.groupby("batter_id"):
        setting = group[group["innings_number"] == 1]
        chasing = group[group["innings_number"] == 2]

        for label, subset in [("Setting", setting), ("Chasing", chasing)]:
            if len(subset) == 0:
                continue

            runs = subset["runs"].sum() if "runs" in subset.columns else 0
            balls = subset["balls_faced"].sum() if "balls_faced" in subset.columns else 0
            outs = subset["out"].sum() if "out" in subset.columns else 0
            innings = len(subset)

            sr = (runs / balls * 100) if balls > 0 else None
            avg = (runs / outs) if outs > 0 else None

            # Simple composite: average of normalized SR and avg
            # Normalize: SR/130 * 50 + avg/30 * 50 (rough T20 benchmarks)
            composite = 0.0
            if sr is not None and avg is not None:
                sr_norm = min(sr / 130, 2.0) * 50  # SR=130 → 50 points
                avg_norm = min(avg / 30, 2.0) * 50  # avg=30 → 50 points
                composite = round((sr_norm + avg_norm) / 2, 1)
            elif sr is not None:
                composite = round(min(sr / 130, 2.0) * 50, 1)

            results.append({
                "batter_id": batter_id,
                "context": label,
                "innings": innings,
                "avg": round(avg, 1) if avg else None,
                "sr": round(sr, 1) if sr else None,
                "composite": composite,
            })

    return pd.DataFrame(results)
```

### Testing

- Run the pipeline. Check the chase splits in the output.
- On the Player Profile, verify the Chase Splits table shows meaningful numbers for SR, Avg, and Composite.
- Check a known good chaser (e.g., V Kohli) — their chasing composite should be higher than setting.
- Check a known poor chaser — their chasing composite should be lower.

---

## 15. Bonus Changes — Additional Improvements

These are not directly requested but would significantly improve the app based on the patterns observed in the screenshots and codebase:

### 15.1 — Drag-and-Drop Reordering in Team Builder

Allow users to drag players between slots to reorder the batting lineup. Use a library like `@dnd-kit/core` (already common in React).

**Files:** `gui/frontend/src/pages/TeamBuilder.tsx`, `package.json` (add dependency)

### 15.2 — Export Team as Image

Add a "Download as PNG" button on the Team Builder that captures the team + radar chart as a shareable image. Use `html-to-canvas` or a similar library.

### 15.3 — Player Search in Team Builder Should Filter by Slot Type

When a slot is labeled "Bowler", the autocomplete should prioritize bowlers. When labeled "Opener", prioritize batters with opener archetypes. This is a nice quality-of-life improvement.

**File:** `gui/frontend/src/pages/TeamBuilder.tsx` — pass the slot type to `PlayerAutocomplete` as a filter hint.

### 15.4 — Add a "Season" or "Year Range" Filter

Allow users to filter player data to a specific year range (e.g., "2020–2024 only"). This would require the backend to support a date-range filter on career data. Useful for comparing players in their current form vs. all-time.

### 15.5 — Mobile Responsive Improvements

The Team Builder and Compare pages are designed for desktop. On mobile, the 5-column grid collapses but the slots are still too wide. Consider a more compact mobile layout.

### 15.6 — Bowling Phase Group Labels on Radar

The team analysis radar uses generic "Bowl ACR" / "Bowl CTL" / "Bowl THR" labels. Consider adding phase-specific labels like "PP Bowl" / "Middle Bowl" / "Death Bowl" for a more nuanced radar.

### 15.7 — IPL Franchise Team Names

For the IPL dataset, add a mapping of player IDs to franchise names per season. This would allow franchise-based auto-fill in the Team Builder (e.g., "Best CSK XI 2024").

---

## 16. Implementation Order & Dependency Graph

### Priority Tiers

**Tier 1 — Quick Wins (< 1 day each, no pipeline changes):**
1. Change 1 — Form Tracker Y-Axis Fix (frontend only, 30 min)
2. Change 4 — Preserve Batting Order in Shared URLs (frontend only, 1 hr)
3. Change 6 — Hover Tooltips on Compare Page (frontend only, 1 hr)
4. Change 3 — Customisable Slot Positions (frontend only, 2 hr)

**Tier 2 — Backend Logic (1–2 days each, backend changes + some frontend):**
5. Change 2 — Bowling Median: Exclude Non-Bowlers (backend + minor frontend, 3 hr)
6. Change 5 — Exclude Tail-Enders from Batting Aggregates (backend + minor frontend, 3 hr)
7. Change 13 — Chase Splits Tuning (pipeline + backend investigation, 4 hr)
8. Change 8 — Compare Page Role Toggle (frontend + backend, 4 hr)

**Tier 3 — Pipeline Changes (1–3 days each, require re-running pipeline):**
9. Change 10 — Multiple Archetypes (pipeline + backend + frontend, 4 hr)
10. Change 11 — Rating Rebalance (pipeline, config changes, 6 hr + testing)

**Tier 4 — Major Features (3–5 days each):**
11. Change 7 — Era Timeline Enhancements (frontend + minor backend, 4 hr)
12. Change 12 — Team vs Team Comparison (backend + frontend, 1 day)
13. Change 9 — IPL Dataset Support (pipeline + backend + frontend, 3–5 days)

### Dependency Graph

```
Change 9 (IPL Support) depends on:
  └── Pipeline CLI args (must be able to run on different input dirs)

Change 11 (Rating Rebalance) depends on:
  └── Change 10 (Multiple Archetypes) — run pipeline once with both changes

Change 5 (Exclude Tail-Enders) depends on:
  └── Change 2 (Exclude Non-Bowlers) — uses the same pattern

Change 12 (Team Comparison) depends on:
  └── Change 3 (Customisable Slots) — nice to have, not strictly required

All other changes are independent and can be done in parallel.
```

### Recommended Order

1. Change 1 (Y-axis) — immediate visual fix
2. Change 6 (Tooltips) — easy win, improves UX
3. Change 4 (URL order) — fixes a bug
4. Change 3 (Slot customisation) — UX improvement
5. Change 2 (Bowling median) — data correctness
6. Change 5 (Batter filtering) — data correctness
7. Change 13 (Chase splits) — data correctness
8. Change 8 (Compare roles) — UX improvement
9. Change 10 (Multiple archetypes) — run pipeline
10. Change 11 (Rating rebalance) — run pipeline
11. Change 7 (Era timeline) — feature addition
12. Change 12 (Team comparison) — feature addition
13. Change 9 (IPL support) — large feature

---

## 17. File Change Summary

### Frontend Files Modified

| File | Changes |
|------|---------|
| `gui/frontend/src/pages/PlayerProfile.tsx` | Form chart Y-axis auto-scale (Change 1) |
| `gui/frontend/src/pages/TeamBuilder.tsx` | Customisable slot labels (Change 3), URL order preservation (Change 4), batting aggregate display (Change 5), team comparison mode (Change 12) |
| `gui/frontend/src/pages/Compare.tsx` | Metric tooltips (Change 6), role toggle (Change 8) |
| `gui/frontend/src/pages/Eras.tsx` | New metrics: avg run rate, predicted score (Change 7) |
| `gui/frontend/src/api/types.ts` | New fields: archetypes[], genuine_batter_count, genuine_bowler_count, EraBaseline extensions |
| `gui/frontend/src/api/queries.ts` | Format parameter on all queries (Change 9) |
| `gui/frontend/src/api/client.ts` | Format parameter injection (Change 9) |
| `gui/frontend/src/components/ArchetypeBadge.tsx` | isPrimary prop for multiple archetypes (Change 10) |
| `gui/frontend/src/components/Layout.tsx` | Format toggle in nav bar (Change 9) |
| `gui/frontend/src/App.tsx` | FormatProvider wrapper (Change 9) |

### Frontend Files Created

| File | Purpose |
|------|---------|
| `gui/frontend/src/api/FormatContext.tsx` | React context for T20I/IPL toggle (Change 9) |

### Backend Files Modified

| File | Changes |
|------|---------|
| `gui/backend/routers/team.py` | Genuine bowler/batter filtering (Changes 2, 5), team comparison endpoint (Change 12) |
| `gui/backend/routers/compare.py` | Return both roles for each player (Change 8) |
| `gui/backend/routers/eras.py` | avg_rr, predicted_score fields (Change 7) |
| `gui/backend/data_loader.py` | MultiDataStore for T20I + IPL (Change 9) |
| `gui/backend/app.py` | Format query parameter, dual data loading (Change 9) |
| `gui/backend/schemas.py` | New fields: archetypes, genuine counts, era extensions, team compare response |

### Pipeline Files Modified

| File | Changes |
|------|---------|
| `src/presentation.py` | Multiple archetypes (Change 10), superstar bonus cap (Change 11) |
| `src/batting.py` | Responsibility multiplier for control (Change 11) |
| `src/clutch.py` or `src/condition.py` | Chase splits fix (Change 13) |
| `src/main.py` | CLI args for input/output dirs (Change 9) |
| `config.yaml` | Control weight rebalance (Change 11) |

---

## 18. Testing Strategy

### Unit Tests (Python Pipeline)

After making pipeline changes (Changes 10, 11, 13), run:

```bash
cd cricket_metrics
python -m pytest tests/ -v
```

The existing 914 tests should continue to pass. Some test expectations for grade boundaries and archetype names may need updating. Fix these by updating the expected values in the test files — don't change the logic to satisfy old tests if the new logic is correct.

### Integration Tests (Backend API)

Add tests for the new endpoints and modified behavior:

```python
# tests/test_team_api.py
def test_genuine_bowler_filter():
    """Verify that pure batters are not counted in bowling aggregates."""
    # Create a mock DataStore with a batter who bowled 1 match out of 50 batting innings
    # Verify they are NOT in the bowlers list

def test_genuine_batter_filter():
    """Verify that tail-enders are not counted in batting aggregates."""
    # Create a mock DataStore with a bowler who has batting composite < 20
    # Verify they are NOT in the bat_rows used for averages

def test_team_compare():
    """Verify team comparison returns two analyses with comparison metrics."""
```

### Manual Testing Checklist

For each change, the specific testing steps are listed in the change's section above. A comprehensive manual test:

1. [ ] Start backend and frontend
2. [ ] Navigate to Player Profile → verify Form chart auto-scales (Change 1)
3. [ ] Navigate to Team Builder → build a team with 4 batters + no bowlers → verify bowling section reflects genuine bowlers only (Change 2)
4. [ ] Click on slot labels → verify they cycle through roles (Change 3)
5. [ ] Build a team → share URL → open in incognito → verify order preserved (Change 4)
6. [ ] Add Arshdeep Singh to team → verify he doesn't drag down batting averages (Change 5)
7. [ ] Navigate to Compare → hover over "Acceleration" → verify tooltip appears (Change 6)
8. [ ] Navigate to Eras → toggle "Avg Run Rate" → verify purple line appears (Change 7)
9. [ ] Compare JJ Bumrah vs PJ Cummins → verify bowling comparison shown by default (Change 8)
10. [ ] Toggle between T20I and IPL → verify data changes (Change 9)
11. [ ] Check a player's profile → verify up to 3 archetypes shown (Change 10)
12. [ ] Check top 20 leaderboard → verify mix of archetypes, not all Explosive Finishers (Change 11)
13. [ ] Enter compare mode in Team Builder → build two teams → verify side-by-side comparison (Change 12)
14. [ ] Check a player's Chase Splits → verify SR and Avg are populated, not dashes (Change 13)

### Performance Considerations

- **Change 9 (IPL support):** Loading two DataStores doubles memory usage. On a machine with 16 GB RAM, this should be fine (each DataStore is ~200–500 MB). Monitor startup time — it may increase from ~3s to ~6s.
- **Change 2 (Genuine bowler filter):** The `_get_genuine_bowlers_df` function iterates over all bowl_careers rows. With ~500 bowlers, this is negligible. Cache the result if needed.
- **Change 12 (Team comparison):** The comparison endpoint calls `analyse_team` twice. Each call is fast (< 50ms). No performance concern.

---

*End of Version 0.3 Implementation Plan.*