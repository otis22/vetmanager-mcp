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

# ── PostgreSQL data & backup directories ──────────────────────────────────────
PG_DATA_DIR="/var/lib/vetmanager-postgres"
PG_BACKUP_DIR="/var/backups/vetmanager-postgres"
${SUDO} mkdir -p "${PG_DATA_DIR}" "${PG_BACKUP_DIR}"
${SUDO} chown "$(id -u):$(id -g)" "${PG_DATA_DIR}" "${PG_BACKUP_DIR}"
echo "--> Created ${PG_DATA_DIR} and ${PG_BACKUP_DIR}"

# ── .env ─────────────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    echo ""
    echo ">>> Created .env from .env.example."
  else
    echo "WARNING: .env.example not found in ${REMOTE_DIR}, skipping .env creation."
  fi
fi

# Generate POSTGRES_PASSWORD if not already set
if ! grep -q '^POSTGRES_PASSWORD=.\+' .env 2>/dev/null; then
  PG_PASS="$(openssl rand -base64 24 | tr -d '=/+' | head -c 32)"
  if grep -q '^POSTGRES_PASSWORD=' .env 2>/dev/null; then
    sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=${PG_PASS}|" .env
  else
    echo "POSTGRES_PASSWORD=${PG_PASS}" >> .env
  fi
  echo ">>> Generated POSTGRES_PASSWORD in .env"
fi

# Set DATABASE_URL if not already set
if ! grep -q '^DATABASE_URL=.\+' .env 2>/dev/null; then
  # Read the password we just set
  PG_PASS="$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2-)"
  PG_USER="$(grep '^POSTGRES_USER=' .env | cut -d= -f2- || true)"
  PG_USER="${PG_USER:-vetmanager}"
  DB_URL="postgresql+asyncpg://${PG_USER}:${PG_PASS}@postgres:5432/vetmanager"
  if grep -q '^# \?DATABASE_URL=' .env 2>/dev/null || grep -q '^DATABASE_URL=' .env 2>/dev/null; then
    sed -i "s|^#\? \?DATABASE_URL=.*|DATABASE_URL=${DB_URL}|" .env
  else
    echo "DATABASE_URL=${DB_URL}" >> .env
  fi
  echo ">>> Set DATABASE_URL in .env"
fi

echo ""
echo ">>> IMPORTANT: review ${REMOTE_DIR}/.env — verify POSTGRES_PASSWORD, STORAGE_ENCRYPTION_KEY, WEB_SESSION_SECRET."

# ── Backup cron job ───────────────────────────────────────────────────────────
CRON_FILE="/etc/cron.d/vetmanager-backup"
${SUDO} tee "${CRON_FILE}" >/dev/null <<CRON
# vetmanager-mcp PostgreSQL backups — twice daily
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
0 3,15 * * * root REMOTE_DIR=${REMOTE_DIR} ${REMOTE_DIR}/scripts/backup_postgres.sh >> /var/log/vetmanager-backup.log 2>&1
CRON
${SUDO} chmod 644 "${CRON_FILE}"
echo "--> Installed backup cron: ${CRON_FILE} (03:00, 15:00 daily)"

# ── Nginx reverse proxy with keepalive ────────────────────────────────────────
NGINX_SITE="/etc/nginx/sites-available/vetmanager-mcp.conf"
${SUDO} tee "${NGINX_SITE}" >/dev/null <<EOF
upstream mcp_backend {
    server 127.0.0.1:8000;
    keepalive 32;
}

server {
    listen 80;
    server_name ${SSL_DOMAIN};

    location / {
        proxy_pass http://mcp_backend;
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
  docker build --target production --build-arg UID="${UID_VAL}" --build-arg GID="${GID_VAL}" -t vetmanager-mcp .
else
  echo "WARNING: Dockerfile not found in ${REMOTE_DIR}, skipping image build."
fi

echo ""
echo "==> Init complete. Edit .env if needed, then run:"
echo "    docker compose --profile production up -d"
echo "==> Nginx configured for ${SSL_DOMAIN} on port 80 with upstream keepalive."
REMOTE

echo "==> Done. Server is ready at ${SSH_TARGET}:${REMOTE_DIR}"
