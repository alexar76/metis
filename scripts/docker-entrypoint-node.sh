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

NODE_ID="${NODE_ID:-local-node}"
CONFIG="${METIS_NODE_CONFIG:-/app/config/docker-node.yaml}"
HOST="${METIS_NODE_HOST:-0.0.0.0}"
PORT="${METIS_NODE_PORT:-8443}"

if [ -n "${OLLAMA_BASE_URL:-}" ]; then
  export METIS_BASE_URL="$OLLAMA_BASE_URL"
fi

if [ ! -f "$CONFIG" ]; then
  echo "ERROR: node config not found: $CONFIG" >&2
  exit 1
fi

# Wait for Ollama when using local-models profile.
if [ -n "${OLLAMA_HOST:-}" ]; then
  echo "Waiting for Ollama at ${OLLAMA_HOST}..."
  i=0
  while [ "$i" -lt 60 ]; do
    if wget -q -O /dev/null "http://${OLLAMA_HOST}/api/tags" 2>/dev/null; then
      echo "Ollama is ready"
      break
    fi
    i=$((i + 1))
    sleep 2
  done
fi

echo "Starting node ${NODE_ID} on ${HOST}:${PORT} (config=${CONFIG})"
exec metis-node \
  --config "$CONFIG" \
  --host "$HOST" \
  --port "$PORT" \
  --node-id "$NODE_ID" \
  --production
