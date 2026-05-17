# Stage 165 Discovery Manifest

Date: 2026-05-17

Source snapshot for discovery: commit:4f309031cf0023bfc68b3c2516746b9d06226e60

This manifest records which sources were treated as finding sources for Stage 165. It intentionally stores paths and classifications only; it does not reproduce raw secrets, raw tokens, clinic data, or concrete personal data.

## Finding Source Files

Review artifacts:

- `artifacts/review/2026-04-17-baseline-post-stage-84.md`
- `artifacts/review/2026-04-17-post-stages-85-95.md`
- `artifacts/review/2026-04-18-changed-stage-104.md`
- `artifacts/review/2026-04-19-changed-105-110-stage-110.md`
- `artifacts/review/2026-04-20-full-stage-121.md`
- `artifacts/review/2026-04-23-full-stage-130.md`
- `artifacts/review/2026-04-24-changed-stage-135.md`
- `artifacts/review/2026-04-24-full-stage-136.md`
- `artifacts/review/2026-04-26-changed-stage-150-prod.md`
- `artifacts/review/2026-04-30-changed-stage-150-152.md`
- `artifacts/review/inadequate-findings-index.md`
- `artifacts/review/kimi-usage-stats.md`

Security artifacts:

- `artifacts/security-threat-model-vetmanager-mcp-ru.md`
- `artifacts/security/stage-163-pattern-scan-triage.md`
- `artifacts/security/stage-164-openapi-privacy-audit.md`
- `artifacts/security/stage-164-openapi-structure-baseline.json`

Broad-scope artifacts reviewed with negative or already-covered results:

- `artifacts/security-deployment-notes-vetmanager-mcp-ru.md` — deployment secret separation, trusted proxy, host validation, and regression subset are current controls; no accepted unfixed High/Critical finding.
- `artifacts/architecture-review-vetmanager-mcp-ru.md` — architecture/refactor recommendations only; no accepted High/Critical security/privacy finding.
- `artifacts/tech-debt-register-vetmanager-mcp-ru.md` — historical architecture/tech-debt severities TD-46/55/61 are represented by Roadmap stages 58-67 or are not security/privacy findings; no accepted unfixed High/Critical security/privacy finding.
- `artifacts/operations-readiness-vetmanager-mcp-ru.md` — operations guidance; Stage 136 fixed the metrics-auth metric-name drift; no accepted unfixed High/Critical finding.
- `artifacts/release-checklist-vetmanager-mcp-ru.md` — release/deploy checklist; no accepted unfixed High/Critical finding.
- `artifacts/runbook-operator-ip-mask.md` — operator runbook uses metadata-only SQL examples and explicit anti-patterns; no accepted unfixed High/Critical finding.
- `artifacts/observability-runbook-vetmanager-mcp-ru.md` — operations guidance; Stage 136/141 fixed known metric/auth guidance drift; no accepted unfixed High/Critical finding.
- `artifacts/api-research-notes-ru.md` — API research notes; no accepted unfixed High/Critical security/privacy finding.
- `artifacts/api_entity_reference-ru.md` — entity reference; no accepted unfixed High/Critical security/privacy finding.

Workflow and planning evidence:

- `Roadmap.md`
- `AssumptionLog.md`
- `artifacts/security/stage-165-sweep-files.txt`
- `PRD/этап-150-agent-feedback-pii-guardrails.md`
- `PRD/этап-163-historical-api-key-literal-redaction.md`
- `PRD/этап-164-openapi-artifact-pii-sanitization.md`
- `PRD/этап-165-critical-security-findings-inventory.md`

PRD source coverage:

- Security/review/follow-up PRDs matched by the Stage 165 vocabulary sweep are persisted in `artifacts/security/stage-165-sweep-files.txt`.
- PRDs directly used as inventory source rows: `PRD/этап-111-blocker-cleanup.md`, `PRD/этап-150-agent-feedback-pii-guardrails.md`, `PRD/этап-163-historical-api-key-literal-redaction.md`, `PRD/этап-164-openapi-artifact-pii-sanitization.md`, and `PRD/этап-165-critical-security-findings-inventory.md`.

## Enumeration Commands

Review artifact list:

```sh
find artifacts/review -maxdepth 1 -type f | sort
```

Security artifact list:

```sh
find artifacts/security -maxdepth 1 -type f | sort
```

Repo-wide security vocabulary sweep used for out-of-scope grouping:

```sh
rg -l -i "critical|blocker|high|security|privacy|secret|credential|token|bearer|auth|deploy|pii|personal|exposure|leak|rate.limit|csrf|ssrf|rce|dos|access control|scope" .
```

Persisted output: `artifacts/security/stage-165-sweep-files.txt`.

Explicit exclusions applied for the persisted sweep:

- `.git/**`
- `.venv/**`
- `node_modules/**`
- `.pytest_cache/**`
- `htmlcov/**`
- `dist/**`
- `build/**`

## Out-Of-Scope Source Groups

The repo-wide sweep also matched source, test, config, migration, and generated/reference files where the match was an implementation identifier, environment variable name, fixture name, or current code path rather than an accepted finding. Concrete findings from those paths were inventoried through the review, PRD, Roadmap, AssumptionLog, or security artifacts above.

Grouped examples:

- Runtime source and scripts: `auth/`, `tools/`, `resources/`, `vm_transport/`, `web*.py`, `service_metrics.py`, `host_resolver.py`, `scripts/`.
- Tests and fixtures: `tests/`, `conftest.py`, migration regression tests, smoke-check tests.
- Config and deployment plumbing: `.github/workflows/`, `docker-compose*.yml`, `scripts/init_server.sh`, deploy/backup/rollback scripts.
- Historical/reference material: `artifacts/`, `PRD/`, README/security/runbook documents, where accepted findings are already represented by the scoped finding sources.
