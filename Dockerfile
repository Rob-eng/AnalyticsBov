# ── Estágio 1: compila a plataforma web (React + Vite) ───────────────────────
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund --omit=optional || npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ── Estágio 2: API + bots (Python) ────────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# Copy application code
COPY . .
# Site compilado (servido pelo FastAPI em /app)
COPY --from=web /web/dist /app/web/dist

# Set environment variables
ENV PYTHONPATH=/app

# Run the application (Bot + API)
CMD ["python", "run_all.py"]
