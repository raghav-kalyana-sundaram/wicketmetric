# Cricket Metrics — Deployment Guide

This document describes how to deploy the **frontend** to [Vercel](https://vercel.com) and the **backend API** to [Railway](https://railway.app), then connect them.

## Prerequisites

- Pipeline data: the backend loads Parquet/CSV from up to four slices under one tree: `data/output/mens_t20i`, `data/output/womens_t20i`, `data/output/mens_ipl`, `data/output/womens_ipl` (or legacy repo-root `output/…`, `output_t20i` / `output_ipl`, and `output/womens_t20` for an older women’s intl folder name). Generate locally with `python src/main.py` or run [`scripts/sync_cricsheet.sh`](scripts/sync_cricsheet.sh) to download Cricsheet zips and build all four. Restart the API after refreshing data.
- GitHub repo pushed and connected to both Vercel and Railway.

---

## 1. Backend (Railway)

### 1.1 Create a Railway project

1. Go to [railway.app](https://railway.app) and sign in (e.g. with GitHub).
2. **New Project** → **Deploy from GitHub repo** → select this repository.
3. **Root Directory:** You can use either:
   - **Leave empty (repo root):** Railway uses the root **`Dockerfile`**, which copies only `gui/backend/` (no pipeline data in the image). Provide data at runtime via a **Volume** and **`DATA_ROOT`** (see § 1.2).
   - **Set to `gui/backend`:** Railway uses **`gui/backend/Dockerfile`**; same result — data via volume + `DATA_ROOT` or `OUTPUT_DIR`.

### 1.2 Provide pipeline data

The API loads data at startup. Choose one approach:

- **Option A — One folder `output/` under `DATA_ROOT` (recommended):** Locally that tree is **`data/output/`** with subfolders **`mens_t20i`**, **`womens_t20i`**, **`mens_ipl`**, **`womens_ipl`**. Generate with [`scripts/sync_cricsheet.sh`](scripts/sync_cricsheet.sh) (from repo root) or manually:
  ```bash
  python src/main.py /path/to/t20s_male_json --output data/output/mens_t20i --format t20i
  python src/main.py /path/to/t20s_female_json --output data/output/womens_t20i --format t20i
  python src/main.py /path/to/ipl_male_json --output data/output/mens_ipl --format ipl
  python src/main.py /path/to/wpl_female_json --output data/output/womens_ipl --format ipl
  ```
  On Railway, mount a **Volume** at e.g. `/data`, place the **`output`** folder on it (`/data/output/mens_t20i`, …), and set **`DATA_ROOT=/data`**.
- **Option B — Legacy men’s only:** Put **`output_t20i`** and **`output_ipl`** inside the volume and set **`DATA_ROOT`** to the volume path. The backend maps those to **`mens_t20i`** and **`mens_ipl`**.
- **Option C — Single format (legacy):** Set **`OUTPUT_DIR`** to one pipeline output directory. Only that format (e.g. T20I) is loaded.
- **Option D — No data:** Do not set `OUTPUT_DIR` or `DATA_ROOT`. The app will start but endpoints will return empty results until data is available.

### 1.3 Variables

In Railway → your service → **Variables**, add if needed:

| Variable       | Description |
|----------------|-------------|
| `DATA_ROOT`    | Optional. Root path for pipeline data; resolves `output/{mens_t20i,womens_t20i,mens_ipl,womens_ipl}` or legacy `output_t20i` / `output_ipl` / `output/womens_t20`. |
| `OUTPUT_DIR`   | Optional. Single pipeline output directory (legacy single-format mode). |
| `CORS_ORIGINS` | Optional. Comma-separated allowed origins for API requests (e.g. `https://your-app.vercel.app`). Add your Vercel (or custom) frontend URL so the browser can call the API. |

### 1.4 Deploy and get the API URL

- Trigger a deploy (or push to the branch Railway watches). After a successful deploy, open **Settings** → **Networking** → **Generate Domain** to get a public URL (e.g. `https://your-app.up.railway.app`).
- Use this URL as the **backend API base URL** for the frontend (no trailing slash).
- **If the build fails** with `Dockerfile does not exist`: ensure the repo has a root **`Dockerfile`** (it only copies the backend; data is provided at runtime via volume + `DATA_ROOT`).

---

## 2. Frontend (Vercel)

### 2.1 Create a Vercel project

1. Go to [vercel.com](https://vercel.com) and sign in (e.g. with GitHub).
2. **Add New** → **Project** → import this repository.
3. In **Configure Project**, set **Root Directory** to **`gui/frontend`** (or leave empty and override Build & Output as below).
4. If you did **not** set Root Directory to `gui/frontend`, set:
   - **Build Command:** `cd gui/frontend && npm ci && npm run build`
   - **Output Directory:** `gui/frontend/dist`
   - **Install Command:** `cd gui/frontend && npm ci`

If Root Directory is **`gui/frontend`**, the repo’s `gui/frontend/vercel.json` will be used (build and output are already set there).

### 2.2 Environment variable for the API

In Vercel → your project → **Settings** → **Environment Variables**, add:

| Name           | Value                    | Environments   |
|----------------|--------------------------|----------------|
| `VITE_API_URL` | Your Railway API URL     | Production (and Preview if you want) |

Example: `https://your-app.up.railway.app` (no trailing slash).

The frontend uses this to call the backend; without it, production builds will try to use the same origin and API calls will fail.

### 2.3 Deploy

Push to the connected branch or trigger a deploy from the Vercel dashboard. The app will be available at the Vercel URL (e.g. `https://your-project.vercel.app`).

---

## 3. Post-deploy checklist

- [ ] **Backend health:** open `https://your-railway-url.up.railway.app/api/meta`. You should get JSON. If you get CORS errors in the browser, add your Vercel URL to **`CORS_ORIGINS`** on Railway.
- [ ] **Frontend loads data:** In Vercel, set **`VITE_API_URL`** to your Railway URL (e.g. `https://your-app.up.railway.app`, no trailing slash). Redeploy the frontend after changing it. Without this, the UI shows "Failed to load" because API requests go to the wrong place.
- [ ] **CORS:** On Railway, set **`CORS_ORIGINS`** to your Vercel URL (e.g. `https://your-project.vercel.app`) so the browser allows API requests from the frontend.
- [ ] Format/data: switch gender and T20 vs IPL in the UI; missing slices are skipped at startup—only loaded folders appear in the toggle.

---

## 4. Local development

- **Backend:** `cd gui/backend && uvicorn app:app --reload --port 8000` (ensure `data/output/` subfolders or legacy `output_t20i`/`output_ipl` exist, or set `OUTPUT_DIR`).
- **Frontend:** `cd gui/frontend && npm run dev`. The Vite dev server proxies `/api` to `http://localhost:8000`; no `VITE_API_URL` needed for local dev.

See `gui/frontend/.env.example` and `gui/backend/.env.example` for optional local env vars.

---

## 5. Troubleshooting

| Issue | Fix |
|-------|-----|
| **Railway build fails:** `Dockerfile does not exist` | Ensure the root **`Dockerfile`** is present (it builds from repo root; no pipeline data in image — use a volume + `DATA_ROOT`). |
| **Railway build fails:** `COPY gui/backend/ ... not found` | Use **Root Directory** = repo root (empty) so the root Dockerfile’s context includes `gui/backend`, or set Root Directory to **`gui/backend`** to use `gui/backend/Dockerfile`. |
| **Frontend shows "Failed to load"** on cards/rankings | Set **`VITE_API_URL`** in Vercel to your Railway API URL (e.g. `https://your-app.up.railway.app`), then redeploy the frontend. |
| **API returns 403 or CORS errors in browser** | Set **`CORS_ORIGINS`** on Railway to your Vercel (or frontend) origin, e.g. `https://your-project.vercel.app`. |
| **Backend starts but endpoints return empty** | Provide pipeline data via a volume + **`DATA_ROOT`**, or **`OUTPUT_DIR`**; see § 1.2. |
