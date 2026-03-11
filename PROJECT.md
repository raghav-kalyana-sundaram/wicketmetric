# Cricket Metrics — Project Documentation

> **Single source of truth for the entire codebase.**
> Replaces: `README.md`, `ARCHITECTURE.md`, `Version_1.0.md`, `version02.md`, `version03.md`, `documentation.md`, `gui.md`, `HOSTING.md`, `algorithm_update.md`
>
> **Current Version:** 2.0 (post v0.3 implementation)
> **Status:** All 914 tests passing · Full pipeline operational for T20I + IPL
> **Python:** 3.12+ · **Node:** 18+ · **Dependencies:** pandas, numpy, scipy, pyarrow, pyyaml, orjson

---

## Table of Contents

1. [What This Project Does](#1-what-this-project-does)
2. [Quick Start](#2-quick-start)
3. [Repository Layout](#3-repository-layout)
4. [Architecture & Data Flow](#4-architecture--data-flow)
5. [Pipeline Modules](#5-pipeline-modules)
6. [Metric Design](#6-metric-design)
7. [Rating System](#7-rating-system)
8. [Feature Inventory (18 Features)](#8-feature-inventory)
9. [Configuration System](#9-configuration-system)
10. [GUI — Backend (FastAPI)](#10-gui--backend-fastapi)
11. [GUI — Frontend (React + TypeScript)](#11-gui--frontend-react--typescript)
12. [API Reference](#12-api-reference)
13. [Output Files](#13-output-files)
14. [Testing](#14-testing)
15. [Hosting & Deployment](#15-hosting--deployment)
16. [Design Decisions](#16-design-decisions)
17. [Glossary](#17-glossary)
18. [Version History](#18-version-history)
19. [Known Limitations](#19-known-limitations)
20. [Roadmap (v3.0)](#20-roadmap-v30)

---

## 1. What This Project Does

Cricket Metrics is a production-grade T20 cricket analytics platform that transforms raw ball-by-ball Cricsheet JSON data into multi-dimensional player ratings, career profiles, and advanced statistical insights. It covers both **T20I** (international) and **IPL** (franchise) cricket.

**Core capabilities:**

- **3 batting dimensions** (Acceleration, Power, Control) with xR-enhanced components
- **3 bowling dimensions** (Accuracy, Control, Threat) with xR-enhanced components
- **TrueSkill-inspired Bayesian rating system** with uncertainty penalties
- **18 analytical features** (clutch index, matchup shrinkage, WAR, form tracker, peak ratings, venue analysis, era adjustment, etc.)
- **Full-stack web GUI** — interactive player profiles, rankings, head-to-head matchups, team builder, era explorer, venue analysis
- **914 automated tests** across 14 test files with zero failures

The platform processes every T20I and IPL match from Cricsheet data and produces per-player career profiles with percentile-based scores (0–100), letter grades (S/A+/A/B+/B/C+/C/D), role archetypes, and dozens of contextual metrics.

---

## 2. Quick Start

### Prerequisites

- Python 3.12+ with pip
- Node.js 18+ with npm
- Raw Cricsheet JSON data in `t20s_male_json/` (T20I) and/or `ipl_json/` (IPL)

### Run the Pipeline

```bash
# Install Python dependencies
pip install -r requirements.txt

# Run for T20I
python src/main.py                          # reads t20s_male_json/ → output_t20i/

# Run for IPL
python src/main.py --data-dir ipl_json --output-dir output_ipl --format ipl

# Run tests
python -m pytest tests/ -v                  # ~25 seconds, 914 tests
```

### Start the GUI

```bash
# Backend
cd gui/backend
pip install -r requirements.txt
unset OUTPUT_DIR   # auto-discovers output_t20i/ and output_ipl/
uvicorn app:app --reload --port 8000

# Frontend (new terminal)
cd gui/frontend
npm install
npm run dev        # http://localhost:5173
```

### Docker (Full Stack)

```bash
cd gui
docker compose up --build    # Backend on :8000, Frontend on :3000
```

---

## 3. Repository Layout

```
cricket_metrics/
├── PROJECT.md                  # ← This file (single source of truth)
├── config.yaml                 # All tuning constants
├── requirements.txt            # Python dependencies (6 packages)
├── Dockerfile                  # Root-level backend Dockerfile for Railway
├── .dockerignore               # Docker build context exclusions
│
├── src/                        # Analytics pipeline (Python)
│   ├── main.py                 # Pipeline orchestrator
│   ├── parser.py               # Cricsheet JSON → flat deliveries DataFrame
│   ├── context.py              # Match/innings context (par SR, par RR, phases)
│   ├── config.py               # Config loader with deep merge & dot-notation
│   ├── batting.py              # Batting: extraction, components, career aggregation (~2,800 lines)
│   ├── bowling.py              # Bowling: extraction, components, career aggregation (~1,800 lines)
│   ├── expected_value.py       # xR models, RVA, CABI, survival rates (~1,100 lines)
│   ├── rating.py               # Bayesian shrinkage, percentile scoring
│   ├── presentation.py         # Grades, overall scores, archetypes
│   ├── clutch.py               # Pressure tagging, clutch index (932 lines)
│   ├── condition.py            # Condition-Dependence Index (770 lines)
│   ├── era.py                  # Era baselines, cross-era normalisation (758 lines)
│   ├── form_tracker.py         # Rolling-window form series (444 lines)
│   ├── matchups.py             # Head-to-head analysis + Bayesian shrinkage (1,209 lines)
│   ├── peak_ratings.py         # Peak vs current ratings (661 lines)
│   ├── similarity.py           # Cosine-similarity player comparison (548 lines)
│   ├── venue.py                # Venue difficulty, flat-track bully index (710 lines)
│   ├── war.py                  # Positional WAR (595 lines)
│   └── wpa.py                  # Win Probability Added (970 lines)
│
├── tests/                      # 914 tests across 14 files
│   ├── conftest.py             # Shared synthetic fixtures
│   ├── test_batting.py         # 193 tests
│   ├── test_bowling.py         # 76 tests
│   ├── test_config.py          # 73 tests
│   ├── test_context.py         # 14 tests
│   ├── test_presentation.py    # 49 tests
│   ├── test_rating.py          # 38 tests
│   ├── test_v02_phase2.py      # 37 tests (chase splits, anchor cost, selfless)
│   ├── test_v02_phase3.py      # 69 tests (form, peak, similarity)
│   ├── test_v02_phase3b.py     # 93 tests (venue, WAR, era)
│   ├── test_v02_phase4.py      # 66 tests (clutch/pressure)
│   ├── test_v02_phase5.py      # 81 tests (matchups, WPA)
│   └── test_v02_phase6.py      # 94 tests (bowl splits, condition, matchup shrinkage)
│
├── gui/                        # Web GUI
│   ├── docker-compose.yml
│   ├── backend/                # FastAPI Python backend
│   │   ├── app.py              # App entry point & lifespan
│   │   ├── data_loader.py      # Parquet → MultiDataStore (auto-discovers T20I + IPL)
│   │   ├── search_index.py     # Trigram fuzzy search
│   │   ├── schemas.py          # Pydantic response models
│   │   ├── export_static.py    # Static JSON export for GitHub Pages
│   │   ├── requirements.txt
│   │   ├── Dockerfile
│   │   └── routers/
│   │       ├── search.py       # /api/search, /api/autocomplete
│   │       ├── player.py       # /api/player/:id (profile, form, innings, matchups, similar)
│   │       ├── rankings.py     # /api/rankings/bat, /api/rankings/bowl
│   │       ├── compare.py      # /api/compare
│   │       ├── matchups.py     # /api/matchups, /api/h2h
│   │       ├── venues.py       # /api/venues
│   │       ├── eras.py         # /api/eras
│   │       └── team.py         # /api/team/analyse, /api/team/compare
│   │
│   └── frontend/               # React + TypeScript (Vite)
│       ├── src/
│       │   ├── App.tsx         # Router + QueryClient + FormatProvider
│       │   ├── api/            # client.ts, queries.ts, types.ts
│       │   ├── components/     # Layout, PlayerAutocomplete, ScoreBar, GradeBadge, etc.
│       │   ├── hooks/          # useDebounce, useTheme
│       │   ├── lib/            # colours.ts, format.ts
│       │   ├── pages/          # Home, Search, PlayerProfile, Rankings, Compare,
│       │   │                   # Matchups, TeamBuilder, Eras, Venues, Glossary, etc.
│       │   └── styles/         # globals.css (Tailwind layers)
│       ├── vite.config.ts
│       ├── tailwind.config.ts
│       └── package.json
│
├── t20s_male_json/             # Cricsheet T20I source data (~3,000 match JSON files)
├── ipl_json/                   # Cricsheet IPL source data
├── output_t20i/                # Pipeline output: T20I (4,049 batters, 3,006 bowlers)
├── output_ipl/                 # Pipeline output: IPL (703 batters, 551 bowlers)
└── output/                     # Legacy output directory (fallback)
```

---

## 4. Architecture & Data Flow

### Pipeline Flow

```
Cricsheet JSON files (t20s_male_json/ or ipl_json/)
        │
        ▼
   ┌─────────┐
   │ parser  │ → deliveries DataFrame (one row per ball, ~721K rows for T20I)
   └────┬────┘
        │
        ▼
   ┌──────────┐
   │ context  │ → match_ctx (par SR, par RR, boundary rates, phase pars)
   └────┬─────┘   innings_ctx (per-innings stats)
        │
   ┌────┴────────────────────┐
   │                         │
   ▼                         ▼
┌─────────┐            ┌──────────┐
│ batting │            │ bowling  │
│ innings │            │ spells   │
└────┬────┘            └────┬─────┘
     │                      │
     ▼                      ▼
┌──────────┐          ┌──────────┐
│ batting  │          │ bowling  │
│components│          │components│
└────┬─────┘          └────┬─────┘
     │                      │
     ▼                      ▼
┌──────────┐          ┌──────────┐
│ batting  │          │ bowling  │
│ careers  │          │ careers  │
└────┬─────┘          └────┬─────┘
     │                      │
     ├──────────┬───────────┤
     ▼          ▼           ▼
  ┌──────┐ ┌────────┐ ┌────────┐
  │rating│ │ gates  │ │features│
  │system│ │(avg,vol│ │(18 v02 │
  │      │ │,comp) │ │modules)│
  └──┬───┘ └───┬───┘ └───┬────┘
     │         │          │
     └─────────┼──────────┘
               ▼
        ┌────────────┐
        │presentation│ → grades, archetypes, overall scores
        └─────┬──────┘
              │
              ▼
        ┌──────────┐
        │  output  │ → .parquet + .csv files
        └──────────┘
```

### GUI Architecture

```
┌──────────────────────┐         ┌───────────────────────────────┐
│  Frontend (React)    │  ──→    │  Backend (FastAPI + Python)    │
│  Static HTML/JS/CSS  │  /api/* │  Loads Parquet data into RAM   │
│  ~5 MB built         │         │  ~360 MB memory at runtime     │
└──────────────────────┘         └───────────────────────────────┘
                                          ▲
                                          │ reads at startup
                                 ┌────────┴───────────┐
                                 │  output_t20i/ (32MB)│
                                 │  output_ipl/  (13MB)│
                                 └────────────────────┘
```

**Key facts:**

| Concern | Detail |
|---------|--------|
| Backend language | Python 3.12+ (FastAPI + uvicorn) |
| Frontend | Static files (React 18, Vite, TypeScript, Tailwind CSS) |
| Database | **None** — all data is read from Parquet into memory at startup |
| Data size on disk | ~45 MB total (T20I + IPL) |
| Backend RAM | ~360 MB with both formats loaded |
| Startup time | ~1–3 seconds |
| API type | Read-only, stateless, no auth |

### Design Principles

1. **Pure functions:** Every analytical module takes DataFrames in and returns DataFrames out. No side effects, no global state mutation.
2. **Config-driven:** All tuning constants live in `config.yaml` with hardcoded fallback defaults. Pipeline works out-of-the-box with zero configuration.
3. **Graceful degradation:** Optional features (xR models, WPA, era adjustment) are toggled via config. When disabled or data is insufficient, the pipeline fills neutral values rather than crashing.
4. **Context-adjusted everything:** Every metric is normalised against match-level par (par SR, par RR), venue difficulty, opposition quality, and era baselines.

---

## 5. Pipeline Modules

### `parser.py` — Cricsheet JSON → Deliveries DataFrame

Converts Cricsheet JSON match files into a flat DataFrame with one row per ball. Handles all T20 edge cases: super overs, DLS, abandoned matches, penalty runs.

### `context.py` — Match & Innings Context

Computes match-level and innings-level normalisation metrics:
- `match_par_sr` — Average strike rate across both innings (pitch/era normaliser)
- `match_par_rr` — Average run rate
- `match_boundary_rate` — Boundaries per legal ball
- `match_dot_pct` — Dot ball percentage
- Phase-specific par rates (powerplay, middle, death)

### `batting.py` (~2,800 lines) — Batting Analytics

**Innings Extraction:** One row per batter per match with raw stats, context columns (match_par_sr, opposition quality, ICC ranking weights, team quality), recency weights, selfless approach-zone SR, anchor cost (balls_to_par).

**Component Computation:** Transforms raw innings into 3 dimensions:

| Dimension | Sub-Components (weight) |
|-----------|------------------------|
| **Acceleration** | overall_sr (0.15), sr_growth (0.12), death_sr (0.10), impact (0.13), runs_above_expected (0.25), leveraged_rva (0.25) |
| **Power** | boundary_pct (0.12), six_rate (0.15), boundary_rate_vs_par (0.13), peak_phase_sr (0.10), finishing_burst (0.15), power_impact (0.10), cabi (0.25) |
| **Control** | dot_pct_weighted (0.08), rotation (0.08), contribution (0.10), avg_proxy (0.22), dismissal_quality (0.10), scoring_consistency (0.14), survival_ratio (0.28) |

**Career Aggregation:** Opposition-quality-weighted averaging → Z-score normalisation (within position groups if enabled) → weighted composite per dimension → multiplicative average quality gate → volume scaling → competition quality gate.

Also includes: `compute_chase_splits()` (setting vs chasing SR and avg).

### `bowling.py` (~1,800 lines) — Bowling Analytics

Mirror of batting with 3 dimensions:

| Dimension | Sub-Components (weight) |
|-----------|------------------------|
| **Accuracy** | economy_vs_par (0.20), dot_pct (0.20), extras_penalty (0.15), boundary_penalty (0.15), run_yield_variance (0.30) |
| **Control** | economy_vs_par (0.15), vs_others (0.22), entropy (0.10), phase_consistency (0.10), extras (0.08), extras_pct (0.05), bowling_rv (0.30) |
| **Threat** | wickets (0.10), quality_wickets (0.10), sr (0.10), bowled_lbw (0.10), pressure (0.15), dots (0.15), wha (0.30) |

Also includes: `compute_bowling_innings_splits()` (bowl first / bowl second index).

### `expected_value.py` (~1,100 lines) — xR Framework

- `build_expected_value_models()` — GAM-approximated baseline run expectancies
- `compute_context_adjusted_rva()` — Run Value Added per delivery
- `compute_context_adjusted_boundary_index()` — CABI residuals
- `compute_expected_survival_rates()` — Cox-inspired survival analysis
- Win probability lookup tables for both innings

### `rating.py` — Bayesian Rating System

TrueSkill-inspired hierarchical Bayesian rating (see [Section 7](#7-rating-system)).

### `presentation.py` — Grades, Archetypes, Overall Scores

**Grades:** Maps 0–100 scores to letter grades: S (95+), A+ (85+), A (75+), B+ (60+), B (45+), C+ (30+), C (15+), D (0+).

**Overall Score:** Weighted mean of dimension scores with superstar bonus (capped at single best dimension, +5% weight per dimension ≥ 85) and a career production bonus (batting only) that adds up to 2 points based on total career runs (3000+ runs for full bonus). This ensures consistent high-volume producers rank above situational finishers with comparable per-ball metrics. Dimension z-scores use a blended approach (60% within-position-group + 40% population) to keep scores comparable across batting positions.

**Batting Archetypes** (13 types, first-match-wins, up to 3 assigned):

Archetypes are now **position-aware** — `_conditions_match()` supports `position_min` / `position_max` conditions that read the batter's `modal_position` (most frequent batting position, 1–11). This prevents top-order batters with elite ACC+POW from being labelled "Explosive Finisher" when they should be "Explosive Opener".

| Archetype | Key Condition(s) |
|-----------|-----------------|
| Explosive Opener | ACC ≥ 85, POW ≥ 85, position ≤ 3 |
| Explosive Finisher | ACC ≥ 85, POW ≥ 85, position ≥ 4 |
| Power Hitter | POW ≥ 85, CTRL ≤ 50 |
| Pinch Hitter | ACC ≥ 85, CTRL ≤ 45 |
| Aggressive Opener | ACC ≥ 80, POW ≥ 65, position ≤ 3 |
| Power Middle-Order | ACC ≥ 80, POW ≥ 65, position ≥ 4 |
| Classic Anchor | CTRL ≥ 80, ACC ≤ 55 |
| Power Anchor | POW ≥ 75, CTRL ≥ 70 |
| All-Round Elite | ACC ≥ 72, POW ≥ 68, CTRL ≥ 68 |
| Strike Rotator | CTRL ≥ 75, POW ≤ 40 |
| Accumulator | CTRL ≥ 70, ACC ≤ 50, POW ≤ 50 |
| Float | ACC ≥ 60, POW ≥ 55, CTRL ≥ 60 |
| Utility Player | *(fallback)* |

**Bowling Archetypes** (8 types):

| Archetype | Key Condition(s) |
|-----------|-----------------|
| Death Specialist | ACC ≥ 75, CTRL ≥ 75, THR ≥ 70 |
| Powerplay Enforcer | THR ≥ 75, ACC ≥ 70 |
| Strike Bowler | THR ≥ 80 |
| Spin Restrictor | ACC ≥ 80, THR ≤ 55 |
| Economical | ACC ≥ 78, CTRL ≥ 72, THR ≤ 55 |
| All-Round Threat | ACC ≥ 70, CTRL ≥ 70, THR ≥ 70 |
| Restrictive Spinner | ACC ≥ 75, THR ≤ 45 |
| Enforcer | THR ≥ 72, ACC ≥ 55 |

### `main.py` — Pipeline Orchestrator

The `run_pipeline()` function runs 9 steps:

| Step | Description |
|------|-------------|
| 1 | Parse Cricsheet JSON → deliveries DataFrame |
| 2 | Build match/innings context |
| 3 | Extract batting innings + compute components |
| 4 | Extract bowling spells + compute components |
| 5 | Aggregate careers + apply rating system |
| 6 | Apply gates (avg quality, volume, competition) |
| 7 | Compute all 18 features (clutch, chase splits, selfless, form, peak, similarity, venue, WAR, era, matchups, WPA, bowl splits, condition, matchup shrinkage) |
| 8 | Presentation layer (grades, archetypes, overall scores) |
| 9 | Export outputs (Parquet + CSV) |

---

## 6. Metric Design

### Why Three Dimensions Instead of One?

A single number loses too much information. Batters have different roles (anchor vs finisher vs power hitter), and bowlers have different styles (economical vs wicket-taking vs pressure). Three dimensions capture these archetypes:

| Batting Example | ACC | POW | CTRL |
|-----------------|-----|-----|------|
| Explosive finisher (Maxwell) | High | High | Medium |
| Anchor (Kohli) | Medium | Medium | High |
| Balanced (Buttler) | High | High | High |
| Low-average slogger | Medium (gated) | Medium (gated) | Low |

| Bowling Example | ACC | CTRL | THR |
|-----------------|-----|------|-----|
| Death specialist (Bumrah) | High | Very High | High |
| Spin restrictor (Narine) | High | High | Medium |
| Strike bowler (Rabada) | Medium | Medium | Very High |

### Blended Position-Group Z-Scores

Z-scores for all dimension components are computed using a **weighted blend** of within-group (position or phase) and population-wide z-scores:

    blended = α × within_group_z + (1 − α) × population_z     α = 0.6

Pure within-group z-scoring (α = 1.0) makes scores incomparable across position groups — a top-order batter who is average *for an opener* on boundary% would score near zero on Power while a middle-order batter with identical raw stats could score in the 90s. The blend preserves role-aware comparison while ensuring cross-group comparability.

### Context Normalisation

- **SR vs par** uses a ratio (`SR / match_par_sr`), not a difference
- **Phase-specific par**: Death batting is compared to death par, not overall match par
- **Economy vs par** for bowlers uses `economy / match_par_rr`

### Z-Score Normalisation

Before compositing, every sub-component is z-score normalised. When position/phase groups are enabled (the default), a **blended z-score** is used:

    blended = α × within_group_z + (1 − α) × population_z     α = 0.6

This ensures that a top-order batter is still compared primarily to other top-order batters (60% weight), but also retains a meaningful absolute signal from the full population (40% weight). Pure within-group z-scoring (α = 1.0) caused cross-group incomparability — e.g. V Kohli scoring Power = 28 in IPL because he was merely average *for a top-order batter* on boundary%, while a middle-order batter with similar raw stats scored 96.

Missing values are filled with 0 (population average).

### Five-Layer Opposition Weighting

Innings are weighted during career aggregation:

```
innings_weight = opp_bowling_quality × opp_team_quality × icc_ranking_weight
                 × match_quality_weight × recency_weight
```

1. **Opposition bowling quality**: Average bowler strength faced → up to 1.30× weight for elite attacks
2. **Team quality**: Iterative PageRank-style index from win rates → up to 1.25× weight
3. **ICC ranking weight**: `floor + (ceiling − floor) × (rating/max_rating)^curve` — India → ~1.35, Oman → ~0.87, Unranked → ~0.51
4. **Match quality weight**: Average of both teams' ICC ratings (symmetric) — India vs Australia → ~1.19, Uganda vs PNG → ~0.92
5. **Recency**: `2^(−days_since / half_life)` with 545-day (~1.5 year) half-life and 0.03 floor

Combined effect: recent innings against a top team with a strong attack in a high-quality match → ~1.59 weight; associate vs associate → ~0.54 weight.

### Post-Percentile Gates

After the rating system produces 0–100 scores, three multiplicative gates adjust final scores:

1. **Average Quality Gate** (batting only): Penalises low-average sloggers — reduces ACC/POW scores for batters with sub-par career averages
2. **Volume Scaling**: Penalises small sample sizes (uses `log1p(innings) / log1p(ref_innings)`)
3. **Competition Quality Gate**: Directly scales down scores based on career-average opponent ICC rating — players facing mostly weak opposition lose 10–30%, top-nation players lose ≤3%

---

## 7. Rating System

Converts raw z-score composites to displayed 0–100 scores. Applied identically to batting and bowling.

```
raw composite (z-score, unbounded)
  │
  ▼  Step 1: Bayesian shrinkage
adjusted = (n × raw + k × pop_mean) / (n + k)     k=12 bat, k=10 bowl
  │
  ▼  Step 2: Confidence bonus
adjusted × (1 + 0.03 × ln(1+n) / ln(1+100))
  │
  ▼  Step 3: Percentile mapping → 0–100 score
  │
  ▼  Step 4: Average quality gate (batting only)
  │
  ▼  Step 5: Volume scaling (with beyond-reference bonus)
  │
  ▼  Step 6: Competition quality gate
  │
  ▼  Step 7: Overall score (superstar bonus + career production bonus)
  │
  ▼
FINAL DISPLAYED SCORE (0–100)
```

**Shrinkage by sample size:**

| Innings | Own Data | Population Mean |
|---------|----------|----------------|
| 1 | 8% | 92% |
| 5 | 29% | 71% |
| 12 | 50% | 50% |
| 25 | 68% | 32% |
| 50 | 81% | 19% |
| 100 | 89% | 11% |

**Volume scaling (post-percentile):**

Applied to all three dimension scores. Uses a base floor + power curve up to the reference innings, then a linear beyond-reference bonus for high-volume players:

| Innings | Factor | Effect |
|---------|--------|--------|
| 10 | ~0.79 | 21% penalty |
| 19 | ~0.83 | 17% penalty |
| 30 | ~0.86 | 14% penalty |
| 50 | ~0.91 | 9% penalty |
| 75 | ~0.96 | 4% penalty |
| 100 | 1.00 | no penalty |
| 120 | ~1.01 | 1% bonus |
| 150 | ~1.03 | 3% bonus |
| 200+ | 1.06 | 6% bonus (max) |

**Overall score (batting):**

The overall score combines the three dimension scores with two bonuses:
- **Superstar bonus** (weight 0.05): if any dimension exceeds 85, the single best dimension's excess is added at 5% weight.
- **Career production bonus** (max 2.0 points): additive bonus based on total career runs — `bonus = 2.0 × clip(runs / 3000, 0, 1)^0.8`. Players with 3000+ runs get the full 2-point bonus; a 700-run finisher gets ~0.6 points.

---

## 8. Feature Inventory

| # | Feature | Module | Description |
|---|---------|--------|-------------|
| 1 | Grades | `presentation.py` | S/A+/A/B+/B/C+/C/D letter grades from 0–100 scores |
| 2 | Archetypes | `presentation.py` | 11 batting + 8 bowling archetypes (up to 3 per player) |
| 3 | Clutch Index | `clutch.py` | Delivery-level pressure tagging; composite performance delta under pressure vs normal |
| 4 | Head-to-Head Matchups | `matchups.py` | Batter × bowler matchup aggregation with dominance index and phase breakdowns |
| 5 | Peak vs Current | `peak_ratings.py` | Recency-free career aggregate + sliding 2-year window peak |
| 6 | Chase Master Index | `batting.py` | Setting vs chasing SR and avg splits |
| 7 | Similarity Engine | `similarity.py` | Cosine similarity on z-normalised career component vectors |
| 8 | Selfless Index | `batting.py` | Milestone approach-zone SR (40–49, 90–99) — selfless vs stat-padder |
| 9 | Venue Difficulty | `venue.py` | Per-venue baselines + flat-track bully index |
| 10 | Win Probability Added | `wpa.py` | Empirical WP models + per-delivery WPA scoring (disabled by default) |
| 11 | Anchor Cost | `batting.py` | Balls-to-par: deliveries before cumulative SR reaches match par |
| 12 | Wicket Quality | `bowling.py` | Position-weighted wickets (top-order worth ~1.5× tailenders) |
| 13 | Form Tracker | `form_tracker.py` | Rolling-window batting/bowling form time-series |
| 14 | Positional WAR | `war.py` | Value above replacement within position/phase group |
| 15 | Era Adjustment | `era.py` | Cross-era normalisation with rolling 3-year windows (disabled by default) |
| 16 | Bowl Splits | `bowling.py` | Bowl first / bowl second index |
| 17 | Condition Dependence | `condition.py` | Flat-track bully / tough-track star detection via Pearson correlation |
| 18 | Matchup Shrinkage | `matchups.py` | Bayesian Empirical Bayes shrinkage of sparse matchup data toward archetype baselines |

---

## 9. Configuration System

### How It Works

1. `src/config.py` defines `_DEFAULTS` — the complete set of hardcoded defaults
2. `config.yaml` provides user overrides (optional)
3. `_deep_merge(_DEFAULTS, yaml_overrides)` produces the final config
4. `cfg("dotted.key.path")` provides module-level singleton access

**Important:** For weight dicts (which must sum to 1.0), you must provide ALL keys in your YAML override because merge adds your values on top of default keys.

### Key Config Sections

| Section | Purpose |
|---------|---------|
| `pipeline.*` | Min innings/overs thresholds |
| `rating.*` | Shrinkage k, confidence alpha |
| `batting_acceleration_weights` | ACC dimension weights (6 keys, sum=1.0) |
| `batting_power_weights` | POW dimension weights (7 keys, sum=1.0) |
| `batting_control_weights` | CTRL dimension weights (7 keys, sum=1.0) |
| `bowling_accuracy_weights` | ACC dimension weights (5 keys, sum=1.0) |
| `bowling_control_weights` | CTRL dimension weights (7 keys, sum=1.0) |
| `bowling_threat_weights` | THR dimension weights (7 keys, sum=1.0) |
| `batting_avg_quality.*` | Average quality gate parameters |
| `batting_volume.*` | Volume scaling |
| `icc_ranking.*` | Per-team ICC rating values and curve parameters |
| `match_quality.*` | Symmetric match quality weighting |
| `recency.*` | Time-decay half-life (default 545 days) |
| `clutch.*` | Pressure thresholds |
| `matchups.*` | Min balls, top-K bunnies/dominant |
| `form_tracker.*` | Window sizes (default 8 bat, 10 bowl) |
| `war.*` | Replacement percentile (default 25th) |
| `wpa.*` | WPA model parameters (disabled by default) |
| `era_adjustment.*` | Era normalisation (disabled by default) |
| `condition_dependence.*` | CDI parameters |
| `matchup_shrinkage.*` | Bayesian shrinkage balls (default 30) |

### Common Recipes

**Tune a metric weight:**
1. Edit `config.yaml` (e.g., `bowling_control_weights.vs_others: 0.40`)
2. Ensure weights sum to 1.0
3. Re-run: `python src/main.py`

**Change recency half-life:**
```yaml
recency:
  enabled: true
  half_life_days: 365   # 1 year instead of 1.5
  min_weight: 0.03
```

**Add a player alias (deduplication):**
```yaml
player_aliases:
  "secondary_registry_id": "canonical_registry_id"
player_name_overrides:
  "canonical_registry_id": "Preferred Display Name"
```

---

## 10. GUI — Backend (FastAPI)

### Data Loading

`data_loader.py` implements `MultiDataStore` — auto-discovers `output_t20i/` and `output_ipl/` directories at startup. Each format gets its own `DataStore` with all DataFrames loaded into memory. The `?format=` query parameter selects which dataset to query.

### DataFrames Loaded at Startup

| Variable | Source File | Rows (T20I) | Key Columns |
|----------|-----------|-------------|-------------|
| `bat_careers` | `batting_careers_full.parquet` | ~4K | scores, grades, archetype(s), peak ratings, WAR, clutch, chase splits, etc. |
| `bowl_careers` | `bowling_careers_full.parquet` | ~3K | scores, grades, archetype(s), peak ratings, WAR, clutch, etc. |
| `bat_innings` | `batting_innings_detail.parquet` | ~51K | per-innings stats with all component columns |
| `bowl_spells` | `bowling_spells_detail.parquet` | ~38K | per-spell stats |
| `bat_form` | `batting_form_series.parquet` | ~150K | rolling window form series |
| `bowl_form` | `bowling_form_series.parquet` | ~100K | rolling window form series |
| `bat_sim` | `batting_similarities.parquet` | ~40K | top-K similar batters |
| `bowl_sim` | `bowling_similarities.parquet` | ~25K | top-K similar bowlers |
| `matchups` | `matchups.parquet` | variable | batter × bowler matchup stats + dominance |
| `matchups_phase` | `matchups_by_phase.parquet` | variable | phase-level matchups |
| `venue` | `venue_baselines.parquet` | ~200 | per-venue difficulty scores |

### Search Index

Trigram-based fuzzy matching built at startup from all player names. Supports exact substring, fuzzy matching ("Bumra" → "JJ Bumrah"), and country-filtered search.

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OUTPUT_DIR` | *(auto-discover)* | Path to pipeline output directory |
| `PORT` | `8000` | Server port |
| `HOST` | `0.0.0.0` | Server host |

---

## 11. GUI — Frontend (React + TypeScript)

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Framework | React 18 + TypeScript |
| Routing | React Router v6 |
| State | TanStack Query (React Query) |
| Charts | Recharts + D3 (custom radar/spider) |
| Styling | Tailwind CSS + shadcn/ui |
| Build | Vite |

### Pages & Routes

| Route | Page | Description |
|-------|------|-------------|
| `/` | Home | Dashboard with hero search, leaderboard cards |
| `/search` | Search | Player search with filters |
| `/player/:id` | Player Profile | Full player profile (batting + bowling) |
| `/player/:id/innings` | Innings Log | Paginated batting innings log |
| `/player/:id/spells` | Spells Log | Paginated bowling spells log |
| `/rankings` | Rankings | Leaderboards with sorting, filtering, pagination |
| `/compare?ids=...` | Compare | Side-by-side comparison (2–4 players), role-aware radar |
| `/matchups` | Matchups | Head-to-head lookup and matchup explorer |
| `/similar/:id` | Similar Players | Cosine-similarity nearest neighbours |
| `/team-builder` | Team Builder | Build hypothetical XI, team vs team compare mode |
| `/eras` | Era Explorer | Timeline with par SR, boundary rate, avg RR, predicted score |
| `/venues` | Venue Analysis | Venue difficulty and flat-track index |
| `/glossary` | Glossary | Metric definitions and methodology |

### Key Components

| Component | Description |
|-----------|-------------|
| `<FormatToggle>` | T20I/IPL format switcher (pill toggle in nav, only shows when >1 format) |
| `<PlayerAutocomplete>` | Fuzzy search input with dropdown suggestions |
| `<ScoreBar>` | Horizontal 0–100 bar with colour gradient (S=gold → D=red) |
| `<GradeBadge>` | Letter grade chip with colour coding |
| `<ArchetypeBadge>` | Archetype label with icon (supports multiple archetypes with opacity fade) |
| `<MetricTooltip>` | Hover tooltip with plain-English metric explanations |
| `<FormSparkline>` | Mini inline time-series chart for form indication |
| `<ExportButton>` | CSV / PNG / shareable URL export |
| `<ThemeToggle>` | Dark/light mode toggle with OS preference detection |

### Score Colour Mapping

| Score Range | Colour | Grade |
|-------------|--------|-------|
| 95–100 | Gold (#FFD700) | S |
| 85–94 | Emerald (#10B981) | A+ |
| 75–84 | Green (#22C55E) | A |
| 60–74 | Cyan (#06B6D4) | B+ |
| 45–59 | Blue (#3B82F6) | B |
| 30–44 | Amber (#F59E0B) | C+ |
| 15–29 | Orange (#F97316) | C |
| 0–14 | Red (#EF4444) | D |

### Frontend Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_URL` | `http://localhost:8000` | Backend API base URL |

---

## 12. API Reference

All endpoints return JSON. The API is read-only and stateless. All endpoints accept an optional `?format=t20i|ipl` query parameter.

### Meta & Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check (status, loaded formats) |
| `GET` | `/api/meta` | Dataset metadata (counts, countries, archetypes) |
| `GET` | `/api/formats` | List available formats (e.g., `["t20i", "ipl"]`) |

### Search

| Method | Path | Params | Description |
|--------|------|--------|-------------|
| `GET` | `/api/search` | `q`, `role`, `country`, `archetype`, `limit` | Full-text search |
| `GET` | `/api/search/autocomplete` | `q` | Lightweight autocomplete |
| `GET` | `/api/search/countries` | — | All countries in dataset |
| `GET` | `/api/search/archetypes` | — | Archetype lists by role |

### Player

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/player/:id` | Full profile (auto-detects bat/bowl) |
| `GET` | `/api/player/:id/batting` | Batting-specific profile |
| `GET` | `/api/player/:id/bowling` | Bowling-specific profile |
| `GET` | `/api/player/:id/innings` | Paginated batting innings log |
| `GET` | `/api/player/:id/spells` | Paginated bowling spells log |
| `GET` | `/api/player/:id/form` | Form time-series |
| `GET` | `/api/player/:id/matchups` | Paginated matchup list |
| `GET` | `/api/player/:id/similar` | Similar players |

### Rankings

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/rankings/bat` | Batting leaderboard (paginated, sortable, filterable) |
| `GET` | `/api/rankings/bowl` | Bowling leaderboard |
| `GET` | `/api/rankings/top` | Top N by any metric |
| `GET` | `/api/rankings/columns/bat` | Available sort columns for batting |
| `GET` | `/api/rankings/columns/bowl` | Available sort columns for bowling |

### Comparison

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/compare?ids=...` | Side-by-side profile comparison (2–4 players) |
| `GET` | `/api/compare/form?ids=...` | Overlaid form time-series |
| `GET` | `/api/compare/shared-matchups?ids=...` | Shared matchup opponents |

### Matchups

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/matchups?bat=...&bowl=...` | Head-to-head matchup detail |
| `GET` | `/api/matchups/explore?player_id=...&role=...` | Paginated matchup explorer |
| `GET` | `/api/matchups/top-bunnies?bowler_id=...` | Top bunny matchups |
| `GET` | `/api/matchups/top-nemeses?batter_id=...` | Top nemesis matchups |
| `GET` | `/api/matchups/top-dominant?batter_id=...` | Top dominant matchups |

### Venues

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/venues` | All venues with baselines |
| `GET` | `/api/venues/detail?venue=...` | Single venue detail |
| `GET` | `/api/venues/players?venue=...&role=...` | Player performance at a venue |
| `GET` | `/api/venues/flat-track-index` | Flat-track bully leaderboard |

### Eras

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/eras` | Era baselines by year (par SR, boundary rate, dot %, multiplier) |

### Team Builder

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/team/analyse?ids=...` | Aggregate team analysis (avg scores, WAR, weaknesses) |
| `GET` | `/api/team/compare?a=...&b=...` | Team vs team comparison with edge indicators |
| `GET` | `/api/team/auto-fill?strategy=...` | Auto-fill XI suggestions |

---

## 13. Output Files

### CSV Outputs

| File | Description |
|------|-------------|
| `batting_profiles.csv` | One row per batter: IDs, career stats, 0–100 scores, grades, archetypes |
| `bowling_profiles.csv` | One row per bowler: IDs, career stats, 0–100 scores, grades, archetypes |
| `era_summary.csv` | Per-year era baselines (human-readable) |
| `potential_duplicates.csv` | Suspected player ID duplicates for manual review |

### Parquet Outputs

| File | Rows (T20I) | Description |
|------|-------------|-------------|
| `batting_careers_full.parquet` | ~4K | Complete batting career profiles with all intermediate columns |
| `bowling_careers_full.parquet` | ~3K | Complete bowling career profiles |
| `batting_innings_detail.parquet` | ~51K | Per-innings component breakdown |
| `bowling_spells_detail.parquet` | ~38K | Per-spell component breakdown |
| `batting_form_series.parquet` | ~150K | Rolling-window batting form time-series |
| `bowling_form_series.parquet` | ~100K | Rolling-window bowling form time-series |
| `batting_similarities.parquet` | ~40K | Top-K similar batters |
| `bowling_similarities.parquet` | ~25K | Top-K similar bowlers |
| `matchups.parquet` | variable | Batter × bowler head-to-head matchups |
| `matchups_by_phase.parquet` | variable | Phase-level matchup breakdowns |
| `venue_baselines.parquet` | ~200 | Per-venue difficulty scores |
| `era_baselines.parquet` | — | Year-by-year era baselines |
| `batting_condition_terciles.parquet` | — | Per-batter condition tercile splits |

### Key DataFrame Schemas

**Batting Careers:** `batter_id`, `batter`, `country`, `innings_count`, `total_runs`, `total_balls`, `career_sr`, `career_avg`, `raw_acceleration`, `raw_power`, `raw_control`, `score_acceleration`, `score_power`, `score_control`, `grade_overall`, `archetype`, `archetypes`, `war_batting`, `clutch_index`, `chase_master_index`, `flat_track_index`, `peak_acceleration`, `peak_power`, `peak_control`, `is_provisional_bat`, `position_group`, `setting_sr`, `setting_avg`, `chasing_sr`, `chasing_avg`, …

**Bowling Careers:** `bowler_id`, `bowler`, `country`, `matches`, `total_overs`, `total_wickets`, `career_economy`, `career_sr_bowl`, `score_accuracy`, `score_control`, `score_threat`, `grade_overall`, `archetype`, `war_bowling`, `clutch_index_bowl`, `bowl_first_index`, `bowl_second_index`, `is_provisional_bowl`, …

---

## 14. Testing

### Test Suite

914 tests across 14 files, all passing. Tests use **synthetic fixtures** (no real match data required) defined in `tests/conftest.py`.

```
tests/test_batting.py          — 193 tests
tests/test_bowling.py          —  76 tests
tests/test_config.py           —  73 tests
tests/test_context.py          —  14 tests
tests/test_presentation.py     —  49 tests
tests/test_rating.py           —  38 tests
tests/test_v02_phase2.py       —  37 tests (chase splits, anchor cost, selfless)
tests/test_v02_phase3.py       —  69 tests (form, peak, similarity)
tests/test_v02_phase3b.py      —  93 tests (venue, WAR, era)
tests/test_v02_phase4.py       —  66 tests (clutch/pressure)
tests/test_v02_phase5.py       —  81 tests (matchups, WPA)
tests/test_v02_phase6.py       —  94 tests (bowl splits, condition, matchup shrinkage)
────────────────────────────────────────────
TOTAL                          — 914 tests, ALL PASSING
```

### Running Tests

```bash
python -m pytest tests/ -v                          # Full suite (~25s)
python -m pytest tests/test_batting.py -v           # Single module
python -m pytest tests/ --cov=src --cov-report=term-missing  # With coverage
```

### Key Fixtures

| Fixture | Description |
|---------|-------------|
| `synthetic_deliveries_simple` | Basic two-innings match with known batter/bowler stats |
| `synthetic_deliveries_with_phases` | Match with deliveries across PP/middle/death |
| `synthetic_multi_match_career` | Multiple matches for career aggregation testing |
| `synthetic_deliveries_with_extras` | Match with wides, no-balls, leg-byes |
| `innings_context_simple` | Pre-built innings context for unit tests |
| `match_context_simple` | Pre-built match context |

---

## 15. Hosting & Deployment

### Architecture for Hosting

The app has two parts: a **static frontend** (~5 MB) and a **Python backend** (~360 MB RAM, reads Parquet at startup, no database). Both are containerised.

### Option A: Railway (Recommended — Easiest)

1. Push repo to GitHub (include `output_t20i/` and `output_ipl/` in the repo)
2. Create Railway project → add Backend service (root Dockerfile, port 8000)
3. Add Frontend service (gui/frontend/Dockerfile, set `VITE_API_URL` to backend URL)
4. Add backend production domain to CORS in `gui/backend/app.py`

### Option B: Docker Compose (Any Server)

```bash
cd gui
docker compose up --build    # Backend :8000, Frontend :3000
```

### Option C: Vercel (Frontend) + Railway (Backend)

Frontend as static site on Vercel/Cloudflare Pages (free), backend on Railway/Render.

### Option D: VPS (DigitalOcean, Hetzner)

Nginx reverse proxy → uvicorn backend + static frontend build. See the `Dockerfile` and `gui/frontend/Dockerfile` for container setup.

### Key Deployment Notes

- Backend auto-discovers `output_t20i/` and `output_ipl/` — do **not** set `OUTPUT_DIR`
- Frontend needs `VITE_API_URL` set at **build time** (it's baked into the static bundle)
- Backend CORS: add your frontend domain to `allow_origins` in `gui/backend/app.py`
- RAM requirement: ~360 MB with both T20I and IPL loaded
- The root-level `Dockerfile` is designed for Railway (copies data into image)
- `gui/backend/Dockerfile` is for local dev (expects data mounted as volumes)

### Troubleshooting

| Problem | Solution |
|---------|----------|
| "Available formats: ['t20i']" — IPL missing | Ensure `output_ipl/` is in the Docker build context |
| Backend crashes with "Killed" / OOM | Need ≥512 MB RAM |
| CORS errors in browser | Add frontend domain to `allow_origins` in `app.py` |
| Frontend shows loading skeletons | Backend isn't returning data — check `/api/health` |
| Form Tracker flat line | Pipeline data may be stale — re-run pipeline |

---

## 16. Design Decisions

| Decision | Rationale |
|----------|-----------|
| **ICC ranking-based opposition weighting** | External authoritative signal capturing squad depth, coaching, competitiveness beyond raw in-sample stats |
| **Separate match quality weight** | Captures contest quality (both teams elite) vs just opponent strength |
| **Post-percentile competition quality gate** | Prevents inflation for players who only face weak opposition |
| **Z-score over min-max** | Robust to outliers, natural interpretation (0 = average), combines different scales |
| **Opposition quality uses bowling stats, not batting ratings** | Avoids circular dependency between batting and bowling ratings |
| **Bayesian shrinkage over minimum-innings cutoff** | Gracefully handles low samples (3-innings player gets a rating, pulled toward mean) |
| **Recency weighting (545-day half-life)** | T20 evolves fast; recent form 2× more predictive than 1.5-year-old data |
| **Phase-specific par rates** | Death SR of 170 vs overall par of 140 would overstate performance |
| **No auto-merge duplicates** | False positives (merging different people) worse than false negatives |
| **FastAPI over JS backend** | Same language as pipeline; native Parquet/pandas support; no ETL needed |
| **No database** | All data fits in memory (~360 MB); sub-millisecond queries; zero infrastructure |
| **Superstar bonus capped at max** | Prevents explosive finishers from inflating overall score via sum of bonuses |
| **Responsibility multiplier on control** | Batters facing more balls (avg 75+ balls/inn) get up to 15% control bonus |

---

## 17. Glossary

| Term | Definition |
|------|-----------|
| **Delivery** | A single ball bowled (the atomic unit of cricket data) |
| **Innings** | One team's turn to bat (typically ~120 legal deliveries in T20) |
| **Spell** | A bowler's contribution in one innings (1–4 overs) |
| **Phase** | Powerplay (overs 0–5), Middle (6–15), Death (16–19) |
| **Match par SR** | Average strike rate across both innings — proxy for pitch/era difficulty |
| **Registry ID** | Cricsheet's unique identifier for a player |
| **Provisional** | Player whose rating is heavily shrunk toward population mean (<10 batting innings or <30 bowling overs) |
| **Z-score** | `(value − mean) / std` — number of standard deviations from average |
| **Bayesian shrinkage** | Pulling individual estimates toward population mean, weighted by sample size |
| **Percentile score** | 0–100 value where 50 = median, 99 = top 1% |
| **ICC ranking weight** | Multiplicative per-innings weight from opponent's ICC T20I team rating |
| **Match quality weight** | Symmetric weight from average ICC rating of both teams |
| **Competition quality gate** | Post-percentile multiplicative penalty based on career-avg opponent quality |
| **Average quality gate** | Multiplicative penalty for low-average batters (reduces ACC/POW scores) |
| **Volume scaling** | Multiplicative factor rewarding players with more innings/matches |
| **Recency weight** | Exponential time-decay: `2^(−days/half_life)` |
| **Economy vs others** | Bowler's economy minus other bowlers' economy in the same innings |
| **Wicket quality** | Position-weighted wicket count (top-order ~1.5× tailenders) |
| **Dominance index** | Composite matchup measure: SR premium + boundary bonus − dot penalty − dismissal rate |
| **WAR** | Wins Above Replacement — value above the replacement-level player in the same role |
| **Clutch index** | Performance composite under pressure minus performance under normal conditions |
| **Flat-track bully index** | Pearson correlation of performance vs pitch difficulty (positive = bully) |
| **CDI** | Condition Dependence Index — measures if performance spikes in favourable conditions |
| **CABI** | Context-Adjusted Boundary Index — boundary hitting residual after adjusting for context |
| **RVA** | Run Value Added — per-delivery expected runs contribution from xR framework |
| **WHA** | Wicket Hazard Added — bowling equivalent, measures added dismissal probability |

---

## 18. Version History

### v0.1 — Core Engine

- Parser, context, batting, bowling modules
- 3-dimension rating system with Bayesian shrinkage
- Basic pipeline producing CSV profiles

### v0.2 — Feature Expansion (18 Features)

All 18 analytical features implemented:
1. Grades & Archetypes (`presentation.py`)
2. Clutch / Pressure Index (`clutch.py`)
3. Head-to-Head Matchups + Bayesian Shrinkage (`matchups.py`)
4. Peak vs Current Ratings (`peak_ratings.py`)
5. Chase Master Index, Selfless Index, Anchor Cost (`batting.py`)
6. Form Tracker (`form_tracker.py`)
7. Player Similarity Engine (`similarity.py`)
8. Venue & Pitch Difficulty (`venue.py`)
9. Win Probability Added (`wpa.py`)
10. Positional WAR (`war.py`)
11. Era-Adjusted Ratings (`era.py`)
12. Bowl First / Bowl Second Index (`bowling.py`)
13. Condition-Dependence Metrics (`condition.py`)

Test count: 914 tests, all passing.

### v1.0 — Stability Release

- Fixed critical `KeyError: match_par_sr` crash in condition dependence
- Fixed config weight dict sums (6/6 now sum to 1.0)
- Fixed archetype ordering (Float no longer matches before specific types)
- Graceful handling of missing xR columns
- All 914 tests passing, 0 runtime errors

### v0.3 / v2.0 — GUI & IPL Support

Major features implemented:
1. **IPL Dataset Support** — Full pipeline run on IPL data (703 batters, 551 bowlers), `MultiDataStore` with format toggle
2. **Rating Rebalance** — Superstar bonus capped at max (not sum), weight reduced 0.15→0.10; control weights rebalanced; responsibility multiplier for high-volume batters
3. **Multiple Archetypes** — Up to 3 archetypes per player with comma-separated storage
4. **Team vs Team Comparison** — Compare mode in Team Builder with edge indicators
5. **Role-Aware Compare** — Auto/bat/bowl view modes, separate radar axes per role
6. **Era Timeline Enhancements** — Avg run rate, predicted score metrics with toggles
7. **Form Tracker Y-Axis Fix** — Auto-scales with 15% padding
8. **Bowling Median Fix** — Excludes non-bowlers from percentile computations
9. **Customisable Slot Positions** — 6 slot types in Team Builder, persisted in URLs
10. **Chase Splits Tuning** — Actual SR and avg per split (not just differential indices)
11. **Hover Tooltips on Compare Page** — MetricLabel component with explanations
12. **Exclude Tail-Enders** — Genuine-batter/bowler filters for team analysis
13. **Preserve Batting Order in Shared URLs** — Promise.all order preservation

### Deployment History

- Backend deployed on Railway (uvicorn, port 8080)
- Frontend deployed separately (Vite build, serve)
- Fixed CORS configuration, Docker build context, serve@13 CLI compatibility
- Production: `VITE_API_URL` baked into frontend build pointing at backend domain

---

## 19. Known Limitations

| Limitation | Detail |
|------------|--------|
| **Type-checking diagnostics** | ~500+ pyright warnings due to pandas typing ambiguity — not runtime errors |
| **WPA disabled by default** | Computational cost; enable with `wpa.enabled: true` |
| **Era adjustment disabled** | Primarily benefits historical cross-decade analysis |
| **No mixed-effects models** | Uses Pearson correlation and Empirical Bayes rather than full multilevel regression |
| **No deep learning embeddings** | Similarity uses cosine similarity on z-normalised vectors (works excellently without ML dependencies) |
| **ICC ratings are static** | Stored in `config.yaml`, need periodic manual updates |
| **No bowling style data** | Cricsheet JSON doesn't include pace/spin classification |
| **IPL dataset smaller** | 703 batters / 551 bowlers vs 4,049 / 3,006 for T20I |

---

## 20. Roadmap (v3.0)

The following changes are planned for v3.0.

### ~~Archetype Classification Fix~~ ✅ Done
**Problem:** Openers (Abhishek Sharma, Chris Gayle, etc.) were being labelled as "Explosive Finisher" because the archetype system only checked score thresholds (ACC ≥ 85, POW ≥ 85), not batting position.
**Fix:** Added `position_min` / `position_max` conditions to `_conditions_match()` in `presentation.py`. "Explosive Finisher" now requires `position ≥ 4`. New "Explosive Opener" archetype (ACC ≥ 85, POW ≥ 85, position ≤ 3) for top-order power hitters. "Aggressive Opener" gated to position ≤ 3; new "Power Middle-Order" for position ≥ 4. Updated `team.py` `_BATTING_ARCHETYPES` set and `ArchetypeBadge.tsx` icons/colours for new archetypes.

### ~~Rating Rebalance — Reduce Finisher Overvaluation~~ ✅ Done
**Problem:** Two related issues causing finisher overvaluation and cross-position score incomparability:
1. The system undervalued volume and sustained production. In T20I, Dhoni (82 inn, 1584 runs) scored 93.6 overall vs Kohli (112 inn, 3969 runs) at 89.2. Low-volume finishers like KD Karthik (47 inn, 686 runs) reached 95.5 overall.
2. Within-position-group z-scoring made scores incomparable across groups. In IPL, V Kohli (top_order, boundary_pct=0.515) got Power=28.8 because he was merely average *for a top-order batter*, while RG Sharma (upper_middle, boundary_pct=0.598) got Power=95.6 because he was elite *for a middle-order batter*. Overall gap: Rohit 88.7 vs Kohli 74.1 despite Kohli having more runs, higher avg, and higher SR.

**Fix:** Four-pronged rebalance:
1. **Strengthened volume scaling** (`batting.py`, `bowling.py`, `config.yaml`): lowered `VOLUME_BASE` 0.80→0.70 (bigger penalty for low-volume), raised `VOLUME_REF` 50→100 (reward extends further), lowered `VOLUME_CURVE` 0.6→0.5, and added a beyond-reference bonus (`VOLUME_BEYOND_MAX=0.06`) so players exceeding the reference innings get up to 6% additional scaling. A 50-innings player now sees a ~9% penalty (was 0%), while a 140-innings player gets a ~4% bonus (was 0%).
2. **Reduced superstar bonus** (`presentation.py`): `superstar_bonus_weight` reduced 0.10→0.05, halving the outsized uplift that explosive finishers with both ACC and POW above 85 received.
3. **Career production bonus** (`presentation.py`): new `_career_production_bonus()` adds up to 2 points to the overall score based on total career runs (`RUNS_BONUS_MAX=2.0`, `RUNS_BONUS_REF=3000`, `RUNS_BONUS_CURVE=0.8`). Players with 3000+ runs get the full bonus; a 700-run finisher gets ~0.6 points. This directly rewards sustained high-volume production.
4. **Blended z-scores** (`batting.py::_grouped_zscore`, `bowling.py::_grouped_zscore_bowl`, `config.yaml`): replaced pure within-group z-scoring with a weighted blend of within-group and population z-scores (`blend_alpha=0.6`). Formula: `blended = 0.6 × within_group_z + 0.4 × population_z`. This preserves position-aware comparison while keeping cross-group scores on a comparable scale. V Kohli's IPL Power went from 28.8 → 73.9; the Kohli–Rohit overall gap shrank from 14.6 → 2.2 points.

**Result (T20I):** Buttler 100.0 S, RG Sharma 99.7 S at the top. Kohli 91.9 A+ now edges Dhoni 91.7 A+. Low-volume finishers dropped (Karthik 95.5→86.8, Shepherd 97.0→89.4).
**Result (IPL):** Kohli 90.0 A+ (was 74.1 B+), Rohit 92.2 A+ (was 88.7). Gap reduced from 14.6 to 2.2 points. Dhoni 100.0 S at 241 innings — genuinely earned through massive volume + elite per-ball metrics.

### Rankings Page — Show All Stats
**Problem:** Users can't see clutch index, WAR, or other advanced metrics on the rankings page.
**Fix:** Add these columns as optional display/sort columns on the rankings leaderboard.

### Table Number Alignment
**Problem:** Numbers in tables (By Phase, matchups, etc.) are not right-aligned, making comparison difficult.
**Fix:** Right-align all numeric columns using `text-align: right` / Tailwind `text-right` and use `tabular-nums` font feature.

### Dominance Index — Human-Readable Scale
**Problem:** Dominance values like "+1.1" are meaningless to users. The raw composite (SR premium + boundary bonus − dot penalty − dismissal rate) has no intuitive interpretation.
**Fix:** Rescale dominance to a 0–100 or descriptive tier system (e.g., "Dominant" / "Slight Edge" / "Even" / "Struggles" / "Bunny") so users instantly understand the matchup dynamic.

### Clutch Index — Human-Readable Scale
**Problem:** Clutch values are very small numbers (±0.02) that convey nothing to average users. It seems like nobody is clutch.
**Fix:** Rescale clutch to a more interpretable range (e.g., 0–100 percentile, or letter grades, or descriptive tiers). Consider also showing the raw pressure SR delta alongside the composite for intuitive understanding.

### General: Avoid Tiny Numbers
**Problem:** Several metrics (dominance, clutch, dot %, boundary %) display as very small decimals or sub-1% values that are hard for users to conceptualise.
**Fix:** Scale all user-facing numbers to intuitive ranges. Percentages should be real percentages (e.g., "34.2%" not "0.3%"). Composite indices should use 0–100 or descriptive tiers.

### Matchups — Year/Period Filter
**Problem:** Matchup data is career-aggregate only; users can't see how a matchup evolved over time.
**Fix:** Add a year range filter (slider or dropdown) to the matchups section. Filter the underlying delivery data by date range before computing matchup aggregates.

### Matchups — Player Search
**Problem:** Users have to scroll through paginated matchup lists to find a specific bowler/batter.
**Fix:** Add a search/autocomplete field in the matchups section so users can quickly look up a specific opponent.

### Responsive Navigation
**Problem:** At narrow viewport widths, nav items overflow and get cut off ("Glos...", "T20I" and "IPL" overlap).
**Fix:** Implement a responsive hamburger menu or "more" dropdown that collapses nav items at smaller breakpoints. Keep the mobile nav clean.

---

*This document was last updated at the start of the v3.0 development cycle. It consolidates and replaces all previous documentation files: `README.md`, `ARCHITECTURE.md`, `Version_1.0.md`, `version02.md`, `version03.md`, `documentation.md`, `gui.md`, `HOSTING.md`, and `algorithm_update.md`.*