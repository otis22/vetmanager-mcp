# Этап 184. Medical cards date-range listing for daily control

## Контекст

Production feedback `#20` показал product gap: `get_medical_cards` требует
`pet_id`, а daily control требует получить все медкарты за дату/период. Агент
вынужден обходить это через admissions/invoices/exact card IDs или через Report
AI, который может остаться в queue и не дать same-turn fallback.

## Проверенные факты

- `/rest/api/MedicalCards` указан в OpenAPI как стандартный list endpoint с
  `limit`, `offset`, `sort`, `filter`.
- `api_entity_reference-ru.md` фиксирует поле даты `date_create` в формате
  `YYYY-MM-DD HH:MM:SS`.
- CRUD permissions разрешают `MedicalCards` `restList`, `restView`,
  `restCreate`, `restUpdate`; delete запрещён.
- Real API probe через штатный `VetmanagerClient` и `.env`:
  - response key: `data.medicalCards`;
  - `data.totalCount` присутствует;
  - `date_create` filter принимает стандартные filter clauses;
  - row shape содержит `clinic_id`, `patient_id`, `date_create`,
    clinical fields, `patient` nested object;
  - row shape не содержит nested `pet`, `doctor`, `owner`, `client`;
  - `invoice` field есть, но в проверенной строке был `null`.
- User clarification: `clinic_id` must not be required by default because it
  can hide important records, including analyses/medical cards from another
  branch. Branch filtering is useful only when the user explicitly asks for it.

## Цель

Добавить прямой read-only MCP tool для списка медкарт за дату/период поверх
`/rest/api/MedicalCards`, чтобы daily control не зависел от Report AI и не
терял записи из других филиалов по умолчанию.

## Scope

### In scope

- Новый tool `get_medical_cards_by_date`.
- `date` XOR `date_from`/`date_to` validation.
- Range mode requires both `date_from` and `date_to`; no open-ended ranges in
  this tool.
- Half-open date filters:
  - `date_create >= YYYY-MM-DD 00:00:00`;
  - `date_create < next_day 00:00:00`.
- Optional `clinic_id` filter only when user explicitly narrows branch.
- Response metadata:
  - `date_from`, `date_to`;
  - `clinic_filter_applied`;
  - `clinic_id`;
  - `total`;
  - `medical_cards_count`;
  - `truncated`;
  - `limit`;
  - `offset`;
  - `owner_context_available`.
- Preserve upstream nested `patient` and `invoice` values if present.
- Access registry scope `medical_cards.read`.
- Tool descriptions/docs/tests.
- Production feedback closure after deploy/prod smoke.

### Out of scope

- Unbounded owner/client enrichment.
- New broad daily clinical-control aggregate over admissions/invoices/medical
  cards.
- Changing existing `get_medical_cards(pet_id=...)` contract.
- Writing/updating/deleting medical cards.
- Hiding records from other branches by default.

## Архитектурное решение

### Проблема

Existing MCP surface only exposes pet-scoped and client-scoped medical-card
queries. The API already has a standard `MedicalCards` list endpoint that can
filter by `date_create`, but the MCP does not expose that user workflow. Report
AI is asynchronous and not reliable as a same-turn fallback for operational
daily control.

### Контекст и ограничения

- Existing pattern: medical-card tools live in `tools/medical_card.py` and use
  `filters.build_list_query_params`.
- Existing list validation caps `limit` at 100 and `offset` at 10000.
- Public MCP contract changes require access registry/schema tests.
- Privacy: medical-card rows contain clinical text and patient details. MCP
  depersonalization wrapper remains responsible for depersonalized tokens; this
  stage must not add raw owner/client enrichment that bypasses that path.
- Product: `clinic_id` is optional. Default all-branches behavior is required
  to avoid missing cross-branch analyses/records.
- Date/timezone: Vetmanager accepts and returns `date_create` as naive clinic
  local datetime strings. This tool follows the existing project pattern from
  admissions/payments: user dates are interpreted as clinic-local dates and are
  not converted to UTC.
- Performance: the tool must never auto-fetch an unbounded full day. It returns
  one bounded page with honest `total`/`truncated` metadata.

### Рассмотренные варианты

1. Make `pet_id` optional in `get_medical_cards`.
   - Плюс: no new tool name.
   - Минус: breaks the current clear pet-scoped contract and makes filter
     composition ambiguous.
2. Build a broad daily clinical-control aggregate.
   - Плюс: closer to final workflow.
   - Минус: more endpoints, more PII, larger performance risk and unclear
     product boundary for v1.
3. Add a narrow date-range list tool over `/rest/api/MedicalCards`.
   - Плюс: direct API support, minimal code, clear ownership, no Report AI
     dependency, predictable pagination.
   - Минус: owner/client context remains unavailable unless upstream returns it
     or a later bounded enrichment stage is added.

### Выбранное решение

Add a dedicated `get_medical_cards_by_date` read-only tool. It exposes the
existing list endpoint with date filters, optional branch narrowing, stable
pagination metadata, and conservative context claims. It does not expand into a
multi-endpoint aggregate in this stage.

