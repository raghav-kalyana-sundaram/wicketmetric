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
RUN npm install -g serve@14

# Copy built assets from the build stage
COPY --from=build /app/dist ./dist

EXPOSE 3000

# Serve the built frontend on port 3000
# -s flag enables single-page application mode (rewrites to index.html)
CMD ["serve", "-s", "dist", "-l", "3000"]
