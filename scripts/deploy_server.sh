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
  env UID="${UID_VAL}" GID="${GID_VAL}" docker compose "$@"
}

prepare_storage_permissions() {
  mkdir -p data
  docker run --rm --user 0 -v "${PWD}/data:/target" vetmanager-mcp \
    sh -c "mkdir -p /target && chown -R ${UID_VAL}:${GID_VAL} /target && chmod -R ug+rwX /target"
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

# ── Pre-deploy database backup ────────────────────────────────────────────────
BACKUP_DIR="${REMOTE_DIR}/backups"
mkdir -p "${BACKUP_DIR}"
DB_FILE="${REMOTE_DIR}/data/vetmanager_mcp.db"
if [ -f "${DB_FILE}" ]; then
  BACKUP_NAME="pre-deploy-$(date +%Y%m%d-%H%M%S).db"
  cp "${DB_FILE}" "${BACKUP_DIR}/${BACKUP_NAME}"
  echo "--> Database backed up to backups/${BACKUP_NAME}"
  # Keep only last 10 backups
  ls -t "${BACKUP_DIR}"/pre-deploy-*.db 2>/dev/null | tail -n +11 | xargs rm -f 2>/dev/null || true
else
  echo "--> No database file found at ${DB_FILE}, skipping backup."
fi

# ── Restart service ───────────────────────────────────────────────────────────
echo "--> Restarting service..."
prepare_storage_permissions
compose down --remove-orphans
compose up -d

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

# ── Database integrity check ──────────────────────────────────────────────────
if [ -f "${DB_FILE}" ]; then
  DB_SIZE=$(stat -f%z "${DB_FILE}" 2>/dev/null || stat -c%s "${DB_FILE}" 2>/dev/null || echo "0")
  echo "--> Database file exists (${DB_SIZE} bytes)."
  if [ "${DB_SIZE}" -lt 1024 ] 2>/dev/null; then
    echo "WARNING: Database file is suspiciously small (${DB_SIZE} bytes). Possible data loss."
  fi
else
  echo "WARNING: Database file not found after restart. First deploy or possible data loss."
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