### Инварианты

- `get_medical_cards(pet_id=...)` keeps requiring `pet_id`.
- `clinic_id` is omitted by default and is applied only when explicitly passed.
- Tool descriptions warn that `clinic_id` narrows results and can exclude
  relevant records from other branches.
- Date range is half-open to include `23:59:59` and exclude next-day midnight.
- Date range boundaries are clinic-local naive datetimes, matching existing
  Vetmanager timestamp filters in MCP.
- `owner_context_available=false` unless this stage later implements bounded
  owner enrichment; v1 does not claim owner context when upstream does not
  return it.
- No write endpoint is called.

### Rollback/fallback

If a Vetmanager contour rejects `date_create` filters, the tool will surface the
upstream error and agents can fall back to existing pet/client scoped tools or
Report AI. If response keys differ, normalization supports `medicalCards`,
`medicalcards`, and `medicalcard`. If future upstream adds richer nested
context, the tool preserves it without changing the contract.

Architecture Critique: required because this stage changes public MCP contract,
production behavior, privacy surface and performance/load behavior.

## Functional requirements

1. Register `get_medical_cards_by_date`.
2. Accept either `date` or `date_from` plus `date_to`; reject mixing.
3. If `date` is provided, set `date_from=date_to=date`.
4. Require either `date` or both `date_from` and `date_to`; reject partial
   open-ended ranges.
5. Validate `date_from <= date_to`.
6. Build filters on `date_create` using `>= day_start` and `< next_day_start`.
7. Apply `clinic_id` filter only when `clinic_id > 0` is provided.
8. Default sort is deterministic: `date_create ASC`, `id ASC`.
9. Preserve caller-provided sort only when explicitly passed.
10. Return `medical_cards` from `medicalCards`/`medicalcards`/`medicalcard`.
11. Return `total` from `totalCount` when available; if `totalCount` is absent,
    return `total=null`, `total_known=false` and do not claim complete results.
12. Return `truncated=true` when `totalCount` is present and
    `offset + medical_cards_count < total`; if `totalCount` is absent, return
    `truncated=null`.
13. Return `clinic_filter_applied`.
14. Return `owner_context_available=false` in v1 when only nested `patient` is
    present and no owner/client enrichment is performed.
15. Scope is `medical_cards.read`.

## Decomposition

1. PRD/research/review gates.
2. Tests first: add Stage 184 tests for date validation/filter construction,
   optional `clinic_id`, response normalization and truncation.
3. Implement `get_medical_cards_by_date` in `tools/medical_card.py`.
4. Register access scope and descriptions/schema expectations.
5. Add opt-in real smoke branch for shape/date filter if practical.
6. Checks, audit, review gates, commit/push/deploy.
7. Production triage: link feedback `#20` as fixed only after prod smoke.

## Review gates

- Spark PRD review: first read-only run hit sandbox/bwrap runtime failure before
  completing review, so per workflow it was stopped and repeated once with
  `gpt-5.3-codex-spark -s danger-full-access` and review-only prompt.
- Spark PRD review accepted 3 medium findings and PRD was updated:
  - require both `date_from` and `date_to` in range mode, no open-ended ranges;
  - define clinic-local naive datetime semantics;
  - avoid false `truncated=false` when upstream omits `totalCount`.
- Claude Opus Architecture/PRD review: `{"findings":[]}`.
- Simplicity check: chosen solution remains the narrowest viable fix: one
  read-only date-range list tool over an existing endpoint, no broad aggregate,
  no unbounded enrichment and no changes to existing pet-scoped tool contract.

## Acceptance criteria

- Tests prove `date` and `date_from`/`date_to` are mutually exclusive.
- Tests prove partial range input (`date_from` without `date_to`, or vice
  versa) is rejected.
- Tests prove invalid dates and `date_from > date_to` are rejected.
- Tests prove filters include `date_create >= start 00:00:00` and
  `date_create < next_day 00:00:00`.
- Tests cover day boundary semantics: start-of-day included, `23:59:59`
  included by the clinic-local half-open range, next-day midnight excluded.
- Tests prove no `clinic_id` filter is sent by default.
- Tests prove `clinic_id` filter is sent when provided and
  `clinic_filter_applied=true`.
- Tests cover `medicalCards`, `medicalcards`, `medicalcard`, and empty response.
- Tests cover `total`, `total_known`, `medical_cards_count`, `truncated`,
  `limit`, `offset`.
- Tests cover missing `totalCount`: `total=null`, `total_known=false`,
  `truncated=null`.
- Access registry and tools schema tests include `get_medical_cards_by_date`.
- README/tool descriptions warn that `clinic_id` narrows results and should be
  omitted for full daily control.
- Targeted tests pass.
- Full suite passes.
- Docker suite passes.
- `AssumptionLog.md` records review findings and real/prod smoke status.
- Production feedback `#20` is linked as fixed only after the deployed tool
  returns a valid bounded response for the daily-control shape.
