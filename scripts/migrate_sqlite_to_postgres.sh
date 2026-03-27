#!/usr/bin/env bash
# migrate_sqlite_to_postgres.sh — one-time data migration from SQLite to PostgreSQL.
#
# Run this ON THE SERVER after PostgreSQL is up and Alembic schema is created.
#
# Prerequisites:
#   1. PostgreSQL container is running (docker compose --profile production up -d postgres)
#   2. Alembic migrations applied (docker compose --profile production run --rm mcp alembic upgrade head)
#   3. SQLite database exists at data/vetmanager.db (or SQLITE_PATH)
#
# Usage:
#   ./scripts/migrate_sqlite_to_postgres.sh [/path/to/sqlite.db]

set -euo pipefail

REMOTE_DIR="${REMOTE_DIR:-/opt/vetmanager-mcp}"
SQLITE_PATH="${1:-${REMOTE_DIR}/data/vetmanager.db}"
POSTGRES_USER="${POSTGRES_USER:-vetmanager}"
POSTGRES_DB="${POSTGRES_DB:-vetmanager}"

if [ ! -f "${SQLITE_PATH}" ]; then
  echo "SQLite database not found at ${SQLITE_PATH}"
  echo "Nothing to migrate — fresh PostgreSQL install."
  exit 0
fi

cd "${REMOTE_DIR}"

# Source .env for credentials
if [ -f .env ]; then
  set -a; source .env; set +a
fi

PG_CONTAINER="$(docker compose --profile production ps -q postgres 2>/dev/null || true)"
if [ -z "${PG_CONTAINER}" ]; then
  echo "ERROR: PostgreSQL container is not running."
  echo "Start it first: docker compose --profile production up -d postgres"
  exit 1
fi

echo "==> Migrating data from ${SQLITE_PATH} to PostgreSQL..."

# Get list of tables from SQLite (excluding alembic_version and sqlite internals)
TABLES="$(sqlite3 "${SQLITE_PATH}" ".tables" | tr -s ' ' '\n' | grep -v '^$' | grep -v 'alembic_version' | sort)"

if [ -z "${TABLES}" ]; then
  echo "No user tables found in SQLite database. Nothing to migrate."
  exit 0
fi

echo "Tables to migrate: ${TABLES}"

for TABLE in ${TABLES}; do
  echo "--> Migrating table: ${TABLE}"

  # Export as INSERT statements
  INSERTS="$(sqlite3 "${SQLITE_PATH}" ".mode insert ${TABLE}" ".output stdout" "SELECT * FROM ${TABLE};" 2>/dev/null || true)"

  if [ -z "${INSERTS}" ]; then
    echo "    (empty, skipping)"
    continue
  fi

  ROW_COUNT="$(echo "${INSERTS}" | wc -l)"

  # Pipe INSERTs into PostgreSQL
  echo "${INSERTS}" | docker exec -i "${PG_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -v ON_ERROR_STOP=1 >/dev/null

  # Reset auto-increment sequence if the table has an 'id' column
  docker exec -i "${PG_CONTAINER}" psql -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" -c \
    "DO \$\$ BEGIN IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='${TABLE}' AND column_name='id') THEN PERFORM setval(pg_get_serial_sequence('${TABLE}', 'id'), COALESCE((SELECT MAX(id) FROM \"${TABLE}\"), 0) + 1, false); END IF; END \$\$;" \
    >/dev/null 2>&1 || true

  echo "    ${ROW_COUNT} row(s) migrated."
done

echo ""
echo "==> Migration complete. Verify with:"
echo "    docker exec ${PG_CONTAINER} psql -U ${POSTGRES_USER} -d ${POSTGRES_DB} -c '\\dt'"
