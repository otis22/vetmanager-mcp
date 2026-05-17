# Этап 165. Critical security findings inventory without hiding fixed notes

## Контекст

Пользовательское решение 2026-05-17: artifacts, review notes, security notes и исправленные замечания не скрывать. Если accepted High/Critical security findings остаются без evidence of fix, их нужно явно добавить в Roadmap отдельными narrow stages.

Stage 163 и Stage 164 закрыли current-tree exposure для двух privacy/security findings, но не должны удалять historical notes, review artifacts или fixed findings. Stage 165 делает inventory, а не redaction.

## Цель

Составить видимый inventory accepted High/Critical security findings по review/security artifacts и рабочим заметкам, связать fixed findings с evidence, а unresolved findings превратить в конкретные Roadmap stages.

## Scope

- Источники:
  - `artifacts/review/`
  - `artifacts/security/`
  - `artifacts/security-threat-model-vetmanager-mcp-ru.md`
  - `artifacts/security-deployment-notes-vetmanager-mcp-ru.md`
  - `artifacts/architecture-review-vetmanager-mcp-ru.md`
  - `artifacts/tech-debt-register-vetmanager-mcp-ru.md`
  - `artifacts/operations-readiness-vetmanager-mcp-ru.md`
  - `artifacts/release-checklist-vetmanager-mcp-ru.md`
  - `artifacts/runbook-operator-ip-mask.md`
  - `artifacts/observability-runbook-vetmanager-mcp-ru.md`
  - `artifacts/api-research-notes-ru.md`
  - `artifacts/api_entity_reference-ru.md`
  - security-themed `PRD/*.md` and PRDs with review/follow-up/security/deploy/auth/privacy keywords
  - `AssumptionLog.md`
  - `Roadmap.md` all stages; stages 86-164 are primary because they contain the recent review/security workflow, but pre-86 stages matching the security vocabulary are also classified rather than used only as evidence.
- Before classification, run an enumeration search across the repo for the same severity/security vocabulary, excluding only runtime/build/cache directories (`.git`, `.venv`, `node_modules`, `.pytest_cache`, `htmlcov`, `dist`, `build`). Record the resulting reviewed file list or exclusion summary in the inventory header so the discovery boundary is auditable.
- Enumeration hits outside the scoped sources are not silently dropped: either promote the source into classification scope or record a grouped `out-of-scope-source` justification in the inventory header, e.g. source/test/config files with identifier-only matches and no review/security finding text.
- Severity threshold: only accepted `High` / `Critical` security, privacy, credential, auth, deploy-secret, data-exposure, or access-control findings.
- Operational definition of `accepted`:
  - super-review/review finding with explicit severity vocabulary `blocker`, `critical`, `high`, `CRITICAL`, `HIGH`, `P0`, `P1`, `sev0`, `sev1`, `show-stopper`, `критический`, `критичный`, `высокий`, `блокер`, or `высший приоритет`;
  - `must-fix` counts as High by default for security/privacy/credential/auth/deploy/access-control findings unless the source explicitly downgrades it;
  - `major` counts as High by default for security/privacy/credential/auth/deploy/access-control findings unless the source explicitly downgrades it;
  - prior dismissals in `artifacts/review/inadequate-findings-index.md`, source artifacts, or AssumptionLog are accepted only when they carry a documented rationale; otherwise classify the original finding by severity. Record reviewed High/Critical security dismissals in the inventory as `rejected` rows with source and dismissal rationale;
  - threat-model T-scenarios are included when the threat model or remediation/status table explicitly marks the scenario as High/Critical, highest-priority security risk, release-blocking, red/high risk, or numeric risk score/CVSS-equivalent >= 7.0; qualitative matrix entries also count as accepted High when likelihood is High/Med-High and impact is High/Critical.
