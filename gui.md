# Cricket Metrics — GUI Design Document

## Table of Contents

1. [Overview](#1-overview)
2. [Technology Stack](#2-technology-stack)
3. [Architecture](#3-architecture)
4. [Data Layer](#4-data-layer)
5. [Page & Route Structure](#5-page--route-structure)
6. [Page Designs](#6-page-designs)
   - [6.1 Home / Dashboard](#61-home--dashboard)
   - [6.2 Player Search](#62-player-search)
   - [6.3 Player Profile](#63-player-profile)
   - [6.4 Leaderboards & Rankings](#64-leaderboards--rankings)
   - [6.5 Player Comparison](#65-player-comparison)
   - [6.6 Head-to-Head Matchups](#66-head-to-head-matchups)
   - [6.7 Similarity Explorer ("Comps")](#67-similarity-explorer-comps)
   - [6.8 Team Builder](#68-team-builder)
   - [6.9 Era Explorer](#69-era-explorer)
   - [6.10 Venue Analysis](#610-venue-analysis)
   - [6.11 Glossary & Methodology](#611-glossary--methodology)
7. [Shared Components](#7-shared-components)
8. [Visualisation Specifications](#8-visualisation-specifications)
9. [API Endpoints](#9-api-endpoints)
10. [Search & Filtering](#10-search--filtering)
11. [Responsive Design](#11-responsive-design)
12. [Theming & Brand](#12-theming--brand)
13. [Accessibility](#13-accessibility)
14. [Performance Targets](#14-performance-targets)
15. [Implementation Roadmap](#15-implementation-roadmap)

---

## 1. Overview

The Cricket Metrics GUI is a web application that surfaces the full output of the Cricket Metrics pipeline in an interactive, fan-friendly interface. It enables users to:

- **Search** any T20I batter or bowler by name, country, or archetype.
- **View** rich player profiles with 0–100 scores, letter grades, archetypes, form sparklines, peak vs current ratings, WAR, clutch index, and per-innings breakdowns.
- **Rank** players across any metric with sortable, filterable leaderboards.
- **Compare** 2–4 players side-by-side with radar charts and stat tables.
- **Explore** head-to-head matchups (batter vs bowler) with dominance indices.
- **Discover** similar players via the cosine-similarity engine.
- **Build** hypothetical T20I XIs from the player pool and see aggregate team scores.
- **Analyse** how eras, venues, and match context shape player value.

The GUI reads exclusively from the Parquet and CSV files already produced by the pipeline — there is no write-back. This means the backend is a thin, read-only API layer over static data.

---

## 2. Technology Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| **Frontend** | React 18 + TypeScript | Component model, ecosystem, type safety |
| **Routing** | React Router v6 | Client-side routing with URL-driven state |
| **State** | TanStack Query (React Query) | Server-state caching, deduplication, stale-while-revalidate |
| **Charts** | Recharts + D3 (custom) | Recharts for standard charts; D3 for radar/spider/hexbin |
| **Styling** | Tailwind CSS + shadcn/ui | Utility-first CSS with accessible, composable primitives |
| **Backend** | FastAPI (Python) | Same language as the pipeline; native Parquet/pandas support |
| **Data** | Parquet → pandas → JSON | Pipeline outputs read at startup, served as JSON |
| **Search** | In-memory trigram index (Python) | Fuzzy player name matching without external dependencies |
| **Deployment** | Docker Compose | Single `docker compose up` starts backend + frontend |

### Why FastAPI over a JS backend?

The pipeline already produces pandas DataFrames serialised as Parquet. FastAPI lets us `pd.read_parquet()` once at startup, hold the data in memory (~50 MB total), and serve sub-millisecond queries with zero ETL. Adding a JS backend would require duplicating the data transformation logic or adding an intermediate database.

### Alternative: Static Export

For hosting on GitHub Pages or Vercel without a backend, the build step can pre-render all API responses as static JSON files (one per player, one per leaderboard configuration, etc.). The frontend then fetches `/api/player/{id}.json` as a static asset. This is documented in [Section 15](#15-implementation-roadmap) as Phase 3.

---

## 3. Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                         Browser (React SPA)                      │
│                                                                  │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │  Search  │ │ Profile  │ │ Compare  │ │ Leaders  │  ...       │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘           │
│       │             │            │             │                  │
│       └─────────────┴────────────┴─────────────┘                 │
│                          │                                       │
│                   TanStack Query                                 │
│                          │                                       │
│                     fetch(/api/*)                                 │
└──────────────────────────┬───────────────────────────────────────┘
                           │  HTTP / JSON
┌──────────────────────────┴───────────────────────────────────────┐
│                     FastAPI Backend                               │
│                                                                  │
│  ┌────────────┐  ┌────────────────┐  ┌────────────────────┐     │
│  │  Startup   │  │  API Routes    │  │  Query Engine       │     │
│  │  Loader    │  │  /api/player/* │  │  (pandas filtering, │     │
│  │ (Parquet)  │  │  /api/search   │  │   sorting, slicing) │     │
│  └─────┬──────┘  │  /api/compare  │  └────────────────────┘     │
│        │         │  /api/leaders   │                              │
│        ▼         │  /api/matchups  │                              │
│  In-Memory DFs   │  /api/similar   │                              │
│  (bat_careers,   │  /api/venue     │                              │
│   bowl_careers,  │  /api/form      │                              │
│   innings,       │  /api/team      │                              │
│   matchups,      └────────────────┘                              │
│   similarities,                                                  │
│   form_series,                                                   │
│   venue_baselines)                                               │
└──────────────────────────────────────────────────────────────────┘
          ▲
          │ pd.read_parquet() at startup
          │
┌─────────┴────────────────────────────────────────────────────────┐
│                    output/ directory                              │
│                                                                  │
│  batting_careers_full.parquet    bowling_careers_full.parquet     │
│  batting_innings_detail.parquet  bowling_spells_detail.parquet    │
│  batting_form_series.parquet     bowling_form_series.parquet      │
│  batting_similarities.parquet    bowling_similarities.parquet     │
│  matchups.parquet                matchups_by_phase.parquet        │
│  venue_baselines.parquet         batting_profiles.csv             │
│  bowling_profiles.csv                                            │
└──────────────────────────────────────────────────────────────────┘
```

### Data Flow

1. Pipeline runs offline → writes Parquet/CSV to `output/`.
2. Backend starts → loads all Parquet files into memory as pandas DataFrames.
3. Backend pre-computes search indices (trigram index on player names).
4. Frontend SPA boots → fetches data on demand via REST API.
5. TanStack Query caches responses; subsequent navigations are instant.

---

## 4. Data Layer

### 4.1 DataFrames Loaded at Startup

| Variable | Source File | Rows | Key Columns |
|----------|-----------|------|-------------|
| `bat_careers` | `batting_careers_full.parquet` | ~4K | `batter_id`, `batter`, `country`, `innings_count`, `total_runs`, `career_sr`, `career_avg`, `score_acceleration`, `score_power`, `score_control`, `grade_overall`, `archetype`, `peak_acceleration`, `peak_power`, `peak_control`, `war_batting`, `clutch_index_bat`, `chase_master_index`, `flat_track_index`, `position_group` |
| `bowl_careers` | `bowling_careers_full.parquet` | ~3K | `bowler_id`, `bowler`, `country`, `matches`, `total_wickets`, `career_economy`, `score_accuracy`, `score_control`, `score_threat`, `grade_overall`, `archetype`, `peak_accuracy`, `peak_control`, `peak_threat`, `war_bowling`, `clutch_index_bowl` |
| `bat_innings` | `batting_innings_detail.parquet` | ~51K | `batter_id`, `match_id`, `date`, `runs`, `balls_faced`, `sr`, `opposition`, all component columns |
| `bowl_spells` | `bowling_spells_detail.parquet` | ~38K | `bowler_id`, `match_id`, `date`, `wickets`, `runs_conceded`, `economy`, all component columns |
| `bat_form` | `batting_form_series.parquet` | ~150K | `batter_id`, `date`, rolling window metrics |
| `bowl_form` | `bowling_form_series.parquet` | ~100K | `bowler_id`, `date`, rolling window metrics |
| `bat_sim` | `batting_similarities.parquet` | ~40K | `batter_id_a`, `batter_id_b`, `similarity_score` |
| `bowl_sim` | `bowling_similarities.parquet` | ~25K | `bowler_id_a`, `bowler_id_b`, `similarity_score` |
| `matchups` | `matchups.parquet` | variable | `batter_id`, `bowler_id`, `balls`, `runs`, `sr`, `dismissals`, `dominance_index` |
| `matchups_phase` | `matchups_by_phase.parquet` | variable | Same + `phase` |
| `venue` | `venue_baselines.parquet` | ~200 | `venue`, `difficulty_score`, `avg_par_sr`, `matches` |

### 4.2 Search Index

At startup, the backend builds a trigram index over all player names (batters + bowlers combined). This supports:

- Exact substring matching ("Kohli" → "V Kohli")
- Fuzzy matching ("Bumra" → "JJ Bumrah")
- Country-filtered search ("India" + "K" → all Indian players starting with K)

Implementation: for each player, generate all 3-character substrings of their lowercased name. Store a `dict[str, set[player_id]]` mapping trigrams to player IDs. At query time, intersect the trigram sets for the query and rank by overlap count.

---

## 5. Page & Route Structure

| Route | Page | Description |
|-------|------|-------------|
| `/` | Home / Dashboard | Hero search bar, today's featured players, quick stats |
| `/search?q=...&country=...&role=...` | Search Results | Filterable player list |
| `/player/:id` | Player Profile | Full profile for one player |
| `/player/:id/innings` | Innings Log | Sortable table of all innings for a batter |
| `/player/:id/spells` | Spells Log | Sortable table of all spells for a bowler |
| `/rankings/:role/:metric` | Leaderboards | Sortable rankings with filters |
| `/compare?ids=id1,id2,...` | Player Comparison | Side-by-side radar + table |
| `/matchups?bat=...&bowl=...` | Head-to-Head | Batter vs bowler matchup detail |
| `/matchups/explore` | Matchup Explorer | Search for any batter–bowler combination |
| `/similar/:id` | Similar Players | Cosine-similarity nearest neighbours |
| `/team-builder` | Team Builder | Drag-and-drop XI creation |
| `/eras` | Era Explorer | Cross-generational timeline |
| `/venues` | Venue Analysis | Venue difficulty heatmap + player venue splits |
| `/glossary` | Glossary & Methodology | Metric explanations, formulas, FAQs |

---

## 6. Page Designs

### 6.1 Home / Dashboard

The landing page is designed to immediately engage fans and provide fast access to the most common actions.

```
┌──────────────────────────────────────────────────────────────────┐
│  ┌─── CRICKET METRICS ─────────────────────────────────────────┐ │
│  │              🏏  T20I Player Intelligence                   │ │
│  │                                                             │ │
│  │   ┌─────────────────────────────────────────────────────┐   │ │
│  │   │  🔍  Search any player...              [Bat] [Bowl] │   │ │
│  │   └─────────────────────────────────────────────────────┘   │ │
│  │                                                             │ │
│  │   Popular: Kohli · Buttler · Rashid Khan · Bumrah · SKY    │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌──── TOP RATED ────────┐  ┌──── POWER HITTERS ─────────────┐  │
│  │  1. SKY         93.2  │  │  1. T Head        91.4         │  │
│  │  2. V Kohli     89.7  │  │  2. JC Buttler    89.8         │  │
│  │  3. BKG Mendis  87.1  │  │  3. H Klaasen     88.2         │  │
│  │  4. JC Buttler  86.4  │  │  4. L Ronchi      86.7         │  │
│  │  5. T Head      85.9  │  │  5. CH Gayle      85.1         │  │
│  │  [View All Rankings →] │  │  [View Power Rankings →]       │  │
│  └────────────────────────┘  └────────────────────────────────┘  │
│                                                                  │
│  ┌──── BEST BOWLERS ─────┐  ┌──── CLUTCH PERFORMERS ─────────┐  │
│  │  1. Rashid Khan  91.8 │  │  1. V Kohli      +12.4         │  │
│  │  2. JJ Bumrah   89.3 │  │  2. MS Dhoni      +11.8        │  │
│  │  3. TG Southee  86.1 │  │  3. JC Buttler    +9.7         │  │
│  │  ...                  │  │  ...                            │  │
│  │  [View All →]         │  │  [View All →]                   │  │
│  └────────────────────────┘  └────────────────────────────────┘  │
│                                                                  │
│  ┌──── QUICK COMPARE ────────────────────────────────────────┐   │
│  │  Player 1: [____________]   vs   Player 2: [____________] │   │
│  │                        [Compare →]                        │   │
│  └───────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──── ARCHETYPES ───────────────────────────────────────────┐   │
│  │  🎯 Anchors  │ ⚡ Finishers │ 💥 Power │ 🎨 All-Round   │   │
│  │  Browse players by playing style →                        │   │
│  └───────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

**Features:**
- **Hero search** with autocomplete (debounced, 150ms). Dropdown shows top 8 matches with mini score badges.
- **Quick leaderboard cards** — 4 cards showing top 5 in: Overall Rating, Power, Bowling Accuracy, Clutch Index. Each links to the full leaderboard.
- **Quick compare** — two autocomplete inputs that navigate to `/compare?ids=...`.
- **Archetype browser** — clickable archetype badges that filter to `/rankings` with `archetype=...`.

---

### 6.2 Player Search

**Route:** `/search?q=kohli&country=India&role=bat&archetype=Explosive+Finisher`

```
┌──────────────────────────────────────────────────────────────────┐
│  🔍 [___kohli___________]   Country: [All ▾]  Role: [Bat ▾]    │
│                              Archetype: [All ▾]  Prov: [Hide ▾] │
│                                                                  │
│  3 results for "kohli"                                           │
│  ─────────────────────────────────────────────────────────────── │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  ☆ V Kohli                              India  🇮🇳         │  │
│  │  Archetype: Chase Master                                   │  │
│  │  137 innings · 4,008 runs · SR 137.8 · Avg 52.7           │  │
│  │                                                            │  │
│  │  ACC ████████████████████░░░░░  89.7                       │  │
│  │  POW █████████████████░░░░░░░░  75.3                       │  │
│  │  CTL ██████████████████████░░░  92.1                       │  │
│  │                                                            │  │
│  │  Overall: A+          [View Profile →] [+ Compare]         │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  ☆ V Kohli (2)                          India  🇮🇳         │  │
│  │  ⚠ Provisional (3 innings)                                 │  │
│  │  ...                                                       │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
```

**Features:**
- Trigram-based fuzzy search — tolerates typos and partial names.
- Filters: country (dropdown of all countries in dataset), role (bat/bowl/all), archetype (from `presentation.py` archetypes), provisional toggle.
- Each result card shows: name, country flag, archetype badge, summary stats, mini score bars, overall grade, and action buttons (view profile, add to compare).
- Results sorted by relevance (trigram overlap) then by overall score descending.
- URL-driven state: all filters reflected in query params for shareability.

---

### 6.3 Player Profile

**Route:** `/player/:id`

This is the richest page in the application. It surfaces everything we know about a player.

```
┌──────────────────────────────────────────────────────────────────┐
│  ← Back to Search                                                │
│                                                                  │
│  ╔══════════════════════════════════════════════════════════════╗ │
│  ║  V KOHLI                                    India 🇮🇳       ║ │
│  ║  "Chase Master"                             Overall: A+     ║ │
│  ║  137 innings · 4,008 runs · SR 137.8 · Avg 52.7            ║ │
│  ║  4s: 312  ·  6s: 87  ·  Position: Top Order                ║ │
│  ╚══════════════════════════════════════════════════════════════╝ │
│                                                                  │
│  ┌──── METRIC SCORES ────────────────────────────────────────┐   │
│  │                                                            │   │
│  │  ACCELERATION   ████████████████████░░░░░  89.7   (A+)    │   │
│  │  POWER          █████████████████░░░░░░░░  75.3   (A)     │   │
│  │  CONTROL        ██████████████████████░░░  92.1   (S)     │   │
│  │                                                            │   │
│  │         ┌─────── Radar Chart ───────┐                      │   │
│  │         │       Acceleration        │                      │   │
│  │         │          ╱ ╲              │                      │   │
│  │         │  Control ─── Power        │                      │   │
│  │         │    (filled polygon)       │                      │   │
│  │         └───────────────────────────┘                      │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  [Current] [Peak] [Era-Adjusted]     ← Toggle rating perspective │
│                                                                  │
│  ┌──── PEAK vs CURRENT ──────────────────────────────────────┐   │
│  │              Current    Peak     Delta                     │   │
│  │  Accel.       89.7      91.3     -1.6                     │   │
│  │  Power        75.3      79.8     -4.5                     │   │
│  │  Control      92.1      94.0     -1.9                     │   │
│  │                                                            │   │
│  │  Peak window: Mar 2016 – Feb 2018  (24 months)            │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──── FORM TRACKER ─────────────────────────────────────────┐   │
│  │                                                            │   │
│  │  ──── Acceleration  ──── Power  ──── Control              │   │
│  │                                                            │   │
│  │  100│                                                      │   │
│  │   80│  ╱╲   ╱╲                   ╱╲                       │   │
│  │   60│╱    ╲╱    ╲     ╱╲      ╱╱    ╲                    │   │
│  │   40│              ╲╱    ╲╱╱╱         ╲                   │   │
│  │   20│                                                      │   │
│  │     └──────────────────────────────────────────────────    │   │
│  │      2018    2019    2020    2021    2022    2023    2024   │   │
│  │                                                            │   │
│  │  Window: [10 innings ▾]   Metric: [All ▾]                 │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──── ADVANCED METRICS ─────────────────────────────────────┐   │
│  │                                                            │   │
│  │  WAR (Batting)          3.42    (top 12%)                  │   │
│  │  WAR Rate               0.68    per 50 innings             │   │
│  │  Clutch Index          +12.4    🔥 Clutch Player           │   │
│  │  Chase Master Index      8.7    (top 5%)                   │   │
│  │  Flat Track Index       -0.03   ✅ Performs everywhere     │   │
│  │  WPA (Career)           +18.2                              │   │
│  │  WPA / Match            +0.13                              │   │
│  │                                                            │   │
│  │  ℹ️  Hover any metric for explanation                      │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──── COMPONENT BREAKDOWN ──────────────────────────────────┐   │
│  │                                                            │   │
│  │  Acceleration Components          (stacked bar chart)      │   │
│  │  ┌────────────────────────────────────────────┐            │   │
│  │  │ Overall SR │ SR Growth │ Death SR │ Impact │            │   │
│  │  └────────────────────────────────────────────┘            │   │
│  │                                                            │   │
│  │  Power Components                 (stacked bar chart)      │   │
│  │  ┌────────────────────────────────────────────────────┐    │   │
│  │  │ Bdry% │ 6Rate │ BdryVsPar │ PeakSR │ Burst │ Imp │    │   │
│  │  └────────────────────────────────────────────────────┘    │   │
│  │                                                            │   │
│  │  Control Components               (stacked bar chart)      │   │
│  │  ┌───────────────────────────────────────────────┐         │   │
│  │  │ Dot% │ Rotation │ Contribution │ Avg │ DismQ │         │   │
│  │  └───────────────────────────────────────────────┘         │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──── PHASE SPLITS ─────────────────────────────────────────┐   │
│  │                                                            │   │
│  │           Powerplay    Middle      Death                   │   │
│  │  Balls      412         680         340                    │   │
│  │  Runs       510         820         520                    │   │
│  │  SR        123.8       120.6       152.9                   │   │
│  │  SR/Par     0.98        1.05        1.14                   │   │
│  │  Dot%       31.2%       34.8%       25.1%                  │   │
│  │  Bdry%      18.4%       14.2%       22.8%                  │   │
│  │                                                            │   │
│  │  (horizontal grouped bar chart comparing SR/Par by phase)  │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──── CHASE SPLITS ─────────────────────────────────────────┐   │
│  │                                                            │   │
│  │           Setting (Inn 1)    Chasing (Inn 2)    Delta      │   │
│  │  Innings       65                72              +7        │   │
│  │  Avg          48.2              57.3             +9.1      │   │
│  │  SR          131.4             144.2            +12.8      │   │
│  │  Composite     7.2               9.1             +1.9     │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──── TOP MATCHUPS ─────────────────────────────────────────┐   │
│  │                                                            │   │
│  │  Best Against (Dominates):                                 │   │
│  │   vs T Boult       42 balls  SR 181.0  Dom +32.1          │   │
│  │   vs Rashid Khan   28 balls  SR 167.9  Dom +28.4          │   │
│  │                                                            │   │
│  │  Worst Against (Dominated by):                             │   │
│  │   vs JJ Bumrah     31 balls  SR  89.2  Dom -24.7          │   │
│  │   vs A Zampa       24 balls  SR  95.8  Dom -19.3          │   │
│  │                                                            │   │
│  │  [View all matchups →]                                     │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──── SIMILAR PLAYERS ──────────────────────────────────────┐   │
│  │                                                            │   │
│  │  Players with the most similar statistical profiles:       │   │
│  │                                                            │   │
│  │  1. BKG Mendis (0.94)   ACC 87  POW 72  CTL 90            │   │
│  │  2. KL Rahul   (0.91)   ACC 82  POW 68  CTL 88            │   │
│  │  3. KS Williamson (0.89) ACC 78 POW 64  CTL 91            │   │
│  │                                                            │   │
│  │  [View full similarity analysis →]                         │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──── INNINGS LOG (Recent 10) ──────────────────────────────┐   │
│  │                                                            │   │
│  │  Date        Vs           Runs  Balls  SR     4s  6s      │   │
│  │  2024-06-15  England       76    53   143.4    8   2      │   │
│  │  2024-06-09  Pakistan      47    31   151.6    4   2      │   │
│  │  2024-06-01  Ireland       24*   18   133.3    3   0      │   │
│  │  ...                                                       │   │
│  │                                                            │   │
│  │  [View full innings log →]  [Export CSV]                   │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──── ACTIONS ──────────────────────────────────────────────┐   │
│  │  [Compare with...] [Add to Team Builder] [Share Profile]  │   │
│  └────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

**Bowling Profile Variant:**

For bowlers (detected via `bowler_id` presence), the profile replaces batting-specific sections:

- Metric bars: Accuracy / Control / Threat (instead of Acceleration / Power / Control).
- Phase splits: economy, dot %, SR by powerplay/middle/death.
- Spell log instead of innings log.
- Wicket quality breakdown (bowled/LBW %, top-order wickets, etc.).
- Matchup section shows batters the bowler dominates / is dominated by.

**All-Rounder Detection:**

If a player appears in both `bat_careers` and `bowl_careers` (with non-provisional status in both), show a toggle: `[Batting Profile] [Bowling Profile]` with a combined "All-Rounder Score" card.

---

### 6.4 Leaderboards & Rankings

**Route:** `/rankings/bat/acceleration`, `/rankings/bowl/threat`, etc.

```
┌──────────────────────────────────────────────────────────────────┐
│  LEADERBOARDS                                                    │
│                                                                  │
│  Role: [● Batting  ○ Bowling]                                    │
│                                                                  │
│  Metric: [Acceleration ▾]  Country: [All ▾]  Archetype: [All ▾] │
│  Min Innings: [10____]   Provisional: [Hide ▾]                   │
│  Position: [All ▾]       Active Only: [☐]                        │
│                                                                  │
│  ─── Showing 1–25 of 892 ──────────────────────────────────────  │
│                                                                  │
│  Rk  Player          Country  Inn   Runs   SR    ACC  POW  CTL   │
│  ──  ──────────────  ───────  ───   ────  ────   ───  ───  ───   │
│   1  SKY             India    98   2,894  171.2  93.2 84.1 78.6  │
│   2  V Kohli         India   137   4,008  137.8  89.7 75.3 92.1  │
│   3  BKG Mendis      SL       65   1,490  155.7  87.1 72.4 90.3  │
│   4  JC Buttler      England 112   3,012  148.2  86.4 89.8 71.0  │
│   5  T Head          Aus      54   1,247  158.3  85.9 91.4 65.2  │
│   ·                                                               │
│   ·                                                               │
│  25  DA Warner       Aus     102   2,894  142.5  74.8 76.1 72.4  │
│                                                                  │
│  [← Prev]  Page 1 of 36  [Next →]                               │
│                                                                  │
│  Sort by: [▼ ACC] [POW] [CTL] [SR] [Runs] [Innings] [WAR]       │
│                                                                  │
│  [Export CSV]  [Share URL]                                        │
└──────────────────────────────────────────────────────────────────┘
```

**Features:**
- Column headers are clickable for sorting (ascending/descending toggle).
- Multi-metric sort: click "ACC" to sort by acceleration, click again to reverse.
- All filters update the URL query params for shareability.
- Each player name is a link to their profile.
- Checkbox column for selecting players to compare (max 4). "Compare Selected" button appears when ≥2 selected.
- **Bowling leaderboard** shows: Accuracy / Control / Threat, plus Economy, SR, Wickets.
- **Composite leaderboard** option: sort by `grade_overall` (the superstar-bonus weighted overall score from `presentation.py`).
- **Additional sort columns**: WAR, Clutch Index, Chase Master Index, WPA, Flat Track Index — surfacing all the advanced metrics as leaderboard dimensions.

---

### 6.5 Player Comparison

**Route:** `/compare?ids=p1234,p5678` (supports 2–4 player IDs)

```
┌──────────────────────────────────────────────────────────────────┐
│  COMPARE PLAYERS                                                 │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  [+ Add Player]             │
│  │ 🔍 V Kohli ✕ │  │ 🔍 Buttler ✕ │                             │
│  └──────────────┘  └──────────────┘                              │
│                                                                  │
│  ═══════════════════════════════════════════════════════════════  │
│                                                                  │
│  ┌──── RADAR OVERLAY ────────────────────────────────────────┐   │
│  │                                                            │   │
│  │              Acceleration                                  │   │
│  │                  ╱╲                                        │   │
│  │                ╱    ╲                                      │   │
│  │   Clutch     ╱   ·   ╲     Power                          │   │
│  │            ╱   ·   ·   ╲                                  │   │
│  │          ╱  ·    ·    ·  ╲                                │   │
│  │   Control ─── · ─── · ─── WAR                             │   │
│  │                                                            │   │
│  │   ── V Kohli (blue)     ── JC Buttler (orange)            │   │
│  │                                                            │   │
│  │  Axes: ACC, POW, CTL, WAR, Clutch, Chase Master           │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──── STAT TABLE ───────────────────────────────────────────┐   │
│  │                                                            │   │
│  │  Metric             V Kohli      JC Buttler     Winner     │   │
│  │  ────────────────   ─────────    ──────────     ──────     │   │
│  │  Overall Grade       A+           A              Kohli     │   │
│  │  Archetype          Chase Master  Explosive      —         │   │
│  │  Innings             137          112            Kohli     │   │
│  │  Runs               4,008        3,012           Kohli     │   │
│  │  Career SR          137.8         148.2          Buttler   │   │
│  │  Career Avg          52.7          33.1          Kohli     │   │
│  │  Acceleration        89.7          86.4          Kohli     │   │
│  │  Power               75.3          89.8          Buttler   │   │
│  │  Control             92.1          71.0          Kohli     │   │
│  │  WAR                  3.42          2.87         Kohli     │   │
│  │  Clutch Index       +12.4          +9.7          Kohli     │   │
│  │  Chase Master         8.7           5.2          Kohli     │   │
│  │  WPA / Match         +0.13         +0.11         Kohli     │   │
│  │  Peak Accel.          91.3          88.1         Kohli     │   │
│  │  Peak Power           79.8          92.4         Buttler   │   │
│  │  Peak Control         94.0          74.3         Kohli     │   │
│  │                                                            │   │
│  │  Winner highlights shown in bold / colour                  │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──── FORM COMPARISON ──────────────────────────────────────┐   │
│  │                                                            │   │
│  │  (Overlaid line chart: both players' form over time)       │   │
│  │  Metric: [Acceleration ▾]                                  │   │
│  │                                                            │   │
│  │  100│                                                      │   │
│  │   80│  ── Kohli ── Buttler                                │   │
│  │   60│                                                      │   │
│  │   40│                                                      │   │
│  │     └──────────────────────────────────────────────────    │   │
│  │      2018    2019    2020    2021    2022    2023    2024   │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──── PHASE COMPARISON ─────────────────────────────────────┐   │
│  │  (Grouped bar chart: SR/Par by phase for each player)      │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──── HEAD-TO-HEAD ─────────────────────────────────────────┐   │
│  │  (If one is a batter and one is a bowler, or if both are   │   │
│  │   batters who have faced the same bowlers, show matchup)   │   │
│  │                                                            │   │
│  │  V Kohli vs JC Buttler (shared matchups):                  │   │
│  │  Both faced Rashid Khan:                                   │   │
│  │    Kohli: 28 balls, SR 167.9   Buttler: 34 balls, SR 141.2│   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  [Share Comparison]  [Export PNG]                                 │
└──────────────────────────────────────────────────────────────────┘
```

**Features:**
- Autocomplete inputs for adding/removing players (2–4 supported).
- **6-axis radar chart** with overlaid polygons (one colour per player).
- **Stat comparison table** with automatic "winner" highlighting per row.
- **Form overlay** — line chart showing both players' rolling form on the same time axis. Dropdown to switch between acceleration, power, control.
- **Phase comparison** — grouped bars for powerplay/middle/death SR vs par.
- **Shared matchup analysis** — if both players are batters, find bowlers they've both faced and compare performance against the same opponents.
- URL-driven: the comparison URL is shareable.

---

### 6.6 Head-to-Head Matchups

**Route:** `/matchups?bat=p1234&bowl=p5678`

```
┌──────────────────────────────────────────────────────────────────┐
│  HEAD-TO-HEAD                                                    │
│                                                                  │
│  Batter: [🔍 V Kohli      ]  vs  Bowler: [🔍 JJ Bumrah     ]   │
│                                                                  │
│  ╔══════════════════════════════════════════════════════════════╗ │
│  ║  V Kohli  vs  JJ Bumrah                                    ║ │
│  ║                                                              ║ │
│  ║  31 balls  ·  28 runs  ·  SR 90.3  ·  3 dismissals         ║ │
│  ║  Dots: 14  ·  4s: 3  ·  6s: 0                              ║ │
│  ║                                                              ║ │
│  ║  Dominance Index: -24.7  → Bowler dominates                 ║ │
│  ║                                                              ║ │
│  ║  ░░░░░░░░░░░░░░░░████████████████████████████               ║ │
│  ║  ← Batter            NEUTRAL            Bowler →            ║ │
│  ╚══════════════════════════════════════════════════════════════╝ │
│                                                                  │
│  ┌──── BY PHASE ─────────────────────────────────────────────┐   │
│  │           Powerplay    Middle      Death                   │   │
│  │  Balls       8          15           8                     │   │
│  │  Runs       12          10           6                     │   │
│  │  SR       150.0         66.7        75.0                   │   │
│  │  Dots        2           9           3                     │   │
│  │  Wkts        0           2           1                     │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──── BALL-BY-BALL TIMELINE ────────────────────────────────┐   │
│  │  (Visual timeline: each dot = delivery, coloured by runs)  │   │
│  │                                                            │   │
│  │  Match 1 (2019-01-15):  ● ○ ● ● ◉ ○ ○ W                  │   │
│  │  Match 2 (2021-10-24):  ○ ○ ○ ● ○ ○ W ○ ○ ●              │   │
│  │  Match 3 (2022-09-04):  ○ ● ○ ○ ○ ○ ○ W                  │   │
│  │                                                            │   │
│  │  ● = 1-3 runs  ◉ = boundary  ○ = dot  W = wicket         │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  [View Kohli's profile →]  [View Bumrah's profile →]             │
└──────────────────────────────────────────────────────────────────┘
```

**Matchup Explorer** (`/matchups/explore`):

A browsable page where users can:
- Search for any batter or bowler to see all their matchups.
- Sort by dominance index, balls faced, SR, dismissals.
- Filter by minimum balls (default: 6).
- See "bunnies" (batters a bowler always gets) and "nemeses" (bowlers a batter can't play).

---

### 6.7 Similarity Explorer ("Comps")

**Route:** `/similar/:id`

```
┌──────────────────────────────────────────────────────────────────┐
│  SIMILAR PLAYERS TO: V KOHLI                                     │
│                                                                  │
│  Players ranked by statistical profile similarity (cosine).      │
│  Higher similarity = more similar playing style and output.      │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Rk  Player          Sim    ACC   POW   CTL   Country     │  │
│  │  ──  ──────────────  ────   ───   ───   ───   ───────     │  │
│  │   1  BKG Mendis      0.94   87.1  72.4  90.3  Sri Lanka   │  │
│  │   2  KL Rahul        0.91   82.4  68.1  88.0  India       │  │
│  │   3  KS Williamson   0.89   78.2  64.3  91.4  NZ          │  │
│  │   4  Babar Azam      0.87   80.1  62.8  89.7  Pakistan    │  │
│  │   5  SD Hope         0.85   76.3  60.2  87.1  West Indies │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌──── SIMILARITY MAP ───────────────────────────────────────┐   │
│  │                                                            │   │
│  │  (2D scatter plot: players projected via PCA/t-SNE,        │   │
│  │   target player highlighted, nearest neighbours circled,   │   │
│  │   hover shows player name and scores)                      │   │
│  │                                                            │   │
│  │       ·  · ·                 · ·                           │   │
│  │     ·    ★ KOHLI ·         ·   ·                          │   │
│  │      · Mendis ·  · Rahul                                  │   │
│  │        ·  ·                                                │   │
│  │                        · · ·                               │   │
│  │                       Buttler ·  Head                      │   │
│  │                        · ·                                 │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  Click any player to view their profile or compare.              │
│  [Compare with top similar →]                                    │
└──────────────────────────────────────────────────────────────────┘
```

**Features:**
- Top-K similar players (default K=10, configurable) from the pre-computed similarity matrix.
- 2D projection scatter plot for visual clustering (computed client-side from the 3 metric scores using simple PCA, or pre-computed server-side).
- Click any player in the list to navigate to their profile.
- "Compare with top similar" button pre-fills the compare page with the target + top 3 similar players.

---

### 6.8 Team Builder

**Route:** `/team-builder`

An interactive tool for building hypothetical T20I XIs and seeing their aggregate profile.

```
┌──────────────────────────────────────────────────────────────────┐
│  TEAM BUILDER                                                    │
│                                                                  │
│  ┌──── YOUR XI ──────────────────────────────────────────────┐   │
│  │                                                            │   │
│  │  #  Player          Role     ACC   POW   CTL   Grade      │   │
│  │  1  [🔍 Search...]  Opener                                 │   │
│  │  2  V Kohli         Top 3    89.7  75.3  92.1   A+        │   │
│  │  3  SKY             Top 3    93.2  84.1  78.6   S         │   │
│  │  4  [🔍 Search...]  Middle                                 │   │
│  │  5  [🔍 Search...]  Middle                                 │   │
│  │  6  [🔍 Search...]  Finisher                               │   │
│  │  7  [🔍 Search...]  All-Rnd                                │   │
│  │  8  [🔍 Search...]  Bowler                                 │   │
│  │  9  [🔍 Search...]  Bowler                                 │   │
│  │ 10  [🔍 Search...]  Bowler                                 │   │
│  │ 11  [🔍 Search...]  Bowler                                 │   │
│  │                                                            │   │
│  │  Constraints: Min 5 bowlers, Max 7 batters, 1-2 keepers   │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──── TEAM ANALYSIS ────────────────────────────────────────┐   │
│  │                                                            │   │
│  │  Batting Strength                                          │   │
│  │  Avg Acceleration: 84.2  Avg Power: 76.8  Avg Control: 82.1│  │
│  │                                                            │   │
│  │  Bowling Strength                                          │   │
│  │  Avg Accuracy: 78.4  Avg Control: 80.1  Avg Threat: 74.2  │   │
│  │                                                            │   │
│  │  Team WAR: 28.4        Team Clutch Avg: +7.2              │   │
│  │                                                            │   │
│  │  ┌─── Team Radar ───┐                                     │   │
│  │  │   Bat Accel       │                                     │   │
│  │  │     ╱ ╲          │                                     │   │
│  │  │ Threat  Power     │                                     │   │
│  │  │  │        │       │                                     │   │
│  │  │ Bowl Ctrl Control │                                     │   │
│  │  │     ╲ ╱          │                                     │   │
│  │  │   Accuracy        │                                     │   │
│  │  └───────────────────┘                                     │   │
│  │                                                            │   │
│  │  Weaknesses:                                               │   │
│  │  ⚠ Death bowling below average (avg threat 62.1)          │   │
│  │  ⚠ No left-arm variety                                    │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──── TEMPLATES ────────────────────────────────────────────┐   │
│  │  [Auto-fill: Best XI by WAR]                               │   │
│  │  [Auto-fill: Best Power XI]                                │   │
│  │  [Auto-fill: Best Control XI]                              │   │
│  │  [Auto-fill: India Best XI]  [Auto-fill: Australia Best]   │   │
│  │  [Clear All]                                               │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  [Share Team]  [Export PNG]                                       │
└──────────────────────────────────────────────────────────────────┘
```

**Features:**
- 11 slots with autocomplete search for each position.
- Automatic role detection (from `position_group`) with manual override.
- Real-time aggregate stats recalculation as players are added/removed.
- Team radar chart (6 axes: Bat Acceleration, Bat Power, Bat Control, Bowl Accuracy, Bowl Control, Bowl Threat).
- Weakness detection: flags if any dimension falls below the 50th percentile average.
- Template auto-fill: "Best XI by WAR" greedily picks the highest WAR players respecting positional constraints.
- Country-constrained auto-fill: "Best India XI" picks only Indian players.
- Shareable URL encoding the selected player IDs.

---

### 6.9 Era Explorer

**Route:** `/eras`

```
┌──────────────────────────────────────────────────────────────────┐
│  ERA EXPLORER                                                    │
│                                                                  │
│  How has T20I cricket evolved?                                   │
│                                                                  │
│  ┌──── TIMELINE ─────────────────────────────────────────────┐   │
│  │                                                            │   │
│  │  (Line chart: era baselines over time)                     │   │
│  │                                                            │   │
│  │   ── Par SR   ── Boundary Rate   ── Dot %                 │   │
│  │                                                            │   │
│  │  170│                                   ╱                  │   │
│  │  160│                              ╱╱╱╱                    │   │
│  │  150│                     ╱╱╱╱╱╱╱╱                         │   │
│  │  140│            ╱╱╱╱╱╱╱╱                                  │   │
│  │  130│  ╱╱╱╱╱╱╱╱╱                                           │   │
│  │  120│╱                                                     │   │
│  │     └──────────────────────────────────────────────────    │   │
│  │      2006  2008  2010  2012  2014  2016  2018  2020  2024  │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──── ERA MULTIPLIER TABLE ─────────────────────────────────┐   │
│  │                                                            │   │
│  │  Year   Par SR   Bdry Rate   Dot%   Era Multiplier         │   │
│  │  2007   119.2    12.1%       38.2%   1.28                  │   │
│  │  2010   124.8    13.4%       36.1%   1.21                  │   │
│  │  2014   131.5    14.8%       34.5%   1.14                  │   │
│  │  2018   142.3    16.2%       32.8%   1.06                  │   │
│  │  2022   150.7    17.5%       31.2%   1.01                  │   │
│  │  2024   155.1    18.1%       30.4%   1.00 (baseline)       │   │
│  │                                                            │   │
│  │  ℹ A multiplier of 1.28 means a 2007 performance is       │   │
│  │    worth 28% more than the same raw numbers in 2024.       │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──── CROSS-ERA PLAYER COMPARISON ──────────────────────────┐   │
│  │                                                            │   │
│  │  Compare peak performers across different eras:            │   │
│  │                                                            │   │
│  │  Player 1: [🔍 CH Gayle  (2009-2015)]                     │   │
│  │  Player 2: [🔍 SKY       (2021-2024)]                     │   │
│  │                                                            │   │
│  │  (Radar chart comparing their era-adjusted peak ratings)   │   │
│  │                                                            │   │
│  │             Raw Scores        Era-Adjusted                 │   │
│  │  Gayle     ACC 81 POW 94     ACC 88 POW 97                │   │
│  │  SKY       ACC 93 POW 84     ACC 93 POW 84                │   │
│  │                                                            │   │
│  │  After era adjustment, Gayle's power is even more          │   │
│  │  impressive — he dominated in a lower-scoring era.         │   │
│  └────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

### 6.10 Venue Analysis

**Route:** `/venues`

```
┌──────────────────────────────────────────────────────────────────┐
│  VENUE ANALYSIS                                                  │
│                                                                  │
│  ┌──── VENUE DIFFICULTY MAP ─────────────────────────────────┐   │
│  │                                                            │   │
│  │  (Bubble chart or heatmap: venues plotted by difficulty     │   │
│  │   score, bubble size = matches played)                     │   │
│  │                                                            │   │
│  │  Easier ◄─────────────────────────────────────► Harder     │   │
│  │                                                            │   │
│  │  ○ Dubai       ● Dharamsala    ◉ Melbourne                │   │
│  │  ○ Centurion   ● Mirpur       ◉ Bridgetown               │   │
│  │                                                            │   │
│  │  Click a venue for detailed breakdown.                     │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──── FLAT TRACK BULLY INDEX ───────────────────────────────┐   │
│  │                                                            │   │
│  │  Players sorted by FTB Index (negative = flat track bully) │   │
│  │                                                            │   │
│  │  🏆 V Kohli          -0.03  ✅ Consistent everywhere      │   │
│  │  🏆 AB de Villiers   -0.05  ✅ Consistent everywhere      │   │
│  │  ⚠️  RG Sharma       -0.18  ⚠ Slight flat-track bias     │   │
│  │  🚩 [Player X]       -0.42  🚩 Flat track bully           │   │
│  │                                                            │   │
│  │  Search: [🔍 ____________]  Min Innings: [20]              │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                  │
│  ┌──── PLAYER AT VENUE ──────────────────────────────────────┐   │
│  │                                                            │   │
│  │  Player: [🔍 V Kohli]                                     │   │
│  │                                                            │   │
│  │  Venue            Inn  Runs   SR     Avg    SR/Par         │   │
│  │  Melbourne          8   342  141.2   48.9   1.08           │   │
│  │  Colombo (RPS)      6   218  152.1   54.5   1.12           │   │
│  │  Dubai              12  380  128.4   38.0   0.96           │   │
│  │  ...                                                       │   │
│  └────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

### 6.11 Glossary & Methodology

**Route:** `/glossary`

A comprehensive reference page explaining every metric. Organised into sections:

1. **Core Batting Metrics** — Acceleration, Power, Control (with sub-component breakdowns).
2. **Core Bowling Metrics** — Accuracy, Control, Threat (with sub-component breakdowns).
3. **Rating System** — Bayesian shrinkage, percentile mapping, confidence bonus.
4. **Advanced Metrics** — WAR, Clutch Index, Chase Master Index, WPA, Flat Track Index.
5. **Context Adjustments** — Opposition quality, team quality, match quality, recency weighting, era adjustment.
6. **Grades & Archetypes** — Grade boundaries, archetype definitions.
7. **Similarity** — Cosine similarity methodology.
8. **FAQ** — Common questions ("Why is Player X rated lower than I expect?", "How is provisional status determined?", etc.).

Each metric entry includes:
- Plain-English definition.
- Formula (rendered with KaTeX or MathJax).
- Interpretation guide (what's good, what's bad).
- Example player illustrating the metric.

---

## 7. Shared Components

### 7.1 Component Library

| Component | Description | Used On |
|-----------|-------------|---------|
| `<PlayerCard>` | Compact card with name, country, archetype, mini score bars | Search, Home |
| `<ScoreBar>` | Horizontal bar (0–100) with colour gradient and label | Profile, Search, Compare |
| `<RadarChart>` | 3–6 axis spider chart, supports overlaid polygons | Profile, Compare, Team Builder |
| `<FormSparkline>` | Mini time-series line (100px wide) for form indication | Leaderboards, Search cards |
| `<GradeBadge>` | Letter grade chip (S/A+/A/B+/B/C+/C/D) with colour | Everywhere |
| `<ArchetypeBadge>` | Styled label with icon for archetype | Profile, Search |
| `<MetricTooltip>` | Hover tooltip with metric explanation | Profile, Glossary |
| `<PlayerAutocomplete>` | Fuzzy search input with dropdown suggestions | Search, Compare, Team Builder |
| `<PhaseBar>` | Grouped bar chart for powerplay/middle/death splits | Profile, Compare |
| `<DominanceGauge>` | Horizontal gauge from -50 (bowler) to +50 (batter) | Matchups |
| `<CountryFlag>` | Emoji or SVG flag for country | Everywhere |
| `<ProvisionalBadge>` | Warning indicator for provisional players | Everywhere |
| `<Pagination>` | Page controls with size selector | Leaderboards, Innings Log |
| `<SortableTable>` | Table with clickable column headers for sorting | Leaderboards, Matchups |
| `<FilterBar>` | Composable filter row (dropdowns, toggles, inputs) | Leaderboards, Search |
| `<ExportButton>` | CSV / PNG / URL share export | Leaderboards, Compare, Team Builder |

### 7.2 Score Bar Colour Mapping

| Range | Colour | Grade |
|-------|--------|-------|
| 95–100 | Gold (#FFD700) | S |
| 85–94 | Emerald (#10B981) | A+ |
| 75–84 | Green (#22C55E) | A |
| 60–74 | Cyan (#06B6D4) | B+ |
| 45–59 | Blue (#3B82F6) | B |
| 30–44 | Amber (#F59E0B) | C+ |
| 15–29 | Orange (#F97316) | C |
| 0–14 | Red (#EF4444) | D |

---

## 8. Visualisation Specifications

### 8.1 Radar / Spider Chart

- **Axes**: 3 (batting: ACC/POW/CTL) or 6 (comparison: all batting + advanced).
- **Scale**: 0–100 on each axis, with gridlines at 25, 50, 75.
- **Polygon fill**: semi-transparent (opacity 0.25) with solid border.
- **Multi-player**: up to 4 overlaid polygons with distinct colours.
- **Interaction**: hover an axis to see the exact value.
- **Library**: D3.js custom component (Recharts doesn't support true radar natively with enough control).

### 8.2 Form Time-Series

- **X-axis**: date (or innings number).
- **Y-axis**: 0–100 (metric score).
- **Line**: smooth (cubic interpolation) with data point dots.
- **Multi-metric**: up to 3 lines (acceleration, power, control) with legend toggle.
- **Brush**: zoomable date range selector at the bottom.
- **Library**: Recharts `<LineChart>` with `<Brush>`.

### 8.3 Component Stacked Bar

- **Horizontal stacked bar** showing the contribution of each sub-component to the overall metric.
- **Segments**: coloured by sub-component, with labels inside if wide enough, otherwise above.
- **Interaction**: hover a segment to see component name, raw value, and weight.
- **Library**: Recharts `<BarChart>` with `layout="vertical"` and `<Bar stackId="a">`.

### 8.4 Phase Grouped Bars

- **Groups**: Powerplay, Middle, Death.
- **Bars per group**: one per player (in compare) or one per stat (in profile).
- **Y-axis**: SR vs Par (centred at 1.0, range 0.5–2.0).
- **Library**: Recharts `<BarChart>`.

### 8.5 Dominance Gauge

- **Horizontal gauge** from -50 to +50.
- **Gradient**: red (bowler dominates) ← neutral (grey) → green (batter dominates).
- **Pointer**: triangle or line indicating the dominance index value.
- **Library**: Custom SVG (simple, ~30 lines of React).

### 8.6 Similarity Scatter Plot

- **2D projection**: PCA of the 3 metric scores (or pre-computed embeddings).
- **Dots**: one per non-provisional player, coloured by archetype.
- **Target player**: highlighted with a larger marker and label.
- **Nearest neighbours**: connected with dashed lines, labelled.
- **Interaction**: hover to see player name; click to navigate.
- **Library**: D3.js with zoom/pan.

### 8.7 Ball-by-Ball Timeline (Matchups)

- **Horizontal strip**: one row per match.
- **Dots**: one per delivery, coloured by outcome (dot=grey, 1-3=blue, boundary=green, six=gold, wicket=red).
- **Library**: Custom SVG component.

---

## 9. API Endpoints

All endpoints return JSON. The API is read-only and stateless.

### 9.1 Search

| Method | Path | Query Params | Response |
|--------|------|-------------|----------|
| GET | `/api/search` | `q` (string), `role` (bat\|bowl\|all), `country` (string), `archetype` (string), `provisional` (bool), `limit` (int, default 20) | `{ results: PlayerSummary[], total: int }` |

### 9.2 Player

| Method | Path | Response |
|--------|------|----------|
| GET | `/api/player/{id}` | Full player profile (career stats, scores, grades, archetype, advanced metrics, peak ratings, phase splits, chase splits, top matchups, similar players) |
| GET | `/api/player/{id}/innings` | `{ innings: InningsDetail[], total: int }` with pagination (`page`, `per_page`) |
| GET | `/api/player/{id}/spells` | `{ spells: SpellDetail[], total: int }` (for bowlers) |
| GET | `/api/player/{id}/form` | `{ series: FormPoint[] }` — time-series form data |
| GET | `/api/player/{id}/matchups` | `{ matchups: Matchup[], top_bunnies: Matchup[], top_nemeses: Matchup[] }` |
| GET | `/api/player/{id}/similar` | `{ similar: SimilarPlayer[] }` |

### 9.3 Leaderboards

| Method | Path | Query Params | Response |
|--------|------|-------------|----------|
| GET | `/api/rankings/{role}` | `sort` (column name), `order` (asc\|desc), `country`, `archetype`, `min_innings` (int), `provisional` (bool), `page`, `per_page` | `{ players: PlayerSummary[], total: int, page: int }` |

### 9.4 Comparison

| Method | Path | Query Params | Response |
|--------|------|-------------|----------|
| GET | `/api/compare` | `ids` (comma-separated, 2–4) | `{ players: FullProfile[], shared_matchups: SharedMatchup[] }` |

### 9.5 Matchups

| Method | Path | Query Params | Response |
|--------|------|-------------|----------|
| GET | `/api/matchups` | `bat` (batter_id), `bowl` (bowler_id) | Full matchup detail with phase breakdown |
| GET | `/api/matchups/explore` | `player_id`, `role` (bat\|bowl), `sort`, `min_balls`, `page`, `per_page` | All matchups for a player, paginated |

### 9.6 Venues

| Method | Path | Query Params | Response |
|--------|------|-------------|----------|
| GET | `/api/venues` | — | `{ venues: VenueBaseline[] }` |
| GET | `/api/venues/{venue_name}/players` | `role`, `min_innings` | Player performance at a specific venue |
| GET | `/api/player/{id}/venues` | — | Player's venue splits |

### 9.7 Eras

| Method | Path | Response |
|--------|------|----------|
| GET | `/api/eras` | `{ baselines: EraBaseline[], multipliers: EraMultiplier[] }` |

### 9.8 Team Builder

| Method | Path | Query Params | Response |
|--------|------|-------------|----------|
| GET | `/api/team/analyse` | `ids` (comma-separated, up to 11) | Aggregate team analysis (avg scores, WAR, weaknesses) |
| GET | `/api/team/auto-fill` | `strategy` (war\|power\|control\|country), `country` (optional) | Suggested XI |

### 9.9 Response Schemas

```
PlayerSummary {
  id: string
  name: string
  country: string
  role: "bat" | "bowl" | "all-rounder"
  archetype: string
  grade_overall: string
  innings_count: int           // or matches for bowlers
  total_runs: int              // or total_wickets for bowlers
  career_sr: float             // or career_economy for bowlers
  career_avg: float
  score_acceleration: float    // or score_accuracy
  score_power: float           // or score_control (bowl)
  score_control: float         // or score_threat
  is_provisional: bool
  form_trend: "up" | "down" | "stable"
}

FullProfile extends PlayerSummary {
  // Career stats
  total_balls: int
  total_fours: int
  total_sixes: int
  position_group: string

  // Scores (0-100)
  score_acceleration: float
  score_power: float
  score_control: float

  // Grades
  grade_acceleration: string
  grade_power: string
  grade_control: string
  grade_overall: string

  // Peak ratings
  peak_acceleration: float
  peak_power: float
  peak_control: float
  peak_window_start: date | null
  peak_window_end: date | null

  // Advanced
  war_batting: float
  war_rate: float
  clutch_index: float
  chase_master_index: float
  flat_track_index: float
  wpa_career: float
  wpa_per_match: float

  // Phase splits
  phases: { powerplay: PhaseSplit, middle: PhaseSplit, death: PhaseSplit }

  // Chase splits
  chase_splits: { setting: ChaseSplit, chasing: ChaseSplit }

  // Components
  components: {
    acceleration: { overall_sr: float, sr_growth: float, death_sr: float, impact: float }
    power: { boundary_pct: float, six_rate: float, boundary_rate_vs_par: float,
             peak_phase_sr: float, finishing_burst: float, power_impact: float }
    control: { dot_pct: float, rotation: float, contribution: float,
               avg_proxy: float, dismissal_quality: float }
  }

  // Top matchups
  top_bunnies: Matchup[]
  top_nemeses: Matchup[]

  // Similar players
  similar: SimilarPlayer[]
}

Matchup {
  opponent_id: string
  opponent_name: string
  balls: int
  runs: int
  sr: float
  dismissals: int
  dominance_index: float
  phase_splits: { powerplay: PhaseMatchup, middle: PhaseMatchup, death: PhaseMatchup } | null
}

SimilarPlayer {
  id: string
  name: string
  country: string
  similarity_score: float
  score_acceleration: float
  score_power: float
  score_control: float
}

FormPoint {
  date: string
  innings_number: int
  window_acceleration: float
  window_power: float
  window_control: float
}

VenueBaseline {
  venue: string
  matches: int
  avg_par_sr: float
  boundary_rate: float
  dot_pct: float
  difficulty_score: float
}
```

---

## 10. Search & Filtering

### 10.1 Autocomplete Behaviour

1. User types ≥ 2 characters.
2. Frontend debounces input (150ms).
3. Sends `GET /api/search?q=...&limit=8`.
4. Backend queries trigram index, returns top 8 matches.
5. Dropdown shows: `PlayerCard` mini-view (name, country, mini scores).
6. User selects → navigates to `/player/:id`.

### 10.2 Trigram Search Implementation (Backend)

```
# Pseudo-code for the trigram index

class TrigramIndex:
    def __init__(self, players: list[dict]):
        self.index: dict[str, set[str]] = defaultdict(set)
        self.players: dict[str, dict] = {}

        for p in players:
            pid = p["id"]
            self.players[pid] = p
            name_lower = p["name"].lower()
            for trigram in self._trigrams(name_lower):
                self.index[trigram].add(pid)

    def _trigrams(self, text: str) -> list[str]:
        padded = f"  {text}  "
        return [padded[i:i+3] for i in range(len(padded) - 2)]

    def search(self, query: str, limit: int = 20) -> list[dict]:
        query_trigrams = self._trigrams(query.lower())
        scores: dict[str, int] = Counter()
        for tri in query_trigrams:
            for pid in self.index.get(tri, []):
                scores[pid] += 1
        ranked = sorted(scores.items(), key=lambda x: -x[1])
        return [self.players[pid] for pid, _ in ranked[:limit]]
```

### 10.3 Filter Combinations

All filter parameters are URL query params and can be combined:

- `?q=koh&country=India&role=bat` — search for Indian batters named "koh".
- `?country=Australia&archetype=Explosive+Finisher&sort=score_power&order=desc` — Australian explosive finishers sorted by power.
- `?min_innings=30&provisional=false` — experienced players only.

---

## 11. Responsive Design

### Breakpoints (Tailwind defaults)

| Breakpoint | Width | Layout |
|-----------|-------|--------|
| `sm` | ≥640px | Single column, stacked cards |
| `md` | ≥768px | Two-column dashboard cards |
| `lg` | ≥1024px | Full sidebar + content layout |
| `xl` | ≥1280px | Wide tables, larger charts |

### Mobile-Specific Adaptations

- **Navigation**: hamburger menu (slide-out drawer) replaces top nav.
- **Radar charts**: simplified to 3 axes only (remove advanced axes on mobile).
- **Comparison**: max 2 players on mobile (stacked vertically).
- **Leaderboards**: horizontal scroll for wide tables, with fixed first column (player name).
- **Team Builder**: simplified list view (no drag-and-drop; tap-to-add).
- **Search**: full-screen overlay with large input and results list.
- **Score bars**: thinner, with numbers only (no inline labels).

### Touch Interactions

- Swipe left/right on comparison cards to switch between players (mobile).
- Long-press on a player card to add to comparison.
- Pull-to-refresh on leaderboards.

---

## 12. Theming & Brand

### Colour Palette

| Name | Hex | Usage |
|------|-----|-------|
| Background | `#0F172A` | Page background (dark mode) |
| Surface | `#1E293B` | Cards, panels |
| Surface Elevated | `#334155` | Hovered cards, active elements |
| Primary | `#3B82F6` | Links, primary buttons, active states |
| Accent | `#10B981` | Success states, positive values |
| Warning | `#F59E0B` | Caution, provisional badges |
| Danger | `#EF4444` | Negative values, wickets |
| Text Primary | `#F8FAFC` | Main text |
| Text Secondary | `#94A3B8` | Labels, descriptions |
| Text Muted | `#64748B` | Disabled, hints |
| Gold | `#FFD700` | S-grade, elite highlights |

### Light Mode

A `prefers-color-scheme: light` variant is supported:

| Name | Hex (Light) |
|------|-------------|
| Background | `#F8FAFC` |
| Surface | `#FFFFFF` |
| Text Primary | `#0F172A` |
| Text Secondary | `#475569` |

### Typography

| Element | Font | Size | Weight |
|---------|------|------|--------|
| H1 (Page title) | Inter | 2rem (32px) | 700 |
| H2 (Section) | Inter | 1.5rem (24px) | 600 |
| H3 (Card title) | Inter | 1.25rem (20px) | 600 |
| Body | Inter | 1rem (16px) | 400 |
| Small / Label | Inter | 0.875rem (14px) | 500 |
| Mono (scores) | JetBrains Mono | 1rem | 500 |

### Icons

Use **Lucide React** icon set for consistency. Key icons:

- 🔍 `Search` — search inputs
- `Trophy` — rankings, grades
- `Zap` — acceleration, power
- `Shield` — control, defence
- `Target` — accuracy, bowling
- `TrendingUp` / `TrendingDown` — form trend indicators
- `Users` — comparison
- `GitCompare` — matchups
- `Fingerprint` — similarity
- `MapPin` — venues
- `Clock` — eras, historical
- `Info` — tooltips, glossary links

---

## 13. Accessibility

### WCAG 2.1 AA Compliance

- **Colour contrast**: all text meets 4.5:1 ratio (7:1 for small text). The dark theme's `#F8FAFC` on `#0F172A` gives 15.4:1.
- **Keyboard navigation**: all interactive elements reachable via Tab, with visible focus rings (`ring-2 ring-blue-500`).
- **Screen readers**: all charts include `aria-label` descriptions and a visually-hidden data table alternative.
- **Alt text**: radar charts render as `<svg role="img" aria-label="Radar chart showing V Kohli's scores: Acceleration 89.7, Power 75.3, Control 92.1">`.
- **Reduced motion**: `prefers-reduced-motion` disables chart animations and transitions.
- **Skip links**: "Skip to main content" link at top of every page.
- **Form labels**: all inputs have associated `<label>` elements.

### Data Table Alternatives

Every chart has a toggleable "View as table" button that renders the same data as a `<table>` with proper `<th>`, `<td>`, `scope`, and `caption` elements.

---

## 14. Performance Targets

| Metric | Target | Strategy |
|--------|--------|----------|
| First Contentful Paint | < 1.5s | Code splitting, tree shaking, CDN |
| Largest Contentful Paint | < 2.5s | Lazy load charts, skeleton screens |
| Time to Interactive | < 3.0s | Defer non-critical JS, prefetch API data |
| API Response (search) | < 50ms | In-memory trigram index |
| API Response (player profile) | < 30ms | Pre-joined data in memory |
| API Response (leaderboard) | < 100ms | pandas `nlargest` + pagination |
| Bundle Size (initial) | < 200KB gzipped | Code split per route, lazy load D3 |
| Memory (backend) | < 500MB | Parquet loaded once, pandas DataFrames |

### Caching Strategy

- **Backend**: DataFrames loaded once at startup. No per-request I/O.
- **Frontend**: TanStack Query with `staleTime: Infinity` (data doesn't change between pipeline runs). Cache persisted to `localStorage` for instant subsequent visits.
- **CDN**: static assets (JS, CSS, fonts) served with `Cache-Control: max-age=31536000, immutable`.
- **API**: `Cache-Control: public, max-age=3600` on all API responses (data is static until next pipeline run).

---

## 15. Implementation Roadmap

### Phase 1: Core MVP (2–3 weeks)

**Goal:** Search, profiles, leaderboards — the essential loop.

| Task | Priority | Effort |
|------|----------|--------|
| FastAPI backend scaffold + Parquet loader | P0 | 2d |
| Search endpoint + trigram index | P0 | 1d |
| Player profile endpoint | P0 | 1d |
| Leaderboard endpoint with filtering/sorting/pagination | P0 | 1d |
| React app scaffold (Vite + React Router + TanStack Query + Tailwind) | P0 | 1d |
| `<PlayerAutocomplete>` component | P0 | 1d |
| Home page with hero search + quick leaderboard cards | P0 | 2d |
| Search results page | P0 | 1d |
| Player profile page (batting) | P0 | 3d |
| Player profile page (bowling variant) | P0 | 1d |
| Leaderboard page | P0 | 2d |
| `<ScoreBar>`, `<GradeBadge>`, `<RadarChart>` components | P0 | 2d |
| Responsive layout (mobile + desktop) | P0 | 1d |

### Phase 2: Rich Features (2–3 weeks)

**Goal:** Comparison, matchups, similarity, form charts, team builder.

| Task | Priority | Effort |
|------|----------|--------|
| Compare endpoint + page | P1 | 3d |
| Matchup endpoints + Head-to-Head page | P1 | 2d |
| Matchup Explorer page | P1 | 1d |
| Similarity endpoint + Similar Players page | P1 | 2d |
| Form tracker endpoint + time-series chart | P1 | 2d |
| Component breakdown stacked bars | P1 | 1d |
| Phase splits grouped bars | P1 | 1d |
| Team Builder page | P2 | 3d |
| Team auto-fill logic | P2 | 1d |
| Innings/Spells log page with pagination | P1 | 1d |
| Peak vs Current toggle on profile | P1 | 1d |

### Phase 3: Polish & Advanced (1–2 weeks)

**Goal:** Era explorer, venues, theming, static export, accessibility audit.

| Task | Priority | Effort |
|------|----------|--------|
| Era Explorer page + endpoint | P2 | 2d |
| Venue Analysis page + endpoint | P2 | 2d |
| Glossary & Methodology page | P2 | 2d |
| Dark/Light theme toggle | P2 | 1d |
| Accessibility audit + fixes | P1 | 2d |
| Static JSON export script (for serverless hosting) | P2 | 2d |
| Docker Compose setup (backend + frontend) | P2 | 1d |
| Export to CSV / PNG / shareable URL | P2 | 1d |
| Performance optimisation pass | P2 | 1d |

### Phase 4: Future Enhancements (Backlog)

| Feature | Description |
|---------|-------------|
| **Live Updates** | Webhook to re-run pipeline and hot-reload data when new match JSONs are added |
| **User Accounts** | Save favourite players, custom team builds, comparison history |
| **Notifications** | Alert when a favourite player's rating changes significantly |
| **Social Sharing** | OpenGraph meta tags for player profiles, comparison cards as images |
| **Embed Widgets** | `<iframe>` embeddable player cards for blogs/articles |
| **Mobile App** | React Native wrapper or PWA with offline support |
| **Prediction Mode** | "Who would win?" — simulate matchups using metric profiles |
| **Commentary Integration** | Match-day overlay showing live player ratings during broadcasts |
| **Bowling Style Matchups** | When bowling-style mapping is added to the pipeline, surface batter-vs-style breakdowns |
| **AI Insights** | LLM-generated natural language summaries of player profiles ("Kohli is a chase master who elevates under pressure...") |

---

## Appendix A: Directory Structure (Proposed)

```
cricket_metrics/
├── gui/
│   ├── backend/
│   │   ├── app.py                 # FastAPI application
│   │   ├── data_loader.py         # Parquet → in-memory DataFrames
│   │   ├── search_index.py        # Trigram search index
│   │   ├── routers/
│   │   │   ├── search.py          # /api/search
│   │   │   ├── player.py          # /api/player/*
│   │   │   ├── rankings.py        # /api/rankings/*
│   │   │   ├── compare.py         # /api/compare
│   │   │   ├── matchups.py        # /api/matchups/*
│   │   │   ├── similar.py         # /api/similar/*
│   │   │   ├── venues.py          # /api/venues/*
│   │   │   ├── eras.py            # /api/eras
│   │   │   └── team.py            # /api/team/*
│   │   ├── schemas.py             # Pydantic response models
│   │   ├── requirements.txt       # fastapi, uvicorn, pandas, pyarrow
│   │   └── Dockerfile
│   │
│   ├── frontend/
│   │   ├── public/
│   │   │   └── favicon.ico
│   │   ├── src/
│   │   │   ├── main.tsx           # Entry point
│   │   │   ├── App.tsx            # Router setup
│   │   │   ├── api/
│   │   │   │   ├── client.ts      # Axios/fetch wrapper
│   │   │   │   ├── queries.ts     # TanStack Query hooks
│   │   │   │   └── types.ts       # TypeScript interfaces
│   │   │   ├── pages/
│   │   │   │   ├── Home.tsx
│   │   │   │   ├── Search.tsx
│   │   │   │   ├── PlayerProfile.tsx
│   │   │   │   ├── Rankings.tsx
│   │   │   │   ├── Compare.tsx
│   │   │   │   ├── Matchups.tsx
│   │   │   │   ├── MatchupExplorer.tsx
│   │   │   │   ├── Similar.tsx
│   │   │   │   ├── TeamBuilder.tsx
│   │   │   │   ├── EraExplorer.tsx
│   │   │   │   ├── VenueAnalysis.tsx
│   │   │   │   └── Glossary.tsx
│   │   │   ├── components/
│   │   │   │   ├── ui/            # shadcn/ui primitives
│   │   │   │   ├── PlayerCard.tsx
│   │   │   │   ├── ScoreBar.tsx
│   │   │   │   ├── RadarChart.tsx
│   │   │   │   ├── FormSparkline.tsx
│   │   │   │   ├── GradeBadge.tsx
│   │   │   │   ├── ArchetypeBadge.tsx
│   │   │   │   ├── MetricTooltip.tsx
│   │   │   │   ├── PlayerAutocomplete.tsx
│   │   │   │   ├── PhaseBar.tsx
│   │   │   │   ├── DominanceGauge.tsx
│   │   │   │   ├── SortableTable.tsx
│   │   │   │   ├── FilterBar.tsx
│   │   │   │   ├── Pagination.tsx
│   │   │   │   └── ExportButton.tsx
│   │   │   ├── hooks/
│   │   │   │   ├── useDebounce.ts
│   │   │   │   ├── useCompare.ts
│   │   │   │   └── useTeamBuilder.ts
│   │   │   ├── lib/
│   │   │   │   ├── colours.ts     # Score-to-colour mapping
│   │   │   │   ├── grades.ts      # Score-to-grade mapping
│   │   │   │   └── format.ts      # Number formatting helpers
│   │   │   └── styles/
│   │   │       └── globals.css    # Tailwind base + custom
│   │   ├── index.html
│   │   ├── tailwind.config.ts
│   │   ├── tsconfig.json
│   │   ├── vite.config.ts
│   │   ├── package.json
│   │   └── Dockerfile
│   │
│   └── docker-compose.yml
│
├── output/                        # Pipeline outputs (read by backend)
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
│   ├── venue_baselines.parquet
│   └── ...
│
├── src/                           # Existing pipeline code
│   ├── main.py
│   ├── batting.py
│   ├── bowling.py
│   └── ...
│
├── config.yaml
├── requirements.txt
└── gui.md                         # This document
```

---

## Appendix B: Docker Compose

```
# docker-compose.yml
version: "3.9"

services:
  backend:
    build: ./gui/backend
    ports:
      - "8000:8000"
    volumes:
      - ./output:/app/output:ro
    environment:
      - OUTPUT_DIR=/app/output
    command: uvicorn app:app --host 0.0.0.0 --port 8000

  frontend:
    build: ./gui/frontend
    ports:
      - "3000:3000"
    environment:
      - VITE_API_URL=http://localhost:8000
    depends_on:
      - backend
```

---

## Appendix C: Quick Start (Development)

### Backend

```bash
cd gui/backend
python -m venv .venv
source .venv/bin/activate
pip install fastapi uvicorn pandas pyarrow
uvicorn app:app --reload --port 8000
```

### Frontend

```bash
cd gui/frontend
npm install
npm run dev   # Vite dev server on http://localhost:5173
```

### Full Stack (Docker)

```bash
docker compose up --build
# Backend: http://localhost:8000
# Frontend: http://localhost:3000
```

---

## Appendix D: Static JSON Export

For serverless deployment (GitHub Pages, Vercel Static, Netlify):

```bash
# Generate all API responses as static JSON files
python gui/backend/export_static.py --output gui/frontend/public/api/

# This creates:
#   public/api/search/index.json          (all players, for client-side search)
#   public/api/player/{id}.json           (one per player)
#   public/api/rankings/bat.json          (pre-sorted leaderboard)
#   public/api/rankings/bowl.json
#   public/api/matchups/{bat_id}/{bowl_id}.json
#   public/api/venues/index.json
#   public/api/eras/index.json
#   public/api/similar/{id}.json
#
# Total: ~10K files, ~50MB uncompressed, ~8MB gzipped

# Then deploy as a static site:
cd gui/frontend
npm run build
# Deploy dist/ to your static host
```

The frontend detects whether it's in "static mode" (no live backend) by checking if `VITE_STATIC_MODE=true` is set, and adjusts fetch URLs to load `.json` files from the public directory instead of hitting a live API.