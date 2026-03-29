# Publishing Cricket Metrics (website + Parquet backend)

This guide walks you from a local machine with built data to a **live site** where the **FastAPI backend can see and load every Parquet tree** the UI expects.

For platform-specific env vars and troubleshooting tables, see [DEPLOYMENT.md](DEPLOYMENT.md).

---

## How the pieces fit together

| Piece | What it is | Where it runs |
|--------|------------|----------------|
| **Frontend** | Vite/React static assets | Vercel (Services, `routePrefix` `/`) |
| **Backend** | FastAPI; loads Parquet **from disk after optional Blob hydrate** at startup | Same Vercel project (Python service, `routePrefix` `/api`) **or** Docker/VPS/Railway |
| **Parquet files** | Pipeline output (`batting_careers_full.parquet`, …) | **Recommended:** [Vercel Blob](https://vercel.com/docs/storage/vercel-blob) under `output/<format>/…`, downloaded into a temp cache by `gui/backend/blob_hydrate.py` when **`BLOB_PARQUET_BASE_URL`** is set. **Alternative:** same filesystem as the API (`DATA_ROOT` / `OUTPUT_DIR`). |

**“Visible” to the backend** means: after startup, either Parquet exists under resolved `DATA_ROOT/output/…` (local disk, volume, or post–Blob hydrate cache) or the API stays **degraded** until data is available.

If you deploy the API image **without** Blob env vars **and** without a mounted `output/` tree, **`/api/health`** reports **`degraded`** and **`/api/formats`** is empty.

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

### 2. Recommended — Vercel (full stack) + Blob

1. **Upload** Parquet to Blob from the repo root (paths must mirror `output/<format>/…` — see below):
   ```bash
   export BLOB_READ_WRITE_TOKEN="vercel_blob_rw_…"
   npm run upload:blob:dry && npm run upload:blob
   ```
   (Use **`npm run upload:blob:private`** for a private store.)
2. **Vercel project:** Services + repo-root **`vercel.json`** (or **`gui/`** root + **`gui/vercel.json`**). See [DEPLOYMENT.md](DEPLOYMENT.md).
3. **Environment variables** in Vercel (see **[vercel.env.example](vercel.env.example)**):
   - **`BLOB_PARQUET_BASE_URL`** — store origin only.
   - **`BLOB_READ_WRITE_TOKEN`** — if the store is private.
   - **`VITE_API_URL`** — **leave unset** so the SPA calls same-origin **`/api/...`** (no CORS).
4. **Deploy** / redeploy. On each cold start the API runs **`blob_hydrate`** then **`data_loader`** (see `gui/backend/app.py`).

### 3. Alternative — API on a host with a disk volume (e.g. Docker, VPS, Railway)

1. Deploy using the root [Dockerfile](Dockerfile) or **`gui/backend/Dockerfile`** ([DEPLOYMENT.md](DEPLOYMENT.md) appendix).
2. Mount or copy **`data/output/`** so **`$DATA_ROOT/output/mens_t20i`**, etc. exist; set **`DATA_ROOT`** accordingly.
3. **Split frontend:** deploy **`gui/frontend`** on Vercel with **`VITE_API_URL`** = your API base URL (**no trailing slash**), and set **`CORS_ORIGINS`** on the API to your Vercel origin.

**Single-slice only (legacy):** set **`OUTPUT_DIR`** to one directory; do not use Blob multi-layout with **`OUTPUT_DIR`** set (hydrate is skipped).

### 4. Blob upload details (store + paths)

1. **Vercel** → **Storage** → **Create** → **Blob**. Choose **Public** or **Private** (access mode is fixed for the life of that store).
2. Link the store to your app project. Set **`BLOB_READ_WRITE_TOKEN`** in the dashboard. If `vercel env pull` creates **`yourproject_READ_WRITE_TOKEN`**, duplicate the value as **`BLOB_READ_WRITE_TOKEN`** for the SDK and **`gui/backend/blob_hydrate.py`**.
3. From **repo root** (local **`data/output/<format>/…`** present):

```bash
export BLOB_READ_WRITE_TOKEN="vercel_blob_rw_..."
npm run upload:blob:dry
npm run upload:blob
```

Use **`npm run upload:blob:private`** for a private store. Blob pathnames must match **`output/mens_t20i/batting_careers_full.parquet`**, etc. (`scripts/upload-parquet-to-vercel-blob.mjs`; **`--prefix`** / **`--root`** optional).

**Troubleshooting uploads:** private store + public access error → **`upload:blob:private`**. **`BlobStoreNotFoundError`** → token/store mismatch, regenerate token. Large files → **`BLOB_UPLOAD_NO_MULTIPART=1 npm run upload:blob`**. CLI: **`vercel blob create-store`** ([project linking](https://vercel.com/docs/cli/project-linking)).

**Runtime:** `gui/backend/app.py` calls **`maybe_hydrate_data_root_from_blob()`** before loading data when **`BLOB_PARQUET_BASE_URL`** is set (`gui/backend/blob_hydrate.py`).

---

## Verify Parquet-backed deployment

Use your live site origin (Vercel full stack: same host for UI and **`/api`**).

1. **`GET /api/health`** — **`ok`** + non-empty **`formats`** when a slice loaded; **`degraded`** if no data after Blob hydrate / disk layout is wrong.
2. **`GET /api/formats`** — lists loaded slices.
3. **`GET /api/meta?format=mens_t20i`** — non-zero **`total_batters`** / **`total_bowlers`** when that slice loaded.
4. UI loads without “Failed to load”. **Same-origin Vercel:** **`VITE_API_URL`** unset. **Split deploy:** set **`VITE_API_URL`** and **`CORS_ORIGINS`** on the API.

---

## Common mistakes (empty site, full build)

| Mistake | Symptom | Fix |
|--------|---------|-----|
| Wrong Blob layout (e.g. only `output/*.parquet` at root) | `degraded`, empty formats | Upload **`output/<format>/…`** per `blob_hydrate.py` |
| No **`BLOB_PARQUET_BASE_URL`** on Vercel | No hydrate; empty API | Set store origin; redeploy |
| **`VITE_API_URL`** still points at old external API | CORS / failed fetch | Remove for Vercel Services; redeploy |
| Split deploy: missing **`VITE_API_URL`** | Wrong API host | Set at Vite build time |
| Split deploy: missing **`CORS_ORIGINS`** | Browser blocks API | Add SPA origin on API |
| No data (no Blob, no volume) | `degraded` | Follow §2 or §3 |
| Wrong **`DATA_ROOT`** (volume) | `degraded` | Parent directory of **`output/mens_t20i`**, etc. |
| Stale Parquet | Old stats | Re-upload Blob and/or new deployment / restart |

---

## After publishing: refreshing data

1. Regenerate **`data/output/…`** locally (or in CI).
2. **Vercel + Blob:** **`npm run upload:blob`** again; redeploy or rely on new invocations (use **`BLOB_CACHE_CLEAR`** in `blob_hydrate.py` if you need a clean cache).
3. **Volume / long-lived API:** replace files on disk and **restart** the process.

---

## Further reading

- [DEPLOYMENT.md](DEPLOYMENT.md) — Vercel Services, Blob env, troubleshooting.
- [vercel.env.example](vercel.env.example) — dashboard variable names.
- [scripts/sync_cricsheet.sh](scripts/sync_cricsheet.sh) — Cricsheet → `data/output/` slices.
- `gui/backend/.env.example` — local `DATA_ROOT` / `OUTPUT_DIR` / `CORS_ORIGINS`.
