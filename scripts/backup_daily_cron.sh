#!/usr/bin/env bash
# backup_daily_cron.sh — Daily PostgreSQL backup for vetmanager-mcp.
#
# Install via crontab on the production server:
#   0 3 * * * /opt/vetmanager-mcp/scripts/backup_daily_cron.sh >> /var/log/vetmanager-backup.log 2>&1
#
# Keeps last 30 daily backups.

set -euo pipefail

REMOTE_DIR="${1:-/opt/vetmanager-mcp}"
BACKUP_DIR="/var/backups/vetmanager-postgres"
KEEP_DAYS=30

cd "${REMOTE_DIR}"

# Source .env for POSTGRES_USER
if [ -f .env ]; then
  set -a
  eval "$(grep -v '^\(UID\|GID\)=' .env | grep -v '^#' | grep -v '^$')"
  set +a
fi

POSTGRES_USER="${POSTGRES_USER:-vetmanager}"
POSTGRES_DB="${POSTGRES_DB:-vetmanager}"

mkdir -p "${BACKUP_DIR}"

# Find running postgres container
PG_CONTAINER="$(docker compose --profile production ps -q postgres 2>/dev/null || true)"
if [ -z "${PG_CONTAINER}" ]; then
  echo "$(date -Iseconds) ERROR: PostgreSQL container not running, skipping backup."
  exit 1
fi

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_FILE="${BACKUP_DIR}/daily-${TIMESTAMP}.sql.gz"

docker exec "${PG_CONTAINER}" pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
  | gzip > "${BACKUP_FILE}"

if [ -s "${BACKUP_FILE}" ]; then
  SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
  echo "$(date -Iseconds) OK: Backup created ${BACKUP_FILE} (${SIZE})"

  # Update symlink to latest backup
  ln -sf "${BACKUP_FILE}" "${BACKUP_DIR}/latest.sql.gz"
else
  echo "$(date -Iseconds) WARNING: Backup is empty, removing."
  rm -f "${BACKUP_FILE}"
  exit 1
fi

# Prune old daily backups
ls -t "${BACKUP_DIR}"/daily-*.sql.gz 2>/dev/null | tail -n +$((KEEP_DAYS + 1)) | xargs rm -f 2>/dev/null || true

echo "$(date -Iseconds) OK: Backup rotation complete. Kept last ${KEEP_DAYS} daily backups."
