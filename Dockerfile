# Dockerfile
FROM python:3.12-slim

# System deps for pydub/ffmpeg + pyaudio + sounddevice
RUN apt-get update && apt-get install -y \
    ffmpeg \
    portaudio19-dev \
    libsndfile1 \
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
CMD ["uv", "run", "python", "main.py"]
