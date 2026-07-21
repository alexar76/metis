#!/usr/bin/env bash
# Sync SKOPOS sources to metis and run deploy.sh (run from monorepo root or set REPO).
set -euo pipefail

REPO="${REPO:-$(cd "$(dirname "$0")/../../.." && pwd)}"
METIS_HOST="${METIS_HOST:-root@31.77.67.99}"
APP_REMOTE="/opt/skopos-test/app"
DEPLOY_REMOTE="/opt/skopos-test/deploy"
APACHE_REMOTE="/opt/metis/deploy/apache-test"
LANDING_REMOTE="/var/www/metis-landing/skopos"
NGINX_REMOTE="/opt/metis/deploy/nginx.conf"

echo "[sync] ${REPO}/skopos → ${METIS_HOST}:${APP_REMOTE}"
ssh "${METIS_HOST}" "mkdir -p ${APP_REMOTE} ${DEPLOY_REMOTE} ${APACHE_REMOTE}"

rsync -avz --delete \
  --exclude '.venv/' \
  --exclude '__pycache__/' \
  --exclude '*.sqlite3' \
  --exclude '*.sqlite3-shm' \
  --exclude '*.sqlite3-wal' \
  --exclude '.env' \
  --exclude '.git/' \
  "${REPO}/skopos/" "${METIS_HOST}:${APP_REMOTE}/"

rsync -avz \
  "${REPO}/metis/deploy/skopos-test/" "${METIS_HOST}:${DEPLOY_REMOTE}/"

rsync -avz \
  "${REPO}/metis/deploy/apache-test/" "${METIS_HOST}:${APACHE_REMOTE}/"

echo "[sync] landing → ${METIS_HOST}:${LANDING_REMOTE}"
ssh "${METIS_HOST}" "mkdir -p ${LANDING_REMOTE}"
rsync -avz --delete \
  "${REPO}/skopos/docs/landing/" "${METIS_HOST}:${LANDING_REMOTE}/"

echo "[sync] nginx.conf → ${METIS_HOST}:${NGINX_REMOTE}"
# --inplace: the file is bind-mounted into metis-nginx; a rename-style update
# creates a new inode the container never sees, so the in-container `nginx -t`
# below would validate the STALE config while restart applies the new one.
rsync -avz --inplace \
  "${REPO}/metis/deploy/nginx.conf" "${METIS_HOST}:${NGINX_REMOTE}"

# Ensure probe key exists, distribute to factory/oracle, then build + start stack.
ssh "${METIS_HOST}" "bash -s" <<'REMOTE'
set -euo pipefail
ROOT="/opt/skopos-test/deploy"
SSH_DIR="${ROOT}/ssh"
mkdir -p "${SSH_DIR}"
if [[ ! -f "${SSH_DIR}/id_ed25519" ]]; then
  ssh-keygen -t ed25519 -f "${SSH_DIR}/id_ed25519" -N "" -C "skopos-metis-probe"
  chmod 700 "${SSH_DIR}"
  chmod 600 "${SSH_DIR}/id_ed25519"
  chmod 644 "${SSH_DIR}/id_ed25519.pub"
  PUB="$(cat "${SSH_DIR}/id_ed25519.pub")"
  grep -qF "${PUB}" /root/.ssh/authorized_keys 2>/dev/null || echo "${PUB}" >> /root/.ssh/authorized_keys
  chmod 600 /root/.ssh/authorized_keys
fi
REMOTE

PROBE_PUB="$(ssh "${METIS_HOST}" "cat ${DEPLOY_REMOTE}/ssh/id_ed25519.pub 2>/dev/null" || true)"
if [[ -n "${PROBE_PUB}" ]]; then
  for spec in "root@5.129.212.122:8443" "root@78.17.126.214:22"; do
    target="${spec%%:*}"
    port="${spec##*:}"
    ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -p "${port}" "${target}" \
      "grep -qF '${PROBE_PUB}' /root/.ssh/authorized_keys 2>/dev/null || { mkdir -p /root/.ssh; chmod 700 /root/.ssh; echo '${PROBE_PUB}' >> /root/.ssh/authorized_keys; chmod 600 /root/.ssh/authorized_keys; echo installed; }" \
      2>/dev/null && echo "[sync] probe key → ${target}:${port}" || echo "[sync] probe key skipped for ${target}:${port}"
  done
fi

ssh "${METIS_HOST}" "chmod +x ${DEPLOY_REMOTE}/deploy.sh ${APACHE_REMOTE}/deploy.sh 2>/dev/null || true; bash ${DEPLOY_REMOTE}/deploy.sh"

echo "[sync] reload nginx"
ssh "${METIS_HOST}" "docker exec metis-nginx nginx -t && docker restart metis-nginx"

# Optional GitHub Pages mirror (OFF by default — canonical publish is Gitea via mirror_to_gitea.sh).
echo "[sync] prepare landing for GitHub Pages"
"${REPO}/scripts/build_skopos_landing.sh"
if [[ "${SKOPOS_PAGES_PUBLISH:-0}" == "1" ]] && [[ -n "${GH_PAT:-${GITHUB_TOKEN:-}}" ]]; then
  echo "[sync] publish landing → GitHub Pages (alexar76/skopos) — explicit SKOPOS_PAGES_PUBLISH=1"
  "${REPO}/scripts/publish_all_repos.sh" --satellite skopos
else
  echo "[sync] GitHub Pages: skipped (default). Gitea: ./scripts/mirror_to_gitea.sh skopos"
fi

if [[ "${SKOPOS_GITEA_PUBLISH:-0}" == "1" ]]; then
  echo "[sync] mirror skopos → Gitea (SKOPOS_GITEA_PUBLISH=1)"
  "${REPO}/scripts/mirror_to_gitea.sh" skopos
fi
