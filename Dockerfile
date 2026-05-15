# ---- build stage: install deps + pre-download models -----------------------
FROM python:3.12-slim AS builder

WORKDIR /app

# Install uv for fast Python package management
RUN pip install --no-cache-dir uv

# Install system dependencies needed for building Python packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy dependency definitions first (better Docker layer caching)
COPY pyproject.toml ./
COPY src/ ./src/

# Install dependencies in system Python
RUN uv pip install --system -e "."

# Pre-download Docling models and FlashRank model during build
# This avoids 1-2 minute cold-start penalty on HF Spaces
ENV HF_HUB_DISABLE_SYMLINKS=1
ENV HF_HOME=/app/.cache/huggingface
ENV FLASHRANK_HOME=/app/.cache/flashrank
COPY scripts/preload_models.py ./scripts/
RUN python scripts/preload_models.py

# ---- production stage: lean runtime image ----------------------------------
FROM python:3.12-slim

WORKDIR /app

# Install only runtime system deps (no build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy pre-downloaded model caches
COPY --from=builder /app/.cache /app/.cache

# Copy application code
COPY app.py ./
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY ARCHITECTURE.md ./
COPY PROJECT_PLAN.md ./
COPY README.md ./

# HF Spaces uses port 7860 by default
EXPOSE 7860

# Set environment for production
ENV PYTHONUNBUFFERED=1
ENV HF_HUB_DISABLE_SYMLINKS=1
ENV GRADIO_SERVER_NAME=0.0.0.0
ENV GRADIO_SERVER_PORT=7860

# Health check for HF Spaces (checks every 30s, 3 retries)
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7860')" || exit 1

# Run the Gradio app
CMD ["python", "app.py"]
