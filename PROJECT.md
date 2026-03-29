# Cricket Metrics — Project Documentation

> **Single source of truth for the entire codebase.**
> Replaces: `README.md`, `ARCHITECTURE.md`, `Version_1.0.md`, `version02.md`, `version03.md`, `documentation.md`, `gui.md`, `HOSTING.md`, `algorithm_update.md`
>
> **Current Version:** 2.0 (post v0.3 implementation)
> **Status:** Full pipeline operational for T20I + IPL
> **Python:** 3.12+ · **Node:** 18+ · **Dependencies:** pandas, numpy, scipy, pyarrow, pyyaml, orjson

---

## Table of Contents

1. [Product Vision](#1-product-vision)
2. [What This Project Does](#2-what-this-project-does)
3. [Quick Start](#3-quick-start)
4. [Repository Layout](#4-repository-layout)
5. [Architecture & Data Flow](#5-architecture--data-flow)
6. [Pipeline Modules](#6-pipeline-modules)
7. [Metric Design](#7-metric-design)
8. [Rating System](#8-rating-system)
9. [Feature Inventory (18 Features)](#9-feature-inventory)
10. [Configuration System](#10-configuration-system)
11. [GUI — Backend (FastAPI)](#11-gui--backend-fastapi)
12. [GUI — Frontend (React + TypeScript)](#12-gui--frontend-react--typescript)
13. [API Reference](#13-api-reference)
14. [Output Files](#14-output-files)
15. [Testing](#15-testing)
16. [Hosting & Deployment](#16-hosting--deployment)
17. [Design Decisions](#17-design-decisions)
18. [Glossary](#18-glossary)
19. [Version History](#19-version-history)
20. [Known Limitations](#20-known-limitations)
21. [Roadmap](#21-roadmap)
22. [Product Specification](#22-product-specification)

---

## 1. Product Vision

### Product Distillation

Cricket Metrics aims to be a **dark-mode analytical identity** cricket intelligence platform with:

- **Dense leaderboards** — High information density, compact summary cards
- **Compare flows** — Side-by-side player comparison with role-aware radars
- **Matchup Analysis** — Head-to-head batter vs bowler, phase splits, dominance
- **Team-builder Concept** — Visualize how good a hypothetical XI is
- **Era and venue exploration** — Context across time and place
- **Rich player profile surfaces** — Overview, splits, form, matchups, similar players
- **Metric-driven storytelling** — Control, Acceleration, Threat, Power, Accuracy as narrative
- **Easily accessible metrics** — “Control”, “Acceleration”, “Threat”, “Power”, “Accuracy”
- **Overall Scores** — Single-number summaries with letter grades
- **Player contribution** — Wins added over replacement, Clutch Score, Matchups
- **Live scores** — Extra features to make viewing accessible; viewers should feel compelled to keep the app open even if watching the game
- **Player tags** — “Death Specialist”, “Powerplay Enforcer” to identify roles
- **Advanced Metrics** — WAR, Pressure Score, Avg Matchup Edge, Pressure Spells, Dominant, Flat Track Index
- **Phase Splits** — Powerplay / middle / death breakdowns
- **Form Tracker** — Rolling-window form time-series
- **Sticky global navigation** — Always accessible
- **Compact summary cards** — Glanceable before deep tables
- **Page-level sub tabs** — “State of the world first, drill down second”
- **Dashboards that feel live** — Even when not actually live
- **Feature parity** — With espncricinfo (apart from cricinfo and articles)

### Product Principles

- **High information density is good, but visual randomness is bad**
- **Everything should be independently testable** — No feature should require three unfinished systems to exist first
- **Derived metrics should be precomputed** — Do not make the browser compute heavy cricket analytics on page load
- **One page = one primary analytical job:**
  - **Rankings:** discover
  - **Compare:** contrast players
  - **Matchups:** inspect batter vs bowler
  - **Team builder:** construct and compare XI’s
  - **Eras:** translate context (batting and bowling evolved over years)
  - **Venues:** understand environment and past scores
  - **Player profile:** explain a player and their history
- **Every page needs both a quick insight layer and a deep exploration**

### Engineering Principles

1. Keep features vertical
2. No premature drag-and-drop
3. No giant client-side global state store unless pain appears
4. Prefer server data fetching + client-only island for interactivity
5. Use stable query contracts and typed transformations
6. Keep chart data adapters separate from chart components
7. Every metric should have: name, definition, display format, calculation owner, source tables, fallback behavior if data missing

### Recommended Product Structure

**Global routes:**
- `/` — Home
- `/rankings` — Leaderboards
- `/compare` — Player comparison
- `/matchups` — Head-to-head
- `/team-builder` — XI construction
- `/eras` — Era explorer
- `/venues` — Venue analysis
- `/players/[slug]` — Player profile
- `/glossary` — Metric definitions

**Persistent header:**
- Brand
- Format toggle: T20I / ODI / Test / IPL (later)
- Global search
- Theme controls
- User actions (later)

**Page-level subnav:**
- **Rankings:** Batting / Bowling / All-Rounders
- **Matchups:** Head-to-Head / Explorer
- **Venues:** Venue List / Venue Detail / Trend
- **Players:** Overview / Splits / Form / Matchups / Similar Players

---

## 2. What This Project Does

Cricket Metrics is a production-grade T20 cricket analytics platform that transforms raw ball-by-ball Cricsheet JSON data into multi-dimensional player ratings, career profiles, and advanced statistical insights. It covers both **T20I** (international) and **IPL** (franchise) cricket.

**Core capabilities:**

- **3 batting dimensions** (Acceleration, Power, Control) with xR-enhanced components
- **3 bowling dimensions** (Accuracy, Control, Threat) with xR-enhanced components
- **TrueSkill-inspired Bayesian rating system** with uncertainty penalties
- **18 analytical features** (clutch index, matchup shrinkage, WAR, form tracker, peak ratings, venue analysis, era adjustment, etc.)
- **Full-stack web GUI** — interactive player profiles, rankings, head-to-head matchups, team builder, era explorer, venue analysis
- **Scorecards module** — Per-match scorecards with ball-by-ball drill-down (built from deliveries; API and GUI page exist; pipeline integration pending)
- **ESPN Cricinfo scraper** — Optional scraper for T20I / T20 / IPL match discovery and hydration (python-espncricinfo + Playwright)

The platform processes every T20I and IPL match from Cricsheet data and produces per-player career profiles with percentile-based scores (0–100), letter grades (S/A+/A/B+/B/C+/C/D), role archetypes, and dozens of contextual metrics.

---

## 3. Quick Start

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
python -m pytest tests/ -v
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

## 4. Repository Layout

```
cricket_metrics/
├── PROJECT.md                  # ← This file (single source of truth)
├── config.yaml                 # All tuning constants
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Root-level backend image (Docker Compose / optional VPS)
├── .dockerignore
│
├── src/                        # Analytics pipeline (Python)
│   ├── main.py                 # Pipeline orchestrator
│   ├── parser.py               # Cricsheet JSON → flat deliveries DataFrame
│   ├── context.py              # Match/innings context (par SR, par RR, phases)
│   ├── config.py               # Config loader with deep merge & dot-notation
│   ├── batting.py              # Batting: extraction, components, career aggregation
│   ├── bowling.py              # Bowling: extraction, components, career aggregation
│   ├── expected_value.py       # xR models, RVA, CABI, survival rates
│   ├── rating.py               # Bayesian shrinkage, percentile scoring
│   ├── presentation.py         # Grades, archetypes, overall scores
│   ├── clutch.py               # Pressure tagging, clutch index
│   ├── condition.py            # Condition-Dependence Index
│   ├── era.py                  # Era baselines, cross-era normalisation
│   ├── form_tracker.py         # Rolling-window form series
│   ├── matchups.py             # Head-to-head analysis + Bayesian shrinkage
│   ├── peak_ratings.py         # Peak vs current ratings
│   ├── similarity.py           # Cosine-similarity player comparison
│   ├── venue.py                # Venue difficulty, flat-track bully index
│   ├── war.py                  # Positional WAR
│   ├── wpa.py                  # Win Probability Added
│   ├── scorecards.py           # Per-match scorecards from deliveries (ball-by-ball drill-down)
│   └── espncricinfo_scraper.py  # ESPN Cricinfo match discovery & hydration (T20I/T20/IPL)
│
├── tests/
│   ├── conftest.py             # Shared synthetic fixtures
│   ├── test_*.py               # 14+ test files
│   ├── scorecards/
│   │   └── test_scorecards.py  # Scorecards module tests
│   └── test_espncricinfo_scraper.py
│
├── gui/
│   ├── docker-compose.yml
│   ├── backend/                # FastAPI Python backend
│   │   ├── app.py              # App entry point & lifespan
│   │   ├── data_loader.py      # Parquet → MultiDataStore (auto-discovers T20I + IPL)
│   │   ├── search_index.py     # Trigram fuzzy search
│   │   ├── schemas.py          # Pydantic response models
│   │   ├── export_static.py    # Static JSON export for GitHub Pages
│   │   └── routers/
│   │       ├── search.py       # /api/search, /api/autocomplete
│   │       ├── player.py       # /api/player/:id
│   │       ├── rankings.py     # /api/rankings/bat, /api/rankings/bowl
│   │       ├── compare.py      # /api/compare
│   │       ├── matchups.py     # /api/matchups, /api/h2h
│   │       ├── venues.py       # /api/venues
│   │       ├── eras.py         # /api/eras
│   │       ├── team.py         # /api/team/analyse, /api/team/compare
│   │       └── match_scorecards.py  # /api/scorecards/*
│   │
│   └── frontend/               # React + TypeScript (Vite)
│       ├── src/
│       │   ├── App.tsx         # Router + QueryClient + FormatProvider
│       │   ├── api/            # client.ts, queries.ts, types.ts
│       │   ├── components/     # Layout, PlayerAutocomplete, ScoreBar, GradeBadge, etc.
│       │   ├── hooks/         # useDebounce, useTheme
│       │   ├── lib/            # colours.ts, format.ts
│       │   ├── pages/          # Home, Search, PlayerProfile, Rankings, Compare,
│       │   │                   # Matchups, TeamBuilder, Eras, Venues, Glossary,
│       │   │                   # Scorecards (page exists; route not yet in App.tsx)
│       │   └── styles/         # globals.css, scorecards.css
│       ├── vite.config.ts
│       ├── tailwind.config.ts
│       └── package.json
│
├── cricketdata/                # cricketdata R package reference (placeholder)
├── t20s_male_json/             # Cricsheet T20I source data
├── ipl_json/                   # Cricsheet IPL source data
├── output_t20i/                # Pipeline output: T20I
├── output_ipl/                 # Pipeline output: IPL
└── output/                     # Legacy output directory (fallback)
```

---

## 5. Architecture & Data Flow

### Pipeline Flow

```
Cricsheet JSON files (t20s_male_json/ or ipl_json/)
        │
        ▼
   ┌─────────┐
   │ parser  │ → deliveries DataFrame (one row per ball)
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

### Scorecards (Separate from Main Pipeline)

The scorecards module (`src/scorecards.py`) builds per-match JSON scorecards from the deliveries DataFrame. It is **not** currently invoked by `main.py`. To generate scorecards:

```python
from src.parser import parse_all_matches
from src.scorecards import stream_write_scorecards

df, _ = parse_all_matches("t20s_male_json")
stream_write_scorecards(df, Path("output_t20i/scorecards"), include_deliveries=True)
```

The GUI backend expects scorecards in `output_dir/scorecards/*.json`. The Scorecards page exists (`gui/frontend/src/pages/Scorecards.tsx`) but is **not yet wired** into the App router or Layout nav.

### GUI Architecture

```
┌──────────────────────┐         ┌───────────────────────────────┐
│  Frontend (React)    │  ──→    │  Backend (FastAPI + Python)  │
│  Static HTML/JS/CSS  │  /api/* │  Loads Parquet data into RAM   │
└──────────────────────┘         └───────────────────────────────┘
                                          ▲
                                          │ reads at startup
                                 ┌────────┴───────────┐
                                 │  output_t20i/      │
                                 │  output_ipl/       │
                                 └────────────────────┘
```

**Key facts:**

| Concern | Detail |
|---------|--------|
| Backend language | Python 3.12+ (FastAPI + uvicorn) |
| Frontend | React 18, Vite, TypeScript, Tailwind CSS |
| Database | **None** — all data read from Parquet into memory at startup |
| Data size on disk | ~45 MB total (T20I + IPL) |
| Backend RAM | ~360 MB with both formats loaded |
| API type | Read-only, stateless, no auth |

---

## 6. Pipeline Modules

### `parser.py` — Cricsheet JSON → Deliveries DataFrame

Converts Cricsheet JSON match files into a flat DataFrame with one row per ball. Handles T20 edge cases: super overs, DLS, abandoned matches, penalty runs.

### `context.py` — Match & Innings Context

Computes match-level and innings-level normalisation metrics: `match_par_sr`, `match_par_rr`, `match_boundary_rate`, `match_dot_pct`, phase-specific par rates.

### `batting.py` — Batting Analytics

**Innings Extraction:** One row per batter per match with raw stats, context columns, recency weights, selfless approach-zone SR, anchor cost.

**Component Computation:** 3 dimensions — Acceleration, Power, Control (see [Section 7](#7-metric-design)).

**Career Aggregation:** Opposition-quality-weighted averaging → blended Z-score normalisation → weighted composite → gates → volume scaling.

### `bowling.py` — Bowling Analytics

Mirror of batting with 3 dimensions: Accuracy, Control, Threat. Includes bowl first / bowl second splits.

### `expected_value.py` — xR Framework

- `build_expected_value_models()` — GAM-approximated baseline run expectancies
- `compute_context_adjusted_rva()` — Run Value Added per delivery
- `compute_context_adjusted_boundary_index()` — CABI residuals
- `compute_expected_survival_rates()` — Cox-inspired survival analysis

### `rating.py` — Bayesian Rating System

TrueSkill-inspired hierarchical Bayesian rating with shrinkage k, confidence bonus, percentile mapping, gates.

### `presentation.py` — Grades, Archetypes, Overall Scores

**Grades:** S (95+), A+ (85+), A (75+), B+ (60+), B (45+), C+ (30+), C (15+), D (0+).

**Overall Score:** Weighted mean of dimension scores + superstar bonus + career production bonus + career average bonus.

**Batting Archetypes (13):** Explosive Opener, Explosive Finisher, Power Hitter, Pinch Hitter, Aggressive Opener, Power Middle-Order, Classic Anchor, Power Anchor, All-Round Elite, Strike Rotator, Accumulator, Float, Utility Player.

**Bowling Archetypes (8):** Death Specialist, Powerplay Enforcer, Strike Bowler, Spin Restrictor, Economical, All-Round Threat, Restrictive Spinner, Enforcer.

### `scorecards.py` — Per-Match Scorecards

- `build_scorecards(deliveries_df)` — Build scorecards keyed by `match_id`
- `player_performances_from_scorecards(scorecards, player_id)` — Extract all match performances for a player
- `scorecards_to_dataframe(scorecards)` — Flatten batting performances
- `iter_scorecards(df)` — Yield per-match scorecards
- `stream_write_scorecards(df, out_dir)` — Write one JSON file per match to disk

### `espncricinfo_scraper.py` — ESPN Cricinfo Scraper

Optional scraper for T20I / T20 / IPL match discovery and hydration. Uses `python-espncricinfo` and Playwright. Supports date range, competition filtering, and caching.

---

## 7. Metric Design

### Three Dimensions

| Batting | ACC | POW | CTRL |
|---------|-----|-----|------|
| Bowling | ACC | CTRL | THR |

### Blended Position-Group Z-Scores

`blended = 0.6 × within_group_z + 0.4 × population_z` — preserves role-aware comparison while keeping cross-group scores comparable.

### Context Normalisation

- SR vs par uses ratio (`SR / match_par_sr`), not difference
- Phase-specific par for death vs overall
- Economy vs par for bowlers

### Five-Layer Opposition Weighting

`innings_weight = opp_bowling_quality × opp_team_quality × icc_ranking_weight × match_quality_weight × recency_weight`

### Post-Percentile Gates

1. Average Quality Gate (batting only)
2. Volume Scaling (with beyond-reference bonus)
3. Competition Quality Gate

---

## 8. Rating System

```
raw composite (z-score)
  → Bayesian shrinkage
  → Confidence bonus
  → Percentile mapping → 0–100
  → Average quality gate (batting only)
  → Volume scaling
  → Competition quality gate
  → Overall score (weighted dimensions + bonuses)
  → FINAL DISPLAYED SCORE (0–100)
```

**Overall score (batting):** `weighted_mean(ACC, POW, CTRL) + superstar_bonus + runs_bonus + avg_bonus`

- Dimension weights: ACC 0.35, POW 0.20, CTRL 0.45
- Career production bonus: up to 2 points (3000+ runs)
- Career average bonus: up to 5 points (avg 38+)

---

## 9. Feature Inventory

| # | Feature | Module | Description |
|---|---------|--------|-------------|
| 1 | Grades | `presentation.py` | S/A+/A/B+/B/C+/C/D letter grades |
| 2 | Archetypes | `presentation.py` | 13 batting + 8 bowling archetypes |
| 3 | Clutch Index | `clutch.py` | Performance delta under pressure |
| 4 | Head-to-Head Matchups | `matchups.py` | Batter × bowler with dominance index |
| 5 | Peak vs Current | `peak_ratings.py` | Recency-free career + sliding 2-year peak |
| 6 | Chase Master Index | `batting.py` | Setting vs chasing SR and avg splits |
| 7 | Similarity Engine | `similarity.py` | Cosine similarity on career component vectors |
| 8 | Selfless Index | `batting.py` | Milestone approach-zone SR |
| 9 | Venue Difficulty | `venue.py` | Per-venue baselines + flat-track bully index |
| 10 | Win Probability Added | `wpa.py` | Empirical WP models (disabled by default) |
| 11 | Anchor Cost | `batting.py` | Balls-to-par |
| 12 | Wicket Quality | `bowling.py` | Position-weighted wickets |
| 13 | Form Tracker | `form_tracker.py` | Rolling-window form time-series |
| 14 | Positional WAR | `war.py` | Value above replacement |
| 15 | Era Adjustment | `era.py` | Cross-era normalisation (disabled by default) |
| 16 | Bowl Splits | `bowling.py` | Bowl first / bowl second index |
| 17 | Condition Dependence | `condition.py` | Flat-track bully detection |
| 18 | Matchup Shrinkage | `matchups.py` | Bayesian Empirical Bayes shrinkage |

---

## 10. Configuration System

### How It Works

1. `src/config.py` defines `_DEFAULTS`
2. `config.yaml` provides user overrides (optional)
3. `_deep_merge(_DEFAULTS, yaml_overrides)` produces final config
4. `cfg("dotted.key.path")` provides module-level singleton access

### Key Config Sections

`pipeline.*`, `rating.*`, `batting_*_weights`, `bowling_*_weights`, `batting_avg_quality.*`, `batting_volume.*`, `bowling_volume.*`, `batting_position_groups.*`, `bowling_phase_groups.*`, `presentation.*`, `icc_ranking.*`, `match_quality.*`, `recency.*`, `clutch.*`, `matchups.*`, `form_tracker.*`, `war.*`, `wpa.*`, `era_adjustment.*`, `condition_dependence.*`, `matchup_shrinkage.*`

---

## 11. GUI — Backend (FastAPI)

### Data Loading

`data_loader.py` implements `MultiDataStore` — auto-discovers `output_t20i/` and `output_ipl/` at startup. Each format gets its own `DataStore` with all DataFrames loaded into memory. The `?format=` query parameter selects which dataset to query.

### Routers

| Router | Prefix | Description |
|--------|--------|-------------|
| search | /api | Search, autocomplete, countries, archetypes |
| player | /api | Player profile, innings, spells, form, matchups, similar |
| rankings | /api | Batting/bowling leaderboards |
| compare | /api | Side-by-side comparison |
| matchups | /api | Head-to-head, explore, bunnies, nemeses |
| venues | /api | Venue list, detail, flat-track index |
| eras | /api | Era baselines |
| team | /api | Team analyse, compare, auto-fill |
| match_scorecards | /api | Scorecards search, get by match_id, player performances |

### Scorecards API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/scorecards/available` | List all match IDs with scorecards |
| GET | `/api/scorecards/{match_id}` | Full scorecard JSON |
| GET | `/api/scorecards/search` | Search by date range, team, player_id |
| GET | `/api/scorecards/player/{player_id}` | All per-match performances for a player |

**Note:** Scorecards are read from `output_dir/scorecards/*.json`. The main pipeline does not write these; use `stream_write_scorecards()` from `src.scorecards` or a separate script.

---

## 12. GUI — Frontend (React + TypeScript)

### Tech Stack

React 18, TypeScript, React Router v6, TanStack Query, Recharts + D3, Tailwind CSS, shadcn/ui, Vite.

### Pages & Routes

| Route | Page | Status |
|-------|------|--------|
| `/` | Home | ✅ |
| `/search` | Search | ✅ |
| `/player/:id` | Player Profile | ✅ |
| `/player/:id/innings` | Innings Log | ✅ |
| `/player/:id/spells` | Spells Log | ✅ |
| `/rankings` | Rankings | ✅ |
| `/compare` | Compare | ✅ |
| `/matchups` | Matchups | ✅ |
| `/matchups/explore` | Matchups Explorer | ✅ |
| `/similar/:id` | Similar Players | ✅ |
| `/team-builder` | Team Builder | ✅ |
| `/eras` | Era Explorer | ✅ |
| `/venues` | Venue Analysis | ✅ |
| `/glossary` | Glossary | ✅ |
| `/scorecards` | Match Scorecards | ⚠️ Page exists; route not in App.tsx; nav not in Layout |

### Key Components

`FormatToggle`, `PlayerAutocomplete`, `ScoreBar`, `GradeBadge`, `ArchetypeBadge`, `MetricTooltip`, `FormSparkline`, `ExportButton`, `ThemeToggle`.

---

## 13. API Reference

All endpoints return JSON. Optional `?format=t20i|ipl` query parameter.

### Meta & Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check |
| GET | `/api/meta` | Dataset metadata |
| GET | `/api/formats` | List available formats |

### Search, Player, Rankings, Compare, Matchups, Venues, Eras, Team

See [Section 11](#11-gui--backend-fastapi) for router summaries.

---

## 14. Output Files

### CSV Outputs

`batting_profiles.csv`, `bowling_profiles.csv`, `era_summary.csv`, `potential_duplicates.csv` (if applicable).

### Parquet Outputs

`batting_careers_full.parquet`, `bowling_careers_full.parquet`, `batting_innings_detail.parquet`, `bowling_spells_detail.parquet`, `batting_form_series.parquet`, `bowling_form_series.parquet`, `batting_similarities.parquet`, `bowling_similarities.parquet`, `matchups.parquet`, `matchups_by_phase.parquet`, `venue_baselines.parquet`, `era_baselines.parquet`, `batting_condition_terciles.parquet`, `allrounder_war.parquet`.

### Scorecards (Optional)

`output_dir/scorecards/*.json` — per-match scorecard JSON (built by `stream_write_scorecards`, not by main pipeline).

---

## 15. Testing

Tests use synthetic fixtures in `tests/conftest.py`. Run with `python -m pytest tests/ -v`.

---

## 16. Hosting & Deployment

**Recommended:** one **Vercel** project (**Services**: Vite + FastAPI), Parquet in **Vercel Blob**, hydrated at API startup (`gui/backend/blob_hydrate.py`). See [DEPLOYMENT.md](DEPLOYMENT.md) and [vercel.env.example](vercel.env.example).

**Also supported:** Docker Compose (`gui/docker-compose.yml`), root **Dockerfile** / VPS with disk + `DATA_ROOT`, or split deploy (frontend on Vercel + API elsewhere with `VITE_API_URL` + `CORS_ORIGINS`).

- Backend auto-discovers `data/output/<format>/` and legacy `output_t20i/` / `output_ipl/`
- **Same-origin Vercel deploy:** leave `VITE_API_URL` empty; **split deploy:** set `VITE_API_URL` at build time
- **Split deploy only:** add frontend origin to `CORS_ORIGINS` (or defaults in `gui/backend/app.py`)
- RAM: large when all slices load (plan Vercel function memory accordingly; see `vercel.json`)

---

## 17. Design Decisions

| Decision | Rationale |
|----------|-----------|
| ICC ranking-based opposition weighting | External authoritative signal |
| Blended z-scores | Cross-position comparability |
| Bayesian shrinkage | Graceful handling of low samples |
| Recency weighting (545-day half-life) | T20 evolves fast |
| No database | All data fits in memory |
| FastAPI over JS backend | Same language as pipeline; native Parquet/pandas |

---

## 18. Glossary

| Term | Definition |
|------|------------|
| **Delivery** | A single ball bowled |
| **Phase** | Powerplay (0–5), Middle (6–15), Death (16–19) |
| **Match par SR** | Average strike rate across both innings |
| **Registr ID** | Cricsheet's unique player identifier |
| **Provisional** | Heavily shrunk rating (<10 innings or <30 overs) |
| **Z-score** | `(value − mean) / std` |
| **Bayesian shrinkage** | Pulling estimates toward population mean |

---

## 19. Version History

### v0.1 — Core Engine

Parser, context, batting, bowling, 3-dimension rating system.

### v0.2 — Feature Expansion (18 Features)

All 18 analytical features implemented.

### v1.0 — Stability Release

Critical bug fixes, config weight sums, archetype ordering.

### v0.3 / v2.0 — GUI & IPL Support

IPL dataset, MultiDataStore, format toggle, team vs team comparison, role-aware compare, era timeline, form tracker fix, customisable slot positions, chase splits, hover tooltips, exclude tail-enders.

### v3.0 — Rating Rebalance, Archetype Fix & Average Valorisation

Position-aware archetypes, blended z-scores, career production bonus, career average bonus, weighted dimension scores, volume scaling beyond-reference bonus.

---

## 20. Known Limitations

| Limitation | Detail |
|------------|--------|
| Type-checking diagnostics | ~500+ pyright warnings (pandas typing) |
| WPA disabled by default | Computational cost |
| Era adjustment disabled | Primarily for historical analysis |
| Scorecards not in pipeline | Must be built separately |

---

## 21. Roadmap

- **Scorecards:** Wire `/scorecards` route and Layout nav; add pipeline step to write scorecards
- **Rankings:** Add clutch, WAR, advanced metrics as optional columns
- **Table alignment:** Right-align numeric columns
- **Dominance / Clutch:** Human-readable scale (0–100 or tiers)
- **Matchups:** Year/period filter, player search
- **Responsive nav:** Hamburger menu at narrow viewports
- **Live scores:** Integrate live data source; extra viewer features

---

## 22. Product Specification

This section captures the detailed product requirements derived from the elaboration questions. It serves as the authoritative spec for UI, UX, and feature design.

---

### 22.1 Home — Match Center

When live cricket exists, Home should feel like a **match center**. When it doesn't, Home should feel like the **fastest doorway into deep cricket analysis**.

**Two modes:** Live mode (when matches are happening) and Discovery mode (when there are no live matches).

#### State A — Live Match in Progress

Dominates the page. Should feel like a **cricket control room**, not just a score block.

**Live Match Block:** Teams (flags/logos), live score, overs, wickets, target/required run rate, current run rate, summary of past 10 balls, win probability, match status. CTA buttons: View live match, Predict result, Compare key players, View matchups.

**Match Context Strip:** Top batter right now, top bowler right now, current partnership, last wicket, projected score/defendability, venue difficulty tag, pressure level tag.

**Best Performances of the Day:** Best batting performance, best bowling spell, best under pressure, biggest overperformance vs expectation.

**User Action Zone:** Predict winner, predict top scorer, predict total score, build fantasy XI for today's slate, compare opening batters, explore batter vs bowler live matchup, predict next over.

#### State B — Match Day, No Live Match Right Now

Match later today, innings break, just-finished match, end of day's play (Test).

#### State C — No Match Today

Pure discovery: hero search, top-ranked batters card, top bowlers card, best under pressure card, quick compare panel, featured matchups, recently viewed players.

---

### 22.2 Theme & Visual Identity

- **Default theme:** Dark
- **Avoid:** Vibe-coding clichés (e.g. gradients)
- **Tone:** Analytical, cater to statistically aligned cricket fans

---

### 22.3 Rankings / Leaderboard

**Default columns:** Player trend (rising/falling/unchanged), mini form sparkline. Batters: rolling composite, recent strike rate, recent runs per innings. Bowlers: rolling composite, recent wickets, economy/strike rate.

**Top summary bar:** Current filter scope, number of players shown, average score of visible set, top archetype in current view.

**Presets:** Overall, Recent form, Power hitters, Anchors, Death specialists, Powerplay bowlers.

**Row behavior:** Expandable row or hover panel explaining rankings; open profile in new tab; add to team builder; single click → right-side preview panel (player summary, key metrics, phase splits, recent form, quick actions).

**Filters:** Min innings, min balls faced, min overs bowled, min matches, recent window.

**Density options:** Compact, Default, Expanded.

**Sticky columns on horizontal scroll:** Rank, player, country, overall score.

**Custom sort logic:** e.g. 50% overall + 30% pressure + 20% form + prioritize Power and WAR; compare raw vs adjusted stats.

**Filterable by every metric:** Users can add/remove metrics from the leaderboard.

---

### 22.4 Format Expansion (ODI / Test)

**Test batter dimensions:** Control (keep); Acceleration (rework for innings pacing — consistent scoring vs quick/slow phases); Power → **Patience** (ability to play long innings, tire out bowlers).

**ODI batter dimensions:** Replace Patience with **Pacing** (ability to pace a good innings of 80–100 balls).

**Bowlers (all formats):** Accuracy, Control, Threat remain; recalibrated for longer formats.

---

### 22.5 Player Tags

Algorithm-driven; accurate.

---

### 22.6 Team Builder

Display: Batting strength, bowling strength, total WAR, collective advanced stats. Filter stats by role (batter vs bowler) so averages don't tank on either side.

---

### 22.7 Matchup Explorer

Head-to-head for two specific players; nemeses (who dominates them); who they dominate.

---

### 22.8 Era Exploration

Years covered; how metrics have changed: run rate, dot balls, boundary %, acceleration in different phases.

---

### 22.9 Venue Detail

Beyond difficulty and flat-track index: average run rate over time, scores.

---

### 22.10 Metric Storytelling

**Rule:** Narrative should be **layered, not dumped.**

**Level 1 — Micro-insights:** Above tables, summary cards, player headers, compare verdicts, matchup cards. Short, declarative, grounded in data, readable in under 2 seconds. Examples: "Elite death-over accelerator", "Ranks far higher in pressure than raw average suggests".

**Level 2 — Section insights:** At top of module or chart. Explain why the section matters. Examples: "Kohli leads on control and pressure, but Sharma has the stronger acceleration profile."

**Level 3 — Deep narrative:** Use sparingly. Player profile "Analyst Notes", compare verdict block, scorecard post-match summary, era interpretation panel. Collapsible, secondary, never first thing user sees.

**Template:** Claim + evidence + context. **Avoid:** Vague praise, long AI summaries, insights with no metric, contradictory insights, jargon without tooltips.

---

### 22.11 Clutch / Pressure Score

Present as **Pressure Score** with "Clutch" as plain-English interpretation. **Three layers:** (1) Simple score + label, (2) Interpretation band (80–100 Elite | 65–79 Strong | 45–64 Neutral | 30–44 Below average | 0–29 Struggles), (3) Why — 2–3 drivers. **Best places:** Player profile, rankings column, compare table, live match cards. **Visual:** Numeric score, short label, tooltip. **Tooltip answers:** What counts as pressure? Format-specific? Sample size? Relative to era or raw?

---

### 22.12 WAR Explanation

**Plain-English:** "WAR estimates how much more value a player provides than a readily available replacement-level player." "Think of WAR as 'how many wins this player is worth above a baseline squad option.'" **Answer:** What is replacement? Batting/bowling/total? Is 5.0 good? Cross-era? Cumulative or rate? **Supporting visual:** Pair WAR with component drivers. **Safeguard:** Never show WAR alone without tooltip, glossary link, component breakdown, or percentile/band.

---

### 22.13 Glanceable vs Deep (Per-Page)

**Rule:** Every page gets: (1) Quick insight layer (5–20 seconds), (2) Deep analysis layer.

| Page | Quick insight | Deep layer |
|------|---------------|------------|
| Home | Live match hero or hero search; top performers; discovery cards | Featured matchups; compare widget; recently viewed |
| Rankings | Scope summary; top player; filter chips; biggest riser; best value; sort explanation | Dense table; column picker; filters; row expansion |
| Compare | Headline verdict; 3–5 key winner calls; radar summary; one-sentence insight | Full metric table; phase splits; form chart; shared matchups |
| Matchups | Matchup edge; balls/runs/dismissals; verdict | By-phase table; dismissal patterns; similar matchup explorer |
| Player Profile | Identity card; grade; 3 core metric bars; one-line style summary; peak vs current | Advanced metrics; component breakdown; phase splits; form; matchups |
| Eras | Era trend cards; one-line interpretation; equivalent calculator result | Timeline chart; multiplier table; methodology |
| Venues | Hardest/easiest venue; total venues; what defines environment | Venue table; detail; trend charts; player-at-venue |
| Team Builder | XI summary; budget; total WAR; balance; biggest weakness | Player pool; drafted XI; composition breakdown |
| Glossary | Simple definitions; why metric matters; when to use | Methodology; caveats; examples; component math |

---

### 22.14 ESPNcricinfo Parity

**Principle:** Familiar baseline + analytics differentiation. **Must-haves:** Live scores, fixtures/results, scorecards, match summary, player-of-match; player search, profiles, career stats, splits; sortable rankings, filters; innings scorecard, batting/bowling figures, partnerships, fall of wickets; venue basics, format filter, recent form; compare players, matchup page, metric explanations, quick insights. **Nice-to-haves:** Editorial news, commentary feed, galleries; archive UI, squad pages, series hubs; fantasy articles, records pages; social, personalization. **Core expectations:** Find match → open scorecard → find player → see basic stats → drill deeper.

---

### 22.15 Scorecards Integration

**Dual drill-down:** Scorecard-centric (from live matches, fixtures, daily cards) and Entity-centric (from rankings, compare, matchups, profiles). **Primary for matches/innings, not only path.** **Scorecard structure:** Top: result, summary, win probability, standout performances. Middle: batting/bowling tables, partnerships, fall of wickets, extras. Analytics: pressure moments, best over, turning point, top matchup, innings rating vs venue/era. **Linking:** Home live card → Scorecard, Matchups, Predict, Compare. Scorecard → player (profile), bowler/batter pair (matchup), venue (venue page), standout (innings analysis). Player profile → recent innings (scorecards), top matchups (matchup pages). Matchup page → innings, both profiles. **Row interactions:** Click player → profile; hover: Compare, View matchup vs key bowlers; dismissal → matchup; partnership → mini breakdown; fall of wickets → score state, required rate, leverage.

---

### 22.16 Final Recommendations

| Topic | Recommendation |
|-------|----------------|
| Metric storytelling | Layered: micro first, section second, deep only when expanded |
| Clutch/pressure | Present as **Pressure Score**, "clutch" as plain-language interpretation |
| WAR | "How many wins above replacement-level option"; show drivers |
| Quick insight layer | Every page: "What matters here, in one glance, before the table proves it?" |
| Cricinfo parity | Match core expectations; differentiate through analytics |
| Scorecards | Major drill-down for matches; not the only analytical path |

---

*This document consolidates and replaces all previous documentation files. Last updated with Product Specification v1.*