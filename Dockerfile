# Dockerfile
FROM python:3.12-slim

# System deps for pydub/ffmpeg + pyaudio + sounddevice + voice pipeline
RUN apt-get update && apt-get install -y \
    ffmpeg \
    portaudio19-dev \
    libsndfile1 \
    build-essential \
    python3-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (layer cache)
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev 2>/dev/null || uv sync --no-dev

# Copy source
COPY . .

ENV PYTHONUNBUFFERED=1

# Healthcheck — verifies the process is listening on the web port
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8090/health')" \
    || exit 1

# Entrypoint script waits for HelixDB before starting Raven
COPY <<"ENTRYPOINT" /usr/local/bin/docker-entrypoint.sh
#!/bin/sh
set -e

# Wait for HelixDB if HELIX_URL is set
if [ -n "${HELIX_URL:-}" ]; then
    echo "Waiting for HelixDB at $HELIX_URL..."
    until curl -fsS "$HELIX_URL/health" 2>/dev/null; do
        sleep 2
    done
    echo "HelixDB is ready."
fi

exec uv run python main.py "$@"
ENTRYPOINT

RUN chmod +x /usr/local/bin/docker-entrypoint.sh
ENTRYPOINT ["docker-entrypoint.sh"]
CMD []
