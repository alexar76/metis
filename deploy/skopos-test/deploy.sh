#!/usr/bin/env bash
# Run ON metis — build & start SKOPOS test stack (Postgres + dashboard).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="${SKOPOS_APP_DIR:-/opt/skopos-test/app}"
ENV_FILE="${ROOT}/.env"
APACHE_DEPLOY="${METIS_APACHE_DEPLOY_DIR:-/opt/metis/deploy/apache-test}"

log() { echo "[skopos-test] $*"; }

if [[ ! -d "${APP_DIR}" ]]; then
  echo "Missing app dir ${APP_DIR}. Run remote-sync.sh from your laptop first." >&2
  exit 1
fi

SSH_DIR="${ROOT}/ssh"
mkdir -p "${SSH_DIR}"
if [[ ! -f "${SSH_DIR}/id_ed25519" ]]; then
  log "Generating SSH probe key for fleet log collection…"
  ssh-keygen -t ed25519 -f "${SSH_DIR}/id_ed25519" -N "" -C "skopos-metis-probe"
  chmod 700 "${SSH_DIR}"
  chmod 600 "${SSH_DIR}/id_ed25519"
  chmod 644 "${SSH_DIR}/id_ed25519.pub"
  PUB="$(cat "${SSH_DIR}/id_ed25519.pub")"
  if ! grep -qF "${PUB}" /root/.ssh/authorized_keys 2>/dev/null; then
    echo "${PUB}" >> /root/.ssh/authorized_keys
    chmod 600 /root/.ssh/authorized_keys
  fi
fi

install_probe_key() {
  local target="$1"
  local port="${2:-22}"
  local pub_file="${SSH_DIR}/id_ed25519.pub"
  [[ -f "${pub_file}" ]] || return 0
  ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -p "${port}" "${target}" \
    "grep -qF \"$(cat "${pub_file}")\" /root/.ssh/authorized_keys 2>/dev/null || { mkdir -p /root/.ssh; chmod 700 /root/.ssh; echo \"$(cat "${pub_file}")\" >> /root/.ssh/authorized_keys; chmod 600 /root/.ssh/authorized_keys; }" \
    2>/dev/null && log "Probe key installed on ${target}:${port}" || log "Probe key skipped for ${target}:${port} (no SSH access from metis)"
}

# Best-effort: allow SKOPOS container to SSH to factory + oracle for fleet logs.
install_probe_key "root@modeldev.modelmarket.dev" 8443 || true
install_probe_key "root@oracles.modelmarket.dev" 22 || true

if [[ ! -f "${ENV_FILE}" ]]; then
  log "Creating .env from example with generated passwords…"
  cp "${ROOT}/.env.example" "${ENV_FILE}"
  DASH_PW="$(openssl rand -base64 24 | tr -d '/+=' | head -c 20)"
  PG_PW="$(openssl rand -base64 32 | tr -d '/+=' | head -c 28)"
  if sed --version >/dev/null 2>&1; then
    sed -i "s/CHANGE_ME_DASHBOARD_PASSWORD/${DASH_PW}/" "${ENV_FILE}"
    sed -i "s/CHANGE_ME_POSTGRES_PASSWORD/${PG_PW}/g" "${ENV_FILE}"
  else
    sed -i '' "s/CHANGE_ME_DASHBOARD_PASSWORD/${DASH_PW}/" "${ENV_FILE}"
    sed -i '' "s/CHANGE_ME_POSTGRES_PASSWORD/${PG_PW}/g" "${ENV_FILE}"
  fi
  chmod 600 "${ENV_FILE}"
  log "Dashboard password written to ${ENV_FILE} (SKOPOS_DASHBOARD_PASSWORD)"
fi

# Apache test logs (optional SKOPOS source) — idempotent
if [[ -x "${APACHE_DEPLOY}/deploy.sh" ]]; then
  log "Ensuring Apache test instance (port 8088)…"
  bash "${APACHE_DEPLOY}/deploy.sh"
  mkdir -p "${APACHE_DEPLOY}/logs"
  chmod 755 "${APACHE_DEPLOY}/logs"
fi

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
