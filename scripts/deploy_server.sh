#!/usr/bin/env bash
# deploy_server.sh — обновление и перезапуск vetmanager-mcp на удалённом сервере.
#
# Предусловие: init_server.sh уже запущен, ssh-copy-id настроен.
# Использование:
#   ./scripts/deploy_server.sh user@host [/path/to/repo-on-server]

set -euo pipefail

SSH_TARGET="${1:?Usage: $0 user@host [/server/path]}"
REMOTE_DIR="${2:-/opt/vetmanager-mcp}"
SSL_DOMAIN="${SSL_DOMAIN:-342915.simplecloud.ru}"
SKIP_GIT_PULL="${SKIP_GIT_PULL:-0}"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"

echo "==> Deploying vetmanager-mcp to ${SSH_TARGET}:${REMOTE_DIR} (domain: ${SSL_DOMAIN})"

CERTBOT_EMAIL_ARG="${CERTBOT_EMAIL:-__EMPTY__}"

ssh "${SSH_TARGET}" bash -s "${REMOTE_DIR}" "${SSL_DOMAIN}" "${SKIP_GIT_PULL}" "${CERTBOT_EMAIL_ARG}" << 'REMOTE'
set -euo pipefail
REMOTE_DIR="$1"
SSL_DOMAIN="$2"
SKIP_GIT_PULL="$3"
CERTBOT_EMAIL="$4"
if [ "${CERTBOT_EMAIL}" = "__EMPTY__" ]; then
  CERTBOT_EMAIL=""
fi
export CERTBOT_EMAIL

cd "${REMOTE_DIR}"

# Source .env for POSTGRES_USER etc. (skip UID/GID — readonly in bash)
if [ -f .env ]; then
  set -a
  eval "$(grep -v '^\(UID\|GID\)=' .env | grep -v '^#' | grep -v '^$')"
  set +a
fi

POSTGRES_USER="${POSTGRES_USER:-vetmanager}"
POSTGRES_DB="${POSTGRES_DB:-vetmanager}"

# ── Pull latest code ──────────────────────────────────────────────────────────
if [ "${SKIP_GIT_PULL}" = "1" ]; then
  echo "--> SKIP_GIT_PULL=1, skipping git pull."
elif [ -d .git ]; then
  echo "--> Pulling latest code..."
  git pull --ff-only
else
  echo "WARNING: ${REMOTE_DIR} is not a git repo — skipping git pull."
fi

# ── Rebuild image ─────────────────────────────────────────────────────────────
echo "--> Building Docker image..."
UID_VAL="${DOCKER_UID:-$(id -u)}"
GID_VAL="${DOCKER_GID:-$(id -g)}"
if [ "${UID_VAL}" -eq 0 ]; then UID_VAL=1000; fi
if [ "${GID_VAL}" -eq 0 ]; then GID_VAL=1000; fi
docker build --target production --build-arg UID="${UID_VAL}" --build-arg GID="${GID_VAL}" -t vetmanager-mcp .

compose() {
  env UID="${UID_VAL}" GID="${GID_VAL}" docker compose --profile production "$@"
}

dump_compose_diagnostics() {
  echo "--> Deploy diagnostics..."
  compose ps || true
  if compose ps -q mcp >/dev/null 2>&1; then
    compose logs --tail=100 mcp || true
  else
    compose logs --tail=100 || true
  fi
}

# ── Pre-deploy PostgreSQL backup ─────────────────────────────────────────────
BACKUP_DIR="/var/backups/vetmanager-postgres"
mkdir -p "${BACKUP_DIR}"
PG_CONTAINER="$(docker compose --profile production ps -q postgres 2>/dev/null || true)"
if [ -n "${PG_CONTAINER}" ]; then
  TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
  BACKUP_FILE="${BACKUP_DIR}/pre-deploy-${TIMESTAMP}.sql.gz"
  docker exec "${PG_CONTAINER}" pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
    | gzip > "${BACKUP_FILE}"
  if [ -s "${BACKUP_FILE}" ]; then
    echo "--> Pre-deploy backup: ${BACKUP_FILE}"
  else
    echo "WARNING: Pre-deploy backup is empty, removing."
    rm -f "${BACKUP_FILE}"
  fi
  # Keep only last 20 pre-deploy backups
  ls -t "${BACKUP_DIR}"/pre-deploy-*.sql.gz 2>/dev/null | tail -n +21 | xargs rm -f 2>/dev/null || true
