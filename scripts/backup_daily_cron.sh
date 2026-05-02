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

# Stage 153 (F1): whitelist-extract POSTGRES_USER/DB from .env (no eval).
# Same pattern as deploy_server.sh — see PRD/этап-153 for rationale.
POSTGRES_USER="${POSTGRES_USER:-vetmanager}"
POSTGRES_DB="${POSTGRES_DB:-vetmanager}"
if [ -f .env ]; then
  PG_USER_LINE="$( { grep -E '^POSTGRES_USER=' .env || true; } | head -n 1 | cut -d= -f2- | tr -d '\r')"
  PG_DB_LINE="$( { grep -E '^POSTGRES_DB=' .env || true; } | head -n 1 | cut -d= -f2- | tr -d '\r')"
  if [ -n "${PG_USER_LINE}" ]; then
    POSTGRES_USER="${PG_USER_LINE%\"}"
    POSTGRES_USER="${POSTGRES_USER#\"}"
  fi
  if [ -n "${PG_DB_LINE}" ]; then
    POSTGRES_DB="${PG_DB_LINE%\"}"
    POSTGRES_DB="${POSTGRES_DB#\"}"
  fi
fi

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
