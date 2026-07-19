#!/usr/bin/env bash
# Apply PostgreSQL hardening on a running metis-skopos-postgres container.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT}/.env"
CONTAINER="${SKOPOS_PG_CONTAINER:-metis-skopos-postgres}"
PG_USER="${SKOPOS_POSTGRES_USER:-skopos}"
PG_DB="${SKOPOS_POSTGRES_DB:-skopos}"

log() { echo "[postgres-harden] $*"; }

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}" >&2
  exit 1
fi

# shellcheck disable=SC1090
set -a && source "${ENV_FILE}" && set +a
export PGPASSWORD="${SKOPOS_POSTGRES_PASSWORD:?SKOPOS_POSTGRES_PASSWORD not set}"

if ! docker ps --format '{{.Names}}' | grep -qx "${CONTAINER}"; then
  echo "Container ${CONTAINER} is not running." >&2
  exit 1
fi

psql_exec() {
  docker exec -e PGPASSWORD="${PGPASSWORD}" "${CONTAINER}" \
    psql -U "${PG_USER}" -d "${PG_DB}" -v ON_ERROR_STOP=1 "$@"
}

log "Installing pg_hba.conf (Docker subnet only, SCRAM)…"
docker cp "${ROOT}/postgres/pg_hba.conf" "${CONTAINER}:/var/lib/postgresql/data/pg_hba.conf"

log "Applying SQL hardening…"
psql_exec <<SQL
REVOKE ALL ON DATABASE ${PG_DB} FROM PUBLIC;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT ALL ON SCHEMA public TO ${PG_USER};
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO ${PG_USER};
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO ${PG_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO ${PG_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO ${PG_USER};
ALTER SYSTEM SET password_encryption = 'scram-sha-256';
ALTER SYSTEM SET log_connections = 'on';
ALTER SYSTEM SET log_disconnections = 'on';
ALTER SYSTEM SET log_statement = 'ddl';
SELECT pg_reload_conf();
SQL

log "Verifying SKOPOS can connect…"
docker exec metis-skopos python -c "
from skopos.db_connection import connect
import os
c = connect(os.environ['SKOPOS_DATABASE_URL'])
row = c.execute('SELECT COUNT(*) AS c FROM http_requests').fetchone()
print('http_requests', row['c'] if isinstance(row, dict) else row[0])
c.close()
"

log "Done."
