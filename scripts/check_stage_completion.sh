#!/usr/bin/env bash
# Per-stage completion checker — runs after finishing a stage to verify
# that all workflow compliance boxes are checked.
#
# Usage:
#   ./scripts/check_stage_completion.sh <stage_number>
#   ./scripts/check_stage_completion.sh           # auto-detect from last commit
#
# Exit codes:
#   0 — stage is fully compliant
#   1 — one or more high-severity findings (missing PRD / AssumptionLog /
#       Roadmap status / test suite not run)
#   2 — usage error
#
# Output: YAML findings list (same format as review_workflow_check.sh)
# + human-readable summary to stderr.

set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

emit() {
  local severity="$1" category="$2" file="$3" lines="$4"
  local problem="$5" why="$6" fix="$7" conf="$8"
  cat <<EOF
- severity: ${severity}
  reviewer: stage-completion
  category: ${category}
  file: ${file}
  lines: "${lines}"
  problem: "${problem}"
  why_it_matters: "${why}"
  suggested_fix: "${fix}"
  confidence: ${conf}
EOF
}

FAIL=0

# ── 1. Resolve stage number ─────────────────────────────────────────────────

STAGE="${1:-}"
if [ -z "$STAGE" ]; then
  # Parse from last commit message "Stage N: ..."
  STAGE=$(git log -1 --pretty=%s | grep -oE '[Ss]tage [0-9]+' | grep -oE '[0-9]+' | head -1 || true)
fi

if [ -z "$STAGE" ]; then
  echo "ERROR: could not determine stage number. Pass as arg or ensure last commit message starts with 'Stage N:'." >&2
  exit 2
fi

echo "# stage-completion check for Stage ${STAGE}" >&2

# ── 2. PRD file exists ──────────────────────────────────────────────────────

PRD_FILE=$(ls PRD/этап-${STAGE}-*.md 2>/dev/null | head -1 || true)
if [ -z "$PRD_FILE" ]; then
  emit high missing_prd "Roadmap.md" "N/A" \
    "Stage ${STAGE} has no PRD/этап-${STAGE}-*.md" \
    "CLAUDE.md § 3 mandates PRD before implementation" \
    "Create retroactive PRD referencing AssumptionLog if needed" \
    0.95
  FAIL=1
else
  echo "  ✓ PRD exists: ${PRD_FILE}" >&2
fi

# ── 3. AssumptionLog entry exists ───────────────────────────────────────────

if ! grep -qE "^## Этап ${STAGE}[[:space:].:]" AssumptionLog.md 2>/dev/null; then
  emit high missing_assumption "AssumptionLog.md" "N/A" \
    "No '## Этап ${STAGE}' section in AssumptionLog.md" \
    "CLAUDE.md § 6 requires AssumptionLog entry as completion criterion" \
    "Add '## Этап ${STAGE}. <title>' with what was done / deferred / Codex outcome" \
    0.95
  FAIL=1
else
  echo "  ✓ AssumptionLog entry exists" >&2
fi

# ── 4. Roadmap status ≠ in_progress ─────────────────────────────────────────

STAGE_LINE=$(grep -m1 "^## Этап ${STAGE}\." Roadmap.md 2>/dev/null || true)
if [ -z "$STAGE_LINE" ]; then
  emit high missing_roadmap_header "Roadmap.md" "N/A" \
    "No '## Этап ${STAGE}. ...' header in Roadmap.md" \
    "Roadmap is the single source of queue status" \
    "Add roadmap entry for stage ${STAGE}" \
    0.9
  FAIL=1
elif echo "$STAGE_LINE" | grep -qE '\bin_progress\b|\btodo\b'; then
  emit medium stage_still_open "Roadmap.md" "N/A" \
    "Stage ${STAGE} header still marked in_progress/todo" \
    "Completion check expects done/stop/partially done after commit" \
    "Update Roadmap: '— \`done\`' or explicit '— \`stop\`'" \
    0.8
  FAIL=1
else
  echo "  ✓ Roadmap marker set" >&2
fi

# ── 5. Commit message prefix ────────────────────────────────────────────────

