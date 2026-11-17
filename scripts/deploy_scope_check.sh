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
# Only explicit documentation and CI inputs may skip deployment. The caller
# supplies the whole diff from the actual last successful deployment, with
# rename detection disabled so both sides of a rename are classified.
set -euo pipefail

# The whole list is read even once the answer is known: leaving early would
# close the pipe under a still-writing `git diff`, and that becomes exit 141
# the moment this step runs under `pipefail` — for code commits only.
seen_any=false
needs_deploy=false
path=""

while IFS= read -r -d '' path; do
  seen_any=true
  case "${path}" in
    ''|/*|*//*|*\\*|./*|../*|*/./*|*/../*|*/.|*/..|*[[:cntrl:]]*) needs_deploy=true ;;
    README.md|Roadmap.md|Roadmap-archive.md|AssumptionLog.md|PRD/*.md|docs/*.md) ;;
    .github/workflows/test.yml|.github/workflows/docs.yml|.github/workflows/shellcheck.yml|.github/workflows/test-real.yml) ;;
    scripts/ci_scope.py|scripts/check_roadmap_structure.py|scripts/offline_gate_manifest.py) ;;
    scripts/run_fast_test_suite.py|scripts/run_default_test_suite.py|scripts/run_isolated_test_suite.py|scripts/run_opt_in_real_test_suite.py) ;;
    scripts/default_node_inventory.json|scripts/postgres_node_inventory.json|scripts/real_group_manifest.json|scripts/offline_integration_files.json) ;;
    tests/test_*.py)
      # In a case pattern '*' also matches '/'; only root test modules qualify.
      if [[ "${path#tests/}" == */* ]]; then needs_deploy=true; fi
      ;;
    *) needs_deploy=true ;;
  esac
done

if [ "${seen_any}" = false ] || [ -n "${path}" ]; then
  needs_deploy=true
fi

echo "${needs_deploy}"