- For non-review sources without explicit severity vocabulary, any concrete item describing credential/secret/PII exposure, auth bypass, deploy-secret handling, or access-control gap is treated as accepted High by default and must appear in the inventory as `fixed`, `unresolved`, or `rejected` with source backreference.
- If per-reviewer and aggregator severities conflict, aggregator severity wins only when a downgrade below the maximum reviewer severity has explicit rationale in `artifacts/review/inadequate-findings-index.md`, source review text, or AssumptionLog. Otherwise use the maximum reviewer severity. Cite both severities and any dismissal source in `evidence` when they differ.
- Output artifact: `artifacts/security/stage-165-critical-findings-inventory.md`.
- Inventory header records the source snapshot commit SHA used for discovery. Subsequent Stage 165 edits to Roadmap/AssumptionLog/inventory are exempt from source-discovery enumeration and are evaluated as Stage 165 workflow evidence, but privacy/security checks still scan the Stage 165 inventory before commit.
- Finding ids are deterministic: `S165-<source-tag>-<short-slug>`, where `source-tag` is the source file stem or threat id and `short-slug` is derived from the source finding title/heading. If the source already has a stable id (`T*`, `F*`, review id), include it in the slug.
- If unresolved accepted High/Critical finding is found, add a dedicated Roadmap stage with narrow scope, tests/checks, review gates and deploy/verification criteria.
- New follow-up Roadmap stages are appended after Stage 165 as Stage 166, 167, ... in severity-then-source order: Critical/P0/sev0/blocker before High/P1/sev1/must-fix/major; threat-model T-scenarios first within the same severity. Stage 165 may be closed only after every unresolved row has a `todo` follow-up stage and cross-reference.
- AssumptionLog search procedure:
  - include stage sections whose headers or body mention security/privacy/secret/credential/auth/token/leak/exposure/deploy/CSRF/SSRF/access-control terms;
  - include sections with vulnerability vocabulary: injection/command injection/RCE/XSS/IDOR/ReDoS/DoS/rate limit/RBAC/race condition/replay/CVE/bypass/authorization/permission/TLS/SSL/cert/certificate/MITM/password/passphrase/key rotation/incident/DDoS and Russian equivalents `уязвимость`, `утечка`, `авторизация`, `права доступа`, `инъекция`, `обход`, `гонка`, `лимит`, `сертификат`, `пароль`, `ротация`, `инцидент`, `атака`;
  - include entries that reference threat-model T-scenarios or review finding ids;
  - do not re-litigate unrelated operational notes without security/privacy markers.

## Out of scope

- Hiding, deleting or rewriting review/security artifacts.
- General cleanup of old notes.
- Current-tree redaction unless a new active concrete secret/PII value is found; that must become its own narrow Roadmap stage.
- Full generic secret scanning framework. Stage 165 can use targeted searches to support inventory, but it is not a repo-wide scanner stage.

## Acceptance criteria

- Inventory artifact exists and contains a table:
  - finding id / source / severity / status / evidence / follow-up Roadmap stage / rationale-notes.
- Every accepted High/Critical finding in scoped sources is classified as:
  - `fixed` with evidence link to stage/commit/artifact/check;
  - `unresolved` with new Roadmap stage;
  - `rejected` only if the source finding is speculative, duplicate, false positive, explicitly downgraded, or covered by a reviewed prior dismissal, with rationale and mandatory source backreference.
- Fixed security notes remain visible; only concrete secrets/PII values already handled by Stage 163/164 remain sanitized.
- Inventory artifact contains no raw secrets, no concrete PII values, and no reproductions of sanitized Stage 163/164 values; use finding ids, source paths, severity, status, evidence stage/commit refs and rationale only.
- Inventory artifact is explicitly included in privacy checks by `scripts/check_stage165_inventory_privacy.py`, which scans `artifacts/security/stage-165-critical-findings-inventory.md` for Stage 163/164 deny-list values and generic privacy patterns before commit.
- Inventory artifact also passes deterministic generic privacy triage before commit: no JWT-like tokens, no API-key-like high-entropy tokens, no non-reserved email addresses, no phone-like values, no chat-id-like values, no address-like PII phrases, and no suspicious long alphanumeric hex/base64 secrets. Allowlist is limited to explicit `commit:<40-hex>` source snapshot/evidence refs, `sha256:<64-hex>` hash fingerprints that are documented as fingerprints, and required source/finding/check identifiers. Reserved emails are limited to IANA example domains (`example.com`, `example.net`, `example.org`) and explicit redaction placeholders.
- Every `fixed` row includes a one-line closure justification in `rationale-notes` and a current-HEAD regression check/test/script name that would regress if the fix were reverted. If no current check exists, classify as `unresolved` and add a follow-up stage to add the regression check before marking the finding fixed. Stage 163 and Stage 164 closures must cross-link to their underlying source findings.
- If inventory work surfaces a new live concrete secret or PII value, do not write it into the inventory; add a separate narrow Roadmap stage for rotate/redact first.
- AssumptionLog records the search boundaries and unresolved list. If none remains unresolved, it explicitly says so.
- Roadmap records Stage 165 completion and any new follow-up stages.
- `git diff --check` and relevant artifact checks pass.

