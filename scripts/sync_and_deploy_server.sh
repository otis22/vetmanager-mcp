#!/usr/bin/env bash
# sync_and_deploy_server.sh — синхронизация кода по rsync и запуск deploy.
#
# Использование:
#   ./scripts/sync_and_deploy_server.sh user@host [/path/to/repo-on-server]

set -euo pipefail

SSH_TARGET="${1:?Usage: $0 user@host [/server/path]}"
REMOTE_DIR="${2:-/opt/vetmanager-mcp}"
SSL_DOMAIN="${SSL_DOMAIN:-vetmanager-mcp.vromanichev.ru}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "==> Syncing ${PROJECT_ROOT} to ${SSH_TARGET}:${REMOTE_DIR} via rsync"

ssh "${SSH_TARGET}" "mkdir -p '${REMOTE_DIR}'"

rsync -az --delete \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '.cursor/' \
  --exclude '__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude '.env' \
  "${PROJECT_ROOT}/" "${SSH_TARGET}:${REMOTE_DIR}/"

echo "==> Sync complete. Running deploy_server.sh with SKIP_GIT_PULL=1"
SKIP_GIT_PULL=1 SSL_DOMAIN="${SSL_DOMAIN}" CERTBOT_EMAIL="${CERTBOT_EMAIL:-}" \
  "${SCRIPT_DIR}/deploy_server.sh" "${SSH_TARGET}" "${REMOTE_DIR}"
