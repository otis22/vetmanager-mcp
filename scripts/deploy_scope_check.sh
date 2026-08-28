#!/usr/bin/env bash
# Stage 254.3: decide whether a pushed range needs a production deploy.
#
# Reads NUL-separated paths on stdin — the form `git diff --name-only -z`
# produces. The separator is the point of this script existing: plain
# `--name-only` escapes non-ASCII paths into octal and wraps them in quotes
# (`"PRD/\321\215...md"`), and every PRD in this repository is named in
# Russian. A documentation commit therefore read as a code commit, and prod
# was recreated for a text change.
#
# Prints `true` when anything outside PRD/, docs/ and *.md changed, and
# `false` otherwise. An empty list prints `true`: a deploy is never skipped
# on the strength of a list we failed to obtain.
set -euo pipefail

# The whole list is read even once the answer is known: leaving early would
# close the pipe under a still-writing `git diff`, and that becomes exit 141
# the moment this step runs under `pipefail` — for code commits only.
seen_any=false
needs_deploy=false

while IFS= read -r -d '' path; do
  seen_any=true
  case "${path}" in
    PRD/*|docs/*|*.md) ;;
    *) needs_deploy=true ;;
  esac
done

if [ "${seen_any}" = false ]; then
  needs_deploy=true
fi

echo "${needs_deploy}"
