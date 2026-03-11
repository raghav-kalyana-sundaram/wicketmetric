# Cricket Metrics — Documentation

## How to Run the Project

This document provides complete instructions for setting up and running the Cricket Metrics T20I Player Performance Profiling Engine, including both the data pipeline and the interactive web GUI.

---

## Table of Contents

- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Project Structure](#project-structure)
- [Step 1: Run the Data Pipeline](#step-1-run-the-data-pipeline)
- [Step 2: Start the Backend API](#step-2-start-the-backend-api)
- [Step 3: Start the Frontend](#step-3-start-the-frontend)
- [Running with Docker](#running-with-docker)
- [Verifying Everything Works](#verifying-everything-works)
- [Environment Variables](#environment-variables)
- [API Reference](#api-reference)
- [Frontend Pages & Routes](#frontend-pages--routes)
- [Architecture Overview](#architecture-overview)
- [Configuration](#configuration)
- [Hosting & Sharing](#hosting--sharing)
- [Troubleshooting](#troubleshooting)
- [What's Next](#whats-next)
- [Quick Reference: Run Everything](#quick-reference-run-everything)

---

## Overview

Cricket Metrics is a T20I cricket player performance analysis system composed of three parts:

1. **Data Pipeline** (`src/`) — Processes raw Cricsheet ball-by-ball JSON data and produces Parquet/CSV output files containing player career profiles, form time-series, matchup data, venue baselines, and similarity matrices.

2. **Backend API** (`gui/backend/`) — A FastAPI server that loads the pipeline's Parquet outputs into memory at startup and exposes them via a read-only REST API with sub-millisecond response times.

3. **Frontend** (`gui/frontend/`) — A React + TypeScript single-page application (built with Vite) that provides an interactive dashboard for searching, comparing, and analysing T20I players.

---

## Prerequisites

| Requirement | Minimum Version | Purpose |
|---|---|---|
| **Python** | 3.11+ | Data pipeline and backend API |
| **pip** | Latest | Python package management |
| **Node.js** | 18+ | Frontend build and dev server |
| **npm** | 9+ | Frontend package management |
| **Git** | Any | Cloning the repository |

Optional:
- **Docker** and **Docker Compose** — for containerised deployment

---

## Project Structure

```
cricket_metrics/
├── documentation.md              # This file
├── requirements.txt              # Python dependencies for the pipeline
├── config.yaml                   # Pipeline configuration
├── gui.md                        # GUI design specification
├── ARCHITECTURE.md               # Pipeline architecture documentation
│
├── src/                          # Data pipeline source code
│   ├── main.py                   # Pipeline entry point
│   ├── parser.py                 # Cricsheet JSON parser
│   ├── batting.py                # Batting career aggregation
│   ├── bowling.py                # Bowling career aggregation
│   ├── context.py                # Match context (venue, era adjustments)
│   ├── era.py                    # Era baseline computation
│   ├── venue.py                  # Venue difficulty baselines
│   ├── form_tracker.py           # Rolling form time-series
│   ├── matchups.py               # Batter vs bowler matchup engine
│   ├── similarity.py             # Cosine-similarity player comparisons
│   ├── peak_ratings.py           # Peak performance window detection
│   ├── rating.py                 # Score/grade assignment (0–100)
│   ├── war.py                    # Wins Above Replacement calculation
│   ├── wpa.py                    # Win Probability Added
│   ├── clutch.py                 # Clutch index computation
│   └── presentation.py           # Output formatting and export
│
├── t20s_male_json/               # Raw Cricsheet T20I ball-by-ball data (JSON)
│
├── output/                       # Pipeline outputs (generated)
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
│   └── ... (CSV variants and additional files)
│
├── gui/
│   ├── README.md                 # GUI-specific readme
│   ├── docker-compose.yml        # Docker setup for both services
│   │
│   ├── backend/                  # FastAPI backend
│   │   ├── app.py                # Application entry point
│   │   ├── data_loader.py        # Parquet → DataStore loader
│   │   ├── search_index.py       # Trigram fuzzy search index
│   │   ├── schemas.py            # Pydantic response models
│   │   ├── export_static.py      # Static JSON export script
│   │   ├── requirements.txt      # Python dependencies
│   │   ├── Dockerfile
│   │   └── routers/              # API route modules
│   │       ├── search.py         # Search & autocomplete
│   │       ├── player.py         # Player profiles, innings, form, matchups
│   │       ├── rankings.py       # Leaderboards
│   │       ├── compare.py        # Side-by-side comparison
│   │       ├── matchups.py       # Head-to-head matchups
│   │       ├── venues.py         # Venue analysis
│   │       ├── eras.py           # Era baselines
│   │       └── team.py           # Team builder
│   │
│   └── frontend/                 # React + TypeScript (Vite)
│       ├── index.html
│       ├── package.json
│       ├── vite.config.ts
│       ├── tailwind.config.ts
│       ├── tsconfig.json
│       ├── Dockerfile
│       └── src/
│           ├── main.tsx
│           ├── App.tsx
│           ├── api/              # API client, React Query hooks, types
│           ├── components/       # Shared UI components
│           ├── pages/            # Route-level page components
│           ├── hooks/            # Custom React hooks
│           ├── lib/              # Utility modules
│           └── styles/           # Tailwind CSS
│
└── tests/                        # Pipeline tests
```

---

## Step 1: Run the Data Pipeline

The pipeline processes raw Cricsheet JSON data and produces the Parquet files that the GUI consumes.

### 1.1 Install Pipeline Dependencies

```bash
cd cricket_metrics

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt
```

### 1.2 Ensure Raw Data Exists

The pipeline expects Cricsheet T20I ball-by-ball JSON files in the `t20s_male_json/` directory. If you don't have this data, download it from [Cricsheet](https://cricsheet.org/downloads/) and extract the T20I male JSON files into that directory.

### 1.3 Run the Pipeline

```bash
python src/main.py
```

This will:
- Parse all T20I match JSON files
- Compute batting and bowling career aggregates
- Generate form time-series, matchup tables, venue baselines, and similarity matrices
- Write all outputs to the `output/` directory

The pipeline typically takes a few minutes depending on the size of the dataset.

### 1.4 Verify Pipeline Output

After the pipeline completes, confirm the output files exist:

```bash
ls output/*.parquet
```

You should see at least the following files:
- `batting_careers_full.parquet`
- `bowling_careers_full.parquet`
- `batting_innings_detail.parquet`
- `bowling_spells_detail.parquet`
- `batting_form_series.parquet`
- `bowling_form_series.parquet`
- `batting_similarities.parquet`
- `bowling_similarities.parquet`
- `matchups.parquet`
- `matchups_by_phase.parquet`
- `venue_baselines.parquet`

---

## Step 2: Start the Backend API

The backend is a FastAPI application that loads pipeline outputs into memory and serves them via a REST API.

### 2.1 Install Backend Dependencies

```bash
cd gui/backend

# You can use the same venv from Step 1, or create a new one
# If using the project root venv:
source ../../.venv/bin/activate

# Install backend-specific dependencies
pip install -r requirements.txt
```

The backend requires: `fastapi`, `uvicorn`, `pandas`, `pyarrow`, `pydantic`.

### 2.2 Configure the Output Directory

The backend auto-discovers datasets by looking for `output_t20i/` and `output_ipl/` directories in the project root. **Do not set `OUTPUT_DIR`** unless you only want a single format:

```bash
# ✅ Recommended: leave OUTPUT_DIR unset for multi-format support (T20I + IPL)
# The backend will auto-discover output_t20i/ and output_ipl/ in the project root.
cd gui/backend
python app.py

# ⚠️  Legacy single-format mode (only use if you have a single output/ directory):
# Setting OUTPUT_DIR forces the backend to load ONLY that directory as T20I.
# IPL data will NOT be available.
# export OUTPUT_DIR=../../output
```

> **Common pitfall:** If you previously ran `export OUTPUT_DIR=../../output` in your
> shell, it will persist for the session and force single-format mode. Run
> `unset OUTPUT_DIR` before starting the backend to restore multi-format discovery.

### 2.3 Start the Server

```bash
# Development mode (with auto-reload)
uvicorn app:app --reload --port 8000

# Production mode
uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4
```

You should see startup logs like:

```
============================================================
  Cricket Metrics API — Starting up
============================================================
Loading pipeline outputs from: /path/to/output
  [OK]   batting_careers_full.parquet: 1,234 rows × 45 cols
  [OK]   bowling_careers_full.parquet: 987 rows × 40 cols
  ...
Building search index...

✅ Startup complete in 2.34s
   Batters:  1,234
   Bowlers:  987
   Search index: 2,221 players
   Matchups: 45,678
   Venues:   89
============================================================
```

### 2.4 Verify the Backend

Open these URLs in your browser:

| URL | Description |
|---|---|
| http://localhost:8000/api/health | Should return `{"status": "ok"}` |
| http://localhost:8000/api/meta | Returns dataset statistics |
| http://localhost:8000/api/docs | Interactive Swagger documentation |
| http://localhost:8000/api/redoc | ReDoc API documentation |

---

## Step 3: Start the Frontend

The frontend is a React application built with Vite that provides the interactive web interface.

### 3.1 Install Frontend Dependencies

```bash
cd gui/frontend

# Install Node.js dependencies
npm install
```

### 3.2 Start the Development Server

```bash
npm run dev
```

The frontend will start on **http://localhost:5173**. Vite's dev server automatically proxies all `/api` requests to the backend at `http://localhost:8000`, so you don't need to configure CORS or API URLs during development.

### 3.3 Open in Browser

Navigate to **http://localhost:5173** in your browser. You should see the Cricket Metrics dashboard with:
- A hero search bar
- Leaderboard cards
- Quick navigation links

### 3.4 Build for Production

To create an optimised production build:

```bash
npm run build
```

The built assets will be in `gui/frontend/dist/`. You can serve them with any static file server:

```bash
npx serve -s dist -l 3000
```

---

## Running with Docker

If you prefer to use Docker, a `docker-compose.yml` is provided that runs both the backend and frontend in containers.

### Start Both Services

```bash
cd gui

# Build and start
docker compose up --build

# Or run in the background
docker compose up --build -d
```

This starts:
- **Backend** on port `8000`
- **Frontend** on port `3000`

The Docker Compose file automatically mounts the `output/` directory from the project root into the backend container as a read-only volume.

### Stop Services

```bash
docker compose down
```

---

## Verifying Everything Works

Once both the backend and frontend are running, verify the full stack:

1. **Health check**: Visit http://localhost:8000/api/health — should return `{"status": "ok"}`
2. **Search**: Type a player name (e.g. "Kohli") in the search bar on the home page
3. **Player Profile**: Click on a search result to see the full player profile with scores, grades, form chart, and matchups
4. **Rankings**: Navigate to `/rankings` to see sortable leaderboards
5. **Compare**: Navigate to `/compare` and add 2–4 players for side-by-side comparison
6. **Venues**: Navigate to `/venues` to see venue difficulty analysis
7. **Eras**: Navigate to `/eras` to see how T20I cricket has evolved over time

---

## Environment Variables

### Pipeline

The pipeline uses `config.yaml` for configuration. No environment variables are required.

### Backend

| Variable | Default | Description |
|---|---|---|
| `OUTPUT_DIR` | `../../output` (relative to `gui/backend/`) | Path to pipeline output directory |
| `PORT` | `8000` | Server port |
| `HOST` | `0.0.0.0` | Server host |
| `RELOAD` | `false` | Enable auto-reload (development) |

### Frontend

| Variable | Default | Description |
|---|---|---|
| `VITE_API_URL` | _(empty — uses Vite proxy)_ | Backend API base URL. Only needed for production builds if the API is on a different domain. |

---

## API Reference

The backend exposes the following REST endpoints. All endpoints are `GET` requests and return JSON.

### Meta & Health

| Path | Description |
|---|---|
| `/api/health` | Health check (`{"status": "ok"}` or `{"status": "degraded"}`) |
| `/api/meta` | Dataset metadata: total players, countries, archetypes |

### Search

| Path | Description |
|---|---|
| `/api/search?q=...` | Full-text fuzzy search with trigram matching. Supports filters: `role`, `country`, `archetype`, `provisional`, `min_innings`, `limit` |
| `/api/search/autocomplete?q=...` | Lightweight autocomplete (min 2 chars). Supports: `role`, `country`, `limit` |
| `/api/search/countries` | Sorted list of all countries in the dataset |
| `/api/search/archetypes` | Archetype lists keyed by role (`bat`, `bowl`) |

### Player Profiles

| Path | Description |
|---|---|
| `/api/player/{id}` | Full player profile (auto-detects batting vs bowling) |
| `/api/player/{id}/batting` | Explicit batting profile |
| `/api/player/{id}/bowling` | Explicit bowling profile |
| `/api/player/{id}/innings?page=&per_page=&sort_by=&order=` | Paginated batting innings log |
| `/api/player/{id}/spells?page=&per_page=&sort_by=&order=` | Paginated bowling spells log |
| `/api/player/{id}/form` | Form time-series (rolling window composite) |
| `/api/player/{id}/matchups?role=&min_balls=&sort_by=&order=&page=&per_page=` | Paginated matchup list |
| `/api/player/{id}/similar?limit=` | Top-K similar players |

### Rankings

| Path | Description |
|---|---|
| `/api/rankings/bat?sort=&order=&country=&archetype=&position_group=&min_innings=&provisional=&page=&per_page=` | Batting leaderboard |
| `/api/rankings/bowl?sort=&order=&country=&archetype=&phase_group=&min_innings=&provisional=&page=&per_page=` | Bowling leaderboard |
| `/api/rankings/top?role=&metric=&limit=&provisional=&min_innings=` | Top N players by any metric |
| `/api/rankings/columns/bat` | Valid sort columns for batting |
| `/api/rankings/columns/bowl` | Valid sort columns for bowling |

### Comparison

| Path | Description |
|---|---|
| `/api/compare?ids=id1,id2,...` | Side-by-side profiles for 2–4 players |
| `/api/compare/form?ids=id1,id2,...` | Overlaid form time-series |
| `/api/compare/shared-matchups?ids=id1,id2,...&min_balls=&limit=` | Shared bowlers across compared batters |

### Matchups

| Path | Description |
|---|---|
| `/api/matchups?bat=...&bowl=...` | Head-to-head detail between a specific batter and bowler |
| `/api/matchups/explore?player_id=&role=&min_balls=&sort=&order=&page=&per_page=` | Browse all matchups for a player |
| `/api/matchups/top-bunnies?bowler_id=&min_balls=&limit=` | Bowler's top bunnies (batters they dominate) |
| `/api/matchups/top-nemeses?batter_id=&min_balls=&limit=` | Batter's top nemeses (bowlers who dominate them) |
| `/api/matchups/top-dominant?batter_id=&min_balls=&limit=` | Bowlers a batter dominates the most |

### Venues

| Path | Description |
|---|---|
| `/api/venues?sort=&order=&min_matches=` | All venue baselines |
| `/api/venues/detail?venue=...` | Single venue detail |
| `/api/venues/players?venue=&role=&min_innings=&sort=&order=&page=&per_page=` | Player performance at a specific venue |
| `/api/venues/flat-track-index?role=&min_innings=&provisional=&sort=&order=&page=&per_page=` | Flat-track bully leaderboard |
| `/api/venues/summary` | High-level venue difficulty summary |

### Eras

| Path | Description |
|---|---|
| `/api/eras` | Era baselines by year (par SR, boundary rate, dot %, era multiplier) |

### Team Builder

| Path | Description |
|---|---|
| `/api/team/analyse?ids=id1,id2,...` | Aggregate analysis for a team selection |
| `/api/team/auto-fill?strategy=&country=&exclude=` | Auto-fill XI suggestions |

---

## Frontend Pages & Routes

| Route | Page | Description |
|---|---|---|
| `/` | Home | Dashboard with hero search, leaderboard cards, quick compare |
| `/search?q=...` | Search | Full-text player search with filters |
| `/player/:id` | Player Profile | Complete player profile with scores, form, matchups |
| `/player/:id/innings` | Innings Log | Full paginated batting innings history |
| `/player/:id/spells` | Spells Log | Full paginated bowling spells history |
| `/rankings` | Rankings | Leaderboards with sorting, filtering, pagination |
| `/compare?ids=...` | Compare | Side-by-side comparison of 2–4 players |
| `/matchups` | Matchups | Head-to-head lookup and matchup explorer |
| `/similar/:id` | Similar Players | Similarity scatter plot and nearest neighbours |
| `/team-builder` | Team Builder | Build a hypothetical XI with analysis |
| `/eras` | Era Explorer | Timeline of T20I era evolution |
| `/venues` | Venue Analysis | Venue difficulty and flat-track index |
| `/glossary` | Glossary | Metric definitions, methodology, FAQ |

---

## Architecture Overview

### Data Flow

```
Cricsheet JSON  →  Pipeline (src/main.py)  →  Parquet Files (output/)
                                                      ↓
                                               Backend (FastAPI)
                                               loads into memory
                                                      ↓
                                                REST API (/api/*)
                                                      ↓
                                              Frontend (React/Vite)
                                              renders in browser
```

### Backend Architecture

- **DataStore** (`data_loader.py`): Loads all Parquet files into pandas DataFrames at startup. Provides helper accessors for common queries (get player by ID, paginated innings, form series, matchups).
- **TrigramIndex** (`search_index.py`): Builds an in-memory trigram index over all player names for fuzzy search with O(1) lookup per query character.
- **Pydantic Schemas** (`schemas.py`): Define the JSON response shapes for every endpoint, with automatic NaN → null conversion for JSON safety.
- **Routers** (`routers/*.py`): Modular FastAPI routers for each feature area. Dependency-injected with the DataStore and TrigramIndex at startup.

### Frontend Architecture

- **API Layer** (`api/client.ts`): Typed fetch wrapper with automatic query string building, timeout handling, and error parsing.
- **React Query Hooks** (`api/queries.ts`): TanStack Query hooks wrapping every API call with caching, stale-time configuration, and placeholder data for smooth UX.
- **Type Definitions** (`api/types.ts`): TypeScript interfaces matching all backend response shapes.
- **Pages**: Route-level components using lazy-loading (code splitting) for smaller initial bundle size.
- **Components**: Shared UI components (ScoreBar, GradeBadge, PlayerAutocomplete, Pagination, etc.) following the design spec.

---

## Configuration

### Pipeline Configuration (`config.yaml`)

The pipeline's behaviour is controlled by `config.yaml` at the project root. Key settings include:
- Minimum innings/spells thresholds for provisional status
- Rolling window sizes for form tracking
- Similarity computation parameters
- Score band boundaries for grading

### Frontend Theming

The frontend supports **dark mode** (default) and **light mode**:
- Toggle via the sun/moon button in the navigation bar
- Persisted in `localStorage` under the key `cricket-metrics-theme`
- Respects OS `prefers-color-scheme` preference on first visit
- All design tokens are defined in `gui/frontend/tailwind.config.ts`

### Score Colour Mapping

| Score Range | Grade | Colour |
|---|---|---|
| 95–100 | S (Elite) | Gold (#FFD700) |
| 85–94 | A+ (Exceptional) | Emerald (#10B981) |
| 75–84 | A (Excellent) | Green (#22C55E) |
| 60–74 | B+ (Very Good) | Cyan (#06B6D4) |
| 45–59 | B (Good) | Blue (#3B82F6) |
| 30–44 | C+ (Average) | Amber (#F59E0B) |
| 15–29 | C (Below Average) | Orange (#F97316) |
| 0–14 | D (Poor) | Red (#EF4444) |

---

## Hosting & Sharing

There are two ways to host Cricket Metrics and share a link with others: a **static export** (free, no server required) and a **live deployment** (cheap, full interactivity). The static approach is simplest and cheapest.

---

### Option A: Static Export to GitHub Pages (Free — Recommended)

This is the simplest and cheapest path. You pre-compute every API response as a JSON file, bundle them with the frontend, and deploy the whole thing as a static site. No Python server runs in production — just HTML, JS, and JSON files served from a CDN.

**Cost:** $0. GitHub Pages is free for public repos.

#### 1. Generate the static JSON files

```bash
cd gui/backend

# Make sure the pipeline outputs exist in ../../output
# Then export all API responses as static JSON:
python export_static.py --output ../frontend/public/api/

# This creates ~10K JSON files under frontend/public/api/
# (one per player, plus leaderboards, venues, eras, search index, etc.)
# Total size: ~50 MB uncompressed, ~8 MB gzipped
```

#### 2. Build the frontend in static mode

```bash
cd gui/frontend

# Tell the frontend to load from local JSON files instead of a live API
VITE_STATIC_MODE=true npm run build
```

The built assets (HTML + JS + all the JSON files) land in `gui/frontend/dist/`.

#### 3. Deploy to GitHub Pages

```bash
# Option A: Use the gh-pages npm package
npm install -g gh-pages
gh-pages -d dist

# Option B: Push dist/ to a gh-pages branch manually
#   1. Create a gh-pages branch
#   2. Copy the contents of dist/ into it
#   3. Push to GitHub
#   4. In repo Settings → Pages, set source to the gh-pages branch

# Option C: Use a GitHub Actions workflow (see below)
```

Your site will be live at `https://<username>.github.io/<repo-name>/`.

#### GitHub Actions Workflow (automate the deploy)

Create `.github/workflows/deploy.yml` in your repo:

```yaml
name: Deploy to GitHub Pages

on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - uses: actions/setup-node@v4
        with:
          node-version: "20"

      - name: Install Python deps
        run: |
          pip install -r requirements.txt
          pip install -r gui/backend/requirements.txt

      - name: Run pipeline
        run: python src/main.py

      - name: Export static JSON
        run: |
          cd gui/backend
          python export_static.py --output ../frontend/public/api/

      - name: Build frontend
        run: |
          cd gui/frontend
          npm ci
          VITE_STATIC_MODE=true npm run build

      - uses: actions/upload-pages-artifact@v3
        with:
          path: gui/frontend/dist

      - uses: actions/deploy-pages@v4
```

Every push to `main` will re-run the pipeline, regenerate all the JSON, build the frontend, and deploy — fully automated.

#### Limitations of static mode

- **No server-side search** — the frontend downloads the full search index JSON and does client-side trigram matching. This works fine for the ~2,000 player dataset but adds ~1–2 MB to the initial load.
- **No dynamic pagination** — innings logs and matchup explorers are pre-rendered as single JSON files (all pages in one file). For most players this is fine (<100 innings), but very prolific players may produce larger files.
- **No Team Builder auto-fill** — the auto-fill endpoint requires server-side ranking logic. The manual player-selection part of Team Builder still works.
- **Updating data requires a re-deploy** — there's no live pipeline. You re-run the pipeline, re-export, and re-deploy.

---

### Option B: Deploy to Railway / Render / Fly.io (Cheap — Full Features)

If you want the full live experience (server-side search, dynamic pagination, Team Builder auto-fill), deploy the backend and frontend as two services on a cheap PaaS. The cheapest options:

| Platform | Free Tier | Paid Tier | Notes |
|---|---|---|---|
| **Railway** | 500 hours/month free | $5/month | Easiest Docker deploy |
| **Render** | Free tier (spins down after inactivity) | $7/month | Free tier has cold starts |
| **Fly.io** | 3 shared VMs free | $3–5/month | Closest to bare metal |

#### Deploy to Railway (simplest)

1. Push your repo to GitHub.
2. Go to [railway.app](https://railway.app) and create a new project from your GitHub repo.
3. Add two services:
   - **Backend**: set root directory to `gui/backend`, set `OUTPUT_DIR=/app/output`, add a volume or include the output Parquet files in the repo.
   - **Frontend**: set root directory to `gui/frontend`, set `VITE_API_URL` to the backend's Railway URL.
4. Railway auto-detects the Dockerfiles and deploys both.

#### Deploy to Render

1. Create a **Web Service** for the backend:
   - Root directory: `gui/backend`
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn app:app --host 0.0.0.0 --port $PORT`
   - Environment: `OUTPUT_DIR=../../output`
2. Create a **Static Site** for the frontend:
   - Root directory: `gui/frontend`
   - Build command: `npm ci && VITE_API_URL=https://<backend-url> npm run build`
   - Publish directory: `dist`

#### Important: Including the data

The backend needs the Parquet files at runtime. You have three options:

1. **Commit them to the repo** — they're ~50 MB total, which is fine for most Git hosts. Simplest approach.
2. **Build step** — include the raw JSON data and run the pipeline as part of the deploy build step (slower deploys, but always fresh).
3. **Persistent volume** — platforms like Railway and Fly.io support persistent volumes. Upload the Parquet files once and mount the volume into the backend container.

---

### Option C: Static Export to Vercel / Netlify (Free)

Same as Option A, but using Vercel or Netlify instead of GitHub Pages:

```bash
# Generate static JSON + build
cd gui/backend && python export_static.py --output ../frontend/public/api/
cd gui/frontend && VITE_STATIC_MODE=true npm run build
```

Then:
- **Vercel**: `npx vercel --prod` from `gui/frontend/dist/`, or connect your GitHub repo and set the root directory to `gui/frontend` with build command `VITE_STATIC_MODE=true npm run build`.
- **Netlify**: drag-and-drop `gui/frontend/dist/` onto [app.netlify.com](https://app.netlify.com), or connect your GitHub repo.

Both are free for static sites.

---

## Troubleshooting

### "Data not loaded" / degraded health status

The backend couldn't find or read the pipeline output files.

**Fix:**
1. Verify the `OUTPUT_DIR` environment variable points to the correct directory.
2. Confirm the pipeline has been run and Parquet files exist in `output/`.
3. Check file permissions allow the backend process to read the files.
4. Look at the backend startup logs for `[WARN] Missing:` or `[ERR]` messages.

### Backend starts but endpoints return empty results

The Parquet files may exist but be empty or have unexpected column names.

**Fix:**
1. Re-run the pipeline: `python src/main.py`
2. Check the backend startup logs for the row counts printed for each loaded file.
3. Visit `/api/meta` to see how many batters/bowlers were loaded.

### CORS errors in the browser console

The backend's CORS configuration doesn't include the frontend's origin.

**Fix:**
The backend allows requests from `localhost:3000`, `localhost:5173`, and `localhost:5174`. If your frontend runs on a different port, add it to the `allow_origins` list in `gui/backend/app.py`.

### Frontend shows "Failed to fetch" or network errors

The backend is not running or not reachable.

**Fix:**
1. Confirm the backend is running on port 8000: `curl http://localhost:8000/api/health`
2. If using a different port, set `VITE_API_URL` before starting the frontend:
   ```bash
   VITE_API_URL=http://localhost:9000 npm run dev
   ```
3. Check that nothing else is occupying port 8000.

### TypeScript compilation errors

**Fix:**
```bash
cd gui/frontend
npx tsc --noEmit
```

The project should compile cleanly with zero errors. If not, ensure `node_modules` is up to date:
```bash
rm -rf node_modules package-lock.json
npm install
```

### Python (Pyright) type-checking warnings in the backend

The backend shows many Pyright warnings related to pandas type stubs. These are **not runtime bugs** — they are a known limitation of pandas' type annotations. The backend runs correctly despite these static analysis warnings.

### Search returns no results

The trigram search index is built at startup from the career DataFrames. If those are empty (missing Parquet files), search returns nothing.

**Fix:** Check the backend startup logs for `Search index: 0 players`. If zero, the career Parquet files were not loaded — re-run the pipeline.

### Team Builder shared URL not loading players

When opening a shared Team Builder URL (`/team-builder?ids=...`), the page fetches each player's profile from the API. If the backend is not running or the IDs are invalid, slots remain empty.

**Fix:** Check the browser console for fetch errors and verify the IDs exist via `/api/search`.

### Docker issues

If `docker compose up` fails:
1. Ensure Docker Desktop is running.
2. Check that ports 8000 and 3000 are not in use.
3. Verify the `output/` directory exists relative to the `gui/` directory.
4. Run `docker compose up --build` to force a fresh build.

---

## What's Next

This section outlines planned improvements and known gaps, roughly ordered by impact.

---

### 1. Data Accumulation & Freshness

**Problem:** The pipeline runs once against a snapshot of Cricsheet data. As new T20Is are played, the dataset goes stale.

**Planned improvements:**

- **Incremental pipeline runs** — detect which match JSON files are new since the last run and only re-process those, then merge into existing Parquet outputs. This would drop a full re-run from minutes to seconds.
- **Automated Cricsheet sync** — a script (or GitHub Actions cron job) that downloads the latest Cricsheet T20I JSON bundle nightly, runs the incremental pipeline, re-exports static JSON, and re-deploys. This would keep the site current within 24 hours of a match being played.
- **Date-stamped metadata** — surface the "data as of" date in the UI header and `/api/meta` response so users know how fresh the data is.

---

### 2. Venue Data Depth

**Problem:** Many venues have very few T20I matches (some have only 1–2), which makes their baselines unreliable. The venue difficulty scores and flat-track bully index are noisy for low-sample venues.

**Planned improvements:**

- **Accumulate domestic / franchise T20 data** — Cricsheet also publishes IPL, BBL, CPL, PSL, SA20, The Hundred, and other franchise T20 data. Adding these matches would massively increase the per-venue sample sizes. A venue like Wankhede Stadium might go from 15 T20Is to 150+ T20 matches, producing far more stable baselines.
- **Venue clustering** — group venues with similar characteristics (e.g. Australian fast-bouncy pitches, subcontinental spin-friendly tracks) using the baseline features as a clustering vector. Players with no data at a new venue could be assigned the cluster average.
- **Country-level baselines** — as a fallback for venues with <5 matches, use the average baseline across all venues in that country.
- **Venue surface in player profiles** — currently the venue-adjusted composite is computed but the GUI doesn't show a per-venue breakdown on the player profile page. Adding a "Performance by Venue" expandable section with sparklines per ground would be valuable.

---

### 3. Test & CI Coverage

**Problem:** The backend has no automated test suite, and the frontend has no E2E tests.

**Planned improvements:**

- **Backend unit tests** — pytest tests using FastAPI's `TestClient` with a small fixture DataStore (10–20 synthetic player rows). Cover every router: search, player profile, rankings, compare, matchups, venues, eras, team builder.
- **Frontend E2E tests** — Playwright or Cypress tests for the critical user flows: search → profile → compare, rankings with filters, Team Builder selection + analysis.
- **CI pipeline** — GitHub Actions workflow that runs on every PR:
  1. `tsc --noEmit` (frontend type check)
  2. `npm run build` (frontend build)
  3. `pytest` (backend tests)
  4. Optionally: Lighthouse CI for performance and accessibility scores.
- **Pipeline regression tests** — snapshot tests that run the pipeline on a small subset of matches and assert the output DataFrames have the expected shape, column names, and approximate value ranges.

---

### 4. T20 Franchise Data Integration

**Problem:** The system currently only processes T20 **Internationals**. Franchise leagues (IPL, BBL, CPL, PSL, etc.) are a massive source of additional data.

**Planned improvements:**

- **Multi-format support** — extend the parser to accept franchise T20 match JSON alongside T20Is. Add a `format` column (`t20i`, `ipl`, `bbl`, etc.) to all DataFrames.
- **Weighted integration** — T20I performances should still carry more weight than franchise matches (international pressure, varied conditions), but franchise data would dramatically improve sample sizes for newer players and venue baselines.
- **Format-specific profiles** — allow the GUI to toggle between "T20I only", "All T20s", or a specific franchise. The profile page would show a format selector.
- **Player-ID deduplication** — Cricsheet uses different player registries across formats. A robust name + DOB matching system would be needed to unify player IDs.

---

### 5. GUI Polish & UX Improvements

**Planned improvements:**

- **Accessibility audit** — run axe/Lighthouse, fix colour contrast issues, add ARIA roles to all charts, ensure full keyboard navigation.
- **PNG export** — the Export button supports CSV and URL sharing, but PNG screenshot (via `html2canvas`) is optional. Installing it as a default dependency and wiring it into the Compare and Rankings pages would be valuable.
- **Player Profile: Peak vs Current toggle** — the peak rating data is already computed and returned by the API, but the profile page doesn't yet have an explicit toggle to switch between "career", "peak window", and "current form" views.
- **Compare page radar overlay** — the Compare page shows side-by-side stat tables but could benefit from an overlaid radar chart showing all 2–4 players' score profiles at a glance.
- **Mobile responsiveness** — the app is responsive at a basic level but some pages (Rankings table, Compare multi-column layout) could be improved for phone screens.
- **Loading skeletons everywhere** — some pages show a generic spinner while data loads. Replacing these with content-shaped skeleton placeholders (already implemented for PlayerCard) would feel smoother.

---

### 6. Advanced Analytics Features

**Planned improvements:**

- **Win Probability Added (WPA) in the UI** — the pipeline already computes WPA (`src/wpa.py`), but it's disabled by default (`wpa.enabled: false` in config) and the GUI doesn't surface it yet. Enabling it and adding a WPA column to the innings log + a WPA chart on the profile page would add a powerful "clutch moment" visualisation.
- **Match context overlays** — on the innings log, show the match situation (target, required rate, wickets fallen) alongside each innings to give context to raw numbers.
- **Archetype evolution** — track how a player's archetype has changed over time (e.g. "Aggressive Opener" → "All-Phase" as they matured). The form tracker already has the rolling window data; this would be a classification pass over each window.
- **Team Builder constraints** — enforce minimum bowling overs, keeper detection, left/right hand balance, and pace/spin mix in the auto-fill algorithm. Currently auto-fill just picks the highest-WAR players.
- **Head-to-head prediction** — given a batter and bowler, predict the expected SR and dismissal probability based on their profiles and matchup history. This would be a fun "what if" feature.

---

### 7. Performance & Scalability

**Planned improvements:**

- **Backend caching headers** — add `Cache-Control: public, max-age=3600` to all responses since the data is static between pipeline runs.
- **Search index persistence** — serialise the trigram index to disk so restarts don't re-build it from scratch (saves ~1s on startup).
- **CDN for static assets** — when deploying the live backend, put a CDN (Cloudflare, CloudFront) in front of the API for caching.
- **Parquet → DuckDB** — for much larger datasets (franchise T20s would 10x the data), swap pandas for DuckDB as the in-memory query engine. DuckDB can query Parquet files directly with SQL, uses less memory, and is faster for analytical queries.

---

## Quick Reference: Run Everything

```bash
# From the project root (cricket_metrics/)

# 1. Set up Python environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r gui/backend/requirements.txt

# 2. Run the pipeline (if output/ doesn't already have data)
python src/main.py

# 3. Start the backend (in one terminal)
cd gui/backend
# Do NOT set OUTPUT_DIR — the backend auto-discovers output_t20i/ and output_ipl/
unset OUTPUT_DIR
uvicorn app:app --reload --port 8000

# 4. Start the frontend (in another terminal)
cd gui/frontend
npm install
npm run dev

# 5. Open http://localhost:5173 in your browser
```
