# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \    
    curl ca-certificates tini \ 
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

FROM base AS deps
COPY requirements.txt ./
RUN python -m pip install --upgrade pip \ 
  && pip install --no-cache-dir -r requirements.txt

FROM base AS runtime
RUN adduser --disabled-password --gecos "" appuser
USER appuser
WORKDIR /app

COPY --from=deps /usr/local/lib/python3.12 /usr/local/lib/python3.12
COPY --from=deps /usr/local/bin /usr/local/bin

COPY . ./agentservice
# COPY config.yaml ./config.yaml
# COPY entrypoint.sh ./entrypoint.sh

EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -fsS http://localhost:8081/healthz || exit 1

ENTRYPOINT ["/usr/bin/tini","--"]
# CMD ["bash","/app/entrypoint.sh"]
CMD ["python", "-m", "agentservice.main"]
