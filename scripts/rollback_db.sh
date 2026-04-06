#!/usr/bin/env bash
# rollback_db.sh — Restore PostgreSQL from a backup file.
#
# Usage:
#   ./scripts/rollback_db.sh [backup_file]
#
# If backup_file is omitted, restores from the latest symlink.

set -euo pipefail

REMOTE_DIR="${REMOTE_DIR:-/opt/vetmanager-mcp}"
BACKUP_DIR="/var/backups/vetmanager-postgres"
BACKUP_FILE="${1:-${BACKUP_DIR}/latest.sql.gz}"

cd "${REMOTE_DIR}"

# Source .env for POSTGRES_USER
if [ -f .env ]; then
  set -a
  eval "$(grep -v '^\(UID\|GID\)=' .env | grep -v '^#' | grep -v '^$')"
  set +a
fi

POSTGRES_USER="${POSTGRES_USER:-vetmanager}"
POSTGRES_DB="${POSTGRES_DB:-vetmanager}"

if [ ! -f "${BACKUP_FILE}" ]; then
  echo "ERROR: Backup file not found: ${BACKUP_FILE}"
  echo "Available backups:"
  ls -lt "${BACKUP_DIR}"/*.sql.gz 2>/dev/null | head -10 || echo "  (none)"
  exit 1
fi

FILE_SIZE="$(du -h "${BACKUP_FILE}" | cut -f1)"
echo "==> Restoring from: ${BACKUP_FILE} (${FILE_SIZE})"
echo "    Target: ${POSTGRES_USER}@${POSTGRES_DB}"
echo ""
echo "WARNING: This will DROP and recreate the database '${POSTGRES_DB}'."
echo "Press Ctrl+C within 5 seconds to abort..."
sleep 5

# Find running postgres container
PG_CONTAINER="$(docker compose --profile production ps -q postgres 2>/dev/null || true)"
if [ -z "${PG_CONTAINER}" ]; then
  echo "ERROR: PostgreSQL container not running. Start it first:"
  echo "  docker compose --profile production up -d postgres"
  exit 1
fi

# Stop MCP to release connections
echo "--> Stopping MCP service..."
docker compose --profile production stop mcp 2>/dev/null || true

# Drop and recreate database
echo "--> Dropping database ${POSTGRES_DB}..."
docker exec "${PG_CONTAINER}" psql -U "${POSTGRES_USER}" -d postgres \
  -c "DROP DATABASE IF EXISTS ${POSTGRES_DB};"

echo "--> Creating database ${POSTGRES_DB}..."
docker exec "${PG_CONTAINER}" psql -U "${POSTGRES_USER}" -d postgres \
  -c "CREATE DATABASE ${POSTGRES_DB} OWNER ${POSTGRES_USER};"

# Restore
echo "--> Restoring data..."
zcat "${BACKUP_FILE}" | docker exec -i "${PG_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --quiet

# Verify
TABLE_COUNT="$(docker exec "${PG_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -t \
  -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';")"
TABLE_COUNT="$(echo "${TABLE_COUNT}" | tr -d ' ')"
echo "--> Restore complete. Tables in database: ${TABLE_COUNT}"

# Restart MCP
echo "--> Starting MCP service..."
docker compose --profile production up -d

echo "==> Rollback complete from ${BACKUP_FILE}"