## Checks

```bash
rg -in "^(#{1,6} .*)?(blocker|critical|high|P0|P1|sev0|sev1|must-fix|major|show-stopper|критический|критичный|высокий|блокер|высший приоритет)\\b|\\b(CRITICAL|HIGH|P0|P1|sev0|sev1|must-fix|major|show-stopper|blocker)\\b|T[0-9]+|security|secret|credential|api key|privacy|PII|leak|exposure|access control|CSRF|SSRF|deploy|injection|RCE|XSS|IDOR|ReDoS|DoS|rate.?limit|RBAC|race condition|replay|CVE|bypass|authorization|permission|TLS|SSL|cert|certificate|MITM|password|passphrase|key rotation|incident|DDoS|уязвимость|утечка|авторизация|права доступа|инъекция|обход|гонка|лимит|сертификат|пароль|ротация|инцидент|атака" artifacts/review artifacts/security artifacts/security-threat-model-vetmanager-mcp-ru.md artifacts/security-deployment-notes-vetmanager-mcp-ru.md artifacts/architecture-review-vetmanager-mcp-ru.md artifacts/tech-debt-register-vetmanager-mcp-ru.md artifacts/operations-readiness-vetmanager-mcp-ru.md artifacts/release-checklist-vetmanager-mcp-ru.md artifacts/runbook-operator-ip-mask.md artifacts/observability-runbook-vetmanager-mcp-ru.md artifacts/api-research-notes-ru.md artifacts/api_entity_reference-ru.md PRD AssumptionLog.md Roadmap.md
rg -il "blocker|critical|high|P0|P1|sev0|sev1|must-fix|major|show-stopper|критический|критичный|высокий|блокер|высший приоритет|security|secret|credential|api key|privacy|PII|leak|exposure|access control|CSRF|SSRF|deploy|injection|RCE|XSS|IDOR|ReDoS|DoS|rate.?limit|RBAC|race condition|replay|CVE|bypass|authorization|permission|TLS|SSL|cert|certificate|MITM|password|passphrase|key rotation|incident|DDoS|уязвимость|утечка|авторизация|права доступа|инъекция|обход|гонка|лимит|сертификат|пароль|ротация|инцидент|атака" . -g '!/.git/**' -g '!/.venv/**' -g '!/node_modules/**' -g '!/.pytest_cache/**' -g '!/htmlcov/**' -g '!/dist/**' -g '!/build/**'
python3 scripts/check_no_historical_api_key_literal.py
python3 scripts/check_reference_artifact_privacy.py
python3 scripts/check_stage165_inventory_privacy.py
git diff --check  # hygiene only
```

If inventory creates new scripts or code, run targeted tests and full suite. If only docs/artifacts change, no application full suite is required unless review requests it.

## Review gates

- Spark PRD scout review before formal PRD review.
- Strong PRD review via Claude Opus for Codex-agent workflow.
- Spark committed-diff scout review before push.
- Strong committed-diff review via Claude Opus before push.

## Simplicity decision

Keep Stage 165 as a bounded evidence table and Roadmap planning pass. Do not turn it into broad cleanup or generic scanning; unresolved accepted High/Critical items become explicit future stages.
