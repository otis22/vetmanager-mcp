# Этап 149. Agent feedback loop + DB-backed verified KB

## Статус

`done — full suite passed, committed-diff reviews completed`

## Контекст

Нужно замкнуть петлю обратной связи между LLM-агентами, которые используют `vetmanager-mcp`, и разработкой проекта. Агент должен иметь простой способ сообщить, что tool ошибся, описание ввело его в заблуждение, не хватает параметра/tool, ответ выглядит подозрительно или известная проблема повторилась.

Первичная идея JSONL/локальной KB отклонена. В проекте уже есть production storage layer: SQLAlchemy models, Alembic migrations, Postgres в production и SQLite fallback для local/dev. Поэтому source of truth для feedback и known issues должен быть в БД.

Важная граница: **автоисправлений кода нет**. Runtime не вызывает LLM для генерации советов. Агентам можно возвращать только проверенные, заранее сохранённые workaround/playbook из verified KB по детерминированным правилам.

## Цели

- Добавить MCP tool `report_problem`, который LLM-агент может вызвать без участия пользователя.
- Сохранять структурированный feedback в БД с привязкой к account/token/request metadata, если они безопасно доступны.
- Поддержать verified KB известных проблем и workaround-ов в БД.
- При совпадении с verified known issue возвращать агенту безопасный deterministic playbook.
- Подготовить offline triage контур: агент/разработчик может группировать feedback и готовить Roadmap/PRD draft, но не auto-merge и не auto-fix.

## Не цели

- Нет автоисправления кода.
- Нет runtime LLM для генерации workaround-а.
- Нет UI.
- Нет внешних интеграций с GitHub Issues, Bitrix24, Slack/Telegram.
- Нет сохранения raw Vetmanager payload, секретов, login/password, API keys, raw bearer token.
- Нет semantic embeddings в v1; только deterministic match rules/fingerprint.

## Проверенные ограничения проекта

- `server.py` создаёт `FastMCP(name="vetmanager", instructions=...)`, регистрирует tools через `tools.register_all(mcp)`, prompts и web routes.
- Все существующие entity tools проходят через `_ToolRegistrationProxy` в `tools/__init__.py`, где уже есть preflight bearer auth, scope enforcement и depersonalization wrapper. Это естественная точка для error hint / known issue injection.
- Storage foundation уже есть: `storage.py`, `storage_models.py`, Alembic `alembic/versions/*`, `bootstrap_storage_schema()` для SQLite fresh runtimes.
- Production deploy запускает Alembic migrations и проверяет critical DB tables.
- PRD требует bearer-only MCP runtime: tools не принимают runtime credentials как аргументы; все секреты должны быть замаскированы в логах/ошибках.
- `tools/list` description является source of truth для LLM-клиентов; `report_problem` description должен прямо объяснять, когда его вызывать.

## Data Model

### `agent_feedback_reports`

Сырые, не доверенные сообщения от моделей и auto-events.

Поля:

- `id` integer PK
- `created_at`, `updated_at`
- `source` enum text: `model | auto | user_complaint`
- `category` enum text: `bug | missing_tool | bad_description | contract | perf | docs | other`
- `severity` enum text: `low | medium | high`
- `status` enum text: `new | grouped | triaged | linked | ignored`
- `account_id` nullable FK `accounts.id`, index
- `bearer_token_id` nullable FK `service_bearer_tokens.id`, index
- `related_tool` nullable string, index
- `related_call_id` nullable string
- `request_id` nullable string
- `http_status` nullable integer
- `error_code` nullable string
- `params_shape_json` nullable text: JSON list of safe parameter names only
- `summary` string, max 240 chars
- `details` text, max 8000 chars after redaction/truncation
- `suggested_fix` nullable text, max 4000 chars
- `reproduce` nullable text, max 4000 chars
- `error_fingerprint_hash` nullable string, index; non-reversible hash/HMAC only
- `known_issue_id` nullable FK `known_issues.id`
- `duplicate_of_id` nullable FK `agent_feedback_reports.id`
- `redaction_version` integer