else
  echo "--> PostgreSQL container not running, skipping pre-deploy backup."
fi

# ── Ensure PostgreSQL is running, restart only MCP ───────────────────────────
# IMPORTANT: Never `compose down` postgres — it destroys the container and can
# cause data loss on reinit.  Only stop/recreate the MCP service.
echo "--> Stopping MCP service (keeping PostgreSQL)..."
compose stop mcp 2>/dev/null || true

echo "--> Ensuring PostgreSQL is running..."
compose up -d postgres

# Wait for PostgreSQL to be healthy
echo "--> Waiting for PostgreSQL to be ready..."
for i in $(seq 1 30); do
  PG_CONTAINER_ID="$(compose ps -q postgres || true)"
  if [ -n "${PG_CONTAINER_ID}" ] && docker exec "${PG_CONTAINER_ID}" pg_isready -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; then
    echo "--> PostgreSQL is ready."
    break
  fi
  if [ "${i}" -eq 30 ]; then
    echo "ERROR: PostgreSQL did not become ready in time."
    dump_compose_diagnostics
    exit 1
  fi
  sleep 2
done

# ── Verify PostgreSQL data directory is not empty ────────────────────────────
PG_DATA="/var/lib/vetmanager-postgres"
if [ -d "${PG_DATA}" ] && [ -f "${PG_DATA}/PG_VERSION" ]; then
  echo "--> PostgreSQL data directory verified: ${PG_DATA}/PG_VERSION exists."
else
  echo "ERROR: PostgreSQL data directory is missing or empty at ${PG_DATA}."
  echo "       This likely means data was lost. Aborting deploy to prevent overwrite."
  echo "       Restore from backup: zcat /var/backups/vetmanager-postgres/latest.sql.gz | psql ..."
  exit 1
fi

# ── Run database migrations before starting the app ───────────────────────────
echo "--> Running database migrations..."
compose run --rm mcp alembic upgrade head

# ── Start all services ────────────────────────────────────────────────────────
echo "--> Starting mcp service..."
compose up -d --build --force-recreate mcp

# ── Container smoke check ─────────────────────────────────────────────────────
echo "--> Container smoke check..."
sleep 5
compose ps

MCP_CONTAINER_ID="$(compose ps -q mcp || true)"
if [ -z "${MCP_CONTAINER_ID}" ]; then
  echo "ERROR: mcp container is missing."
  compose logs --tail=30
  exit 1
fi

MCP_RUNNING="$(docker inspect -f '{{.State.Running}}' "${MCP_CONTAINER_ID}" 2>/dev/null || echo "false")"
if [ "${MCP_RUNNING}" != "true" ]; then
  echo "ERROR: mcp container is not running."
  compose logs --tail=50
  exit 1
fi

# ── TLS certificate renew (<30 days) ──────────────────────────────────────────
if [ -f "./scripts/renew_cert_if_needed.sh" ]; then
  echo "--> Checking TLS certificate..."
  bash ./scripts/renew_cert_if_needed.sh "${SSL_DOMAIN}"
else
  echo "WARNING: scripts/renew_cert_if_needed.sh not found, skipping TLS renew."
fi

# ── App smoke checks ──────────────────────────────────────────────────────────
if [ -f "./scripts/post_deploy_smoke_checks.sh" ]; then
  echo "--> Running post-deploy smoke checks..."
  if ! SMOKE_MAX_ATTEMPTS=20 bash ./scripts/post_deploy_smoke_checks.sh "http://127.0.0.1:8000" "${SSL_DOMAIN}"; then
    echo "ERROR: post-deploy smoke checks failed."
    dump_compose_diagnostics
    exit 1
  fi
else
  echo "WARNING: scripts/post_deploy_smoke_checks.sh not found, skipping app smoke checks."
fi
REMOTE

echo "==> Deploy complete: ${SSH_TARGET}:${REMOTE_DIR}"
