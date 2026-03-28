# Publishing Cricket Metrics (website + Parquet backend)

This guide walks you from a local machine with built data to a **live site** where the **FastAPI backend can see and load every Parquet tree** the UI expects.

For platform-specific env vars and troubleshooting tables, see [DEPLOYMENT.md](DEPLOYMENT.md).

---

## How the pieces fit together

| Piece | What it is | Where it runs |
|--------|------------|----------------|
| **Frontend** | Vite/React static assets | e.g. Vercel (CDN) |
| **Backend** | FastAPI reads Parquet/CSV **from disk at process startup**, keeps data in memory | e.g. Railway, Fly.io, a VPS |
| **Parquet files** | Pipeline output (`batting_careers_full.parquet`, `bowling_careers_full.parquet`, etc.) | **Same machine/filesystem as the API**, not on Vercel |

**“Visible” to the backend** means: inside the API container/process, the directories below exist and contain the expected files. The API does **not** download Parquet from the frontend and does **not** serve raw `.parquet` URLs to browsers by default—it **opens files from paths** resolved via `DATA_ROOT` / `OUTPUT_DIR` (see `gui/backend/data_loader.py`).

If you deploy only the Docker image without attaching data, `/api/health` may still return `200`, but **`/api/health` reports `degraded`** and `/api/formats` is empty until valid output folders are present.

---

## Recommended folder layout (one tree)

Generate data locally (from repo root):

```bash
./scripts/sync_cricsheet.sh
```

That produces:

```text
data/output/
  mens_t20i/      # Parquet + CSV from men’s T20I pipeline
  womens_t20i/
  mens_ipl/
  womens_ipl/
```

Legacy layouts (repo-root `output/`, `output_t20i`, `output_ipl`, or `output/womens_t20` for older women’s intl) also work; the loader tries several candidates. The **canonical** layout for all four slices is `data/output/<format_key>/` as above.

---

## Publish in this order

### 1. Build pipeline outputs locally

- Ensure `data/output/mens_t20i`, `data/output/womens_t20i`, `data/output/mens_ipl`, `data/output/womens_ipl` each contain the career Parquet files (at minimum files the pipeline writes, e.g. `batting_careers_full.parquet`, `bowling_careers_full.parquet`).
- Sizes can be large; **do not rely on Git** to carry `data/output/` unless you explicitly use Git LFS or a separate artifact store.

### 2. Deploy the API with disk access to pipeline `output/`

**Railway (typical):**

1. Connect the repo and deploy using the root [Dockerfile](Dockerfile) (or `gui/backend/Dockerfile` with root directory set—see [DEPLOYMENT.md](DEPLOYMENT.md)).
2. Add a **persistent volume** (e.g. mount at `/data`).
3. **Copy your local `data/output/` tree onto that volume** so you have paths like:
   - `/data/output/mens_t20i/…`
   - `/data/output/womens_t20i/…`
   - `/data/output/mens_ipl/…`
   - `/data/output/womens_ipl/…`
4. Set **`DATA_ROOT=/data`** in Railway variables.  
   The default image sets `DATA_ROOT=/app`; if your data lives on `/data`, **you must override** `DATA_ROOT` or the API will not see your Parquets.
5. Redeploy or **restart** the service after changing data (the app loads Parquet **once at startup**).

**Getting files onto the volume:** use Railway’s shell/file workflows, `rsync`/`scp` to a bastion, or a one-off job that downloads an archive you uploaded to object storage. The important part is the **final path** matches what `DATA_ROOT` implies (`$DATA_ROOT/output/mens_t20i`, etc.).

**Single-slice only (legacy):** set **`OUTPUT_DIR`** to one absolute path containing that slice’s Parquet files; only that format loads.

### 3. Point the frontend at the API

On Vercel (root directory `gui/frontend`):

- Set **`VITE_API_URL`** to your public API origin, e.g. `https://your-service.up.railway.app` (**no trailing slash**).
- Redeploy the frontend after changing this variable (Vite bakes it at build time).

### 4. Allow browser → API (CORS)

On the backend host, set **`CORS_ORIGINS`** to your frontend origin(s), e.g. `https://your-project.vercel.app`. Without this, the UI may fail even when the API and Parquet are correct.

---

## Verify Parquet-backed deployment

Run these against your **production API base URL** (replace the example):

