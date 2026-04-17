#!/usr/bin/env bash
# Mechanical workflow compliance checks for /deep-review.
# Outputs YAML findings to stdout in the same format as LLM reviewers.
#
# Usage:
#   ./scripts/review_workflow_check.sh [stage_number]
# If stage_number omitted, uses the last in-progress stage from Roadmap.md.

set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

emit() {
  # emit severity category file lines problem why_it_matters suggested_fix confidence
  local severity="$1" category="$2" file="$3" lines="$4"
  local problem="$5" why="$6" fix="$7" conf="$8"
  cat <<EOF
- severity: ${severity}
  reviewer: workflow-check
  category: ${category}
  file: ${file}
  lines: "${lines}"
  problem: "${problem}"
  why_it_matters: "${why}"
  suggested_fix: "${fix}"
  confidence: ${conf}
  codex_verdict: null
EOF
}

# 1. Detect current stage
STAGE="${1:-}"
if [ -z "$STAGE" ]; then
  # Find last in_progress line in Roadmap.md
  STAGE=$(grep -oE 'Этап [0-9]+.*in_progress' Roadmap.md 2>/dev/null | grep -oE '[0-9]+' | head -1 || true)
fi

if [ -z "$STAGE" ]; then
  # Fallback — latest done stage
  STAGE=$(grep -oE 'Этап [0-9]+' Roadmap.md 2>/dev/null | grep -oE '[0-9]+' | sort -n | tail -1 || echo "")
fi

# 2. PRD file for stage exists?
if [ -n "$STAGE" ]; then
  PRD_FILE=$(ls PRD/этап-${STAGE}-*.md 2>/dev/null | head -1 || true)
  if [ -z "$PRD_FILE" ]; then
    emit high missing_prd "Roadmap.md" "N/A" \
      "Stage ${STAGE} referenced but no PRD/этап-${STAGE}-*.md file exists" \
      "CLAUDE.md § 3 requires PRD before implementation" \
      "Create PRD/этап-${STAGE}-*.md with decomposition" \
      0.95
  fi
fi

# 3. Uncommitted diff size
STAGED_LOC=$(git diff --cached --stat 2>/dev/null | tail -1 | grep -oE '[0-9]+ (insertion|deletion)' | awk '{s+=$1} END {print s+0}')
UNSTAGED_LOC=$(git diff --stat 2>/dev/null | tail -1 | grep -oE '[0-9]+ (insertion|deletion)' | awk '{s+=$1} END {print s+0}')
TOTAL_LOC=$((STAGED_LOC + UNSTAGED_LOC))

if [ "$TOTAL_LOC" -gt 150 ]; then
  emit medium oversize_diff "git" "N/A" \
    "Uncommitted diff size is ${TOTAL_LOC} LOC" \
    "CLAUDE.md § 3 limits subtasks to ≤150 LOC; larger diffs suggest missed decomposition" \
    "Split into smaller commits or reconsider decomposition in PRD" \
    0.75
fi

# 4. Untracked Python files that should be tracked
UNTRACKED_PY=$(git ls-files --others --exclude-standard -- '*.py' 2>/dev/null | grep -v '^tests/' | grep -v '^\.' || true)
if [ -n "$UNTRACKED_PY" ]; then
  FILES_JOINED=$(echo "$UNTRACKED_PY" | tr '\n' ',' | sed 's/,$//')
  emit low untracked_code "${FILES_JOINED}" "N/A" \
    "Untracked Python files not in tests/ or hidden dirs" \
    "Forgotten git add likely" \
    "Run git status and decide git add or .gitignore" \
    0.7
fi

# 5. AssumptionLog entry for stage
if [ -n "$STAGE" ]; then
  if ! grep -qE "Этап ${STAGE}[[:space:].:]" AssumptionLog.md 2>/dev/null; then
    emit medium missing_assumption "AssumptionLog.md" "N/A" \
      "No entry for Stage ${STAGE} in AssumptionLog.md" \
      "CLAUDE.md § 6 requires AssumptionLog entry on completion" \
      "Add section 'Этап ${STAGE}: ...' with decisions and assumptions" \
      0.8
  fi
fi

