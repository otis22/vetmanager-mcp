#!/usr/bin/env bash
# Retry the known public ECR base-image pull limit, never a failed test/build step.
set -euo pipefail

if [ "$#" -lt 2 ] || [ "$1" != docker ] || [ "$2" != build ]; then
  echo 'usage: retry_ecr_build.sh docker build ...' >&2
  exit 2
fi

log_file="$(mktemp)"
trap 'rm -f "$log_file"' EXIT

for attempt in 1 2 3; do
  echo "Docker build attempt ${attempt}/3"
  if "$@" >"$log_file" 2>&1; then
    cat "$log_file"
    exit 0
  else
    status=$?
  fi
  cat "$log_file"

  # BuildKit prints its terminal failure as an ERROR line. Earlier ECR errors
  # must not justify retrying a later Dockerfile failure in the same build.
  final_error="$(grep -E '^ERROR: failed to (build|solve):' "$log_file" | tail -n 1 || true)"
  if [[ "$final_error" != *'public.ecr.aws/docker/library/python:3.12-slim'* ]] ||
     [[ "$final_error" != *'toomanyrequests: Data limit exceeded'* ]] ||
     [[ "$final_error" != *'failed to resolve source metadata'* &&
        "$final_error" != *'failed to copy'* ]]; then
    echo "Docker build failed with exit ${status}; no retry (not the known ECR pull limit)" >&2
    exit "$status"
  fi

  if [ "$attempt" -eq 3 ]; then
    echo "Docker build failed with exit ${status}; ECR retry limit reached" >&2
    exit "$status"
  fi
  if [ "$attempt" -eq 1 ]; then delay=5; else delay=15; fi
  echo "ECR pull limit detected; retrying Docker build after ${delay}s" >&2
  sleep "$delay"
done
