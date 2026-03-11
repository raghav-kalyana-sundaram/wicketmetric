# ── Stage 1: Build ────────────────────────────────────────────────
FROM node:18-alpine AS build

WORKDIR /app

# Install dependencies first (better layer caching)
COPY package.json package-lock.json ./
RUN npm ci

# Copy source and build
COPY . .

# Allow the API URL to be set at build time
ARG VITE_API_URL=http://localhost:8000
ENV VITE_API_URL=${VITE_API_URL}

RUN npm run build

# ── Stage 2: Serve ────────────────────────────────────────────────
FROM node:18-alpine AS runtime

WORKDIR /app

# Install a lightweight static file server
# Pin to v13 for stable, simple CLI flag support (-s, -p)
RUN npm install -g serve@13

# Copy built assets from the build stage
COPY --from=build /app/dist ./dist

# Railway injects $PORT dynamically; default to 3000 for local use
ENV PORT=3000
EXPOSE ${PORT}

# Serve the built frontend
# -s flag enables single-page application mode (rewrites to index.html)
# -p flag sets the port (works reliably in serve@13)
CMD serve -s dist -p ${PORT}
