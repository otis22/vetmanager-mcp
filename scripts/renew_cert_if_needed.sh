#!/usr/bin/env bash
# renew_cert_if_needed.sh — выпуск/обновление TLS-сертификата для MCP-хоста.
#
# Использование:
#   ./scripts/renew_cert_if_needed.sh [domain]
#
# Переменные:
#   CERTBOT_EMAIL   email для Let's Encrypt (опционально)
#   RENEW_DAYS      порог продления в днях (по умолчанию 30)

set -euo pipefail

DOMAIN="${1:-${SSL_DOMAIN:-342915.simplecloud.ru}}"
CERTBOT_EMAIL="${CERTBOT_EMAIL:-}"
RENEW_DAYS="${RENEW_DAYS:-30}"
CERT_PATH="/etc/letsencrypt/live/${DOMAIN}/fullchain.pem"

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
else
  SUDO="sudo"
fi

issue_certificate() {
  echo "--> Issuing new certificate for ${DOMAIN}..."
  if [ -n "${CERTBOT_EMAIL}" ]; then
    ${SUDO} certbot --nginx --non-interactive --agree-tos --redirect \
      --email "${CERTBOT_EMAIL}" -d "${DOMAIN}"
  else
    echo "WARNING: CERTBOT_EMAIL is empty, using --register-unsafely-without-email."
    ${SUDO} certbot --nginx --non-interactive --agree-tos --redirect \
      --register-unsafely-without-email -d "${DOMAIN}"
  fi
}

echo "==> Checking TLS certificate for ${DOMAIN} (threshold: ${RENEW_DAYS} days)"

if [ ! -f "${CERT_PATH}" ]; then
  issue_certificate
else
  if ${SUDO} openssl x509 -checkend "$((RENEW_DAYS * 86400))" -noout -in "${CERT_PATH}"; then
    echo "--> Certificate is valid for at least ${RENEW_DAYS} more days. No renewal needed."
  else
    echo "--> Certificate expires in less than ${RENEW_DAYS} days. Running certbot renew..."
    ${SUDO} certbot renew --non-interactive --quiet
  fi
fi

${SUDO} nginx -t
${SUDO} systemctl reload nginx

echo "==> TLS check/update complete for ${DOMAIN}"