# 6. Roadmap status for stage
if [ -n "$STAGE" ]; then
  STAGE_LINE=$(grep -m1 "Этап ${STAGE}" Roadmap.md 2>/dev/null || true)
  if ! echo "$STAGE_LINE" | grep -qE '\b(done|in_progress|stop|todo)\b'; then
    emit low roadmap_status_missing "Roadmap.md" "N/A" \
      "Stage ${STAGE} line has no explicit status marker" \
      "Roadmap.md is the single source of queue status" \
      "Add 'done' / 'in_progress' / 'stop' marker" \
      0.7
  fi
fi

# 7. Fast contour test hint (if any code changed)
if [ "$TOTAL_LOC" -gt 0 ]; then
  # Just a reminder finding — low confidence, informational
  emit low tests_reminder "tests/" "N/A" \
    "Uncommitted code changes detected (${TOTAL_LOC} LOC)" \
    "CLAUDE.md § 9 requires running the test suite before commit" \
    "Run: docker compose --profile test run --rm test" \
    0.5
fi

# 8. AssumptionLog coverage for ALL done stages (не только current)
# Parses Roadmap for every "## Этап N. ... — `done`" and verifies AssumptionLog
# has a matching section. Catches bulk gaps like stages 92-95 that review-
# workflow missed previously.
DONE_STAGES=$(grep -oE '^## Этап [0-9]+\.[^\n]*`done`' Roadmap.md 2>/dev/null | grep -oE '^## Этап [0-9]+' | grep -oE '[0-9]+' | sort -nu || true)
if [ -n "$DONE_STAGES" ]; then
  MISSING_LOG_STAGES=""
  for S in $DONE_STAGES; do
    # Accept: "## Этап N " / "## Этап N." / "## Этап N:" / "## Этап N-M" / "## Этап N–M" (em-dash)
    # The trick: N must be either at-line-end or followed by non-digit, to avoid "1" matching "13".
    if ! grep -qE "^## Этап ${S}([^0-9]|\$)" AssumptionLog.md 2>/dev/null; then
      MISSING_LOG_STAGES="${MISSING_LOG_STAGES}${S},"
    fi
  done
  MISSING_LOG_STAGES="${MISSING_LOG_STAGES%,}"
  if [ -n "$MISSING_LOG_STAGES" ]; then
    emit high missing_assumption_bulk "AssumptionLog.md" "N/A" \
      "Done stages without AssumptionLog entries: ${MISSING_LOG_STAGES}" \
      "CLAUDE.md § 6 mandates AssumptionLog entry per stage; bulk gaps mean review auditability broken" \
      "Backfill '## Этап N' sections for each listed stage" \
      0.95
  fi
fi

# 9. PRD section sanity — every PRD/этап-N-*.md должен иметь разделы Цель + Scope
for PRD in PRD/этап-*.md; do
  [ -f "$PRD" ] || continue
  if ! grep -qiE '^## Цель' "$PRD" 2>/dev/null; then
    BASENAME=$(basename "$PRD")
    emit low prd_missing_section "$PRD" "N/A" \
      "PRD ${BASENAME} has no '## Цель' section" \
      "CLAUDE.md § 3 mandates PRD with goal + decomposition" \
      "Add '## Цель' section (or '## Context' if retroactive)" \
      0.65
  fi
done

# 10. Review artifacts with active "Do not merge" verdict
#     — ищет baseline/super-review документы с активным блокирующим verdict
ACTIVE_VERDICTS=$(grep -lE '\*\*[Dd]o not merge\*\*' artifacts/review/*.md 2>/dev/null || true)
if [ -n "$ACTIVE_VERDICTS" ]; then
  for V in $ACTIVE_VERDICTS; do
    # Skip если уже есть "Resolution" section или superseded note
    if ! grep -qiE 'Resolution|superseded|resolved' "$V" 2>/dev/null; then
      emit medium unresolved_review "$V" "N/A" \
        "Review artifact carries active 'Do not merge' verdict without resolution note" \
        "Blocker-level verdict on merged code misleads future readers and tooling" \
        "Add '## Resolution' section listing which stages closed which findings, mark as superseded" \
        0.85
    fi
  done
fi

exit 0
