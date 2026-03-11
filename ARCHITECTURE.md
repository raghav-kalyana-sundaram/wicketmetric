# Cricket Metrics — Architecture & Onboarding Guide

> **T20 Player Performance Profiling Engine**
>
> Produces three 0–100 metrics per role for every T20 cricketer from ball-by-ball Cricsheet JSON data.
>
> - **Batters:** Acceleration · Power · Control
> - **Bowlers:** Accuracy · Control · Threat

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Quick Start](#2-quick-start)
3. [Repository Layout](#3-repository-layout)
4. [Data: Source, Format & Volume](#4-data-source-format--volume)
5. [Pipeline Architecture](#5-pipeline-architecture)
6. [Module Reference](#6-module-reference)
   - [parser.py](#parserpysrcparserpy)
   - [context.py](#contextpysrccontextpy)
   - [batting.py](#battingpysrcbattingpy)
   - [bowling.py](#bowlingpysrcbowlingpy)
   - [rating.py](#ratingpysrcratingpy)
   - [config.py](#configpysrcconfigpy)
   - [main.py](#mainpysrcmainpy)
7. [Metric Design Philosophy](#7-metric-design-philosophy)
8. [The Rating System](#8-the-rating-system)
9. [Configuration Reference](#9-configuration-reference)
10. [Data Flow Diagram](#10-data-flow-diagram)
11. [Key Data Structures](#11-key-data-structures)
12. [Testing](#12-testing)
13. [Output Files](#13-output-files)
14. [Common Tasks & Recipes](#14-common-tasks--recipes)
15. [Design Decisions & Trade-offs](#15-design-decisions--trade-offs)
16. [Glossary](#16-glossary)
17. [Changelog](#17-changelog)

---

## 1. Project Overview

This project consumes **Cricsheet T20 International JSON data** (ball-by-ball) and produces **six player performance metrics** (three per role) on a 0–100 scale. The scores are designed to be intuitive — like a video game rating — while being statistically grounded.

| Role    | Metric 1        | Metric 2 | Metric 3 |
|---------|-----------------|----------|-----------|
| Batter  | Acceleration    | Power    | Control   |
| Bowler  | Accuracy        | Control  | Threat    |

Each metric is a **weighted composite of z-score-normalised sub-components**, passed through a **Bayesian shrinkage + percentile mapping** rating system, and then adjusted by **average quality gates** and **volume scaling**.

### Core Design Principles

- **Context-normalised**: Every performance is compared to the match par (pitch + era adjustment), not to absolute numbers. A 130 SR in 2008 (par ~120) is valued the same as a 165 SR in 2024 (par ~155).
- **Phase-aware**: Powerplay (overs 0–5), middle (6–15), and death (16–19) each have their own par rates. Death-overs batting is compared to death-overs par, not overall match par.
- **Opposition-weighted**: Innings against stronger bowling attacks, stronger teams, and higher-ICC-ranked opponents count more in career aggregation. ICC T20I team rankings provide an external authority signal alongside the in-sample bowler strength and PageRank team quality indices. A symmetric **match quality** weight further rewards performances in matches between two high-ranked teams.
- **Competition-gated**: A post-percentile gate scales down final scores for players whose career opponents average low ICC ratings, ensuring associate-nation stats against weak opposition cannot match elite-cricket performances.
- **Recency-weighted**: Recent performances are weighted more heavily (configurable half-life, default ~1.5 years / 545 days). Inactive players are penalised more aggressively than active ones.
- **Provisional ratings**: Players with few innings/overs are pulled toward the population mean via Bayesian shrinkage, similar to chess provisional ratings.
- **No circular dependencies**: Bowler strength is computed from raw bowling stats (economy, dot %, SR) independently of batting ratings, so opposition quality weighting has no circular dependency.

---

## 2. Quick Start

### Prerequisites

- Python 3.11+
- ~3,200 Cricsheet T20I JSON files in `t20s_male_json/` (or any directory you point to)

### Setup

```
cd cricket_metrics
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Run the pipeline

```
# Default: reads t20s_male_json/, writes to output/, uses config.yaml
python src/main.py

# Custom data directory and config
python src/main.py /path/to/json/dir --config my_config.yaml --output my_output/
```

### Run tests

```
python -m pytest tests/ -v
```

### Typical pipeline output

```
Matches parsed:    ~3,050  (Afghanistan matches excluded)
Deliveries:      ~690,000
Batting innings:  ~49,000
Bowling spells:   ~36,000
Batters profiled:  ~3,900  (provisional varies)
Bowlers profiled:  ~2,900  (provisional varies)
Run time:            ~25s
```

> **Note:** Afghanistan matches are excluded from the pipeline. All matches where Afghanistan is either the batting or bowling team are filtered out after parsing. This removes all Afghanistan players from the dataset entirely.

---

## 3. Repository Layout

```
cricket_metrics/
├── config.yaml                  # Central configuration (all tuning constants)
├── requirements.txt             # Python dependencies
│
├── src/
│   ├── __init__.py
│   ├── main.py                  # Pipeline orchestrator (CLI entry point)
│   ├── parser.py                # JSON → delivery-level DataFrame
│   ├── context.py               # Match & innings context (par rates)
│   ├── batting.py               # Batting metrics + support functions
│   ├── bowling.py               # Bowling metrics
│   ├── config.py                # YAML config loader with dot-notation access
│   └── rating.py                # Bayesian shrinkage + percentile mapping
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py              # Synthetic test fixtures (no real data needed)
│   ├── test_batting.py          # Batting module tests
│   ├── test_bowling.py          # Bowling module tests
│   ├── test_config.py           # Config loader tests
│   ├── test_context.py          # Context computation tests
│   └── test_rating.py           # Rating system tests
│
├── output/                      # Generated outputs (git-ignored)
│   ├── batting_profiles.csv     # One row per batter, 0–100 scores
│   ├── bowling_profiles.csv     # One row per bowler, 0–100 scores
│   ├── batting_careers_full.parquet
│   ├── bowling_careers_full.parquet
│   ├── batting_innings_detail.parquet
│   ├── bowling_spells_detail.parquet
│   └── potential_duplicates.csv
│
└── t20s_male_json/              # Raw Cricsheet data (not in repo)
    ├── 123456.json
    ├── 123457.json
    └── ...
```

---

## 4. Data: Source, Format & Volume

### Source

[Cricsheet](https://cricsheet.org/) provides free, structured ball-by-ball cricket data. We use the **JSON format** (versions 1.0.0 and 1.1.0) for T20 International men's matches.

### JSON Structure (per match file)

Each file (e.g., `123456.json`) contains:

```
{
  "info": {
    "dates": ["2024-01-15"],
    "venue": "Melbourne Cricket Ground",
    "teams": ["Australia", "India"],
    "players": { "Australia": [...], "India": [...] },
    "registry": { "people": { "V Kohli": "abc123", ... } },
    "toss": { "winner": "India", "decision": "bat" },
    "outcome": { "winner": "India" },
    "overs": 20
  },
  "innings": [
    {
      "team": "India",
      "overs": [
        {
          "over": 0,
          "deliveries": [
            {
              "batter": "RG Sharma",
              "bowler": "MA Starc",
              "non_striker": "V Kohli",
              "runs": { "batter": 4, "extras": 0, "total": 4 },
              "extras": {},
              "wickets": []
            }
          ]
        }
      ]
    }
  ]
}
```

### Key Fields Used by the Parser

| Field | Purpose |
|-------|---------|
| `info.registry.people` | Maps player display names → unique registry IDs (critical for deduplication across matches) |
| `info.dates[0]` | Match date (for recency weighting and era normalisation) |
| `info.outcome.winner` | Used in team quality computation |
| `innings[].team` | Identifies batting team |
| `innings[].overs[].deliveries[]` | Ball-by-ball data with runs, extras, wickets |
| `deliveries[].wickets[]` | Array of dismissals (can have >1 per ball, e.g., run-out of non-striker) |

### Data Volume

| Metric | Typical Value |
|--------|---------------|
| JSON files | ~3,200 |
| Deliveries parsed | ~721,000 |
| Batting innings rows | ~51,000 |
| Bowling spell rows | ~38,000 |
| Unique batters | ~4,000 |
| Unique bowlers | ~3,000 |

---

## 5. Pipeline Architecture

The pipeline runs as a **9-step sequential process** orchestrated by `main.py`:

```
┌─────────────────────────────────────────────────────────────────┐
│  Step 1:   Parse all match JSONs → delivery-level DataFrame     │
│  Step 1b:  Player identity deduplication (alias table)          │
│  Step 2:   Compute match & innings context (par rates)          │
│  Step 2b:  Compute bowler strength index (for opp. quality)     │
│  Step 2c:  Compute team quality index (iterative PageRank)      │
│  Step 3:   Extract batting innings + compute components         │
│  Step 4:   Extract bowling spells + compute components          │
│  Step 5:   Aggregate career profiles (weighted means)           │
│  Step 6:   Apply Bayesian rating system → 0–100 scores          │
│  Step 7:   Apply average gates & volume scaling                 │
│  Step 8:   Write CSV + Parquet outputs                          │
│  Step 9:   Spot-check summaries (print known players)           │
└─────────────────────────────────────────────────────────────────┘
```

### Data Transformation Chain

```
JSON files
  │
  ▼
delivery-level DataFrame (~721K rows)
  │
  ├──► innings context (one row per match/innings/team)
  ├──► match context (one row per match: par SR, par RR, etc.)
  ├──► bowler strength index (one row per bowler_id)
  ├──► team quality index (one row per team)
  │
  ├──► batting innings (one row per match/innings/batter: ~51K rows)
  │      │
  │      ▼
  │    batting components (sub-component scores per innings)
  │      │
  │      ▼
  │    batting careers (one row per batter: ~4K rows)
  │      │
  │      ▼
  │    batting profiles (0–100 scores after rating + gates)
  │
  └──► bowling spells (one row per match/innings/bowler: ~38K rows)
         │
         ▼
       bowling components (sub-component scores per spell)
         │
         ▼
       bowling careers (one row per bowler: ~3K rows)
         │
         ▼
       bowling profiles (0–100 scores after rating + gates)
```

---

## 6. Module Reference

### `parser.py` — `src/parser.py`

**Purpose:** Read all Cricsheet JSON files and produce a single delivery-level DataFrame.

**Key function:** `parse_all_matches(data_dir, max_workers=None) → (DataFrame, list[dict])`

- Uses `ProcessPoolExecutor` for parallel JSON parsing (default: `min(cpu_count, 8)` workers)
- Each delivery becomes one row with ~40 columns
- Tracks cumulative match state (team score, wickets) at each delivery
- Uses `orjson` for fast JSON parsing
- Optimises memory with `int8`/`int16` dtypes and categorical columns
- Returns the DataFrame sorted by date → match → innings → over → ball

**Key columns produced per delivery:**

| Column | Type | Description |
|--------|------|-------------|
| `match_id` | str | Filename stem (e.g., "123456") |
| `batter_id` | str | Unique registry ID from Cricsheet |
| `bowler_id` | str | Unique registry ID |
| `batter_runs` | int8 | Runs scored off the bat (0, 1, 2, 3, 4, 6) |
| `total_runs` | int8 | Total runs from the delivery (batter + extras) |
| `is_legal` | bool | False for wides and no-balls |
| `is_batter_ball` | bool | False for wides (batter didn't face) |
| `is_wicket` | bool | A dismissal occurred |
| `phase` | str | "powerplay" / "middle" / "death" |
| `batting_position` | int8 | Order of first appearance (1 = opener) |
| `is_dot_batter` | bool | Batter scored 0 off a faced ball |
| `is_dot_bowler` | bool | Zero total runs off the delivery |

---

### `context.py` — `src/context.py`

**Purpose:** Build match-level and innings-level context for normalising performances.

**Key functions:**

| Function | Returns | Description |
|----------|---------|-------------|
| `compute_innings_context(df)` | DataFrame | One row per (match, innings, team) with total runs, legal balls, SR, boundary rate, dot % |
| `compute_match_context(innings_ctx)` | DataFrame | One row per match with `match_par_sr` (average SR across both innings), `match_par_rr`, boundary rate, dot % |
| `compute_per_bowler_innings_economy(df)` | DataFrame | Per-bowler economy in each innings + economy vs other bowlers in the same innings |
| `build_full_context(df)` | (innings_ctx, match_ctx) | Public entry point; merges match-level par onto innings context |

**The two-layer context model:**

1. **Match par** → "How easy was it to score on this pitch on this day?" (`match_par_sr`)
2. **Team share** → "How much did this player matter to their own team?" (`team_contribution_pct`)

This lets us correctly value 70(60) in a team total of 120 as elite, even if the match par was 150+.

---

### `batting.py` — `src/batting.py`

**Purpose:** The largest module. Handles player deduplication, opposition/team quality, ICC ranking weighting, match quality weighting, competition quality gating, wicket quality, and all batting metric computation.

**Public functions (in pipeline order):**

| Function | Description |
|----------|-------------|
| `merge_player_identities(df)` | Apply `PLAYER_ALIASES` to remap duplicate registry IDs to canonical IDs |
| `detect_potential_duplicates(df, min_innings)` | Heuristic detection: same surname, same team, non-overlapping match dates |
| `compute_team_quality(df)` | Iterative PageRank-style team strength from win rates weighted by opponent quality |
| `compute_bowler_strength_index(df, min_balls)` | Career-level bowler strength (economy + dot% + SR z-scores); independent of batting ratings |
| `compute_opposition_quality(df, bowler_strength)` | Per-innings bowling attack strength (weighted by balls faced vs each bowler) |
| `compute_icc_ranking_weight(team_name)` | Scalar ICC ranking weight for a single team from the config ratings table |
| `compute_icc_ranking_weights(teams_series)` | Vectorised version: maps a Series of team names to ICC ranking weights |
| `compute_match_quality_weights(batting_teams, bowling_teams)` | Symmetric match quality weight based on the average ICC ranking of both teams |
| `compute_wicket_quality(df)` | Quality-weighted wicket counts by batting position of dismissed batter |
| `extract_batting_innings(df, innings_ctx, bowler_strength, team_quality)` | One row per (match, batter) with runs, balls, phases, SR halves, context, opposition + team + ICC ranking + match quality weights, recency weights, and raw opponent ICC rating |
| `compute_batting_components(bat_innings)` | Raw sub-component scores per innings for ACC/POW/CTRL |
| `aggregate_batting_careers(bat_components, min_innings)` | Career-level aggregation with opposition-quality-weighted means → raw composites; tracks `avg_opp_icc_rating` for competition gate |
| `apply_avg_quality_gate(bat_careers)` | Post-percentile gate: scales scores by career average |
| `apply_volume_scaling(bat_careers)` | Post-percentile volume factor: rewards more innings |
| `apply_competition_quality_gate(bat_careers)` | Post-percentile gate: scales scores by average opponent ICC rating (penalises weak-opposition careers) |
| `apply_bowling_competition_quality_gate(bowl_careers)` | Same gate logic applied to bowling scores |

#### Batting Metric Sub-Components

**Acceleration** (how quickly a batter scores):

| Component | Weight | Description |
|-----------|--------|-------------|
| `overall_sr` | 0.25 | Context-adjusted overall strike rate — True Strike Rate (SR / par − 1) |
| `sr_growth` | 0.20 | SR growth from first to second half of innings |
| `death_sr` | 0.15 | Death-overs SR relative to death-phase par |
| `impact` | 0.25 | Runs × (SR above par); rewards big fast knocks |
| `runs_above_expected` | 0.15 | Phase-based xR delta: (actual runs − expected runs) per ball faced. Expected runs = Σ(balls_in_phase × phase_par_SR / 100). Positive = value-add batter. |

**Power** (boundary hitting ability):

| Component | Weight | Description |
|-----------|--------|-------------|
| `boundary_pct` | 0.40 | Boundary % of total runs (combines 4s + 6s into one weight) |
| `boundary_rate_vs_par` | 0.20 | Boundary rate relative to match average |
| `peak_phase_sr` | 0.25 | Best phase SR relative to that phase's par |
| `timing_factor` | 0.15 | Fours-to-boundary ratio (4s / (4s + 6s)). High ratio = placement and timing over brute force. Separates technically timed batters from pure sluggers. |

**Control** (innings management / survivability):

| Component | Weight | Description |
|-----------|--------|-------------|
| `dot_pct_weighted` | 0.15 | Phase-weighted dot ball % (inverted; death dots penalised 1.5×, PP dots 0.7×) |
| `rotation` | 0.10 | Rotation rate (1s + 2s per ball) |
| `contribution` | 0.15 | Team contribution % |
| `avg_proxy` | 0.30 | Career average (z-scored) — largest weight |
| `dismissal_quality` | 0.15 | Dismissal context quality (inverted) |
| `scoring_consistency` | 0.15 | Raw 1 − dot% (unweighted by phase). Pure "bat on ball, find gaps" control index — a batter who consistently makes contact and rotates strike regardless of phase. |

#### Average Quality Gate (Two-Stage System)

This is a key mechanism that prevents low-average sloggers from topping the Acceleration/Power charts:

**Stage 1 (pre-percentile, on raw z-score composites):**
Asymmetric multiplicative factor around the population median average (~18):
- Below median: steep penalty (exponent 2.5)
- Above median: gentle bonus (exponent 0.5, capped)

**Stage 2 (post-percentile, on final 0–100 scores):**
Direct gate: `gate = base + (1 − base) × clip(avg / ref, 0, 1)`

Combined effect:
| Career Avg | Approx. Score Retained |
|-----------|----------------------|
| 10 | ~55–60% |
| 15 | ~80–83% |
| 25+ | 100% (no penalty) |

---

### `bowling.py` — `src/bowling.py`

**Purpose:** Bowling spell extraction, component computation, and career aggregation.

**Public functions (in pipeline order):**

| Function | Description |
|----------|-------------|
| `extract_bowling_spells(df, innings_ctx, phase_par_rr, team_quality)` | One row per (match, innings, bowler) with economy, dots, phases, economy vs others, recency weight, ICC ranking weight, team quality weight, match quality weight, and raw opponent ICC rating |
| `compute_run_distribution_entropy(df)` | Shannon entropy of per-ball run distribution per spell |
| `compute_bowling_components(bowl_spells, entropy_df, wicket_quality)` | Raw sub-component scores per spell for ACC/CTRL/THREAT |
| `apply_bowling_volume_scaling(bowl_careers)` | Post-percentile volume factor: rewards more matches |
| `aggregate_bowling_careers(bowl_components, df_deliveries, min_overs)` | Career-level aggregation with spell-weight-weighted means → raw composites; tracks `avg_opp_icc_rating` for competition gate |

#### Bowling Metric Sub-Components

**Accuracy** (economy and precision):

| Component | Weight | Description |
|-----------|--------|-------------|
| `economy_vs_par` | 0.35 | Context-adjusted economy (1 − economy_ratio_par) |
| `dot_pct` | 0.30 | Dot ball percentage |
| `extras_penalty` | 0.20 | Wides + no-balls per over (negated) |
| `boundary_penalty` | 0.15 | Boundary % conceded (negated) |

**Control** (consistency and match dominance):

| Component | Weight | Description |
|-----------|--------|-------------|
| `economy_vs_par` | **0.30** | Context-adjusted economy (phase-weighted — fairest signal for death bowlers) |
| `vs_others` | 0.25 | Economy vs other bowlers in same innings — important but reduced to avoid unfairly penalising death specialists |
| `entropy` | 0.15 | Run distribution entropy (inverted) |
| `phase_consistency` | 0.15 | Low variance in economy across phases (boosted) |
| `extras` | 0.10 | Wides + no-balls per over (negated) |
| `extras_pct` | 0.05 | Bowler-responsible extras as % of runs (reduced — overlaps with extras) |

> **Design note:** The `economy_vs_par` component (weight 0.30) is the most important Control signal, using phase-weighted economy ratios so death bowlers are judged against death-overs par, not overall par. The `vs_others` component (weight 0.25) complements this — a bowler who concedes ~1+ RPO less than teammates in the SAME conditions demonstrates elite control (e.g. Bumrah). The previous 0.35 weight on `vs_others` unfairly penalised death specialists like Arshdeep Singh whose economy is naturally higher than PP/middle bowlers in the same match. The rebalancing towards `economy_vs_par` and `phase_consistency` produces fairer scores across all bowling roles.

**Threat** (wicket-taking ability):

| Component | Weight | Description |
|-----------|--------|-------------|
| `pressure` | 0.20 | Economy vs others (pressure differential) |
| `dots` | 0.20 | Dot ball % (sustained pressure creation) |
| `wickets` | 0.15 | Raw wickets per spell |
| `quality_wickets` | 0.15 | Position-weighted wickets (top-order > tail) |
| `sr` | 0.15 | Bowling strike rate (inverted) |
| `bowled_lbw` | 0.15 | Bowled/LBW % of wickets (pure skill) |

#### Wicket Quality Weighting

Dismissals are weighted by the batting position of the batter dismissed:

| Position | Weight | Role |
|----------|--------|------|
| 1–2 | 1.5 | Openers |
| 3 | 1.4 | One-down |
| 4 | 1.2 | Middle order |
| 5 | 1.1 | Middle order |
| 6 | 1.0 | Lower middle (neutral) |
| 7 | 0.8 | Lower order |
| 8 | 0.7 | Lower order |
| 9 | 0.5 | Tail |
| 10 | 0.4 | Tail |
| 11 | 0.3 | Tail |

---

### `rating.py` — `src/rating.py`

**Purpose:** Convert raw composite z-scores into 0–100 displayed scores using a chess-inspired rating system.

**The three-step pipeline (applied per metric):**

1. **Bayesian shrinkage**: `adjusted = (n × score + k × pop_mean) / (n + k)`
   - With k=12, a player needs ~12 innings before their score equals the population mean in weight
   - By ~50 innings, their own data dominates (~80%)

2. **Confidence bonus**: `bonus = α × ln(1 + n) / ln(1 + ref_n)`, capped at α (3%)
   - Small multiplicative uplift for playing more matches
   - Nudges but never dominates

3. **Percentile ranking**: Fractional ranking mapped to 0–100
   - 50 = median player, 99 = top 1%

**Key function:** `apply_rating_system(career_df, raw_cols, sample_col, ...)`

**Utility:** `lookup_player(career_df, player_name=..., player_id=...)` for quick profile lookups.

---

### `config.py` — `src/config.py`

**Purpose:** Centralised YAML configuration with dot-notation access and hardcoded defaults.

**Key features:**
- Loads `config.yaml` from the project root (or a custom path via `--config`)
- Deep-merges user YAML onto `_DEFAULTS` dict, so missing keys never crash
- Dot-notation access: `cfg("recency.half_life_days")` → `730`
- Thread-safe for read-only access
- Module-level `cfg()` function loads on first call, caches thereafter

**Usage patterns:**

```python
from src.config import cfg, get_config, reload_config

# Simple value access
half_life = cfg("recency.half_life_days")        # → 730
weights = cfg("batting_acceleration_weights")     # → dict

# With default fallback
val = cfg("nonexistent.key", default=42)          # → 42

# Load a specific config file
config = reload_config("/path/to/custom.yaml")
```

---

### `main.py` — `src/main.py`

**Purpose:** Pipeline orchestrator and CLI entry point.

**Key function:** `run_pipeline(data_dir, output_dir, config_path, ...) → dict`
- Returns a dict with all intermediate DataFrames for programmatic use

**Utility functions:**
- `print_top_batters(bat_careers, metric, n)` — Print top N non-provisional batters
- `print_top_bowlers(bowl_careers, metric, n)` — Print top N non-provisional bowlers
- `print_player_profile(career_df, name, role)` — Detailed profile with ASCII bar chart

**CLI interface:**

```
python src/main.py [data_dir] [--config path] [--output path]
```

---

## 7. Metric Design Philosophy

### Why Three Metrics Instead of One?

A single rating number loses too much information. Batters have different roles (anchor vs finisher vs power hitter), and bowlers have different styles (economical vs wicket-taking vs all-round pressure). Three metrics per role capture these archetypes:

| Batting Archetype | ACC | POW | CTRL |
|-------------------|-----|-----|------|
| Explosive finisher (e.g., Maxwell) | High | High | Medium |
| Anchor (e.g., Kohli) | Medium | Medium | High |
| Balanced (e.g., Buttler) | High | High | High |
| Low-average slogger | Medium (gated down) | Medium (gated down) | Low |

| Bowling Archetype | ACC | CTRL | THR |
|-------------------|-----|------|-----|
| Death specialist (e.g., Bumrah) | High | Very High | High |
| Spin restrictor (e.g., Narine) | High | High | Medium |
| Strike bowler (e.g., Rabada) | Medium | Medium | Very High |
| Economy but no wickets | High | High | Low |

### Context Normalisation

Every raw metric is computed relative to match par:
- **SR vs par** uses a ratio (`SR / match_par_sr`), not a difference, so that a 130 SR when par is 120 (ratio 1.08) and a 165 SR when par is 153 (ratio 1.08) are valued equally.
- **Phase-specific par**: Death-overs batting is compared to death-overs par, not overall match par.
- **Economy vs par** for bowlers uses `economy / match_par_rr` as a ratio.

### Z-Score Normalisation

Before compositing, every sub-component is z-score normalised across the population:
```
z = (x − mean) / std
```
This ensures each component contributes proportionally to its weight, regardless of its natural scale. It eliminates the need for magic scaling constants. Missing values (NaN) are filled with 0 after z-scoring (which means "population average" — the correct neutral value).

### Opposition and Team Quality Weighting

Innings are weighted during career aggregation:

```
innings_weight = opp_bowling_quality × opp_team_quality × icc_ranking_weight × match_quality_weight × recency_weight
```

- **Opposition bowling quality**: Average bowler strength faced (weighted by balls), converted to a weight: `1 + clip(opp_quality × 0.15, −0.3, 0.3)`. An elite attack gives up to 1.30× weight.
- **Team quality**: Iterative PageRank-style index from win rates. Facing a strong team gives up to 1.25× weight.
- **ICC ranking weight**: Derived from the opponent's ICC T20I team rating. The rating is normalised against the top-rated team and mapped to a configurable floor–ceiling range via a super-linear power curve:
  ```
  normalised = icc_rating / max_rating
  icc_weight = floor + (ceiling − floor) × normalised ^ curve
  ```
  Default parameters: `floor: 0.50`, `ceiling: 1.35`, `curve: 1.8` (super-linear), `max_rating: 272`, `default_rating: 20`. Effect examples: India (272) → ~1.35, England (260) → ~1.32, Afghanistan (221) → ~1.14, Oman (151) → ~0.87, Unranked → ~0.51. The super-linear curve (1.8) concentrates weight toward top-ranked teams, creating a much larger gap between Test nations and associates. The ratings table is a static snapshot stored in `config.yaml` and should be updated periodically.
- **Match quality weight**: A symmetric weight based on the **average** ICC ranking of **both** teams in the match. A match between two top-8 teams (e.g. India vs Australia) is inherently higher quality than a match between two associates, capturing fielding standards, depth of lineups, and pressure of the occasion:
  ```
  avg_rating = (batting_team_rating + bowling_team_rating) / 2
  normalised = avg_rating / max_rating
  match_quality = floor + (ceiling − floor) × normalised ^ curve
  ```
  Default parameters: `floor: 0.75`, `ceiling: 1.20`, `curve: 1.3`. Examples: India vs Australia → ~1.19, India vs Zimbabwe → ~1.13, Uganda vs PNG → ~0.92, Unranked vs Unranked → ~0.76. Combined with the per-opposition ICC ranking weight, this creates a powerful two-layer system: India batter vs Australia gets icc_opp ~1.34 × match_quality ~1.19 ≈ 1.59, while an associate vs associate gets icc_opp ~0.64 × match_quality ~0.85 ≈ 0.54.
- **Recency**: `2^(−days_since / half_life)` with a floor of 0.05. Default half-life is 730 days (2 years).

These five weights are **multiplied** together, so a recent innings against a top-ranked team with a strong bowling attack in a high-quality match gets the highest combined weight.

### Competition Quality Gate (Post-Percentile)

After the rating system converts raw composites to 0–100 percentile scores, a **competition quality gate** directly scales down scores for players who primarily face weak opposition. This is separate from (and complementary to) the per-innings ICC ranking weight which affects career aggregation weights.

The gate uses the player's **average opponent ICC rating** across their entire career:

```
normalised = avg_opp_icc_rating / max_rating          (0 to 1)
gate = base + (1 − base) × normalised ^ curve
```

Default parameters: `base: 0.55`, `curve: 0.5` (sub-linear). The sub-linear curve concentrates the penalty on players with very low average opponent quality while barely affecting players who face top-ranked teams:

| Avg Opponent Rating | Example | Gate | Score Effect |
|---|---|---|---|
| 260 | Faces top-8 teams | 0.99 | −1% |
| 230 | Faces Test nations | 0.96 | −4% |
| 200 | Mixed opponents | 0.94 | −6% |
| 150 | Mid-tier associates | 0.88 | −12% |
| 120 | Low-tier associates | 0.85 | −15% |
| 80 | Very weak opponents | 0.79 | −21% |
| 30 | Unranked opponents | 0.70 | −30% |

This gate is applied to **all three** batting scores (Acceleration, Power, Control) and **all three** bowling scores (Accuracy, Control, Threat). It runs after the average quality gate and volume scaling, ensuring that players from associate nations who score highly against weak opposition are properly differentiated from Test-nation players who achieve similar raw stats against elite opposition.

The gate is applied symmetrically to bowling as well: a bowler's average opponent ICC rating reflects the strength of the batting lineups they have bowled against.

---

## 8. The Rating System

The rating system converts raw z-score composites into displayed 0–100 scores. It is applied identically to batting and bowling metrics.

### Pipeline Visualisation

```
raw_acceleration (z-score composite, unbounded)
  │
  ▼  Step 1: Bayesian shrinkage
adjusted = (n × raw + k × pop_mean) / (n + k)
  │         k=12 for batting, k=10 for bowling
  ▼  Step 2: Confidence bonus
adjusted × (1 + α × ln(1+n) / ln(1+100))     α = 0.03
  │
  ▼  Step 3: Percentile mapping
score_acceleration = percentile_rank × 100     (0–100)
  │
  ▼  Step 4: Average quality gate (batting only)
score × gate(career_avg)
  │
  ▼  Step 5: Volume scaling
score × volume_factor(innings_count)
  │
  ▼  Step 6: Competition quality gate
score × competition_gate(avg_opp_icc_rating)
  │
  ▼
FINAL DISPLAYED SCORE (0–100)
```

### Shrinkage Effect by Sample Size

| Innings | Own Data Weight | Population Mean Weight |
|---------|----------------|----------------------|
| 1 | 8% | 92% |
| 5 | 29% | 71% |
| 12 | 50% | 50% |
| 25 | 68% | 32% |
| 50 | 81% | 19% |
| 100 | 89% | 11% |

---

### Bowling Opposition Weighting

Bowling spells use the same five-layer weighting system as batting:

```
spell_weight = recency_weight × icc_ranking_weight × team_quality_weight × match_quality_weight
```

- **Team quality weight**: The batting team's PageRank-style quality index, converted to a weight the same way as batting's team quality.
- **ICC ranking weight**: Derived from the batting team's ICC T20I rating — bowling against India's lineup carries more weight than bowling against a low-ranked associate.
- **Match quality weight**: Same symmetric formula as batting — spells in matches between two top-ranked teams are worth more.
- **Recency weight**: Same half-life decay as batting (~1.5 years / 545 days).

This ensures full parity between batting and bowling weighting: both use opposition bowling/batting quality, team quality, ICC ranking, match quality, and recency.

---

## 9. Configuration Reference

All tuning constants live in `config.yaml`. The file is extensively commented. Here's a structural overview:

| Section | Key Examples | Purpose |
|---------|-------------|---------|
| `pipeline` | `min_bat_innings: 10`, `min_phase_balls_batting: 4` | Provisional thresholds, minimum ball counts |
| `rating` | `shrinkage_k_bat: 12.0`, `confidence_alpha: 0.03` | Rating system parameters |
| `batting_acceleration_weights` | `overall_sr: 0.30`, `impact: 0.25` | Sub-component weights (must sum to 1.0) |
| `batting_power_weights` | `six_rate: 0.30`, `boundary_pct: 0.25` | Sub-component weights |
| `batting_control_weights` | `avg_proxy: 0.30`, `dot_pct_weighted: 0.20` | Sub-component weights |
| `batting_avg_quality` | `gate_base: 0.55`, `gate_ref: 25.0` | Average quality gate parameters |
| `batting_volume` | `base: 0.80`, `ref: 50.0`, `curve: 0.6` | Volume scaling curve |
| `bowling_accuracy_weights` | `economy_vs_par: 0.35`, `dot_pct: 0.30` | Sub-component weights |
| `bowling_control_weights` | `vs_others: 0.35`, `entropy: 0.15` | Sub-component weights |
| `bowling_threat_weights` | `pressure: 0.20`, `dots: 0.20` | Sub-component weights |
| `bowling_volume` | `base: 0.80`, `ref: 50.0`, `curve: 0.6` | Volume scaling curve |
| `wicket_quality` | `position_weights: {1: 1.5, ..., 11: 0.3}` | Position-based wicket value |
| `opposition_quality` | `scale: 0.15`, `clip: 0.3` | Opposition weighting parameters |
| `team_quality` | `iterations: 5`, `scale: 0.10`, `clip: 0.25` | PageRank iterations and weighting |
| `icc_ranking` | `enabled: true`, `floor: 0.50`, `ceiling: 1.35`, `curve: 1.8`, `ratings: {...}` | ICC T20I team ranking-based opposition weight (static snapshot, super-linear curve) |
| `match_quality` | `enabled: true`, `floor: 0.75`, `ceiling: 1.20`, `curve: 1.3` | Symmetric match quality weight based on average ICC ranking of both teams |
| `competition_quality_gate` | `enabled: true`, `base: 0.55`, `curve: 0.5` | Post-percentile gate scaling down scores for players facing weak opposition |
| `recency` | `enabled: true`, `half_life_days: 730` | Time-decay parameters |
| `batting_dot_penalty_phase_weights` | `powerplay: 1.3`, `death: 0.7` | Phase-specific dot ball penalties |
| `player_aliases` | `{}` | Manual dedup: `secondary_id: canonical_id` |
| `player_name_overrides` | `{}` | Display name preferences |
| `duplicate_detection` | `min_innings: 5`, `export_csv: true` | Heuristic dedup settings |

---

## 10. Data Flow Diagram

```
                    ┌──────────────────┐
                    │  JSON Match Files │
                    │  (t20s_male_json/)│
                    └────────┬─────────┘
                             │
                     parse_all_matches()
                             │
                             ▼
              ┌──────────────────────────┐
              │   Delivery-Level DataFrame │
              │   (~721K rows × ~40 cols)  │
              └──────────┬───────────────┘
                         │
          ┌──────────────┼──────────────────────┐
          │              │                      │
          ▼              ▼                      ▼
   merge_player     build_full            compute_bowler
   _identities()    _context()            _strength_index()
          │              │                      │
          │         ┌────┴────┐                 │
          │         ▼         ▼                 │
          │    innings     match                │
          │    _ctx        _ctx                 │
          │         │                           │
          │         │    compute_team_quality()  │
          │         │         │                 │
          │         │         ▼                 │
          │         │    team_quality            │
          │         │                           │
          ▼         ▼         ▼                 ▼
   ┌──────────────────────────────────────────────┐
   │          extract_batting_innings()             │
   │  Joins: innings_ctx, bowler_strength,          │
   │         team_quality, recency weights          │
   │  → Per-innings rows with all context           │
   └─────────────────────┬────────────────────────┘
                         │
           ┌─────────────┴──────────────┐
           │                            │
           ▼                            ▼
  compute_batting           extract_bowling_spells()
  _components()             compute_bowling_components()
           │                            │
           ▼                            ▼
  aggregate_batting         aggregate_bowling
  _careers()                _careers()
           │                            │
           ▼                            ▼
  apply_rating_system()     apply_rating_system()
           │                            │
           ▼                            ▼
  apply_avg_quality         apply_bowling
  _gate()                   _volume_scaling()
           │                            │
  apply_volume_scaling()                │
           │                            │
           ▼                            ▼
  ┌─────────────┐           ┌──────────────┐
  │ batting_    │           │ bowling_     │
  │ profiles.csv│           │ profiles.csv │
  └─────────────┘           └──────────────┘
```

---

## 11. Key Data Structures

### Delivery DataFrame (from parser)

~721K rows. One row per ball bowled. This is the foundational data structure that all downstream computation is based on.

Key columns: `match_id`, `date`, `innings_num`, `batter_id`, `bowler_id`, `batter_runs`, `total_runs`, `is_legal`, `is_batter_ball`, `is_wicket`, `phase`, `batting_position`, `batting_team`, `bowling_team`, `team_score_before`, `team_wickets_before`.

### Batting Innings DataFrame (from extract_batting_innings)

~51K rows. One row per (match, innings, batter).

Key columns: `runs`, `balls_faced`, `sr`, `fours`, `sixes`, `dots`, `batting_position`, `sr_vs_par`, `team_contribution_pct`, `powerplay_sr`, `middle_sr`, `death_sr`, `first_half_sr`, `second_half_sr`, `opposition_quality`, `opp_quality_weight`, `recency_weight`, `how_out`, `is_out`.

### Batting Components DataFrame (from compute_batting_components)

Same rows as batting innings, with added component columns: `acc_overall_sr`, `acc_sr_growth`, `acc_death_sr`, `acc_impact`, `pow_boundary_pct`, `pow_six_rate`, `pow_boundary_rate_vs_par`, `pow_peak_phase_sr`, `ctrl_dot_pct_weighted`, `ctrl_rotation`, `ctrl_contribution`, `ctrl_avg_proxy`, `ctrl_dismissal_quality`.

### Batting Careers DataFrame (from aggregate_batting_careers)

~4K rows. One row per batter.

Key columns: `batter_id`, `batter`, `country`, `innings_count`, `total_runs`, `total_balls`, `career_sr`, `career_avg`, `raw_acceleration`, `raw_power`, `raw_control`, `is_provisional_bat`.

After rating system: adds `score_acceleration`, `score_power`, `score_control` (0–100).

After gates/scaling: adds `avg_quality_gate`, `volume_factor`.

### Bowling Spells DataFrame (from extract_bowling_spells)

~38K rows. One row per (match, innings, bowler).

Key columns: `legal_balls`, `runs_conceded`, `wickets`, `economy`, `dot_pct`, `extras_per_over`, `economy_vs_others`, `economy_ratio_par`, `spell_weight`, `recency_weight`, phase splits.

### Bowling Careers DataFrame (from aggregate_bowling_careers)

~3K rows. One row per bowler.

Key columns: `bowler_id`, `bowler`, `country`, `matches`, `total_overs`, `total_wickets`, `career_economy`, `career_sr_bowl`, `bowled_lbw_pct`, `raw_accuracy`, `raw_control`, `raw_threat`, `score_accuracy`, `score_control`, `score_threat`, `is_provisional_bowl`.

---

## 12. Testing

### Test Structure

Tests use **synthetic fixtures** (no real match data required) defined in `tests/conftest.py`. The fixtures generate realistic delivery-level DataFrames with controlled properties.

| Test File | Coverage | Test Count |
|-----------|----------|------------|
| `test_batting.py` | Batting components, aggregation, avg gate, volume scaling, opposition quality, recency | ~150+ |
| `test_bowling.py` | Bowling components, aggregation, entropy, volume scaling, wicket quality | ~100+ |
| `test_context.py` | Innings context, match context, phase par | ~30+ |
| `test_config.py` | Config loading, dot-notation, defaults, deep merge | ~20+ |
| `test_rating.py` | Shrinkage, confidence bonus, percentile mapping, full pipeline | ~30+ |
| **Total** | | **~397** |

### Running Tests

```
# All tests
python -m pytest tests/ -v

# Single module
python -m pytest tests/test_batting.py -v

# Single test
python -m pytest tests/test_batting.py::test_avg_quality_gate -v

# With coverage
python -m pytest tests/ --cov=src --cov-report=term-missing
```

### Key Fixtures (conftest.py)

| Fixture | Description |
|---------|-------------|
| `synthetic_deliveries_simple` | Basic two-innings match with known batter/bowler stats |
| `synthetic_deliveries_with_phases` | Match with deliveries spread across PP/middle/death |
| `synthetic_multi_match_career` | Multiple matches for career aggregation testing |
| `synthetic_deliveries_with_extras` | Match with wides, no-balls, leg-byes |
| `innings_context_simple` | Pre-built innings context for unit tests |
| `match_context_simple` | Pre-built match context |
| `full_context_simple` | Tuple of (innings_ctx, match_ctx) |

---

## 13. Output Files

### CSV Outputs (Human-Readable)

**`batting_profiles.csv`** — One row per batter, sorted by Acceleration descending:

| Column | Description |
|--------|-------------|
| `batter_id` | Cricsheet registry ID |
| `batter` | Display name |
| `country` | Primary country (team with most matches) |
| `innings_count` | Career innings |
| `total_runs` | Career runs |
| `total_balls` | Career balls faced |
| `career_sr` | Career strike rate |
| `career_avg` | Career batting average |
| `total_fours` | Career fours |
| `total_sixes` | Career sixes |
| `score_acceleration` | 0–100 |
| `score_power` | 0–100 |
| `score_control` | 0–100 |
| `is_provisional_bat` | True if < 10 innings |

**`bowling_profiles.csv`** — One row per bowler, sorted by Accuracy descending:

| Column | Description |
|--------|-------------|
| `bowler_id` | Cricsheet registry ID |
| `bowler` | Display name |
| `country` | Primary country (team with most matches) |
| `matches` | Career matches |
| `total_overs` | Career overs bowled |
| `total_wickets` | Career wickets |
| `career_economy` | Career economy rate |
| `career_sr_bowl` | Career bowling strike rate |
| `score_accuracy` | 0–100 |
| `score_control` | 0–100 |
| `score_threat` | 0–100 |
| `is_provisional_bowl` | True if < 30 overs |

### Parquet Outputs (Full Detail for Website/Analysis)

| File | Rows | Description |
|------|------|-------------|
| `batting_careers_full.parquet` | ~4K | Full career profiles with all intermediate columns |
| `bowling_careers_full.parquet` | ~3K | Full career profiles with all intermediate columns |
| `batting_innings_detail.parquet` | ~51K | Per-innings component breakdown |
| `bowling_spells_detail.parquet` | ~38K | Per-spell component breakdown |

### Diagnostic Outputs

**`potential_duplicates.csv`** — Suspected player ID duplicates for manual review:

| Column | Description |
|--------|-------------|
| `id_a`, `name_a` | First player |
| `id_b`, `name_b` | Second player |
| `team` | Shared team |
| `innings_a`, `innings_b` | Innings counts |
| `reason` | Detection heuristic |

---

## 14. Common Tasks & Recipes

### Tune a metric weight

1. Edit `config.yaml` (e.g., change `bowling_control_weights.vs_others` from 0.35 to 0.40)
2. Ensure weights in that section still sum to 1.0
3. Re-run: `python src/main.py`
4. Compare outputs

### Add a confirmed player duplicate

1. Identify the secondary and canonical IDs from `output/potential_duplicates.csv`
2. Add to `config.yaml`:
   ```yaml
   player_aliases:
     "secondary_registry_id": "canonical_registry_id"
   player_name_overrides:
     "canonical_registry_id": "Preferred Display Name"
   ```
3. Re-run the pipeline

### Look up a specific player programmatically

```python
from src.main import run_pipeline
from src.rating import lookup_player

results = run_pipeline("t20s_male_json")

# By name (fuzzy substring match)
kohli = lookup_player(results["batting_careers"], player_name="Kohli")
bumrah = lookup_player(results["bowling_careers"], player_name="Bumrah",
                       id_col="bowler_id", name_col="bowler")
```

### Run with a different recency half-life

The default half-life is 545 days (~1.5 years). To change it:

```yaml
# In custom_config.yaml
recency:
  enabled: true
  half_life_days: 365  # 1 year instead of 1.5
  min_weight: 0.03     # Floor for very old innings
```

```
python src/main.py --config custom_config.yaml
```

Examples with the default half_life_days=545 (~1.5 years):
- Today         → weight 1.00
- 6 months ago  → weight 0.79
- 1 year ago    → weight 0.63
- 1.5 years ago → weight 0.50
- 3 years ago   → weight 0.25
- 5 years ago   → weight 0.10

This penalises inactive players like SA Yadav more aggressively than the previous 2-year half-life, while still valuing recent peak form.

### Add a new batting sub-component

1. In `compute_batting_components()` in `batting.py`, compute the new column (e.g., `acc_new_signal`)
2. In `aggregate_batting_careers()`, add it to `component_cols` dict and the z-score + weight section
3. Add its weight to `batting_acceleration_weights` in `config.yaml` (ensure sum = 1.0)
4. Add test cases in `test_batting.py`
5. Run: `python -m pytest tests/ -v && python src/main.py`

### Add a new bowling sub-component

Same pattern as batting:
1. Compute in `compute_bowling_components()`
2. Aggregate in `aggregate_bowling_careers()`
3. Configure weight in `config.yaml`
4. Test and run

---

## 15. Design Decisions & Trade-offs

### Why ICC ranking-based opposition weighting?

The existing opposition weighting signals (bowler strength index, PageRank team quality) are computed entirely from the dataset's own stats. ICC T20I team rankings provide an authoritative external signal that captures overall team stature — including factors like squad depth, coaching infrastructure, and consistent competitiveness — that raw in-sample stats alone may not fully reflect. The ICC weight is multiplicative alongside the other signals, giving innings against top-ranked teams (e.g., India, England, Australia) up to a 35% bonus while innings against weak associates receive up to a 50% penalty. A super-linear curve (1.8) concentrates the differentiation toward the top tier. The ratings table is a static config snapshot (updated periodically) rather than a live API call, keeping the pipeline deterministic and reproducible.

### Why a separate match quality weight on top of the ICC opposition weight?

The ICC opposition weight captures "how good is the team you're playing **against**". Match quality captures "how good is the **contest itself**". India vs Australia is a higher-quality match than India vs Uganda, even from India's perspective — the overall fielding standard, tactical depth, and pressure are elevated when both sides are elite. The match quality weight uses the **average** of both teams' ICC ratings, making it symmetric: both sides benefit equally from playing in an elite fixture. Without it, an associate batter scoring against another associate's attack would only be penalised for the opposition's low ranking, not for the overall low quality of the contest.

### Why a post-percentile competition quality gate?

The per-innings ICC ranking and match quality weights adjust **how much** each innings contributes to the career weighted mean. But if a player *only ever* faces weak opposition, every innings — weighted or not — reflects performance against low-quality bowling/batting. The competition quality gate addresses this by applying a direct multiplicative penalty to the **final** 0–100 score based on career-average opponent quality. It uses a sub-linear curve so that Test-nation players (who occasionally face weaker teams in World Cups) lose at most ~3%, while associate players with career-average opponents rated ~100 lose ~18%. This is the single most effective mechanism for preventing inflation of associate-nation scores.

### Why z-score normalisation instead of min-max?

Z-scores are robust to outliers and have a natural interpretation (0 = average, ±1 = one standard deviation). Min-max scaling would make the composite sensitive to a single extreme value. Z-scores also make it straightforward to combine components with different natural scales.

### Why opposition quality uses bowling stats, not batting ratings?

To avoid circular dependencies. If batting ratings depended on bowling ratings (which depended on batting ratings), we'd need iterative convergence. Instead, bowler strength is computed from raw bowling stats (economy, dot %, bowling SR) — simple, interpretable, and independent.

### Why Bayesian shrinkage instead of simple minimum-innings cutoff?

A hard cutoff (e.g., "exclude players with < 10 innings") wastes information. Bayesian shrinkage gracefully handles low sample sizes: a 3-innings player still gets a rating, but it's pulled strongly toward the population mean. As they play more, their true performance dominates. This is the same principle used in chess (Glicko-2), baseball (Marcel projections), and movie recommendation systems.

### Why recency weighting?

T20 cricket evolves rapidly. A batter's 2018 performances on slower pitches with different bowling attacks are less predictive of current ability than their 2023–2024 performances. The exponential decay with a ~1.5-year half-life (545 days) means recent form is weighted ~2× compared to 1.5-year-old form, while very old data still contributes (floor of 0.03). The shorter half-life (previously 2 years / 730 days) more aggressively penalises players who have been inactive, ensuring that a player who hasn't played in 2+ years cannot maintain inflated scores purely from historical performances.

### Why phase-specific par rates?

Death-overs batting has a fundamentally different par strike rate than powerplay batting. Comparing a death-overs SR of 170 against an overall match par of 140 would overstate the performance. Phase-specific pars ensure apples-to-apples comparisons.

### Why not auto-merge detected duplicates?

False positives in player deduplication (merging two different people who share a surname and team) are worse than false negatives (keeping two entries for the same person). The pipeline surfaces suspects and lets humans decide.

### Why `country` uses most-matches-for heuristic?

Some players have represented multiple teams (e.g., due to nationality changes or associate team appearances). Using the team they played the most matches for is the simplest defensible heuristic. Ties are broken deterministically by sort order.

---

## 16. Glossary

| Term | Definition |
|------|-----------|
| **ICC ranking weight** | Multiplicative per-innings weight derived from the opponent's ICC T20I team rating. Normalised against the top-rated team and mapped to a floor–ceiling range via a super-linear power curve (`curve: 1.8`). Stored in `config.yaml` under `icc_ranking`. |
| **Match quality weight** | Symmetric multiplicative per-innings weight derived from the **average** ICC rating of both teams in the match. Rewards performances in contests between two high-ranked teams and penalises matches between two low-ranked teams. Stored in `config.yaml` under `match_quality`. |
| **Competition quality gate** | Post-percentile multiplicative factor that scales down all six scores (batting + bowling) based on a player's career-average opponent ICC rating. Players who primarily face weak opposition have their final 0–100 scores reduced. Stored in `config.yaml` under `competition_quality_gate`. |
| **Delivery** | A single ball bowled. The atomic unit of cricket data. |
| **Innings** | One team's turn to bat (typically ~120 legal deliveries in T20). |
| **Spell** | A bowler's contribution in one innings (may bowl 1–4 overs). |
| **Legal ball** | A delivery that is not a wide or no-ball. Counts toward the over count. |
| **Phase** | Powerplay (overs 0–5), Middle (6–15), Death (16–19). |
| **Match par SR** | Average strike rate across both innings of a match. Proxy for pitch/era difficulty. |
| **Registry ID** | Cricsheet's unique identifier for a player (survives name changes/transliterations). |
| **Provisional** | A player whose rating is heavily influenced by the population mean due to small sample size. Default thresholds: <10 batting innings, <30 bowling overs. |
| **Z-score** | `(value − mean) / std`. Number of standard deviations from the population average. |
| **Bayesian shrinkage** | Pulling individual estimates toward the population mean, weighted by sample size. |
| **Percentile score** | 0–100 value where 50 = median, 99 = top 1%. The final displayed metric. |
| **Opposition quality** | Z-score-scale measure of how strong the bowling attack was that a batter faced. |
| **Team quality** | PageRank-style strength index: win rate weighted by opponent strength, iterated. |
| **Recency weight** | Exponential time-decay: `2^(−days_since / half_life)`. Recent = higher weight. |
| **Average quality gate** | Post-percentile multiplicative factor that reduces ACC/POW scores for low-average batters. |
| **Volume scaling** | Post-percentile multiplicative factor that rewards players with more innings/matches. |
| **Economy vs others** | A bowler's economy minus the other bowlers' economy in the same innings. Negative = better. |
| **Wicket quality** | Position-weighted wicket count: top-order dismissals are worth ~1.5× tailender dismissals. |
| **Run distribution entropy** | Shannon entropy of per-ball runs in a spell. Low entropy + low runs = controlled bowling. |

---

## 17. Changelog

### v3 — Bowling Control Rebalance, Recency Strengthening & Afghanistan Exclusion

#### 1. Bowling Control Weight Rebalance

**Problem:** Death-overs specialists like Arshdeep Singh scored too low on bowling Control (e.g. 32.4). The previous `vs_others` dominance (weight 0.35) unfairly penalised death bowlers whose economy is naturally higher than PP/middle bowlers in the same match, even when their economy is excellent relative to death-overs par.

**Fix:** Rebalanced bowling Control sub-component weights:

| Component | Before | After | Rationale |
|-----------|--------|-------|-----------|
| `economy_vs_par` | 0.20 | **0.30** | Phase-weighted — fairest signal for death bowlers |
| `vs_others` | 0.35 | **0.25** | Still important but no longer dominant |
| `phase_consistency` | 0.10 | **0.15** | Rewards consistent cross-phase performance |
| `extras_pct` | 0.10 | **0.05** | Reduced — overlaps with `extras` component |
| `entropy` | 0.15 | 0.15 | Unchanged |
| `extras` | 0.10 | 0.10 | Unchanged |

All weights still sum to 1.0. The key change is shifting weight from `vs_others` (which compares to other bowlers in the same match — biased against death specialists) to `economy_vs_par` (which compares each phase against its own par — fair across roles).

#### 2. Stronger Recency Weighting

**Problem:** Inactive players like SA Yadav maintained inflated scores from historical performances despite not playing recently.

**Fix:** Reduced recency half-life and min weight floor:

| Parameter | Before | After | Effect |
|-----------|--------|-------|--------|
| `half_life_days` | 730 (2 years) | **545 (~1.5 years)** | Faster decay for old performances |
| `min_weight` | 0.05 | **0.03** | Lower floor for very old innings |

Impact examples:
- 1 year ago: weight 0.71 → **0.63** (−11%)
- 2 years ago: weight 0.50 → **0.37** (−26%)
- 4 years ago: weight 0.25 → **0.14** (−44%)

This ensures players who haven't played in 2+ years see meaningful score reductions.

#### 3. Afghanistan Match & Player Exclusion

All matches involving Afghanistan (as either batting or bowling team) are now filtered out immediately after parsing. This:
- Removes all Afghanistan players from both batting and bowling profiles
- Removes Afghanistan from the ICC match quality ratings table
- Removes Rashid Khan from the spot-check bowlers list
- Removes ~150 matches and ~30,000 deliveries from the dataset

Files changed: `src/main.py` (filtering logic + spot-check update), `config.yaml` (ratings table), `ARCHITECTURE.md`

---

### v2 — Opposition & Competition Quality Overhaul

**Problem:** Performances against and between low-ranked teams were valued too similarly to elite cricket. Associate-nation players scoring against other associates could achieve 99+ percentile scores, outranking established Test-nation stars.

**Three-layer solution:**

#### 1. Match Quality Weight (new concept)

A **symmetric** multiplicative weight based on the average ICC ranking of **both** teams in a match. India vs Australia (~1.19×) is inherently higher quality than Uganda vs PNG (~0.92×), regardless of which side is batting.

- Config section: `match_quality` (`floor: 0.75`, `ceiling: 1.20`, `curve: 1.3`)
- Applied to both batting innings weights and bowling spell weights
- Files changed: `src/batting.py` (new `compute_match_quality_weights` function), `src/bowling.py`

#### 2. Strengthened ICC Ranking Parameters

Widened the floor–ceiling spread and steepened the super-linear curve to create a much larger gap between Test nations and associates:

| Parameter | Before | After | Effect |
|-----------|--------|-------|--------|
| `floor` | 0.55 | **0.50** | Stronger penalty for unranked teams |
| `ceiling` | 1.30 | **1.35** | Stronger bonus for top teams |
| `curve` | 1.5 | **1.8** | Steeper separation between tiers |
| `default_rating` | 30 | **20** | Unknown teams penalised more |

- Combined two-layer effect (ICC ranking × match quality): India batter vs Australia ≈ 1.59×; associate vs associate ≈ 0.54×. Ratio: **2.9×**.

#### 3. Competition Quality Gate (new post-percentile step)

A **post-percentile gate** that directly scales down final 0–100 scores based on the player's **career-average opponent ICC rating**. This is separate from the per-innings weighting — it applies a ceiling on final scores for players who never face strong opponents.

- Config section: `competition_quality_gate` (`base: 0.55`, `curve: 0.5`)
- Sub-linear curve (0.5): barely touches top-nation players (gate ~0.97), significantly penalises weak-opposition careers (gate ~0.82 at avg opponent rating 100)
- Applied to all six scores (batting ACC/POW/CTRL, bowling ACC/CTRL/THR)
- Files changed: `src/batting.py` (new `apply_competition_quality_gate`, `apply_bowling_competition_quality_gate`), `src/main.py`

#### 4. Bowling Weighting Parity

Bowling spell weights now use the same five-layer system as batting. Two layers were added:

- **Team quality weight**: bowling against a strong batting team (PageRank index) is worth more
- **Match quality weight**: spells in matches between two top-ranked teams are worth more

Previously bowling only used recency + ICC ranking.

- Files changed: `src/bowling.py` (`extract_bowling_spells` now accepts `team_quality` parameter)

#### Impact Summary

| Player | Country | Avg Opp ICC | Before ACC | After ACC | Gate |
|--------|---------|-------------|-----------|-----------|------|
| Riazat Ali Shah | Hong Kong | 99.7 | 99.2 | **81.6** | 0.82 |
| V Kohli | India | 242.0 | 83.1 | **81.0** | 0.97 |
| SA Yadav | India | 236.0 | 97.9 | **94.9** | 0.97 |
| Bumrah (bowl ACC) | India | 235.6 | 98.6 | **95.6** | 0.97 |

Top-nation players lose ~3% (fair — they occasionally play weaker sides in World Cups). Associate-nation players facing primarily weak opposition see 15–20% reductions, properly differentiating their scores from elite-cricket performances.

#### Files Changed

| File | Changes |
|------|---------|
| `config.yaml` | Added `match_quality` section; added `competition_quality_gate` section; strengthened `icc_ranking` params (floor/ceiling/curve/default_rating) |
| `src/batting.py` | Added `MATCH_QUALITY_*` and `COMPETITION_GATE_*` constants; added `compute_match_quality_weights()`; added `apply_competition_quality_gate()` and `apply_bowling_competition_quality_gate()`; `extract_batting_innings` now computes `match_quality_weight` and `opp_icc_rating` columns; `aggregate_batting_careers` now tracks `avg_opp_icc_rating` |
| `src/bowling.py` | `extract_bowling_spells` now accepts `team_quality` param and computes `team_quality_weight`, `match_quality_weight`, `opp_icc_rating`; `spell_weight` now uses all four layers; `aggregate_bowling_careers` now tracks `avg_opp_icc_rating` |
| `src/main.py` | Passes `team_quality` to bowling extraction; applies competition quality gate for both batting and bowling; prints ICC ranking and match quality config in summary |
| `tests/test_batting.py` | 20 new tests covering match quality weights (7), competition quality gate (13); updated 5 existing tests to account for new weight layers in `opp_quality_weight` and `spell_weight` |

#### Test Results

423 tests pass (403 original + 20 new). Pipeline runtime unchanged (~25s).

---

*Last updated: 2025. For questions, start by reading the relevant module's docstring — they are comprehensive.*