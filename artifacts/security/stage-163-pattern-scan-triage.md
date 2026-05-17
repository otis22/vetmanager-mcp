# Stage 163 Pattern Scan Triage — 2026-05-17

## Scope

Command:

```bash
git grep -nE '([[:xdigit:]]{32}|[A-Za-z0-9_-]{40,})' -- ':!artifacts/vetmanager_openapi_v6.json'
```

`artifacts/vetmanager_openapi_v6.json` is excluded here because concrete emails and `passwd` hash-like examples are owned by Stage 164.

## Result

No unclassified matches remain for Stage 163.

The exact historical `devtr6` API key literal is checked by `scripts/check_no_historical_api_key_literal.py` via SHA-256 fingerprint only; the raw literal is not stored in this artifact or in the script.

## Classified Families

| Family | Classification | Evidence |
| --- | --- | --- |
| Exact historical `devtr6` API key literal | Fixed in current tree | Hash-based check returns no tracked-file matches after AssumptionLog redaction. |
| Long PRD/Roadmap/artifact filenames and Markdown paths | Non-secret identifiers | Broad regex matches names such as technical-requirements and stage PRD slugs. |
| Long test function names | Non-secret identifiers | Broad regex matches pytest function names and helper names. |
| Commit SHAs, image digests, UUIDs, migration ids | Non-secret operational/history identifiers | Matches include commit ids, Docker image digest fragments, UUID-style ids, and Alembic migration filenames. |
| Deliberate test secret/redaction fixtures | Non-production test fixtures | Matches include `TEST_ENCRYPTION_KEY` constants and Stage 149 sanitizer corpus values under `tests/`; they are synthetic fixtures used by tests. |
| OpenAPI example PII/password-like values | Deferred to Stage 164 | Excluded from this Stage 163 scan; Stage 164 is the explicit sanitization task. |

## Residual Risk

Current-tree redaction does not rewrite git history. Anyone with existing repository history, forks, caches, or prior logs may still be able to recover old file contents. If the historical key was ever valid after disclosure, the effective mitigation is external rotate/revoke on `devtr6`.
