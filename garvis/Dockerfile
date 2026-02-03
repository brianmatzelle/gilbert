# Garvis Discord Voice Assistant - Dockerfile
# Multi-stage build for optimized image size
#
# Usage:
#   docker build -t garvis .
#   docker run --env-file .env garvis

# =============================================================================
# Stage 1: Builder - Install dependencies
# =============================================================================
FROM python:3.12-slim AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast Python package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set up working directory
WORKDIR /app

# Copy dependency files first for better caching
COPY server/pyproject.toml server/uv.lock ./server/

# Install Python dependencies
# Using CPU-only PyTorch by default (smaller image, cloud mode)
ENV UV_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cpu
WORKDIR /app/server
RUN uv sync --frozen --no-dev

# =============================================================================
# Stage 2: Runtime - Final image
# =============================================================================
FROM python:3.12-slim AS runtime

# Install runtime dependencies
# - ffmpeg: audio conversion (required by pydub)
# - libopus0: Discord voice (required by py-cord)
# - libsodium23: Discord voice encryption (required by PyNaCl)
# - curl: health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libopus0 \
    libsodium23 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash garvis
USER garvis

# Set up working directory
WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder --chown=garvis:garvis /app/server/.venv /app/server/.venv

# Copy application code
COPY --chown=garvis:garvis server/ /app/server/
COPY --chown=garvis:garvis openclaw/ /app/openclaw/

# Set environment variables
ENV PATH="/app/server/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Bot API port (for OpenClaw integration)
EXPOSE 8765

# Health check - uses the bot API status endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8765/api/status || exit 1

# Working directory for running the bot
WORKDIR /app/server

# Default command - run the Discord bot
CMD ["python", "-m", "discord_bot.bot"]
