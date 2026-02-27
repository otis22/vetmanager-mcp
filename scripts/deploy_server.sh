#!/usr/bin/env bash
# deploy_server.sh — обновление и перезапуск vetmanager-mcp на удалённом сервере.
#
# Предусловие: init_server.sh уже запущен, ssh-copy-id настроен.
# Использование:
#   ./scripts/deploy_server.sh user@host [/path/to/repo-on-server]

set -euo pipefail

SSH_TARGET="${1:?Usage: $0 user@host [/server/path]}"
REMOTE_DIR="${2:-/opt/vetmanager-mcp}"

echo "==> Deploying vetmanager-mcp to ${SSH_TARGET}:${REMOTE_DIR}"

ssh "${SSH_TARGET}" bash -s "${REMOTE_DIR}" << 'REMOTE'
set -euo pipefail
REMOTE_DIR="$1"

cd "${REMOTE_DIR}"

# ── Pull latest code ──────────────────────────────────────────────────────────
if [ -d .git ]; then
  echo "--> Pulling latest code..."
  git pull --ff-only
else
  echo "WARNING: ${REMOTE_DIR} is not a git repo — skipping git pull."
fi

# ── Rebuild image ─────────────────────────────────────────────────────────────
echo "--> Building Docker image..."
UID_VAL=$(id -u) GID_VAL=$(id -g)
docker build --build-arg UID="${UID_VAL}" --build-arg GID="${GID_VAL}" -t vetmanager-mcp .

# ── Restart service ───────────────────────────────────────────────────────────
echo "--> Restarting service..."
docker compose down --remove-orphans
docker compose up -d

# ── Smoke check ───────────────────────────────────────────────────────────────
echo "--> Smoke check (waiting 5s)..."
sleep 5
docker compose ps

STATUS=$(docker compose ps --format json 2>/dev/null | python3 -c "
import sys, json
data = [json.loads(l) for l in sys.stdin if l.strip()]
failed = [s['Name'] for s in data if s.get('State') != 'running']
print(','.join(failed))
" 2>/dev/null || echo "")

if [ -n "${STATUS}" ]; then
  echo "ERROR: Containers not running: ${STATUS}"
  docker compose logs --tail=30
  exit 1
fi

echo "--> All containers running."
REMOTE

echo "==> Deploy complete: ${SSH_TARGET}:${REMOTE_DIR}"
