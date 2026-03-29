# Cricket Metrics — Deployment Guide

**Recommended:** one **[Vercel](https://vercel.com)** project running the **Vite frontend** and **FastAPI backend** ([Services](https://vercel.com/docs/services)), with pipeline Parquet in **[Vercel Blob](https://vercel.com/docs/storage/vercel-blob)**. No separate host (e.g. Railway) is required.

---

## Prerequisites

- Repo pushed to GitHub (or GitLab / Bitbucket) and connected to Vercel.
- Local pipeline outputs under `data/output/mens_t20i`, `womens_t20i`, `mens_ipl`, `womens_ipl` when you run uploads (see [PUBLISHING.md](PUBLISHING.md) and [`scripts/sync_cricsheet.sh`](scripts/sync_cricsheet.sh)).

---

## 1. Vercel + Blob (single project)

### 1.1 Project configuration

1. **Import** this repository into Vercel.
2. In **Project → Settings → General**, set **Framework Preset** to **Services** (not **Vite** and not “Leave as auto-detected”). Vercel’s docs require both **`experimentalServices` in `vercel.json`** and this preset; if the preset stays **Vite**, only the frontend is built and **`/api/*` returns 404** on the same deployment URL.
3. Ensure **one** of these is true (paths must match the `vercel.json` Vercel actually reads):
   - **Root Directory** is **empty** (repository root) and **[`vercel.json`](vercel.json)** at the repo root lists **`gui/frontend`** + **`gui/backend/vercel_entry.py`**, **`framework": "services"`**, **or**
   - **Root Directory** = **`gui`** and **`gui/vercel.json`** (entrypoints **`frontend`** / **`backend/vercel_entry.py`**).
4. **Never** set **Root Directory** to **`gui/frontend`**. That folder only contains the Vite app; there is no FastAPI service there, so **`/api`** will not exist.
5. Install [uv](https://docs.astral.sh/uv/getting-started/installation/) locally if you use **`vercel build`** on your machine (Python service builds expect it).

**Services availability:** [Services](https://vercel.com/docs/services) may require the right plan or team access. If the preset is missing, check Vercel account/team settings.

### 1.2 Upload Parquet to Blob

From the **repository root** (after `data/output/…` exists and paths match **`output/<format>/…`** on Blob — see [PUBLISHING.md](PUBLISHING.md)):

```bash
export BLOB_READ_WRITE_TOKEN="vercel_blob_rw_…"   # or use .env.local
npm run upload:blob:dry
npm run upload:blob          # public store
# or: npm run upload:blob:private
```

Set **`BLOB_READ_WRITE_TOKEN`** in Vercel project env for production uploads/CI if you automate this later.

### 1.3 Environment variables (Vercel → Project → Settings)

Checklist of names: **[vercel.env.example](vercel.env.example)**.

| Variable | Purpose |
|----------|---------|
| **`BLOB_PARQUET_BASE_URL`** | Blob store **origin** only, e.g. `https://xxxx.public.blob.vercel-storage.com` (no path). |
| **`BLOB_READ_WRITE_TOKEN`** | Required if the store is **private** or reads need auth. Use the same token as uploads. Also set as **`BLOB_READ_WRITE_TOKEN`** (not only `*_READ_WRITE_TOKEN`) so **`@vercel/blob`** and **`gui/backend/blob_hydrate.py`** agree. |
| **`VITE_API_URL`** | **Leave unset or empty** so the browser calls **`/api/...`** on the same Vercel host (no CORS, no Railway). |

Do **not** set **`OUTPUT_DIR`** when using the multi-slice Blob layout (see `gui/backend/blob_hydrate.py`).

Optional: **`CORS_ORIGINS`** only if the SPA is served from a **different** origin than the API.

### 1.4 Stop using Railway (if you used it before)

1. In **Vercel**, remove or clear **`VITE_API_URL`** if it pointed at `*.up.railway.app`, then **redeploy** the frontend.
2. **Railway:** delete the service or stop the project so you are not billed.
3. No **`CORS_ORIGINS`** gymnastics are needed for browser → same-origin **`/api`**.

### 1.5 Deploy and verify

- Push or **Redeploy** after env changes.
- Open **`https://<your-project>.vercel.app/api/meta`** — expect JSON, not a network error.
- **`/api/health`** should be **`ok`** once Blob hydrate downloaded at least one slice (check function logs for **Blob hydrate** lines).

---

## 2. Post-deploy checklist (Vercel-only)

- [ ] **Framework Preset = Services** (not Vite-only) + **`vercel.json`** with **`experimentalServices`** (repo root or `gui/`).
- [ ] **Root Directory** = repo root **or** `gui` — **not** `gui/frontend`.
- [ ] **`VITE_API_URL`** empty for same-origin API.
- [ ] **`BLOB_PARQUET_BASE_URL`** (+ token if private) set for Production (and Preview if needed).
- [ ] Parquet on Blob under **`output/<format>/…`** matching `gui/backend/blob_hydrate.py`.
- [ ] **`GET /api/meta`** and home page load without CORS errors.

---

## 3. Local development

- **Backend:** `cd gui/backend && uvicorn app:app --reload --port 8000` (use `data/output/` or Blob env vars locally).
- **Frontend:** `cd gui/frontend && npm run dev` — Vite proxies **`/api`** to port 8000; **`VITE_API_URL`** not required.

See **`gui/frontend/.env.example`** and **`gui/backend/.env.example`**.

---

## 4. Troubleshooting

| Issue | Fix |
|-------|-----|
| **`GET /api/meta` (or any `/api/…`) returns 404** on `*.vercel.app` | Almost always **Vite-only** deploy: set **Framework Preset** to **Services**, set **Root Directory** to **repo root** or **`gui`** (never **`gui/frontend`**). Redeploy. In the deployment **Build** logs you should see **both** the frontend (Vite) and backend (Python/FastAPI) services building. |
| **`vercel` / deploy: `Unexpected error`**, inspect shows empty build `output` | Use repo-root **`vercel.json`** **or** set dashboard **Root Directory** to **`gui`** and **Framework Preset** to **Services**. PATCH project API with `rootDirectory` + `framework: "services"` if the dashboard won’t stick. |
| **`uv is required but was not found in PATH`** (local `vercel build`) | Install **uv** (`brew install uv` or Astral install script). |
| **Frontend "Failed to load" / CORS to Railway** | You are still pointing **`VITE_API_URL`** at Railway. **Clear it** and redeploy so the app uses same-origin **`/api`** on Vercel, **or** finish migrating to full-stack Services. |
| **API degraded / empty data** | Check Blob paths (`output/mens_t20i/batting_careers_full.parquet`, …), **`BLOB_PARQUET_BASE_URL`**, and private-store **token**. See [PUBLISHING.md](PUBLISHING.md). |

---

## Appendix: Optional Railway backend

If you prefer a **separate** API on [Railway](https://railway.app) instead of Vercel Functions:

1. Deploy from this repo with the root **`Dockerfile`** or **`gui/backend/Dockerfile`**; mount a volume + **`DATA_ROOT`** for `output/…`, **or** use Blob hydrate on Railway with the same **`BLOB_*`** env vars.
2. Set **`VITE_API_URL`** on Vercel to the Railway base URL (no trailing slash).
3. Set **`CORS_ORIGINS`** on Railway to your Vercel origin (e.g. `https://your-project.vercel.app`).

Details: root **`Dockerfile`**, **`gui/backend/.env.example`**, and Railway networking in the Git history of this file if you need the full legacy walkthrough.
