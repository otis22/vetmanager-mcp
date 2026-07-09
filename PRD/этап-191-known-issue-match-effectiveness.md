# Stage 191. Known issue match effectiveness

## Контекст

Product metrics show `known_issue_match_events=0` за 30 дней, while feedback
reports are linked and active workaround known issues exist. This may mean the
match path is unused, too narrow, or insufficiently observable.

## Цель

Improve confidence in known issue matching and diagnostics without editing
production known issues as the primary artifact.

## Архитектурное решение

Проблема: owner sees 0 match events but cannot distinguish "no matching errors"
from "match/injection path broken".

Ограничения:
- production DB is source of truth for known issues;
- raw feedback/details may contain PII and must not be printed by diagnostics;
- repo changes should be tests/diagnostics/docs, not ad-hoc triage artifacts.

Варианты:
- broaden production match rules immediately: risky without a concrete report;
- add diagnostics and regression tests first: safer.

Выбор: add deterministic tests around match event write/no-match path and extend
triage diagnostics with aggregate-only output.

Инварианты:
- no raw report details in CLI output;
- no automatic code fixes from feedback;
- known issue playbooks only returned for validated `workaround_available`
  issues.

Rollback: revert diagnostics/tests; production data remains untouched.

Architecture Critique: required because this touches feedback/known issue
production behavior and privacy boundary.

## Scope

1. Add/extend tests for known issue matching and event writes.
2. Add aggregate-only triage diagnostics command for recent match effectiveness.
3. Update README/AssumptionLog with interpretation of zero match events.

## Out of scope

- Changing production known issue rows unless a concrete defect is found.
- Printing raw feedback details.
- New feedback schema migration.

## Acceptance Criteria

1. Tests prove matching writes `known_issue_match_events`.
2. Tests prove no-match path does not write false events.
3. CLI diagnostic shows counts by source/status and no raw report text.
4. Product metrics interpretation remains aggregate-only.

## Tests

- Focused unit tests around `agent_feedback_service` match helpers.
- CLI/format test for diagnostics if practical.

## Rollout

Deploy normally. Post-deploy smoke includes running aggregate diagnostic against
prod and confirming no raw details are emitted.