### `known_issues`

Проверенная KB. Только эти записи можно возвращать агентам как known issue/workaround.

Поля:

- `id` integer PK
- `created_at`, `updated_at`
- `status` enum text: `open | acknowledged | workaround_available | fixed | wontfix`
- `category` enum text
- `severity` enum text
- `priority` integer, default 100; lower value wins deterministic matching
- `title` string, max 240 chars
- `related_tool` nullable string, index
- `error_fingerprint_hash` nullable string, index; non-reversible hash/HMAC only
- `match_rules_json` text: deterministic rules (`tool`, `fingerprint`, `error_code`, `http_status`, `text_contains`, `params_shape`)
- `agent_playbook_json` text: structured instructions for the agent
- `public_summary` nullable text
- `workaround` nullable text
- `resolution` nullable text
- `fixed_in_version` nullable string
- `report_count` integer
- `first_seen_at`, `last_seen_at`

Indexes:

- `ix_agent_feedback_reports_tool_fingerprint(related_tool, error_fingerprint_hash)`
- `ix_agent_feedback_reports_status_created(status, created_at)`
- `ix_known_issues_tool_fingerprint(related_tool, error_fingerprint_hash)`
- If portable across SQLite/Postgres without overwork: partial unique index for active `workaround_available` exact matches. Otherwise enforce uniqueness in service code and tests.

### Deferred: `known_issue_match_events`

Отдельная таблица match events полезна для аналитики, но не нужна для v1 acceptance. В Stage 149 она **не реализуется**, чтобы не расширять storage/migration scope. Для v1 достаточно `known_issues.report_count`, `first_seen_at`, `last_seen_at` и связи `agent_feedback_reports.known_issue_id`.

Кандидат для Stage 150:

- `id`, `created_at`
- `known_issue_id`
- `agent_feedback_report_id` nullable
- `account_id` nullable
- `bearer_token_id` nullable
- `related_tool`
- `match_confidence` string: `exact | rule`

## Deterministic Matching

`error_fingerprint_hash` строится без LLM:

- `related_tool`
- normalized error code / exception class if available
- HTTP status if available
- normalized error text: lowercase, stripped volatile ids, dates/times collapsed, whitespace normalized
- safe params shape: names only or whitelisted enum/date presence, not raw business payload

Only the non-reversible hash/HMAC is persisted. The normalized text used to derive the fingerprint must not be stored in DB. It may exist only in request-local memory and tests.

Hash choice:

- Use HMAC-SHA256, not plain SHA-256.
- Pepper source: `FEEDBACK_FINGERPRINT_PEPPER` env var. If missing, fail startup when Stage 149 is enabled in production; tests may inject a deterministic pepper.
- Pepper rotation invalidates exact hash matches; rule-based matching remains available as fallback.
- Add a stability test: same structured incident + same pepper => same hash across process restart.

Unified fingerprint inputs:

- Use one shared `normalize_error_text` / fingerprint builder for both wrapper-derived incidents and `report_problem` structured fields.
- Error-wrapper path derives fields directly from the caught tool exception and safe request-local context.
- `report_problem` accepts optional structured fields (`http_status`, `error_code`, `error_excerpt`, `params_shape`) so model-submitted reports can converge to the same hash when the agent has error context.
- If `report_problem` lacks structured fields, save the report without `error_fingerprint_hash`; triage can link it manually.

Match order:

1. Exact `related_tool + error_fingerprint_hash` with `known_issues.status = workaround_available`.
2. Deterministic `match_rules_json` for same `related_tool` and `known_issues.status = workaround_available`.
3. No match.

Never return raw/unverified feedback as advice.
Never surface `open`, `acknowledged`, `fixed` or `wontfix` known issues to agents as runtime advice in Stage 149. Those statuses are for triage and operator workflow only. Agent-facing playbooks require explicit `workaround_available`.

### Deterministic Selection

If multiple `known_issues` rows match, selection must be deterministic:

