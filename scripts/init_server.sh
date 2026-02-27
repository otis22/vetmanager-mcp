#!/usr/bin/env bash
# init_server.sh — первичная настройка удалённого сервера для vetmanager-mcp.
#
# Предусловие: ssh-copy-id user@host уже выполнен.
# Использование:
#   ./scripts/init_server.sh user@host [/path/to/repo-on-server]
#
# Всё выполняется через Docker на сервере — Python не нужен.

set -euo pipefail

SSH_TARGET="${1:?Usage: $0 user@host [/server/path]}"
REMOTE_DIR="${2:-/opt/vetmanager-mcp}"
REPO_URL="${REPO_URL:-$(git remote get-url origin 2>/dev/null || echo '')}"

echo "==> Initialising vetmanager-mcp on ${SSH_TARGET}:${REMOTE_DIR}"

ssh "${SSH_TARGET}" bash -s "${REMOTE_DIR}" "${REPO_URL}" << 'REMOTE'
set -euo pipefail
REMOTE_DIR="$1"
REPO_URL="$2"

# ── Docker ────────────────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  echo "Installing Docker..."
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$(whoami)"
  echo "Docker installed. You may need to re-login for group membership."
fi

if ! docker compose version &>/dev/null; then
  echo "Installing Docker Compose plugin..."
  sudo apt-get install -y docker-compose-plugin 2>/dev/null || \
    sudo dnf install -y docker-compose-plugin 2>/dev/null || true
fi

# ── Repo ──────────────────────────────────────────────────────────────────────
if [ -d "${REMOTE_DIR}/.git" ]; then
  echo "Repo already exists at ${REMOTE_DIR}, skipping clone."
elif [ -n "${REPO_URL}" ]; then
  git clone "${REPO_URL}" "${REMOTE_DIR}"
else
  mkdir -p "${REMOTE_DIR}"
  echo "No REPO_URL set — created empty directory ${REMOTE_DIR}."
  echo "Copy your code manually or set REPO_URL before running this script."
fi

cd "${REMOTE_DIR}"

# ── .env ─────────────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
  cp .env.example .env
  echo ""
  echo ">>> Created .env from .env.example."
  echo ">>> IMPORTANT: edit ${REMOTE_DIR}/.env and set LOG_LEVEL, UID/GID."
  echo ">>> The MCP server receives domain/api_key per request — no need to set them here."
fi

# ── Build ─────────────────────────────────────────────────────────────────────
UID_VAL=$(id -u) GID_VAL=$(id -g)
docker build --build-arg UID="${UID_VAL}" --build-arg GID="${GID_VAL}" -t vetmanager-mcp .

echo ""
echo "==> Init complete. Edit .env if needed, then run:"
echo "    docker compose up -d"
REMOTE

echo "==> Done. Server is ready at ${SSH_TARGET}:${REMOTE_DIR}"
