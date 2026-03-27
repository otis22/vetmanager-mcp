#!/usr/bin/env bash
# backup_postgres.sh — pg_dump + gzip backup with retention policy.
#
# Usage (standalone):
#   ./scripts/backup_postgres.sh
#
# Cron (twice daily, 03:00 and 15:00):
#   0 3,15 * * * /opt/vetmanager-mcp/scripts/backup_postgres.sh >> /var/log/vetmanager-backup.log 2>&1

set -euo pipefail

REMOTE_DIR="${REMOTE_DIR:-/opt/vetmanager-mcp}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/vetmanager-postgres}"
RETENTION_DAYS="${RETENTION_DAYS:-60}"
POSTGRES_USER="${POSTGRES_USER:-vetmanager}"
POSTGRES_DB="${POSTGRES_DB:-vetmanager}"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_FILE="${BACKUP_DIR}/vetmanager-${TIMESTAMP}.sql.gz"

mkdir -p "${BACKUP_DIR}"

# Resolve postgres container ID via docker compose
PG_CONTAINER="$(docker compose --profile production -f "${REMOTE_DIR}/docker-compose.yml" ps -q postgres 2>/dev/null || true)"
if [ -z "${PG_CONTAINER}" ]; then
  echo "$(date -Iseconds) ERROR: postgres container not found. Is it running?"
  exit 1
fi

# Dump and compress
docker exec "${PG_CONTAINER}" pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
  | gzip > "${BACKUP_FILE}"

# Verify non-empty
if [ ! -s "${BACKUP_FILE}" ]; then
  echo "$(date -Iseconds) ERROR: backup file is empty: ${BACKUP_FILE}"
  rm -f "${BACKUP_FILE}"
  exit 1
fi

SIZE="$(stat -c%s "${BACKUP_FILE}" 2>/dev/null || stat -f%z "${BACKUP_FILE}" 2>/dev/null || echo '?')"
echo "$(date -Iseconds) OK: ${BACKUP_FILE} (${SIZE} bytes)"

# Delete backups older than RETENTION_DAYS
DELETED="$(find "${BACKUP_DIR}" -name "vetmanager-*.sql.gz" -mtime "+${RETENTION_DAYS}" -delete -print | wc -l)"
if [ "${DELETED}" -gt 0 ]; then
  echo "$(date -Iseconds) Cleaned ${DELETED} backup(s) older than ${RETENTION_DAYS} days."
fi
