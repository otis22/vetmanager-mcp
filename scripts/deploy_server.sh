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
docker build --build-arg UID="${UID_VAL}" --build-arg GID="${GID_VAL}" -t vetmanager-mcp .

# ── Restart service ───────────────────────────────────────────────────────────
echo "--> Restarting service..."
docker compose down --remove-orphans
docker compose up -d

# ── Container smoke check ─────────────────────────────────────────────────────
echo "--> Container smoke check..."
sleep 3
docker compose ps

MCP_CONTAINER_ID="$(docker compose ps -q mcp || true)"
if [ -z "${MCP_CONTAINER_ID}" ]; then
  echo "ERROR: mcp container is missing."
  docker compose logs --tail=30
  exit 1
fi

MCP_RUNNING="$(docker inspect -f '{{.State.Running}}' "${MCP_CONTAINER_ID}" 2>/dev/null || echo "false")"
if [ "${MCP_RUNNING}" != "true" ]; then
  echo "ERROR: mcp container is not running."
  docker compose logs --tail=50
  exit 1
fi

# ── TLS certificate renew (<30 days) ──────────────────────────────────────────
if [ -f "./scripts/renew_cert_if_needed.sh" ]; then
  echo "--> Checking TLS certificate..."
  bash ./scripts/renew_cert_if_needed.sh "${SSL_DOMAIN}"
else
  echo "WARNING: scripts/renew_cert_if_needed.sh not found, skipping TLS renew."
fi

# ── HTTPS endpoint smoke check ────────────────────────────────────────────────
echo "--> HTTPS smoke check: https://${SSL_DOMAIN}/mcp"
REACHABLE="false"
for _ in $(seq 1 12); do
  HTTP_CODE="$(curl -sS -o /dev/null -w '%{http_code}' "https://${SSL_DOMAIN}/mcp" || true)"
  if [ "${HTTP_CODE}" -ge 200 ] && [ "${HTTP_CODE}" -lt 500 ]; then
    REACHABLE="true"
    break
  fi
  sleep 5
done

if [ "${REACHABLE}" != "true" ]; then
  echo "ERROR: HTTPS endpoint is not reachable: https://${SSL_DOMAIN}/mcp"
  exit 1
fi

echo "--> Deploy smoke checks passed."
REMOTE

echo "==> Deploy complete: ${SSH_TARGET}:${REMOTE_DIR}"
