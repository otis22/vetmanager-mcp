# Super-review: changed stage 135

_Дата: 2026-04-24_
_Scope: changed (`HEAD~1..HEAD`, stage 135 docs-only)_
_Commit reviewed: `ba392b5 Stage 135: Sync technical docs after presets`_
_Runtime: Codex_

## Review Matrix

- Spark scout: `gpt-5.3-codex-spark` via Codex CLI, 3 passes; no findings.
- Reviewer roles: code, architecture, simplicity, docs, security, performance-and-reliability, observability, tests, product, codex-blindspot.
- Workflow check: `scripts/review_workflow_check.sh 135`; no findings.
- Cross-model arbitration: Claude Opus; all top findings confirmed.

Runtime limitations:
- Scope `changed` was interpreted as `HEAD~1..HEAD`, because `origin/main...HEAD` was empty after push and there were no uncommitted files.
- Codex CLI stderr includes verbose prompt/session logs; reviewer outputs were still valid YAML.
- Spark output was treated as untrusted candidate-only.

## Verdict

**Do not merge as final docs cleanup without follow-up fixes.**

No runtime/code blockers were found, but the docs-only stage still has confirmed documentation defects that can mislead future agents and operators. The main risks are a stale full-access acceptance criterion, a wrong Prometheus metric name in operations guidance, and an incident-response path that points sanitizer failures to the wrong primary signal.

## Top Findings

### F1. Historical Stage 28 PRD still says new tokens default full-access

```yaml
severity: high
reviewer: architecture/product/security/tests/codex-blindspot
category: docs-contract-drift
file: PRD/этап-28-future-scopes-rbac-bearer-tokens.md
lines: "113-118"
problem: >
  Stage 135 added a compatibility note that current stage 130+ token issuance is
  preset-based, but the Stage 28 Acceptance Criteria still says:
  "Новые токены получают default full-access scopes."
why_it_matters: >
  This directly contradicts the current security contract. Future agents can
  treat the stale acceptance criterion as authoritative and reintroduce
  over-privileged default token issuance.
suggested_fix: >
  Mark the criterion historical/superseded: legacy no-scope tokens remain
  full-access compatible, while newly issued tokens use selected preset scopes;
  only the `full_access` preset expands to all supported scopes.
confidence: 0.95
```

Claude arbitration: confirmed, severity high.

### F2. Operations readiness uses a non-existent metric family

```yaml
severity: high
reviewer: tests/workflow
category: runbook-coverage
file: artifacts/operations-readiness-vetmanager-mcp-ru.md
lines: "98-102"
problem: >
  Alert guidance references `auth_failures_total{source="metrics",reason="invalid_token"}`,
  but the actual metric is `vetmanager_auth_failures_total{source="metrics",reason="invalid_token"}`.
why_it_matters: >
  An alert copied from this runbook would not match the real Prometheus series,
  so invalid `/metrics` auth failures could be missed during operations.
suggested_fix: >
  Prefix all auth failure alert metric examples in the runbook with
  `vetmanager_`.
confidence: 0.99
```

Claude arbitration: confirmed, severity high.

### F3. Sanitizer failure investigation points to token audit as primary signal

```yaml
severity: medium
reviewer: observability/performance-and-reliability
category: incident-debuggability
file: artifacts/operations-readiness-vetmanager-mcp-ru.md
lines: "103-104"
problem: >
  The runbook says sanitizer failures should be investigated through
  `token_audit_log_committed`, but sanitizer failures are data-path incidents.
  Token audit is a generic token usage/lifecycle signal and is not guaranteed
  to be the primary failure context.
why_it_matters: >
  During a privacy fail-closed incident, responders need request-scoped
  runtime/security logs and correlation IDs first. The current text can send
  on-call responders down a slower or empty investigation path.
suggested_fix: >
  Point first to `vetmanager_sanitizer_failures_total` plus request/correlation
  IDs in runtime/security logs and the observability runbook. Mention
  `token_audit_log_committed` only as supplemental token trail when related.
confidence: 0.89
```

Claude arbitration: confirmed, severity medium.

### F4. Technical requirements still call scope policy "future"

```yaml
severity: medium
reviewer: code/codex-blindspot
category: stale-wording
file: artifacts/technical-requirements-vetmanager-mcp-ru.md
lines: "550-551"
problem: >
  Security requirements still say "future scope policy", while the same
  document now describes stage 130+ runtime scope enforcement as current.
why_it_matters: >
  This leaves a future-only phrasing in the document stage 135 was meant to
  correct and can confuse whether scope enforcement is live.
suggested_fix: >
  Replace with "token scope policy" or another current-state wording.
confidence: 0.87
```

Claude arbitration: confirmed, severity medium.

### F5. Audit log event is listed under metrics

```yaml
severity: medium
reviewer: observability
category: metrics-log-taxonomy
file: artifacts/technical-requirements-vetmanager-mcp-ru.md
lines: "683-691"
problem: >
  Section `Observability metrics` includes `token_audit_log_committed`, which
  is a structured audit/log event, not a Prometheus metric family.
why_it_matters: >
  Mixing metrics and log event taxonomy can send operators to the wrong backend
  and perpetuates observability documentation drift.
suggested_fix: >
  Keep the metrics list metric-only and move `token_audit_log_committed` into a
  separate `Audit/log events` subsection.
confidence: 0.95
```

Claude arbitration: confirmed, severity medium.

### F6. Stage 135 verification grep omits README and SECURITY

```yaml
severity: medium
reviewer: tests/workflow
category: verification-gap
file: PRD/этап-135-technical-docs-drift-cleanup.md
lines: "52-60"
problem: >
  The stale-wording grep path includes `artifacts/ PRD/ Roadmap.md`, but not
  `README.md` or `SECURITY.md`, both modified by stage 135.
why_it_matters: >
  The docs-cleanup workflow can pass while user-facing docs retain stale token,
  preset, or privacy wording.
suggested_fix: >
  Expand verification to all modified docs, or use a durable command such as
  `git ls-files '*.md' | xargs rg ...`.
confidence: 0.97
```

Claude arbitration: confirmed, severity medium.

## Dismissed / Not Accepted

- Spark scout findings: none.
- Broad claim "Scope 7 makes stage 135 open-ended housekeeping" was not kept as a top finding. It is directionally useful process feedback, but the current confirmed defects are concrete and cheaper to fix directly.
- Product finding that operations docs do not mention correlation/audit was consolidated into F3/F5, which give the actionable correction.

## Systemic Observations

- Docs-only stages need repo-wide markdown grep checks, not hand-curated path lists.
- Metric names should be verified against code-exported metric families; missing `vetmanager_` prefixes are operationally risky.
- Historical PRDs should use explicit "superseded by stage N" markers instead of mixing current corrections into old acceptance text.
- Incident-response wording in operations docs should be treated as high-risk when it prescribes the wrong signal path.

## Suggested Follow-Up

Create a small docs hotfix stage to address F1-F6, run `scripts/review_workflow_check.sh`, grep all markdown docs for stale token/scope/metric wording, and re-run the standard docs-only review gate.

## Follow-Up

- Stage 136 was added to Roadmap to close all high/medium findings F1-F6.
- Closure: stage 136 docs hotfix; see `Roadmap.md` §136 and
  `PRD/этап-136-docs-hotfix-after-stage-135-super-review.md`.