LAST_MSG=$(git log -1 --pretty=%s 2>/dev/null || true)
if ! echo "$LAST_MSG" | grep -qiE "^stage ${STAGE}[:.]"; then
  emit medium weak_commit_prefix "git" "N/A" \
    "Last commit message does not start with 'Stage ${STAGE}:'" \
    "Helps mechanical stage detection (auto-mode of this script + audits)" \
    "Reformat commit or amend: 'Stage ${STAGE}: <what>'" \
    0.65
fi

# ── 6. Tests were run (heuristic via .pytest_cache mtime) ───────────────────

if [ -d .pytest_cache ]; then
  CACHE_MTIME=$(stat -c %Y .pytest_cache 2>/dev/null || stat -f %m .pytest_cache 2>/dev/null || echo 0)
  LAST_COMMIT_TS=$(git log -1 --pretty=%ct 2>/dev/null || echo 0)
  if [ "$CACHE_MTIME" -lt "$LAST_COMMIT_TS" ]; then
    emit medium tests_possibly_stale "tests/" "N/A" \
      "pytest cache older than last commit — tests may not have run on final code" \
      "CLAUDE.md § 4 requires test suite pass before commit" \
      "Run: docker compose --profile test run --rm test" \
      0.55
  else
    echo "  ✓ pytest cache newer than last commit" >&2
  fi
fi

# ── 7. Codex review trace in commit message or AssumptionLog ────────────────

CODEX_MENTIONED=0
echo "$LAST_MSG" | grep -qiE 'codex' && CODEX_MENTIONED=1
COMMIT_BODY=$(git log -1 --pretty=%B 2>/dev/null || true)
echo "$COMMIT_BODY" | grep -qiE 'codex' && CODEX_MENTIONED=1
grep -A 30 "^## Этап ${STAGE}\." AssumptionLog.md 2>/dev/null | grep -qiE 'codex|пропущен' && CODEX_MENTIONED=1

if [ "$CODEX_MENTIONED" -eq 0 ]; then
  emit medium missing_codex_trace "commit|AssumptionLog" "N/A" \
    "No Codex review outcome (or justified skip) mentioned for stage ${STAGE}" \
    "CLAUDE.md § 5 mandates Codex review before commit; skip per § 5.5 requires explicit reason" \
    "Add to commit body or AssumptionLog: 'Codex review: <findings>' or 'Codex review пропущен — <reason>'" \
    0.7
fi

# ── 8. Diff size sanity ─────────────────────────────────────────────────────

STAGE_COMMITS=$(git log --pretty=%H --grep="^[Ss]tage ${STAGE}[:.]" 2>/dev/null | head -5)
if [ -n "$STAGE_COMMITS" ]; then
  FIRST_STAGE_COMMIT=$(echo "$STAGE_COMMITS" | tail -1)
  LAST_STAGE_COMMIT=$(echo "$STAGE_COMMITS" | head -1)
  BASE=$(git merge-base "$FIRST_STAGE_COMMIT"^ HEAD 2>/dev/null || echo "$FIRST_STAGE_COMMIT"^)
  TOTAL_STAGE_LOC=$(git diff --shortstat "$BASE"..."$LAST_STAGE_COMMIT" 2>/dev/null | grep -oE '[0-9]+ (insertion|deletion)' | awk '{s+=$1} END {print s+0}')
  if [ "$TOTAL_STAGE_LOC" -gt 500 ]; then
    emit low oversize_stage "git" "N/A" \
      "Stage ${STAGE} total diff is ${TOTAL_STAGE_LOC} LOC (>500 soft cap)" \
      "CLAUDE.md § 3 expects subtasks ≤150 LOC; stage as whole aggregate <500 ideal" \
      "Consider splitting into X-a/X-b sub-stages if not already" \
      0.55
  fi
fi

# ── 9. Summary ──────────────────────────────────────────────────────────────

if [ "$FAIL" -eq 0 ]; then
  echo "" >&2
  echo "✅ Stage ${STAGE} completion check passed (all high-severity items OK)." >&2
  exit 0
else
  echo "" >&2
  echo "❌ Stage ${STAGE} completion check has high-severity gaps — see YAML findings above." >&2
  exit 1
fi