1. Prefer exact fingerprint matches over rule matches.
2. Then order by `priority ASC`.
3. Then order by `updated_at DESC`.
4. Then order by `id ASC`.

Ambiguity policy:

- For exact matches, service code must prevent two active `workaround_available` known issues from sharing the same non-null `related_tool + error_fingerprint_hash`. Use a DB constraint if portable; otherwise enforce in service code and tests.
- For rule matches, multiple matches are allowed but the ordering above is mandatory.
- If a candidate has invalid data or invalid playbook, skip it and evaluate the next deterministic candidate.
- If all candidates are invalid, return no known issue.

### Match Rules Schema

`match_rules_json` must be versioned and validated by service code before use. Unknown schema versions or unknown operators must fail closed and return no match.

Allowed v1 shape:

```json
{
  "version": 1,
  "all": [
    {"field": "related_tool", "op": "eq", "value": "get_payments"},
    {"field": "error_fingerprint_hash", "op": "eq", "value": "sha256:..."},
    {"field": "http_status", "op": "in", "value": [400, 422]},
    {"field": "normalized_error_text", "op": "contains_any", "value": ["date filter", "old records"]},
    {"field": "params_shape", "op": "has_keys", "value": ["date_from", "date_to"]}
  ]
}
```

Allowed operators in v1: `eq`, `in`, `contains_any`, `contains_all`, `has_keys`, `missing_keys`.

Rules:

- unsupported `field` or `op` => no match
- non-list values for list operators => no match
- rule parsing errors => no match and structured warning log
- `related_tool` must match when present on the known issue
- `normalized_error_text` rule matching uses request-local sanitized normalized text only; that text is not stored on feedback rows

## Agent Playbook Contract

`agent_playbook_json` is structured and safe to render into tool response:

```json
{
  "version": 1,
  "summary": "Known issue summary for the agent.",
  "steps": ["Step 1", "Step 2"],
  "do_not_do": ["Unsafe or misleading action"],
  "recommended_tool_sequence": ["tool_a", "tool_b"],
  "user_message_template": "Optional short user-facing wording.",
  "safe_to_retry": true
}
```

Allowed v1 fields:

- `version: 1`
- `summary` string <= 500 chars
- `steps` list of strings, max 8 items, each <= 500 chars
- `do_not_do` list of strings, max 8 items, each <= 500 chars
- `recommended_tool_sequence` list of registered tool names, max 8 items
- `user_message_template` optional string <= 800 chars
- `safe_to_retry` boolean

Invalid playbook JSON is never returned to agents even if the known issue matches.
Absent or unknown `version` in either `match_rules_json` or `agent_playbook_json` fails closed.

The runtime response may include:

```json
{
  "known_issue": {
    "id": 1,
    "status": "workaround_available",
    "title": "...",
    "playbook": { "...": "..." }
  }
}
```

## MCP Tool `report_problem`

Input:

- `category`
- `severity`
- `summary`
- `details`
- `related_tool` optional
- `related_call_id` optional
- `http_status` optional integer
- `error_code` optional string
- `error_excerpt` optional string, sanitized/truncated before hashing and not persisted raw
- `params_shape` optional list of safe parameter names, values are not accepted
- `suggested_fix` optional
- `reproduce` optional

Description must say when to call:

- unclear tool error
- tool description mismatched behavior
- missing tool/parameter for reasonable user request
- suspicious response shape
- documentation/examples mismatched real behavior

Output:

- `ok: true`
- `feedback_id`
- `known_issue` nullable
- `message` short machine-readable text

### Access Model

`report_problem` must be available to all active bearer tokens that can call MCP tools. It does not access Vetmanager data and must not require a broad business scope like finance/clinical/admin.

Implementation requirement:

