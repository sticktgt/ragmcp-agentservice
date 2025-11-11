# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \    
    curl ca-certificates tini \ 
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app/agentservice

# Install deps
COPY requirements.txt ./requirements.txt
RUN python -m pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

COPY . .

# Non-root
RUN adduser --disabled-password --gecos "" appuser
USER appuser

ENV RS__SERVER__HOST=0.0.0.0
ENV RS__SERVER__PORT=2024
EXPOSE 2024

# Healthcheck against LangGraph server docs endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS "http://127.0.0.1:${RS__SERVER__PORT}/docs" >/dev/null || exit 1

ENTRYPOINT ["/usr/bin/tini","--"]
CMD ["sh","-lc","langgraph dev --host ${RS__SERVER__HOST:-0.0.0.0} --port ${RS__SERVER__PORT:-2024}"]
