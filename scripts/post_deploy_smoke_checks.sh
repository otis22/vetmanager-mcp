#!/usr/bin/env bash
# post_deploy_smoke_checks.sh — базовые smoke checks после deploy/restart.
#
# Использование:
#   ./scripts/post_deploy_smoke_checks.sh [base_url] [public_domain]

set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:${PORT:-8000}}"
PUBLIC_DOMAIN="${2:-}"
SMOKE_MAX_ATTEMPTS="${SMOKE_MAX_ATTEMPTS:-10}"
SMOKE_SLEEP_SECONDS="${SMOKE_SLEEP_SECONDS:-1}"
SMOKE_REQUEST_MAX_TIME_SECONDS="${SMOKE_REQUEST_MAX_TIME_SECONDS:-5}"
TMP_DIR="$(mktemp -d)"

cleanup() {
  rm -rf "${TMP_DIR}"
}

preview_text() {
  printf '%s' "$1" | tr '\n' ' ' | head -c 200
}

# No curl on purpose: since stage 267 the production image does not carry it,
# and this script runs inside that image in tests. Python is present in both
# places, so one implementation serves the host and the container.
SMOKE_REQUEST_PY='
import os, sys, threading, urllib.error, urllib.request

url, max_time, body_file, *rest = sys.argv[1:]
deadline = float(max_time)


def give_up():
    # curl --max-time bounds the whole transfer. urlopen(timeout=...) bounds one
    # socket operation, so a peer dribbling a byte at a time would keep it alive
    # indefinitely — measured at ten seconds against a one-second limit.
    print("TimeoutError: exceeded %ss for the whole request" % deadline, file=sys.stderr)
    sys.stderr.flush()
    os._exit(7)


watchdog = threading.Timer(deadline, give_up)
watchdog.daemon = True
watchdog.start()

headers = {}
index = 0
while index < len(rest):
    if rest[index] == "-H" and index + 1 < len(rest):
        name, _, value = rest[index + 1].partition(":")
        headers[name.strip()] = value.strip()
        index += 2
    else:
        index += 1


class NoRedirects(urllib.request.HTTPRedirectHandler):
    # curl ran without -L: a 3xx is the answer, not a step towards one. Following
    # it would let a redirect to a healthy page hide a broken route.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


try:
    with urllib.request.build_opener(NoRedirects).open(
        urllib.request.Request(url, headers=headers), timeout=deadline
    ) as response:
        body, status = response.read(), response.status
except urllib.error.HTTPError as exc:
    body, status = exc.read(), exc.code
except Exception as exc:
    print("%s: %s" % (type(exc).__name__, exc), file=sys.stderr)
    sys.exit(7)

watchdog.cancel()
with open(body_file, "wb") as handle:
    handle.write(body)
print(status)
'

perform_request() {
  local url="$1"
  shift
  local body_file="${TMP_DIR}/body"
  local error_file="${TMP_DIR}/error"

  : > "${body_file}"
  : > "${error_file}"

  local status
  if status="$(python3 -c "${SMOKE_REQUEST_PY}" \
    "${url}" \
    "${SMOKE_REQUEST_MAX_TIME_SECONDS}" \
    "${body_file}" \
    "$@" 2> "${error_file}")"; then
    SMOKE_LAST_REQUEST_EXIT=0
  else
    SMOKE_LAST_REQUEST_EXIT=$?
    status=""
  fi

  SMOKE_LAST_STATUS="${status}"
  SMOKE_LAST_BODY="$(cat "${body_file}")"
  SMOKE_LAST_ERROR="$(cat "${error_file}")"
}

health_is_ok() {
  [ "${SMOKE_LAST_REQUEST_EXIT}" = "0" ] || return 1
  [ "${SMOKE_LAST_STATUS}" = "200" ] || return 1
  case "${SMOKE_LAST_BODY}" in
    *'"status":"ok"'*|*'"status": "ok"'*) return 0 ;;
  esac
  return 1
}

ready_is_ok() {
  [ "${SMOKE_LAST_REQUEST_EXIT}" = "0" ] || return 1
  [ "${SMOKE_LAST_STATUS}" = "200" ]
}

metrics_is_ok() {
  [ "${SMOKE_LAST_REQUEST_EXIT}" = "0" ] || return 1
  [ "${SMOKE_LAST_STATUS}" = "200" ] || return 1
  case "${SMOKE_LAST_BODY}" in
    *'vetmanager_http_requests_total'*) return 0 ;;
  esac
  return 1
}

mcp_status_is_ok() {
  [ "${SMOKE_LAST_REQUEST_EXIT}" = "0" ] || return 1
  [ "${SMOKE_LAST_STATUS}" -ge 200 ] && [ "${SMOKE_LAST_STATUS}" -lt 500 ]
}

retry_request() {
  local label="$1"
  local url="$2"
  local validator="$3"
  shift 3
  local attempt=1

  while [ "${attempt}" -le "${SMOKE_MAX_ATTEMPTS}" ]; do
    perform_request "${url}" "$@"
    if "${validator}"; then
      return 0
    fi

    echo "--> ${label} attempt ${attempt}/${SMOKE_MAX_ATTEMPTS} failed: url=${url} request_exit=${SMOKE_LAST_REQUEST_EXIT} http_status=${SMOKE_LAST_STATUS:-000} body=$(preview_text "${SMOKE_LAST_BODY}") error=$(preview_text "${SMOKE_LAST_ERROR}")"

    if [ "${attempt}" -lt "${SMOKE_MAX_ATTEMPTS}" ]; then
      sleep "${SMOKE_SLEEP_SECONDS}"
    fi
    attempt=$((attempt + 1))
  done

  echo "ERROR: ${label} failed after ${SMOKE_MAX_ATTEMPTS} attempts: url=${url} request_exit=${SMOKE_LAST_REQUEST_EXIT} http_status=${SMOKE_LAST_STATUS:-000} body=$(preview_text "${SMOKE_LAST_BODY}") error=$(preview_text "${SMOKE_LAST_ERROR}")"
  return 1
}

trap cleanup EXIT

echo "==> Running post-deploy smoke checks against ${BASE_URL}"

retry_request "healthz" "${BASE_URL}/healthz" health_is_ok
retry_request "readyz" "${BASE_URL}/readyz" ready_is_ok
METRICS_AUTH_ARGS=()
if [ -n "${METRICS_AUTH_TOKEN:-}" ]; then
  METRICS_AUTH_ARGS=(-H "Authorization: Bearer ${METRICS_AUTH_TOKEN}")
fi
retry_request "metrics" "${BASE_URL}/metrics" metrics_is_ok "${METRICS_AUTH_ARGS[@]+"${METRICS_AUTH_ARGS[@]}"}"
retry_request "mcp" "${BASE_URL}/mcp" mcp_status_is_ok

if [ -n "${PUBLIC_DOMAIN}" ]; then
  echo "--> Checking public HTTPS endpoint for ${PUBLIC_DOMAIN}"
  retry_request "public_mcp" "https://${PUBLIC_DOMAIN}/mcp" mcp_status_is_ok
fi

echo "==> Post-deploy smoke checks passed."