- add explicit `report_problem` entry to `tool_access_registry.py`
- introduce a narrow baseline allowlist in `_ensure_tool_scopes_allowed`, e.g. `BASELINE_ALLOWED_TOOLS = {"report_problem"}`
- for baseline-allowed tools, return early only after successful runtime auth and non-empty token scopes; expired/revoked/invalid tokens are still rejected by runtime auth
- `report_problem` bypasses business-scope checks but still requires successful runtime auth and an active token
- do **not** add a new `feedback:write` scope in Stage 149, because existing issued tokens have frozen `scopes_json` and would silently lose feedback access without backfill
- add regression tests proving that representative token presets can call `report_problem`
- denied/expired/revoked bearer tokens remain denied by existing runtime auth

## Error Middleware

The shared tool wrapper should add a short hint to tool errors:

`If this error is unclear or you suspect a Vetmanager MCP bug, call report_problem with related_tool="<tool_name>".`

If verified KB matches the error, append structured known issue info to the error response. Keep the hint short; do not leak secrets or raw payload.

Integration point and ordering:

- Add a new wrapper layer around `tool_func` execution after runtime auth and scope preflight have succeeded.
- Place the error-hint try/except strictly around `await tool_func(...)` before depersonalization runs.
- Do not add report hints to auth failures, scope-denied errors, or depersonalization sanitizer failures.
- Only `ToolError`/domain tool failures from the wrapped `tool_func` get the hint and optional known issue injection.
- KB lookup is best-effort with a hard timeout target of 200 ms; lookup failure/timeout must return the original ToolError plus the generic report hint, never mask the original error.
- Tests must cover: scope-denied path has no report hint; tool function ToolError gets hint; matching known issue injects playbook; KB timeout/failure preserves original error.

Auto-events v1:

- Auto feedback rows are written only for tool failures whose fingerprint matches an existing `known_issues` row with status `open | acknowledged | workaround_available`.
- Unmatched failures are not auto-persisted in v1 to avoid DB write storms; agents can still call `report_problem`.
- Auto write is best-effort and non-blocking for the user-visible error path: DB errors are swallowed after structured warning log.
- Dedup cap: at most one auto row per token-first key per 15 minutes:
  - if `bearer_token_id` is available: `(bearer_token_id, error_fingerprint_hash)`
  - else if `account_id` is available: `(account_id, error_fingerprint_hash)`
  - else: do not write an auto-event row
- Global cap: at most 60 auto-events per process per minute; drops emit structured warning logs only.
- Concurrency policy: occasional duplicate auto rows inside the dedup window are accepted in v1 if parallel failures race before commit; offline triage merges duplicates by fingerprint.

Counter update points:

- Increment `known_issues.report_count` and update `last_seen_at` when an auto-event row is written for that known issue.
- Increment `known_issues.report_count` and update `last_seen_at` when `report_problem` directly links a model report to a known issue.
- Set `first_seen_at` if it is missing at the first linked report/event.
- Offline triage promote/link commands update counters when they link existing reports.

## Offline Triage CLI

Add script(s), no UI:

- list recent reports
- group by `related_tool + error_fingerprint_hash`
- show top repeated reports
- promote a report/group into `known_issues`
- mark known issue `workaround_available | fixed | wontfix`
- export a markdown summary that an agent/developer can use to create Roadmap/PRD manually

No automatic code modifications.

## Privacy and Security

Two sanitization domains:

1. **Ingest pipeline** for `report_problem` inputs and auto-event fields:
   - untrusted, per-call, fail-closed on parse/validation errors
   - strict sanitizer/truncation on all free text and structured fields
   - rejects unknown JSON keys/unknown structured metadata
2. **KB activation pipeline** for operator-authored `known_issues` content:
   - schema validation for `match_rules_json` and `agent_playbook_json`
   - lighter secret scan over `public_summary`, `workaround`, `resolution`, `agent_playbook_json`
   - operator-confirmed override allowed for false positives only in CLI path, with explicit audit/log message

