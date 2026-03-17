# Cricket Metrics — Deployment Guide

This document describes how to deploy the **frontend** to [Vercel](https://vercel.com) and the **backend API** to [Railway](https://railway.app), then connect them.

## Prerequisites

- Pipeline data: the backend needs Parquet/CSV output from the Cricket Metrics pipeline (`output_t20i/`, `output_ipl/`, or a single directory via `OUTPUT_DIR`). Generate this locally with `python src/main.py` (and optionally `--scorecards-only`), then upload or mount it for the backend.
- GitHub repo pushed and connected to both Vercel and Railway.

---

## 1. Backend (Railway)

### 1.1 Create a Railway project

1. Go to [railway.app](https://railway.app) and sign in (e.g. with GitHub).
2. **New Project** → **Deploy from GitHub repo** → select this repository.
3. In the new service, open **Settings** → **Root Directory** and set it to **`gui/backend`** (required).
4. With Root Directory = `gui/backend`, Railway will use **`gui/backend/Dockerfile`** (or Nixpacks if no Dockerfile). Do **not** leave Root Directory empty, or the build will fail (the repo root has no `Dockerfile`; see `Dockerfile.repo` for local full-image builds only).
5. Build and start are configured in `gui/backend/railway.toml` when using Nixpacks; the Dockerfile in `gui/backend` works with this root directory.

### 1.2 Provide pipeline data

The API loads data at startup. Choose one approach:

- **Option A — Volume (recommended for larger data):** In Railway, add a **Volume** to the service, mount it (e.g. at `/data`), and set the variable **`DATA_ROOT=/data`**. Then place `output_t20i` and/or `output_ipl` inside that volume (e.g. via a separate job or upload).
- **Option B — Single directory:** Set **`OUTPUT_DIR`** to the path of a single pipeline output directory (e.g. `/data/output` if you mount a volume at `/data` and put the pipeline output there). This runs in legacy single-format mode.
- **Option C — No data (empty API):** Do not set `OUTPUT_DIR` or `DATA_ROOT`. The app will start but endpoints will return empty results until data is available.

### 1.3 Variables

In Railway → your service → **Variables**, add if needed:

| Variable       | Description |
|----------------|-------------|
| `DATA_ROOT`    | Optional. Root path for pipeline data; `output_t20i/` and `output_ipl/` are resolved under this path. |
| `OUTPUT_DIR`   | Optional. Single pipeline output directory (legacy single-format mode). |
| `CORS_ORIGINS` | Optional. Comma-separated allowed origins for API requests (e.g. `https://your-app.vercel.app`). Add your Vercel (or custom) frontend URL so the browser can call the API. |

### 1.4 Deploy and get the API URL

- Trigger a deploy (or push to the branch Railway watches). After a successful deploy, open **Settings** → **Networking** → **Generate Domain** to get a public URL (e.g. `https://your-app.up.railway.app`).
- Use this URL as the **backend API base URL** for the frontend (no trailing slash).
- **If the build fails** with `COPY gui/backend/ ... not found`: Root Directory must be **`gui/backend`** so the build context is the backend folder. The root-level Dockerfile has been renamed to `Dockerfile.repo` so Railway does not use it for this service.

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
- [ ] Format/data: switch between T20I and IPL in the UI; if no data was provided to the backend, lists will be empty but the app should not crash.

---

## 4. Local development

- **Backend:** `cd gui/backend && uvicorn app:app --reload --port 8000` (ensure `output_t20i`/`output_ipl` or `OUTPUT_DIR` is available).
- **Frontend:** `cd gui/frontend && npm run dev`. The Vite dev server proxies `/api` to `http://localhost:8000`; no `VITE_API_URL` needed for local dev.

See `gui/frontend/.env.example` and `gui/backend/.env.example` for optional local env vars.

---

## 5. Troubleshooting

| Issue | Fix |
|-------|-----|
| **Railway build fails:** `COPY gui/backend/ ... not found` | Set **Root Directory** to **`gui/backend`** (not repo root). The root `Dockerfile` was renamed to `Dockerfile.repo` so only the backend Dockerfile is used. |
| **Frontend shows "Failed to load"** on cards/rankings | Set **`VITE_API_URL`** in Vercel to your Railway API URL (e.g. `https://your-app.up.railway.app`), then redeploy the frontend. |
| **API returns 403 or CORS errors in browser** | Set **`CORS_ORIGINS`** on Railway to your Vercel (or frontend) origin, e.g. `https://your-project.vercel.app`. |
| **Backend starts but endpoints return empty** | Provide pipeline data via a volume + **`DATA_ROOT`**, or **`OUTPUT_DIR`**; see § 1.2. |
