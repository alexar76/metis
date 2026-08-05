#!/usr/bin/env bash
# Run ON metis — build & start SKOPOS test stack (Postgres + dashboard).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${SKOPOS_APP_DIR:-/opt/skopos-test/app}"
ENV_FILE="${ROOT}/.env"

log() { echo "[skopos-test] $*"; }

if [[ ! -d "${APP_DIR}" ]]; then
  echo "Missing app dir ${APP_DIR}. Run remote-sync.sh from your laptop first." >&2
  exit 1
fi

# Agent-push fleet: SKOPOS never SSHes out. Do not plant probe keys on hosts.
SSH_DIR="${ROOT}/ssh"
if [[ -d "${SSH_DIR}" ]]; then
  log "Note: ${SSH_DIR} exists but is unused (agent-push only; not mounted)."
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  log "Creating .env from example with generated passwords…"
  cp "${ROOT}/.env.example" "${ENV_FILE}"
  DASH_PW="$(openssl rand -base64 24 | tr -d '/+=' | head -c 20)"
  PG_PW="$(openssl rand -base64 32 | tr -d '/+=' | head -c 28)"
  NODE_KEY="$(python3 -c 'import base64,os; print(base64.b64encode(os.urandom(32)).decode())')"
  AGENT_SECRET="$(openssl rand -hex 32)"
  if sed --version >/dev/null 2>&1; then
    sed -i "s/CHANGE_ME_DASHBOARD_PASSWORD/${DASH_PW}/" "${ENV_FILE}"
    sed -i "s/CHANGE_ME_POSTGRES_PASSWORD/${PG_PW}/g" "${ENV_FILE}"
    sed -i "s|^SKOPOS_NODE_SECRET_KEY=.*|SKOPOS_NODE_SECRET_KEY=${NODE_KEY}|" "${ENV_FILE}"
    sed -i "s|^SKOPOS_AGENT_TOKEN_SECRET=.*|SKOPOS_AGENT_TOKEN_SECRET=${AGENT_SECRET}|" "${ENV_FILE}"
  else
    sed -i '' "s/CHANGE_ME_DASHBOARD_PASSWORD/${DASH_PW}/" "${ENV_FILE}"
    sed -i '' "s/CHANGE_ME_POSTGRES_PASSWORD/${PG_PW}/g" "${ENV_FILE}"
    sed -i '' "s|^SKOPOS_NODE_SECRET_KEY=.*|SKOPOS_NODE_SECRET_KEY=${NODE_KEY}|" "${ENV_FILE}"
    sed -i '' "s|^SKOPOS_AGENT_TOKEN_SECRET=.*|SKOPOS_AGENT_TOKEN_SECRET=${AGENT_SECRET}|" "${ENV_FILE}"
  fi
  chmod 600 "${ENV_FILE}"
  log "Dashboard password written to ${ENV_FILE} (SKOPOS_DASHBOARD_PASSWORD)"
fi

# Ensure production fail-closed flags + sealing keys exist on upgrades.
ensure_env_default() {
  local key="$1" val="$2"
  if ! grep -q "^${key}=" "${ENV_FILE}" 2>/dev/null; then
    echo "${key}=${val}" >> "${ENV_FILE}"
  elif grep -q "^${key}=$" "${ENV_FILE}" 2>/dev/null || grep -q "^${key}=\s*$" "${ENV_FILE}" 2>/dev/null; then
    if sed --version >/dev/null 2>&1; then
      sed -i "s|^${key}=.*|${key}=${val}|" "${ENV_FILE}"
    else
      sed -i '' "s|^${key}=.*|${key}=${val}|" "${ENV_FILE}"
    fi
  fi
}
ensure_env_default "SKOPOS_REQUIRE_DASHBOARD_AUTH" "1"
if ! grep -q "^SKOPOS_NODE_SECRET_KEY=.\+" "${ENV_FILE}" 2>/dev/null; then
  ensure_env_default "SKOPOS_NODE_SECRET_KEY" "$(python3 -c 'import base64,os; print(base64.b64encode(os.urandom(32)).decode())')"
fi
if ! grep -q "^SKOPOS_AGENT_TOKEN_SECRET=.\+" "${ENV_FILE}" 2>/dev/null; then
  ensure_env_default "SKOPOS_AGENT_TOKEN_SECRET" "$(openssl rand -hex 32)"
fi
ensure_env_default "SKOPOS_AGENT_CORS_ORIGINS" "https://skopos.modelmarket.dev"

GEOIP_DIR="${ROOT}/geoip"
mkdir -p "${GEOIP_DIR}"
if [[ -f "${ENV_FILE}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
  set +a
fi
if [[ -x "${APP_DIR}/scripts/install_geolite2_country.sh" ]]; then
  log "Ensuring GeoLite2-Country MMDB (offline country lookup)…"
  if bash "${APP_DIR}/scripts/install_geolite2_country.sh" "${GEOIP_DIR}/GeoLite2-Country.mmdb"; then
    log "GeoLite2 MMDB ready (MaxMind offline boost)"
  else
    log "GeoLite2 skipped — using free HTTP GeoIP (geojs.io + ipwho.is). MaxMind optional."
  fi
fi

export SKOPOS_APP_DIR="${APP_DIR}"
cd "${ROOT}"

log "Building SKOPOS image…"
docker compose build

log "Starting Postgres + SKOPOS…"
docker compose up -d

if [[ -x "${ROOT}/postgres-harden.sh" ]]; then
  log "Hardening PostgreSQL (pg_hba + grants)…"
  bash "${ROOT}/postgres-harden.sh" || log "Postgres hardening skipped (container not ready yet)"
fi

log "Removing stale SQLite artifacts from app dir (Postgres is canonical)…"
rm -f "${APP_DIR}"/skopos.sqlite3 "${APP_DIR}"/skopos.sqlite3-shm "${APP_DIR}"/skopos.sqlite3-wal 2>/dev/null || true

log "Waiting for Streamlit…"
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:8501/_stcore/health" >/dev/null 2>&1; then
    break
  fi
  sleep 2
done

log "Initial collect + security scan…"
docker compose exec -T skopos python skoposctl.py collect || true
docker compose exec -T skopos python skoposctl.py security-scan || true

log "LLM smoke (OpenRouter + DeepSeek briefing chain)…"
docker compose exec -T skopos python3 - <<'PY' || log "LLM smoke failed — check OPENROUTER/DEEPSEEK keys in ${ENV_FILE}"
from skopos.config import load_app_env
load_app_env()
from skopos.agent.config import load_agent_config
from skopos.agent.providers import ChatMessage, chat_completion_with_fallback
from skopos.agent.ecosystem_briefing import _briefing_attempt_chain

cfg = load_agent_config("/app/agent.yaml")
text, provider, model = chat_completion_with_fallback(
    cfg,
    [ChatMessage("user", "Reply with exactly: LLM_OK")],
    _briefing_attempt_chain(cfg),
    max_tokens=32,
)
assert "LLM_OK" in text.upper(), (provider, model, text)
print(f"LLM smoke OK via {provider}/{model}")
PY

log "Done."
echo ""
echo "  UI (on server):  http://127.0.0.1:8501"
echo "  SSH tunnel:      ssh -L 8501:127.0.0.1:8501 root@skopos.modelmarket.dev"
echo "  Password:        grep SKOPOS_DASHBOARD_PASSWORD ${ENV_FILE}"
echo "  Postgres:        docker exec -it metis-skopos-postgres psql -U skopos skopos"
echo "  Logs:            cd ${ROOT} && docker compose logs -f skopos"
