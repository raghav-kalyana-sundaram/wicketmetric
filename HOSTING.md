# Hosting Cricket Metrics Online

This guide covers every way to get Cricket Metrics running on the internet — from the simplest free option to a production-ready setup.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Before You Start](#2-before-you-start)
3. [Option A: Railway (Easiest — Recommended)](#3-option-a-railway)
4. [Option B: Render](#4-option-b-render)
5. [Option C: Fly.io](#5-option-c-flyio)
6. [Option D: VPS (DigitalOcean / Hetzner / Linode)](#6-option-d-vps)
7. [Option E: Docker Compose on Any Server](#7-option-e-docker-compose)
8. [Option F: Vercel (Frontend) + Railway (Backend)](#8-option-f-split-deployment)
9. [Custom Domain & HTTPS](#9-custom-domain--https)
10. [Troubleshooting](#10-troubleshooting)
11. [Cost Comparison](#11-cost-comparison)

---

## 1. Architecture Overview

Cricket Metrics has two parts:

```
┌─────────────────────┐         ┌──────────────────────────────┐
│   Frontend (React)  │  ──→    │   Backend (FastAPI + Python)  │
│   Static HTML/JS/CSS│  /api/* │   Loads Parquet data into RAM │
│   ~5 MB built       │         │   ~360 MB memory at runtime   │
└─────────────────────┘         └──────────────────────────────┘
                                          ▲
                                          │ reads at startup
                                ┌─────────┴──────────┐
                                │  output_t20i/ (32 MB)│
                                │  output_ipl/  (13 MB)│
                                │  Parquet data files   │
                                └──────────────────────┘
```

**Key facts for hosting decisions:**

| Concern | Detail |
|---|---|
| Backend language | Python 3.12+ (FastAPI + uvicorn) |
| Frontend | Static files (React, built with Vite) |
| Database | **None** — all data is read from Parquet files into memory at startup |
| Data size on disk | ~45 MB total (T20I + IPL) |
| Backend RAM usage | ~360 MB with both formats loaded |
| Backend startup time | ~1–3 seconds |
| Backend CPU | Negligible after startup (serves from memory) |
| Frontend build size | ~5 MB |
| API is read-only | Yes — no writes, no user accounts, no auth |

---

## 2. Before You Start

### 2.1 Initialise a Git Repository

Every hosting platform deploys from Git. If you haven't already:

```bash
cd cricket_metrics

# Create .gitignore first
cat > .gitignore << 'EOF'
# Python
__pycache__/
*.pyc
.venv/
*.egg-info/

# Node
node_modules/
gui/frontend/dist/

# Data sources (raw JSON — too large for git)
t20s_male_json/
ipl_json/

# IDE
.vscode/
.idea/
*.swp

# OS
.DS_Store
Thumbs.db

# Legacy output dir
output/
EOF

git init
git add .
git commit -m "Initial commit"
```

### 2.2 Include the Parquet Data in the Repo

The Parquet output files (~45 MB) **must** be accessible to the backend at runtime.
They're small enough to commit directly to Git:

```bash
# Make sure both output directories are tracked
git add output_t20i/ output_ipl/
git commit -m "Add pipeline output data"
```

> **Note:** If you later regenerate the data by re-running the pipeline,
> commit the updated Parquet files again.

### 2.3 Push to GitHub

```bash
# Create a repo on GitHub (public or private), then:
git remote add origin https://github.com/YOUR_USERNAME/cricket_metrics.git
git branch -M main
git push -u origin main
```

---

## 3. Option A: Railway

**Best for:** Getting online in 10 minutes with minimal config.

**Cost:** Free tier gives $5/month credit (enough for light traffic). Hobby plan is $5/month.

### Step 1: Sign up

Go to [railway.app](https://railway.app) and sign in with GitHub.

### Step 2: Create a new project

Click **"New Project"** → **"Deploy from GitHub Repo"** → select your `cricket_metrics` repo.

### Step 3: Configure the Backend service

Railway auto-detects the repo but you need to tell it where the backend lives:

1. Click on the service → **Settings**
2. Set **Root Directory** to `gui/backend`
3. Set **Build Command**: `pip install -r requirements.txt`
4. Set **Start Command**: `uvicorn app:app --host 0.0.0.0 --port $PORT`
5. Add these **Environment Variables**:

| Variable | Value |
|---|---|
| `PORT` | `8000` |
| `HOST` | `0.0.0.0` |

> **Do NOT set `OUTPUT_DIR`.** The backend auto-discovers `output_t20i/` and
> `output_ipl/` relative to the project root. Railway clones the full repo,
> so the directories will be at `../../output_t20i/` and `../../output_ipl/`
> relative to `gui/backend/`, which is exactly where the backend expects them.

6. Under **Networking**, click **"Generate Domain"** to get a public URL (e.g. `cricket-metrics-backend-production.up.railway.app`).

### Step 4: Add the Frontend service

1. In the same project, click **"New"** → **"GitHub Repo"** → select the same repo again.
2. Set **Root Directory** to `gui/frontend`
3. Set **Build Command**: `npm ci && npm run build`
4. Set **Start Command**: `npx serve -s dist -l $PORT`
5. Add these **Environment Variables**:

| Variable | Value |
|---|---|
| `VITE_API_URL` | `https://YOUR-BACKEND-DOMAIN.up.railway.app` |

Use the backend domain from Step 3.6.

6. Generate a domain for the frontend too.

### Step 5: Update CORS

The backend needs to allow requests from your frontend domain. Edit `gui/backend/app.py` and add your Railway frontend URL to the `allow_origins` list:

```python
allow_origins=[
    "http://localhost:3000",
    "http://localhost:5173",
    # ... existing entries ...
    "https://YOUR-FRONTEND-DOMAIN.up.railway.app",  # ← add this
],
```

Commit, push, and Railway will auto-redeploy.

### Step 6: Verify

Visit your frontend URL. You should see the Cricket Metrics homepage with data loading.

---

## 4. Option B: Render

**Best for:** Free tier with slightly more generous limits than Railway.

**Cost:** Free tier (backend sleeps after 15 min of inactivity, ~30s cold start). Paid starts at $7/month.

### Step 1: Create a Render account

Go to [render.com](https://render.com) and connect your GitHub account.

### Step 2: Deploy the Backend as a Web Service

1. Click **"New"** → **"Web Service"**
2. Connect your GitHub repo
3. Configure:

| Setting | Value |
|---|---|
| **Name** | `cricket-metrics-api` |
| **Root Directory** | `gui/backend` |
| **Runtime** | Python 3 |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `uvicorn app:app --host 0.0.0.0 --port $PORT` |
| **Instance Type** | Free (or Starter $7/mo for always-on) |

4. Add environment variable: `PYTHON_VERSION` = `3.12.0`

> **Do NOT set `OUTPUT_DIR`.**

5. Click **Deploy**. Note the URL (e.g. `https://cricket-metrics-api.onrender.com`).

### Step 3: Deploy the Frontend as a Static Site

1. Click **"New"** → **"Static Site"**
2. Connect the same repo
3. Configure:

| Setting | Value |
|---|---|
| **Name** | `cricket-metrics` |
| **Root Directory** | `gui/frontend` |
| **Build Command** | `npm ci && npm run build` |
| **Publish Directory** | `dist` |

4. Add environment variable: `VITE_API_URL` = `https://cricket-metrics-api.onrender.com`

5. Click **Deploy**.

### Step 4: Update CORS

Same as Railway — add your Render frontend URL to `allow_origins` in `app.py`.

> **Free tier caveat:** The backend spins down after 15 minutes of inactivity.
> First visit after a sleep period will take ~30 seconds. Upgrade to Starter ($7/mo)
> for always-on.

---

## 5. Option C: Fly.io

**Best for:** Low latency globally (edge deployment), generous free tier.

**Cost:** Free tier includes 3 shared-cpu VMs with 256 MB RAM each. You'll need the $5/mo plan for the 512 MB+ RAM the backend needs.

### Step 1: Install the Fly CLI

```bash
# macOS
brew install flyctl

# or curl
curl -L https://fly.io/install.sh | sh
```

Sign up / log in:
```bash
fly auth signup   # or: fly auth login
```

### Step 2: Deploy the Backend

```bash
cd gui/backend

# Initialise (choose a region close to your users)
fly launch --name cricket-metrics-api --region sin --no-deploy

# Set the VM size (need at least 512 MB RAM)
fly scale vm shared-cpu-1x --memory 512

# Deploy
fly deploy
```

This uses the existing `gui/backend/Dockerfile`. But you need the data files inside the container. Create a new Dockerfile that copies them:

```dockerfile
# gui/backend/Dockerfile.fly
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Copy output data (paths relative to build context)
COPY ../../output_t20i /data/output_t20i
COPY ../../output_ipl /data/output_ipl

# Do NOT set OUTPUT_DIR — let the app auto-discover.
# But we need to adjust the project root. Easier to just set it:
ENV PYTHONPATH=/app
ENV HOST=0.0.0.0

EXPOSE 8080

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
```

> **Alternative (simpler):** Instead of a custom Dockerfile, just deploy the full repo
> from the project root and set the build context accordingly in `fly.toml`.

### Step 3: Deploy the Frontend

The simplest approach: build locally and deploy the static files:

```bash
cd gui/frontend
VITE_API_URL=https://cricket-metrics-api.fly.dev npm run build
fly launch --name cricket-metrics --region sin
fly deploy
```

Or use the frontend Dockerfile and set `VITE_API_URL` as a build arg.

### Step 4: Update CORS

Add `https://cricket-metrics.fly.dev` to `allow_origins`.

---

## 6. Option D: VPS

**Best for:** Full control, cheapest for always-on hosting, best performance.

**Cost:** $4–6/month (DigitalOcean, Hetzner, Linode — 1 vCPU, 1 GB RAM).

This is the most hands-on option but gives you the most control and best price-to-performance.

### Step 1: Provision a server

Choose any VPS provider:
- **Hetzner** (cheapest): €3.29/mo for 2 vCPU, 2 GB RAM — [hetzner.com/cloud](https://www.hetzner.com/cloud)
- **DigitalOcean**: $6/mo for 1 vCPU, 1 GB RAM — [digitalocean.com](https://www.digitalocean.com)
- **Linode/Akamai**: $5/mo for 1 vCPU, 1 GB RAM — [linode.com](https://www.linode.com)

Choose **Ubuntu 22.04 or 24.04**. Pick a region close to your audience.

> **RAM:** The backend uses ~360 MB. A 1 GB server works but is tight.
> 2 GB is more comfortable and allows room for the OS + nginx.

### Step 2: SSH in and install dependencies

```bash
ssh root@YOUR_SERVER_IP

# Update system
apt update && apt upgrade -y

# Install Python 3.12+, Node.js, nginx, git
apt install -y python3 python3-pip python3-venv nodejs npm nginx git

# Install certbot for HTTPS (optional, for custom domains)
apt install -y certbot python3-certbot-nginx
```

### Step 3: Clone your repo

```bash
cd /opt
git clone https://github.com/YOUR_USERNAME/cricket_metrics.git
cd cricket_metrics
```

### Step 4: Set up the Backend

```bash
cd /opt/cricket_metrics/gui/backend

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Test that it starts
unset OUTPUT_DIR
python app.py
# You should see "Available formats: ['t20i', 'ipl']"
# Ctrl+C to stop
```

Create a systemd service so it runs permanently:

```bash
cat > /etc/systemd/system/cricket-metrics-api.service << 'EOF'
[Unit]
Description=Cricket Metrics API
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/cricket_metrics/gui/backend
Environment="PATH=/opt/cricket_metrics/gui/backend/.venv/bin:/usr/bin"
ExecStart=/opt/cricket_metrics/gui/backend/.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000 --workers 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable cricket-metrics-api
systemctl start cricket-metrics-api

# Check it's running
systemctl status cricket-metrics-api
curl http://localhost:8000/api/health
```

### Step 5: Build the Frontend

```bash
cd /opt/cricket_metrics/gui/frontend

# Install Node dependencies and build
npm ci
# VITE_API_URL is left empty so the frontend uses the same origin (/api/...)
npm run build

# The built files are now in /opt/cricket_metrics/gui/frontend/dist/
```

### Step 6: Configure nginx

nginx serves the static frontend and reverse-proxies `/api` requests to the backend:

```bash
cat > /etc/nginx/sites-available/cricket-metrics << 'EOF'
server {
    listen 80;
    server_name YOUR_DOMAIN_OR_IP;

    # Frontend — static files
    root /opt/cricket_metrics/gui/frontend/dist;
    index index.html;

    # SPA routing: serve index.html for all non-file routes
    location / {
        try_files $uri $uri/ /index.html;
    }

    # API — reverse proxy to FastAPI backend
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Timeouts (the backend is fast, but startup can take a moment)
        proxy_connect_timeout 10s;
        proxy_read_timeout 30s;
    }

    # Cache static assets aggressively
    location /assets/ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # Gzip
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml;
    gzip_min_length 1000;
}
EOF

# Enable the site
ln -sf /etc/nginx/sites-available/cricket-metrics /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# Test and reload
nginx -t
systemctl reload nginx
```

Visit `http://YOUR_SERVER_IP` — the site should be live.

### Step 7: Add HTTPS (if you have a domain)

```bash
certbot --nginx -d yourdomain.com -d www.yourdomain.com
```

Certbot will auto-configure nginx for HTTPS and set up auto-renewal.

### Updating the site

```bash
cd /opt/cricket_metrics
git pull

# Rebuild frontend (if frontend changed)
cd gui/frontend && npm ci && npm run build

# Restart backend (if backend or data changed)
sudo systemctl restart cricket-metrics-api
```

---

## 7. Option E: Docker Compose

**Best for:** Deploying on any server that has Docker installed.

The repo already includes a `docker-compose.yml`. It needs a small update to support multi-format data:

### Step 1: Update docker-compose.yml

Edit `gui/docker-compose.yml`:

```yaml
version: "3.9"

services:
  backend:
    build: ./backend
    ports:
      - "8000:8000"
    volumes:
      - ../output_t20i:/app/output_t20i:ro
      - ../output_ipl:/app/output_ipl:ro
    environment:
      # Do NOT set OUTPUT_DIR — let the backend auto-discover formats
      - HOST=0.0.0.0
      - PORT=8000
    command: uvicorn app:app --host 0.0.0.0 --port 8000
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 30s

  frontend:
    build:
      context: ./frontend
      args:
        VITE_API_URL: http://localhost:8000
    ports:
      - "3000:3000"
    depends_on:
      backend:
        condition: service_healthy
```

> **Important:** The `OUTPUT_DIR` env var is removed so the backend uses `load_all_data()`
> to auto-discover both T20I and IPL. The data directories are volume-mounted into `/app/`.
>
> You will also need to update `data_loader.py`'s `_PROJECT_ROOT` logic to handle
> the Docker layout, or simply set the volumes to mount at the expected relative paths.

### Step 2: Update the backend Dockerfile

```dockerfile
# gui/backend/Dockerfile
FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV HOST=0.0.0.0
ENV PORT=8000

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Step 3: Build and run

```bash
cd gui
docker compose up --build -d

# Check logs
docker compose logs -f backend
# Should show "Available formats: ['t20i', 'ipl']"
```

The frontend will be on `http://localhost:3000` and the API on `http://localhost:8000`.

### Step 4: Put nginx in front (for production)

On the host machine, configure nginx to reverse-proxy to both containers, add HTTPS, etc. Same as the VPS nginx config in Option D but proxying to the container ports.

---

## 8. Option F: Split Deployment

**Best for:** Free hosting by using Vercel (free) for the static frontend and a cheap backend elsewhere.

Since the frontend is just static files, you can host it for free on **Vercel**, **Netlify**, or **Cloudflare Pages**. The backend still needs a server.

### Frontend on Vercel (free)

1. Go to [vercel.com](https://vercel.com) and import your GitHub repo.
2. Configure:

| Setting | Value |
|---|---|
| **Framework Preset** | Vite |
| **Root Directory** | `gui/frontend` |
| **Build Command** | `npm run build` |
| **Output Directory** | `dist` |

3. Add environment variable: `VITE_API_URL` = `https://your-backend-url.com`

4. Deploy.

5. Vercel gives you a URL like `https://cricket-metrics.vercel.app`.

### Frontend on Cloudflare Pages (free)

1. Go to [pages.cloudflare.com](https://pages.cloudflare.com) and connect your repo.
2. Set root directory to `gui/frontend`, build command `npm run build`, output `dist`.
3. Add environment variable `VITE_API_URL`.

### Backend — use Railway, Render, or a VPS

Follow one of the backend-only sections from Options A–D above.

### Update CORS

Add your Vercel/Cloudflare frontend URL to `allow_origins` in `app.py`.

---

## 9. Custom Domain & HTTPS

### On Railway / Render / Fly.io

All three platforms support custom domains from their dashboard:
1. Add your domain in the service settings
2. Point your DNS (CNAME record) to the provided target
3. HTTPS is automatic via Let's Encrypt

### On a VPS

Use Certbot (covered in Option D, Step 7).

### DNS Configuration

Wherever your registrar is (Namecheap, Cloudflare, Google Domains, etc.):

| Record Type | Name | Value |
|---|---|---|
| `CNAME` | `@` or `www` | Your platform's provided domain |
| `A` | `@` | Your VPS IP address (for VPS option) |

If using a split deployment:

| Record Type | Name | Value |
|---|---|---|
| `CNAME` | `@` | Points to frontend host (Vercel, Cloudflare) |
| `CNAME` | `api` | Points to backend host (Railway, Render, VPS) |

Then set `VITE_API_URL=https://api.yourdomain.com`.

---

## 10. Troubleshooting

### "Available formats: ['t20i']" — IPL missing

**Cause:** `OUTPUT_DIR` is set in the environment, forcing single-format mode.

**Fix:** Do NOT set `OUTPUT_DIR`. The backend auto-discovers `output_t20i/` and `output_ipl/` when `OUTPUT_DIR` is unset.

If deploying with Docker volumes, make sure the data directories are mounted where `_PROJECT_ROOT / "output_ipl"` resolves to.

### Backend crashes with "Killed" or OOM

**Cause:** Not enough RAM. The backend needs ~360 MB.

**Fix:** Use a server/plan with at least 512 MB RAM (1 GB recommended).

### CORS errors in the browser console

**Cause:** The frontend URL isn't in the backend's `allow_origins` list.

**Fix:** Add your deployed frontend URL to `allow_origins` in `gui/backend/app.py`:
```python
allow_origins=[
    # ... existing entries ...
    "https://your-frontend-domain.com",
],
```

For maximum flexibility during initial deployment, you can temporarily use:
```python
allow_origins=["*"],
```
Then lock it down once everything works.

### Frontend shows "Failed to load" / API unreachable

1. Check the browser's Network tab — are requests going to the right backend URL?
2. Is `VITE_API_URL` set correctly? (It's baked in at **build time**, not runtime.)
3. Is the backend actually running? Try `curl https://your-backend-url/api/health`.

### Form Tracker shows flat line at 0

**Cause:** The backend loaded stale Parquet files (from before the form tracker overhaul).

**Fix:** Make sure the committed `output_t20i/bowling_form_series.parquet` and
`output_t20i/batting_form_series.parquet` are the regenerated versions (with
`window_composite` values in the 0–100 range, not 0–1). Restart the backend.

### Render free tier: 30-second cold start

This is normal — the free tier spins down after 15 minutes of inactivity.
Upgrade to the Starter plan ($7/month) for always-on.

You can also add a cron job / uptime monitor (e.g. UptimeRobot, free) that
pings `/api/health` every 14 minutes to keep the service warm.

---

## 11. Cost Comparison

| Option | Monthly Cost | Always On? | Setup Difficulty | Notes |
|---|---|---|---|---|
| **Railway** (free tier) | $0 (up to $5 credit) | Yes | ⭐ Easy | Best starting point |
| **Railway** (Hobby) | $5 | Yes | ⭐ Easy | Reliable, simple |
| **Render** (free tier) | $0 | No (sleeps) | ⭐ Easy | 30s cold starts |
| **Render** (Starter) | $7 | Yes | ⭐ Easy | |
| **Fly.io** | $0–5 | Yes | ⭐⭐ Medium | Need 512MB+ VM |
| **Hetzner VPS** | €3.29 (~$4) | Yes | ⭐⭐⭐ Hands-on | Best value, full control |
| **DigitalOcean VPS** | $6 | Yes | ⭐⭐⭐ Hands-on | Good docs, full control |
| **Vercel + Railway** | $0–5 | Mostly | ⭐⭐ Medium | Free frontend, paid backend |
| **Cloudflare + VPS** | ~$4 | Yes | ⭐⭐⭐ Hands-on | Free CDN + cheap backend |

### My Recommendation

- **Just want it online fast?** → [Railway](#3-option-a-railway) (Option A)
- **Want it free?** → [Render free tier](#4-option-b-render) (Option B) — accept the cold starts
- **Want the cheapest always-on?** → [Hetzner VPS](#6-option-d-vps) (Option D) at €3.29/mo
- **Want the best of both worlds?** → [Vercel + Railway](#8-option-f-split-deployment) (Option F) — free frontend, $5/mo backend

---

## Quick Reference: Deploy to Railway in 5 Minutes

```bash
# 1. Initialise git and push to GitHub
cd cricket_metrics
git init
echo -e "__pycache__/\n*.pyc\n.venv/\nnode_modules/\nt20s_male_json/\nipl_json/\noutput/\n.DS_Store" > .gitignore
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOU/cricket_metrics.git
git push -u origin main

# 2. Go to railway.app → New Project → Deploy from GitHub
#    - Backend service: root=gui/backend, start=uvicorn app:app --host 0.0.0.0 --port $PORT
#    - Frontend service: root=gui/frontend, build=npm ci && npm run build, start=npx serve -s dist -l $PORT
#    - Set VITE_API_URL on frontend to backend's Railway URL
#    - Add frontend Railway URL to allow_origins in app.py, push

# 3. Done. Visit your frontend Railway URL.
```
