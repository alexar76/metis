#!/usr/bin/env bash
# Metis backup/restore — snapshots the persistent data dir (knowledge store, vector/episodic
# memory, traces) that lives on the host bind-mount. Run from cron for point-in-time recovery.
#
#   ./backup.sh                       # snapshot -> /opt/metis/backups/metis-data-<ts>.tar.gz
#   ./backup.sh --restore <file>      # restore a snapshot (stops/starts the container)
#   ./backup.sh --list                # list snapshots
#
# Cron (daily 03:30, keep 14):
#   30 3 * * *  /opt/metis/deploy/backup.sh >/var/log/metis-backup.log 2>&1
set -euo pipefail

DATA_DIR="${METIS_DATA_DIR:-/opt/metis/data}"
BACKUP_DIR="${METIS_BACKUP_DIR:-/opt/metis/backups}"
KEEP="${METIS_BACKUP_KEEP:-14}"
CONTAINER="${METIS_CONTAINER:-metis}"
mkdir -p "$BACKUP_DIR"

_ts() { date -u +%Y%m%dT%H%M%SZ; }

case "${1:-}" in
  --list)
    ls -lh "$BACKUP_DIR"/metis-data-*.tar.gz 2>/dev/null || echo "no snapshots"; exit 0 ;;
  --restore)
    src="${2:?usage: --restore <file>}"
    [ -f "$src" ] || { echo "not found: $src" >&2; exit 1; }
    echo "Restoring $src → $DATA_DIR (container will restart)…"
    docker stop "$CONTAINER" >/dev/null 2>&1 || true
    tmp="$(mktemp -d)"; tar -xzf "$src" -C "$tmp"
    rsync -a --delete "$tmp"/data/ "$DATA_DIR"/
    chown -R 1000:1000 "$DATA_DIR"; rm -rf "$tmp"
    docker start "$CONTAINER" >/dev/null 2>&1 || true
    echo "✓ restored"; exit 0 ;;
esac

# default: snapshot
out="$BACKUP_DIR/metis-data-$(_ts).tar.gz"
tar -czf "$out" -C "$(dirname "$DATA_DIR")" "$(basename "$DATA_DIR")"
echo "✓ snapshot → $out ($(du -h "$out" | cut -f1))"
# rotate: keep newest $KEEP
ls -1t "$BACKUP_DIR"/metis-data-*.tar.gz 2>/dev/null | tail -n +"$((KEEP+1))" | xargs -r rm -f
echo "✓ rotation: kept newest $KEEP"