- Redact bearer tokens, API keys, passwords, cookies, auth headers, Vetmanager tokens.
- Do not persist raw tool args/results by default.
- Store only summary/details supplied by model after sanitizer/truncation.
- For depersonalized tokens, never store personal/business payload fragments from tool output.
- DB-backed per account/token rate limit for `report_problem` using recent `agent_feedback_reports.created_at` windows; do not rely only on process memory.
- Global cap for auto-events to avoid DB spam during outages.
- Run the mandatory ingest pipeline over `summary`, `details`, `suggested_fix`, `reproduce`, `error_excerpt`, `params_shape`.
- Run the KB activation pipeline over `public_summary`, `workaround`, `resolution`, `match_rules_json` and `agent_playbook_json`.
- Sanitization must cover emails, phone numbers, bearer-like tokens, REST API keys, cookies, auth headers, Vetmanager user tokens, and common secret key names.
- Stage 149 does not attempt NER or full owner/client name detection without a reliable dictionary/LLM. Free-text details remain operator-only; runtime agent advice can read only verified `known_issues` playbooks, never raw report details.
- If sanitizer cannot parse/validate structured JSON safely, reject `report_problem` with a safe validation error instead of storing raw input.
- Store `redaction_version` on every report for future migrations/reprocessing.

Rate limits:

- `report_problem` DB-backed cap: max 30 reports per bearer token per 1 hour.
- `report_problem` DB-backed cap: max 60 reports per account per 1 hour.
- Auto-event global process cap: max 60 writes per process per 1 minute.
- Auto-event dedup window: token-first key once per 15 minutes as defined above.

Pepper policy:

- `FEEDBACK_FINGERPRINT_PEPPER` is set once for production in v1 and is not rotated routinely.
- If emergency rotation is required, exact historical dedup/KB hash matching is intentionally lost for old rows because raw normalized text is not stored.
- After rotation, operators rely on rule-based matching and can regenerate known issue exact hashes only from structured match data that is safe and still available.
- Report counters may split across pre/post-rotation fingerprints; this is accepted in v1 and should be noted in triage output.

Data lifecycle:

- `agent_feedback_reports` are operational telemetry, not permanent business records.
- Add a configurable retention helper/CLI command in v1: default keep 180 days for `ignored`, `linked`, `triaged` reports and keep `new/grouped` until triaged.
- `known_issues` are retained until an operator marks them obsolete; Stage 149 does not auto-delete KB rows.
- Retention cleanup must be explicit/operator-run in v1, use DB transactions, and log counts only, not report contents.

Structured metadata v1:

- No arbitrary `metadata_json` field in v1.
- Allowed structured fields are only `http_status`, `error_code`, `error_excerpt` for hashing, and `params_shape`.
- Unknown structured keys are rejected.

## Decomposition

All subtasks are scoped to <= 2 hours or <= 150 LOC changed where possible.

1. Schema + models
   - Add Alembic migration for `agent_feedback_reports`, `known_issues`.
   - Add SQLAlchemy models and constants/check constraints.
   - Add migration/model tests.

2a. Ingest sanitization service
   - Add strict sanitizer/truncation for `report_problem`.
   - Reject unknown structured keys and unparseable JSON.
   - Add privacy tests for text and structured fields.

2b. Fingerprint service
   - Implement normalization + HMAC-SHA256 hash generation.
   - Add stability tests with injected pepper.
   - Add tests that raw normalized text is not persisted.

2c. Rule/playbook validation
   - Validate `match_rules_json` version/operators/fields.
   - Validate `agent_playbook_json` version/shape/tool names.
   - Add missing/unknown version fail-closed tests.

2d. Known issue selection
   - Implement exact/rule matching.
   - Implement deterministic tie-break: exactness, priority, updated_at, id.
   - Add ambiguity/invalid-candidate tests.

2e. Feedback service wiring
   - Add `agent_feedback_service.py`.
   - Implement create report + known issue lookup.
   - Implement DB-backed report rate limit windows.
   - Add service integration tests.

3. MCP tool
   - Add `tools/feedback.py`.
   - Register in `tools.register_all()`.
   - Add tool description/docstring with explicit call triggers.
   - Add tests for tool schema/behavior.

