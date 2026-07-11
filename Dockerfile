# syntax=docker/dockerfile:1

FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY metis ./metis

RUN pip install --no-cache-dir --upgrade pip \
    && pip wheel --no-cache-dir --wheel-dir /wheels ".[distributed]"

# -----------------------------------------------------------------------------

FROM python:3.11-slim AS runtime

LABEL org.opencontainers.image.title="metis" \
      org.opencontainers.image.description="Multi-agent reasoning orchestrator" \
      org.opencontainers.image.source="https://github.com/metis/metis"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    METIS_PRODUCTION=true \
    METIS_LOG_LEVEL=INFO \
    METIS_LOG_FORMAT=json \
    METIS_LOG_CONTENT=redacted \
    PATH="/app/.local/bin:$PATH"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 metis \
    && useradd --uid 1000 --gid metis --create-home --shell /usr/sbin/nologin metis

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/* \
    && rm -rf /wheels

COPY metis ./metis
COPY config ./config
COPY scripts/docker-entrypoint-coordinator.sh scripts/docker-entrypoint-node.sh ./scripts/
RUN chmod +x ./scripts/docker-entrypoint-*.sh \
    && mkdir -p /data/memory /data/config /data/logs /data/traces \
    && chown -R metis:metis /app /data

USER metis

EXPOSE 8080 8443 8444

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -sf http://127.0.0.1:${METIS_COORDINATOR_PORT:-8080}/health \
    || curl -sf http://127.0.0.1:${METIS_NODE_PORT:-8443}/metis/health \
       -H "Authorization: Bearer ${METIS_NODE_A_KEY:-${METIS_NODE_B_KEY:-}}" \
    || exit 1

# Default CMD overridden per service in compose
CMD ["metis-coordinator", "--production"]
