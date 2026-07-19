#!/usr/bin/env bash
# Deploy Apache httpd alongside metis-nginx (test only). nginx keeps 80/443; Apache uses 8088.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="${METIS_APACHE_DEPLOY_DIR:-/opt/metis/deploy/apache-test}"
CONTAINER_NAME="${METIS_APACHE_CONTAINER:-metis-apache-test}"
HOST_PORT="${METIS_APACHE_PORT:-8088}"

_install_file() {
  local src="$1" dest="$2"
  if [[ "$(realpath "$src" 2>/dev/null || echo "$src")" == "$(realpath "$dest" 2>/dev/null || echo "$dest")" ]]; then
    return 0
  fi
  install -m 644 "$src" "$dest"
}

mkdir -p "${DEPLOY_DIR}/logs" "${DEPLOY_DIR}/htdocs/admin"
_install_file "${ROOT}/httpd.conf" "${DEPLOY_DIR}/httpd.conf"
_install_file "${ROOT}/index.html" "${DEPLOY_DIR}/htdocs/index.html"
if [[ -f "${ROOT}/htdocs/admin/index.html" ]]; then
  _install_file "${ROOT}/htdocs/admin/index.html" "${DEPLOY_DIR}/htdocs/admin/index.html"
fi
chmod 755 "${DEPLOY_DIR}/logs"

docker rm -f "${CONTAINER_NAME}" 2>/dev/null || true
docker run -d \
  --name "${CONTAINER_NAME}" \
  --restart unless-stopped \
  -p "127.0.0.1:${HOST_PORT}:8080" \
  -v "${DEPLOY_DIR}/httpd.conf:/usr/local/apache2/conf/httpd.conf:ro" \
  -v "${DEPLOY_DIR}/htdocs:/usr/local/apache2/htdocs:ro" \
  -v "${DEPLOY_DIR}/logs:/usr/local/apache2/logs" \
  httpd:2.4-alpine

echo "Apache test container '${CONTAINER_NAME}' listening on http://127.0.0.1:${HOST_PORT}"
echo "Access log: ${DEPLOY_DIR}/logs/access_log"
echo "Smoke: curl -sS http://127.0.0.1:${HOST_PORT}/ | head"
echo "Admin: curl -sS http://127.0.0.1:${HOST_PORT}/admin/ | head"
