# --- Stage 1: build the React frontend ---
FROM node:22-alpine AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


# --- Stage 2: the Python app ---
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# torch needs libgomp at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    HF_HOME=/models

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-cache

COPY app/ app/
COPY scripts/ scripts/
COPY --from=frontend /build/dist frontend/dist

# Bake the model in: no download at startup. This repo ships PyTorch weights plus
# an ONNX copy of the same size, and we only use the PyTorch ones.
RUN uv run python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-m3', ignore_patterns=['onnx/*', 'imgs/*', '*.jpg'])"
ENV HF_HUB_OFFLINE=1

ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uv run uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