4. Error hint and known issue injection
   - Extend shared wrapper in `tools/__init__.py`.
   - Preserve existing auth/scope/depersonalization behavior.
   - Add tests for normal ToolError, matched known issue, and no-match.

5a. Report rate limits
   - DB-backed per account/token caps based on `agent_feedback_reports.created_at`.
   - Add tests for cap hit and reset window.

5b. Auto-event caps
   - Add best-effort auto-event write only for matched known issues.
   - Add token-first 15-minute dedup and process-global 60/min cap.
   - Add tests that auto persistence failure never changes the user-visible tool error.

6. Offline triage script
   - Add `scripts/triage_agent_feedback.py`.
   - Implement list/group/promote/mark commands.
   - Add markdown export of grouped feedback, not automatic PRD/task creation.
   - Add explicit retention cleanup command for old non-active reports.
   - Add unit tests for non-mutating grouping and promote path.

7. Documentation and prompts
   - Update technical requirements or README with feedback tool behavior.
   - Update FastMCP instructions if supported without overloading prompt.

8. Checks and release
   - Full Docker suite.
   - Review gates.
   - Commit/push/deploy.

## Acceptance Criteria

- `report_problem` is visible in MCP tools/list and can save feedback to DB.
- `report_problem` access is explicitly covered by scope/preset tests and does not require unrelated business scopes.
- Feedback persists in Postgres/SQLite storage, not JSONL.
- Verified known issue lookup returns playbook only from `known_issues`, never from raw feedback.
- `report_problem` structured fields and wrapper-derived fields can converge to the same `error_fingerprint_hash` for the same incident.
- Invalid `match_rules_json` or `agent_playbook_json` fails closed and is not returned to agents.
- Multiple known-issue matches are selected deterministically by exactness, priority, updated_at and id.
- Tool errors include short report hint.
- Matching known issue injects safe workaround/playbook into response.
- Auth/scope/depersonalization errors do not get misleading report hints.
- No raw secrets or raw Vetmanager payloads are persisted in tests.
- Normalized raw error text is not persisted; only non-reversible fingerprint hash/HMAC is stored.
- Sanitization/redaction tests cover all free-text and JSON fields stored by the feature.
- Fingerprint tests prove the same simulated incident submitted through `report_problem` structured fields and the wrapper path gets the same hash.
- DB-backed report rate limits and auto-event caps prevent feedback spam.
- Report-rate tests assert the concrete 30/token/hour and 60/account/hour limits.
- Auto-event dedup is token-aware and does not let one noisy token suppress all same-account auto-events when token context is available.
- Known issue counters are updated on linked model reports, matched auto-events, and offline triage linking.
- Feedback report retention can purge old non-active reports explicitly without touching active triage rows or known issues.
- Offline triage can promote a report/group to a known issue without code autofix.
- Offline triage can export grouped feedback as markdown for an agent/developer to turn into Roadmap/PRD manually.
- Full Docker suite passes.

## Review Gates

Before implementation:

- Spark scout pre-pass for PRD: run, accept only adequate important findings, update PRD.
- Self PRD review + simplicity evaluation: remove over-engineering or explicitly record rationale.
- Spark scout pre-pass before budgeted PRD review: run, accept only adequate important findings.
- PRD review сторонней моделью: run within budget, accept only adequate important findings.
- Record review outcomes in AssumptionLog.

Before push:

- Full Docker suite.
- Spark scout pre-pass for committed diff.
- committed-diff review сторонней моделью.
- Self-attestation checklist.

## Simplicity Notes

- No embeddings in v1.
- No external integrations in v1.
- `known_issue_match_events` deferred to Stage 150; v1 uses counters and report linkage only.
- Report rate limits are DB-backed in v1 because feedback spam can affect shared storage. Only auto-event global cap remains process-local, and auto-events are best-effort/matched-only.
- Triage does not create Roadmap/PRD files automatically in v1; it exports markdown evidence for a separate agent/developer workflow.
- Runtime advice is deterministic and testable.
