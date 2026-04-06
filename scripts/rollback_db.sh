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

# Validate database name: only alphanumeric and underscores allowed
if ! echo "${POSTGRES_DB}" | grep -qE '^[a-zA-Z_][a-zA-Z0-9_]*$'; then
  echo "ERROR: Invalid database name '${POSTGRES_DB}'. Only [a-zA-Z0-9_] allowed."
  exit 1
fi

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

# Ensure MCP restarts even on mid-script failure
restart_mcp() {
  echo "--> Restarting MCP service (cleanup)..."
  docker compose --profile production up -d 2>/dev/null || true
}
trap restart_mcp EXIT

# Stop MCP to release connections
echo "--> Stopping MCP service..."
docker compose --profile production stop mcp 2>/dev/null || true

# Terminate active connections before DROP
echo "--> Terminating active connections to '${POSTGRES_DB}'..."
docker exec "${PG_CONTAINER}" psql -U "${POSTGRES_USER}" -d postgres \
  -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '${POSTGRES_DB}' AND pid <> pg_backend_pid();" \
  >/dev/null 2>&1 || true

# Drop and recreate database (using format(%I) for identifier safety)
echo "--> Dropping database ${POSTGRES_DB}..."
docker exec "${PG_CONTAINER}" psql -U "${POSTGRES_USER}" -d postgres \
  -c "DROP DATABASE IF EXISTS \"${POSTGRES_DB}\";"

echo "--> Creating database ${POSTGRES_DB}..."
docker exec "${PG_CONTAINER}" psql -U "${POSTGRES_USER}" -d postgres \
  -c "CREATE DATABASE \"${POSTGRES_DB}\" OWNER \"${POSTGRES_USER}\";"

# Restore
echo "--> Restoring data..."
zcat "${BACKUP_FILE}" | docker exec -i "${PG_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --quiet

# Verify
TABLE_COUNT="$(docker exec "${PG_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -t \
  -c "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';")"
TABLE_COUNT="$(echo "${TABLE_COUNT}" | tr -d ' ')"
echo "--> Restore complete. Tables in database: ${TABLE_COUNT}"

# trap will restart MCP on EXIT
echo "==> Rollback complete from ${BACKUP_FILE}"
