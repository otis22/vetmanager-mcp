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
SSL_DOMAIN="${SSL_DOMAIN:-342915.simplecloud.ru}"
if [ "${REPO_URL+x}" != "x" ]; then
  REPO_URL="$(git remote get-url origin 2>/dev/null || echo '')"
fi

echo "==> Initialising vetmanager-mcp on ${SSH_TARGET}:${REMOTE_DIR} (domain: ${SSL_DOMAIN})"

REPO_URL_ARG="${REPO_URL:-__EMPTY__}"

ssh "${SSH_TARGET}" bash -s "${REMOTE_DIR}" "${REPO_URL_ARG}" "${SSL_DOMAIN}" << 'REMOTE'
set -euo pipefail
REMOTE_DIR="$1"
REPO_URL="$2"
SSL_DOMAIN="$3"
if [ "${REPO_URL}" = "__EMPTY__" ]; then
  REPO_URL=""
fi

if ! command -v apt-get &>/dev/null; then
  echo "ERROR: This script supports Debian/Ubuntu hosts (apt-get required)."
  exit 1
fi

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
else
  SUDO="sudo"
fi

export DEBIAN_FRONTEND=noninteractive

echo "--> Installing system packages..."
${SUDO} apt-get update -y
${SUDO} apt-get install -y git curl ca-certificates nginx certbot python3-certbot-nginx openssl

# ── Docker ────────────────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  echo "Installing Docker..."
  curl -fsSL https://get.docker.com | sh
  if [ -n "${SUDO}" ]; then
    ${SUDO} usermod -aG docker "$(whoami)"
  fi
  echo "Docker installed."
fi

if ! docker compose version &>/dev/null; then
  echo "Installing Docker Compose plugin..."
  ${SUDO} apt-get install -y docker-compose-plugin
fi
${SUDO} systemctl enable --now docker
${SUDO} systemctl enable --now nginx

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
  if [ -f .env.example ]; then
    cp .env.example .env
    echo ""
    echo ">>> Created .env from .env.example."
    echo ">>> IMPORTANT: edit ${REMOTE_DIR}/.env and set LOG_LEVEL, UID/GID."
    echo ">>> The MCP server receives domain/api_key per request — no need to set them here."
  else
    echo "WARNING: .env.example not found in ${REMOTE_DIR}, skipping .env creation."
  fi
fi

# ── Nginx reverse proxy ───────────────────────────────────────────────────────
NGINX_SITE="/etc/nginx/sites-available/vetmanager-mcp.conf"
${SUDO} tee "${NGINX_SITE}" >/dev/null <<EOF
server {
    listen 80;
    server_name ${SSL_DOMAIN};

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
EOF

${SUDO} ln -sfn "${NGINX_SITE}" /etc/nginx/sites-enabled/vetmanager-mcp.conf
if [ -f /etc/nginx/sites-enabled/default ]; then
  ${SUDO} rm -f /etc/nginx/sites-enabled/default
fi
${SUDO} nginx -t
${SUDO} systemctl reload nginx

# ── Build ─────────────────────────────────────────────────────────────────────
if [ -f Dockerfile ]; then
  UID_VAL="${DOCKER_UID:-$(id -u)}"
  GID_VAL="${DOCKER_GID:-$(id -g)}"
  if [ "${UID_VAL}" -eq 0 ]; then UID_VAL=1000; fi
  if [ "${GID_VAL}" -eq 0 ]; then GID_VAL=1000; fi
  docker build --build-arg UID="${UID_VAL}" --build-arg GID="${GID_VAL}" -t vetmanager-mcp .
else
  echo "WARNING: Dockerfile not found in ${REMOTE_DIR}, skipping image build."
fi

echo ""
echo "==> Init complete. Edit .env if needed, then run:"
echo "    docker compose up -d"
echo "==> Nginx configured for ${SSL_DOMAIN} on port 80."
REMOTE

echo "==> Done. Server is ready at ${SSH_TARGET}:${REMOTE_DIR}"
