# Cricket Metrics — GUI

Interactive web dashboard for the Cricket Metrics T20I Player Performance Profiling Engine.

Built with **FastAPI** (Python backend) and **React + TypeScript** (Vite frontend). All data is read-only and loaded from pre-computed pipeline Parquet outputs into memory at startup for sub-millisecond response times.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start (Development)](#quick-start-development)
  - [Backend](#backend)
  - [Frontend](#frontend)
- [Quick Start (Docker)](#quick-start-docker)
- [Vercel (frontend + API)](#vercel-frontend--api)
- [Project Structure](#project-structure)
- [Environment Variables](#environment-variables)
- [API Endpoints](#api-endpoints)
- [Pages & Routes](#pages--routes)
- [Key Components](#key-components)
- [Theming](#theming)
- [UI guide (frontend)](#ui-guide-frontend)
- [Testing](#testing)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

- **Python 3.11+** with pip
- **Node.js 18+** with npm
- **Pipeline outputs** — the GUI reads from pre-computed Parquet/CSV files under `data/output/` (per-slice subfolders such as `data/output/mens_t20i/`). Run the Cricket Metrics pipeline first to generate these files:
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

## Quick Start (Development)

### Backend

```bash
cd gui/backend

# Create a virtual environment (recommended)
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
# .venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Do NOT set OUTPUT_DIR — the backend auto-discovers slices under data/output/<format>/
# (and legacy repo-root output_t20i/ / output_ipl/). If you previously exported it, unset:
unset OUTPUT_DIR

# Start the API server
uvicorn app:app --reload --port 8000
```

The API will be available at **http://localhost:8000**:
- Swagger docs: http://localhost:8000/api/docs
- ReDoc: http://localhost:8000/api/redoc
- Health check: http://localhost:8000/api/health
- Metadata: http://localhost:8000/api/meta

### Frontend

```bash
cd gui/frontend

# Install dependencies
npm install

# Start the Vite dev server
npm run dev
```

The frontend will be available at **http://localhost:5173** and will proxy API requests to the backend on port 8000.

> **Note:** The frontend expects the backend to be running on `http://localhost:8000`. If you use a different port, set the `VITE_API_URL` environment variable:
> ```bash
> VITE_API_URL=http://localhost:9000 npm run dev
> ```

---

## Quick Start (Docker)

```bash
cd gui

# Build and start both services
docker compose up --build

# Or run in the background
docker compose up --build -d
```

This starts:
- **Backend** on port `8000`
- **Frontend** on port `3000`

The Docker Compose file mounts `data/output/` from the project root into the backend container at `/app/output`.

To stop:
```bash
docker compose down
```

---

## Vercel (frontend + API + Blob)

Deploy **frontend + FastAPI** on one Vercel project using [Services](https://vercel.com/docs/services): in the Vercel dashboard set **Framework Preset** to **Services** (not Vite), **Root Directory** to the **repo root** or **`gui`** (never **`gui/frontend`** — that yields **`/api` 404**). Use **`framework": "services"`** and **`experimentalServices`** in the repo-root **`vercel.json`** or **`gui/vercel.json`** accordingly. Put pipeline Parquet on **Vercel Blob** and set **`BLOB_PARQUET_BASE_URL`** (+ token if private); leave **`VITE_API_URL`** unset so the browser uses same-origin **`/api`**.

Full steps, **`vercel dev -L`**, and troubleshooting: **[DEPLOYMENT.md](../DEPLOYMENT.md)** and **[vercel.env.example](../vercel.env.example)**. The Python entrypoint **`backend/vercel_entry.py`** restores the **`/api`** path prefix that Vercel strips before invoking FastAPI.

---

## Project Structure

```
gui/
├── README.md                    # This file
├── vercel.json                  # Vercel Services: frontend + FastAPI
├── docker-compose.yml           # Full-stack Docker setup
│
├── backend/                     # FastAPI Python backend
│   ├── app.py                   # Application entry point & lifespan
│   ├── vercel_entry.py          # Vercel Python service ASGI wrapper
│   ├── data_loader.py           # Parquet/CSV → DataStore loader
│   ├── search_index.py          # Trigram search index
│   ├── schemas.py               # Pydantic response models
│   ├── requirements.txt         # Python dependencies (local, Docker, Vercel)
│   ├── Dockerfile               # Backend container
│   └── routers/                 # API route modules
│       ├── search.py            # /api/search, /api/autocomplete
│       ├── player.py            # /api/player/:id, form, innings, spells, similar
│       ├── rankings.py          # /api/rankings/bat, /api/rankings/bowl
│       ├── compare.py           # /api/compare
│       ├── matchups.py          # /api/matchups, /api/h2h
│       ├── venues.py            # /api/venues
│       ├── eras.py              # /api/eras
│       └── team.py              # /api/team/analyse, /api/team/auto-fill
│
└── frontend/                    # React + TypeScript (Vite)
    ├── index.html               # HTML entry point
    ├── package.json             # Node dependencies & scripts
    ├── vite.config.ts           # Vite configuration
    ├── tailwind.config.ts       # Tailwind CSS theme & design tokens
    ├── tsconfig.json            # TypeScript configuration
    └── src/
        ├── main.tsx             # React root mount
        ├── App.tsx              # Router + QueryClient setup
        ├── vite-env.d.ts        # Vite environment type declarations
        │
        ├── api/                 # API layer
        │   ├── client.ts        # Typed fetch wrapper & endpoint functions
        │   ├── queries.ts       # TanStack Query hooks (usePlayer, useRankings, etc.)
        │   └── types.ts         # TypeScript interfaces for API responses
        │
        ├── components/          # Shared UI components
        │   ├── Layout.tsx       # App shell — nav bar, sidebar, footer
        │   ├── PlayerAutocomplete.tsx  # Fuzzy search input with suggestions
        │   ├── PlayerCard.tsx   # Compact player card (search results, cards)
        │   ├── ScoreBar.tsx     # Horizontal 0–100 score bar with colour coding
        │   ├── GradeBadge.tsx   # Letter grade chip (S/A+/A/B+/B/C+/C/D)
        │   ├── ArchetypeBadge.tsx     # Archetype label with icon
        │   ├── ProvisionalBadge.tsx   # Provisional status warning indicator
        │   ├── MetricTooltip.tsx      # Hover tooltip with metric explanations
        │   ├── FormSparkline.tsx      # Mini time-series chart (100px wide)
        │   ├── Pagination.tsx   # Page navigation controls
        │   ├── ExportButton.tsx # CSV / PNG / URL share export
        │   └── ThemeToggle.tsx  # Dark/light mode toggle
        │
        ├── hooks/               # Custom React hooks
        │   ├── useDebounce.ts   # Debounced value hook
        │   └── useTheme.ts     # Theme (dark/light) management
        │
        ├── lib/                 # Utility modules
        │   ├── colours.ts       # Score-to-colour mapping, chart palette
        │   └── format.ts        # Number/date/country formatting utilities
        │
        ├── pages/               # Route-level page components
        │   ├── Home.tsx         # Dashboard with hero search & leaderboard cards
        │   ├── Search.tsx       # Player search results
        │   ├── PlayerProfile.tsx # Full player profile (batting & bowling)
        │   ├── InningsLog.tsx   # Full batting innings log (paginated)
        │   ├── SpellsLog.tsx    # Full bowling spells log (paginated)
        │   ├── Rankings.tsx     # Leaderboards with sorting & filtering
        │   ├── Compare.tsx      # Side-by-side player comparison (2–4)
        │   ├── Matchups.tsx     # Head-to-head & matchup explorer
        │   ├── Similar.tsx      # Similar players with scatter plot
        │   ├── TeamBuilder.tsx  # Hypothetical XI builder with analysis
        │   ├── Eras.tsx         # Era explorer with timeline chart
        │   ├── Venues.tsx       # Venue analysis & flat-track index
        │   └── Glossary.tsx     # Metric definitions & methodology
        │
        └── styles/
            └── globals.css      # Tailwind base + component + utility layers
```

---

## Environment Variables

### Backend

| Variable | Default | Description |
|----------|---------|-------------|
| `OUTPUT_DIR` | `../../data/output` (relative to `backend/`) | Path to the pipeline output directory containing Parquet files |
| `PORT` | `8000` | Server port |
| `HOST` | `0.0.0.0` | Server host |
| `RELOAD` | `false` | Enable auto-reload for development |

### Frontend

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_URL` | `http://localhost:8000` | Backend API base URL |

---

## API Endpoints

### Meta & Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check |
| `GET` | `/api/meta` | Dataset metadata (counts, countries, archetypes) |

### Search

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/search?q=...` | Full-text search with trigram matching |
| `GET` | `/api/search/autocomplete?q=...` | Lightweight autocomplete suggestions |
| `GET` | `/api/search/countries` | List of all countries in the dataset |
| `GET` | `/api/search/archetypes` | Archetype lists by role |

### Player

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/player/:id` | Full player profile (auto-detects bat/bowl) |
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
| `GET` | `/api/rankings/top` | Top N players by any metric |
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
| `GET` | `/api/matchups/top-bunnies?bowler_id=...` | Top bunny matchups for a bowler |
| `GET` | `/api/matchups/top-nemeses?batter_id=...` | Top nemesis matchups for a batter |
| `GET` | `/api/matchups/top-dominant?batter_id=...` | Top dominant matchups for a batter |

### Venues

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/venues` | Venue list with baselines |
| `GET` | `/api/venues/detail?venue=...` | Single venue detail |
| `GET` | `/api/venues/players?venue=...&role=...` | Player performance at a venue |
| `GET` | `/api/venues/flat-track-index` | Flat-track bully leaderboard |
| `GET` | `/api/venues/summary` | Venue difficulty summary |

### Eras

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/eras` | Era baselines (par SR, boundary rate, dot %, multiplier) by year |

### Team Builder

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/team/analyse?ids=...` | Aggregate analysis for a team selection |
| `GET` | `/api/team/auto-fill?strategy=...` | Auto-fill XI suggestions |

---

## Pages & Routes

| Route | Page | Description |
|-------|------|-------------|
| `/` | Home | Dashboard with hero search, leaderboard cards, quick compare |
| `/search` | Search | Full-text player search with filters |
| `/player/:id` | Player Profile | Complete player profile (batting or bowling) |
| `/player/:id/innings` | Innings Log | Full paginated batting innings log |
| `/player/:id/spells` | Spells Log | Full paginated bowling spells log |
| `/rankings` | Rankings | Leaderboards with sorting, filtering, pagination |
| `/compare?ids=...` | Compare | Side-by-side comparison of 2–4 players |
| `/matchups` | Matchups | Head-to-head lookup and matchup explorer |
| `/similar/:id` | Similar Players | Similarity scatter plot and nearest neighbours |
| `/team-builder` | Team Builder | Build a hypothetical XI with analysis |
| `/eras` | Era Explorer | Timeline of T20I era evolution |
| `/venues` | Venue Analysis | Venue difficulty and flat-track index |
| `/glossary` | Glossary | Metric definitions, methodology, FAQ |

---

## Key Components

| Component | Description |
|-----------|-------------|
| `<PlayerAutocomplete>` | Fuzzy search input with dropdown suggestions, role/country filtering |
| `<PlayerCard>` | Compact card showing name, country, archetype, score bars, grade |
| `<ScoreBar>` | Horizontal 0–100 bar with colour gradient (S=gold → D=red) |
| `<GradeBadge>` | Letter grade chip with colour coding |
| `<ArchetypeBadge>` | Archetype label with emoji icon and optional colour tint |
| `<ProvisionalBadge>` | Warning indicator for low-sample-size players |
| `<MetricTooltip>` | Hover tooltip with plain-English metric explanations |
| `<FormSparkline>` | Mini inline time-series chart (~100px) for form indication |
| `<Pagination>` | Page controls with truncated page numbers and size selector |
| `<ExportButton>` | Export data as CSV, PNG screenshot, or shareable URL |
| `<ThemeToggle>` | Dark/light mode toggle with OS preference detection |

---

## Theming

The app supports **dark mode** (default) and **light mode**, toggled via the theme button in the navigation bar.

- Theme state is persisted in `localStorage` under the key `cricket-metrics-theme`.
- On first visit, the app respects the OS `prefers-color-scheme` preference.
- The Tailwind config uses `darkMode: "class"`, toggling the `dark` class on `<html>`.
- All colour tokens are defined in `tailwind.config.ts` under `theme.extend.colors`.

### UI guide (frontend)

Site-wide visual standards (dark-first monochrome, win probability as reference) live in **[frontend/UI_GUIDE.md](frontend/UI_GUIDE.md)**. For a full dark-mode pass driven by that guide, use **[frontend/DARK_MODE_REDESIGN_PROMPT.md](frontend/DARK_MODE_REDESIGN_PROMPT.md)**.

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

---

## Testing

### Backend

```bash
cd gui/backend
pip install -r requirements.txt pytest
# or with uv: uv sync --extra dev

pytest
```

### Frontend

```bash
cd gui/frontend

# Type check
npx tsc --noEmit

# Build (includes type check)
npm run build

# Lint
npm run lint
```

---

## Troubleshooting

### "Data not loaded" / degraded health status

The backend couldn't find or read the pipeline output files. Check:
1. The `OUTPUT_DIR` environment variable points to the correct directory.
2. The pipeline has been run and the Parquet files exist.
3. File permissions allow the backend process to read the files.

### CORS errors in the browser

The backend allows requests from `localhost:3000`, `localhost:5173`, and `localhost:5174`. If you're running the frontend on a different port, add it to the `allow_origins` list in `app.py`.

### Empty search results

The trigram search index is built at startup from the career DataFrames. If those are empty (missing Parquet files), search will return no results. Check the backend startup logs for `[WARN] Missing:` messages.

### Team Builder not loading from shared URL

When opening a shared Team Builder URL (`/team-builder?ids=...`), the page fetches each player's profile from the API. If the backend is not running or the IDs are invalid, the slots will remain empty. Check the browser console for fetch errors.

### Theme not applying

Clear the `cricket-metrics-theme` key from localStorage and refresh. The theme should then follow your OS preference.