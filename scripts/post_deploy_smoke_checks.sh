#!/usr/bin/env bash
# post_deploy_smoke_checks.sh — базовые smoke checks после deploy/restart.
#
# Использование:
#   ./scripts/post_deploy_smoke_checks.sh [base_url] [public_domain]

set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:${PORT:-8000}}"
PUBLIC_DOMAIN="${2:-}"

echo "==> Running post-deploy smoke checks against ${BASE_URL}"

health_json="$(curl -fsS "${BASE_URL}/healthz")"
ready_body=""
ready_status="$(curl -sS -o /tmp/vm-readyz-body.$$ -w '%{http_code}' "${BASE_URL}/readyz")"
ready_body="$(cat /tmp/vm-readyz-body.$$)"
rm -f /tmp/vm-readyz-body.$$
metrics_body="$(curl -fsS "${BASE_URL}/metrics")"
mcp_status="$(curl -sS -o /dev/null -w '%{http_code}' "${BASE_URL}/mcp" || true)"

case "${health_json}" in
  *'"status":"ok"'*|*'"status": "ok"'*) ;;
  *)
    echo "ERROR: /healthz did not report ok: ${health_json}"
    exit 1
    ;;
esac

if [ "${ready_status}" != "200" ]; then
  echo "ERROR: /readyz returned ${ready_status}: ${ready_body}"
  exit 1
fi

case "${metrics_body}" in
  *'vetmanager_http_requests_total'* ) ;;
  *)
    echo "ERROR: /metrics does not expose expected Prometheus families."
    exit 1
    ;;
esac

if [ "${mcp_status}" -lt 200 ] || [ "${mcp_status}" -ge 500 ]; then
  echo "ERROR: /mcp returned unexpected status ${mcp_status}"
  exit 1
fi

if [ -n "${PUBLIC_DOMAIN}" ]; then
  echo "--> Checking public HTTPS endpoint for ${PUBLIC_DOMAIN}"
  public_status="$(curl -sS -o /dev/null -w '%{http_code}' "https://${PUBLIC_DOMAIN}/mcp" || true)"
  if [ "${public_status}" -lt 200 ] || [ "${public_status}" -ge 500 ]; then
    echo "ERROR: public HTTPS /mcp returned unexpected status ${public_status}"
    exit 1
  fi
fi

echo "==> Post-deploy smoke checks passed."
