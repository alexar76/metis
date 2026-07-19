#!/bin/sh
set -eu

# Map legacy COGNITIVE_* and SUPERBRAIN_* env vars to METIS_* for backward compatibility.
for var in $(env | cut -d= -f1 | grep -E '^(COGNITIVE_|SUPERBRAIN_)' || true); do
  metis_var=$(echo "$var" | sed -e 's/^COGNITIVE_/METIS_/' -e 's/^SUPERBRAIN_/METIS_/')
  eval "val=\$$var"
  if [ -z "$(eval "echo \$$metis_var")" ]; then
    export "$metis_var=$val"
  fi
done

export METIS_PRODUCTION="${METIS_PRODUCTION:-true}"
export PYTHONUNBUFFERED=1

CONFIG="${METIS_CONFIG:-/app/config/docker-runtime.yaml}"
CLUSTER="${METIS_CLUSTER_CONFIG:-/app/config/docker-cluster.yaml}"
HOST="${METIS_COORDINATOR_HOST:-0.0.0.0}"
PORT="${METIS_COORDINATOR_PORT:-8080}"

if [ ! -f "$CONFIG" ]; then
  echo "ERROR: config not found: $CONFIG" >&2
  exit 1
fi

if [ ! -f "$CLUSTER" ]; then
  echo "ERROR: cluster config not found: $CLUSTER" >&2
  exit 1
fi

if [ "$METIS_PRODUCTION" = "true" ] && [ -z "${METIS_API_KEY:-}" ]; then
  echo "ERROR: METIS_API_KEY (or SUPERBRAIN_API_KEY / COGNITIVE_API_KEY) required in production" >&2
  exit 1
fi

echo "Starting coordinator on ${HOST}:${PORT} (config=${CONFIG})"
exec metis-coordinator \
  --config "$CONFIG" \
  --cluster "$CLUSTER" \
  --host "$HOST" \
  --port "$PORT" \
  --production