1. **`GET /api/health`**  
   - Expect `"status": "ok"` and a non-empty **`formats`** list when at least one slice loaded.  
   - `"status": "degraded"` means **no dataset directory with usable career tables** was found—check volume mount and `DATA_ROOT`.

2. **`GET /api/formats`**  
   - Lists which slices loaded (e.g. `mens_t20i`, `womens_ipl`). Missing folders are simply omitted.

3. **`GET /api/meta?format=mens_t20i`** (and other formats you care about)  
   - Expect `"status": "ok"` and non-zero **`total_batters`** / **`total_bowlers`** when Parquet loaded for that slice.

4. Open the live site: rankings and player views should load without “Failed to load” if **`VITE_API_URL`** and **CORS** match.

---

## Common mistakes (empty site, full build)

| Mistake | Symptom | Fix |
|--------|---------|-----|
| Data never copied to the host | `/api/health` → `degraded` | Mount volume + copy your `data/output/` tree so `$DATA_ROOT/output/…` exists; set `DATA_ROOT` to the parent of `output/` |
| Wrong `DATA_ROOT` | Same as above | `DATA_ROOT` must be the root under which `output/mens_t20i` (or legacy dirs) exists on the host (locally that tree lives at `data/output/…` in the repo) |
| Forgot API restart after refresh | Old or empty data | Restart/redeploy backend after replacing Parquet |
| Missing `VITE_API_URL` | UI errors, requests to wrong host | Set in Vercel and redeploy frontend |
| Missing `CORS_ORIGINS` | Browser blocks API | Add exact frontend origin on backend |

---

## After publishing: refreshing data

1. Re-run the pipeline locally (or in CI) to regenerate `data/output/…`.
2. Replace the files on the API server’s volume (or rebuild your data artifact and redeploy).
3. **Restart** the API process so it reloads Parquet from disk.

---

## Optional: Vercel Blob for Parquet artifacts

Vercel Blob is **object storage** (not a query engine). It is useful for **hosting copies** of your Parquet tree so a deploy job or server can **download** them without checking large files into Git.

### 1. Create the store in Vercel

1. Open your project on [vercel.com](https://vercel.com) → **Storage** → **Create** → **Blob**.
2. When prompted for access, choose **Public** if you want anonymous HTTPS URLs (e.g. for simple downloads). Choose **Private** if only authenticated clients should read blobs. **You cannot change this later** for an existing store—create a new store if you picked the wrong type.
3. Link the store to the same project as your frontend (or a dedicated project).
4. Copy **`BLOB_READ_WRITE_TOKEN`** from the store settings (or run `vercel link` then `vercel env pull` in the repo root to populate `.env.local`).

CLI alternative for a **public** store: `vercel blob create-store my-parquet --access public` (from a [linked](https://vercel.com/docs/cli/project-linking) project directory).

### 2. Upload from this repo

From the **repository root** (after `data/output/…` exists locally), either put `BLOB_READ_WRITE_TOKEN` in `.env.local` (or `.env`) at the repo root—the upload script loads those files—or export it in the shell:

```bash
export BLOB_READ_WRITE_TOKEN="vercel_blob_..."
npm run upload:blob
```

Stable blob paths mirror the local tree, e.g. `output/mens_t20i/batting_careers_full.parquet` (override with `--prefix` / `--root`; see `scripts/upload-parquet-to-vercel-blob.mjs`).

Dry run:

```bash
npm run upload:blob:dry
```

If uploads fail with *“Cannot use public access on a private store”*, your store is **private**. Either run **`npm run upload:blob:private`** (or `BLOB_ACCESS=private` in `.env.local`), or create a **new** Blob store with **Public** access and use its token instead.

### 3. Using blobs with the API today

The FastAPI app still expects Parquet **on disk** (or under `DATA_ROOT`) at startup. Blob does **not** replace that by itself: you would add a step that **downloads** blobs to a volume before starting Uvicorn, or refactor the loader to read from URLs. Until then, treat Blob as a **durable artifact mirror** for CI/sync workflows.

---

## Further reading

- [DEPLOYMENT.md](DEPLOYMENT.md) — Vercel/Railway variables, Dockerfile notes, troubleshooting table.
- [scripts/sync_cricsheet.sh](scripts/sync_cricsheet.sh) — downloads Cricsheet zips and fills all four `data/output/` slices.
- `gui/backend/.env.example` — local `DATA_ROOT` / `OUTPUT_DIR` / `CORS_ORIGINS` reference.
