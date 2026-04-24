# PRD Этап 140: VM API contract and pagination correctness

## Цель

Закрыть high/medium findings F7-F8/F11-F14/F16 из full super-review stage 136: убрать неподтверждённый write tool для Payment, выровнять list filters с контрактом Vetmanager API, убрать silent truncation в schedule/medical-card/vaccination tools и нормализовать timesheet datetime payload. F15 уже закрыт stage 139 и не входит в scope stage 140.

## Источники

- `artifacts/review/2026-04-24-full-stage-136.md` — F7-F8/F11-F16.
- `artifacts/api_crud_permissions-ru.md` — CRUD permissions: Payment REST supports only `restList/restView`, Timesheet supports create.
- `artifacts/api_entity_reference-ru.md` — Payment, MedicalCards, VaccinationCard, Pet, Timesheet facts.
- `artifacts/vetmanager_openapi_v6.json` — source of truth for list params and endpoints.
- Current code: `tools/finance.py`, `tools/medical_card.py`, `tools/admission.py`, `tools/operations.py`, `tool_access_registry.py`, `tool_descriptions.py`, tests.

## Проверенные факты

- OpenAPI exposes `GET /rest/api/payment/` and `GET /rest/api/payment/{ID}`; no `POST /rest/api/payment/` path is present.
- `artifacts/api_crud_permissions-ru.md` states Payment supports only `restList, restView`; create/update/delete are forbidden.
- `tools/finance.py::create_payment()` is currently registered as an MCP tool and calls `crud_create("/rest/api/payment", payload)`.
- `tools/invoice.py::get_invoices()` still sends `client_id` as top-level `extra={"client_id": client_id}` while OpenAPI `/rest/api/invoice` exposes standard `filter[]`.
- `get_payments()` already uses `filter[]` for `client_id`; stage 122 fixed this from legacy top-level params.
- `get_invoice_documents()` already uses `filter[]` for `invoice_id`; this covers part of F12 from earlier fixes.
- F12 remaining current call sites verified in code: `tools/warehouse.py::get_good_sale_params()` sends top-level `goodId`; `tools/reference.py::get_cities()` sends top-level `title`; `tools/reference.py::get_streets()` sends top-level `cityId`; `tools/reference.py::get_combo_manual_items()` sends top-level `comboManualNameId`; `tools/operations.py::get_message_reports()` sends top-level `campaign`.
- OpenAPI list endpoints for `/rest/api/invoice`, `/rest/api/goodSaleParam`, `/rest/api/city`, `/rest/api/street`, `/rest/api/ComboManualItem`, `/rest/api/messages/reports`, `/rest/api/payment`, `/rest/api/admission`, `/rest/api/pet`, `/rest/api/MedicalCards`, `/rest/api/timesheet` expose standard `limit`, `offset`, `sort`, `filter` parameters.
- `/rest/api/messages/reports` is a custom messages endpoint, not a standard REST entity. Even though OpenAPI lists generic `filter[]`, current stage 140 keeps top-level `campaign` as a documented special-case to avoid a silent broad-query regression without real API verification.
- `api_entity_reference-ru.md` says `MedicalCards/Vaccinations` is a special endpoint: filtering by pet uses top-level `pet_id`, response is `data.medicalcards`, and it is not a standard REST resource. It explicitly says universal `filter`/`sort` are not supported; `limit`/`offset` support is not verified by entity notes.
- `get_vaccinations()` currently accepts `limit` only, sends `pet_id` and `limit`, and returns `total=len(records)` without upstream `totalCount` or truncation marker.
- `get_daily_schedule()` currently fetches one page at `offset=0`, `limit<=100`, while returning upstream `totalCount`.
- `get_medical_cards_by_client_id()` fetches only first 100 pets for `owner_id`, then fetches one medical-card page for all returned pets.
- `create_timesheet()` currently documents ISO input and forwards `begin_datetime`/`end_datetime` unchanged.
- `vm_datetime.normalize_vm_datetime()` exists and accepts VM native `YYYY-MM-DD HH:MM:SS` unchanged, accepts naive ISO `YYYY-MM-DDTHH:MM[:SS[.ffffff]]`, rejects timezone offsets, and returns VM's naive second-precision format.

## Оценка простоты

- `create_payment`: remove from MCP registration and registry/descriptions/docs instead of adding a feature flag. Feature flag would preserve a known unsupported tool and require tenant-specific runtime knowledge that repo does not have.
- List params audit: migrate only call sites that still use unverified top-level params. Do not rewrite already fixed `get_payments`/`get_invoice_documents`, and do not migrate custom `messages/reports` campaign without real API verification.
- Pagination: prefer explicit helper loops where existing module already uses raw `VetmanagerClient`; no new global pagination abstraction unless duplication becomes larger than the local fixes.
- `get_daily_schedule`: preserve existing response shape and add `truncated`/`returnedCount` semantics if a cap is needed.
- `get_medical_cards_by_client_id`: page pet lookup by owner before medical-card IN query; avoid changing public args unless necessary.
- `create_timesheet`: reuse existing `normalize_vm_datetime` behavior from admission/date utilities if available.

## Scope

1. Remove unsupported `create_payment` tool surface:
   - Unregister `create_payment` from `tools/finance.py`.
   - Remove from access registry and tool descriptions.
   - Update README/API docs/tests that count or assert tool list.
   - Keep Payment read tools.
2. API filter contract audit:
   - Migrate `tools/invoice.py::get_invoices(client_id)` to `filter[]` (F11).
   - Migrate F12 current standard-list call sites to `filter[]`: `get_good_sale_params(good_id)`, `get_cities(title)`, `get_streets(city_id)`, `get_combo_manual_items(combo_manual_name_id)`.
   - Document verified/safety special cases: `MedicalCards/Vaccinations?pet_id=...` and custom `messages/reports?campaign=...`.
3. `get_vaccinations()` completeness:
   - Preserve `limit` as the caller's maximum returned records.
   - Do not assume upstream `limit`/`offset` behavior unless tests or artifacts verify it; implement client-side slicing if upstream returns more than `limit`.
   - Return `returnedCount`, `totalCount` when present, and `truncated`.
   - If upstream omits `totalCount`, set `truncated=True` when raw record count is greater than returned count or when `len(records) >= limit` because completeness is unknown at the limit boundary.
   - Preserve normalized vaccination item fields.
4. `get_daily_schedule()` completeness:
   - Preserve `limit` as the caller's maximum returned admissions.
   - Keep `offset=0`; `get_daily_schedule` does not expose an offset parameter in stage 140.
   - Return `returnedCount`, upstream `totalCount`, and `truncated = totalCount > returnedCount + offset`.
   - Do not claim the page is complete when `totalCount` exceeds returned rows.
5. `get_medical_cards_by_client_id()` completeness:
   - Page `/rest/api/pet` by `owner_id` until upstream `totalCount` is exhausted.
   - Apply a safety cap of 20 pet pages / 2000 pets; if exceeded, return partial result with `pets_truncated=True`.
   - Preserve batched `patient_id IN [...]` medical-card lookup and response shape.
   - Return `pets_count`, `pets_total`, `pets_truncated`.
6. `create_timesheet()` datetime payload:
   - Normalize `begin_datetime` and `end_datetime` to `YYYY-MM-DD HH:MM:SS` before POST.
   - Reject invalid VM/ISO datetimes before HTTP call.
   - Use `vm_datetime.normalize_vm_datetime()`; timezone offsets are rejected, matching existing VM datetime policy.
7. Tests/docs:
   - Add red/green tests for removed tool, pagination/truncation semantics, owner pet pagination and timesheet normalization.
   - Update README and API notes as needed.

## Out of Scope

- Real API e2e.
- New Payment write alternative workflow via invoices/cassa internals.
- Full pagination redesign for every list tool in the repo.
- Changing public read tool names.
- Changing create/update semantics unrelated to F7-F8/F11-F16.

## Декомпозиция

### 140.1 PRD and review gates

- Создать PRD, изучить artifacts, пройти PRD-review gates.
- Closes: workflow requirement.

### 140.2 Remove unsupported `create_payment`

- Remove MCP registration and registry/description/docs references.
- Tests: tool list no longer exposes `create_payment`; Finance README count updated; access registry no stale entry.
- Closes: F7.
- Оценка: ≤ 150 строк.

### 140.3 Filter contract audit/fixes

- Migrate `tools/invoice.py::get_invoices(client_id)` from top-level `client_id` to `filter[]`.
- Migrate `tools/warehouse.py::get_good_sale_params(good_id)` from top-level `goodId` to `filter[]`.
- Migrate `tools/reference.py::get_cities(title)`, `get_streets(city_id)`, `get_combo_manual_items(combo_manual_name_id)` from top-level legacy params to `filter[]`.
- Document verified top-level `pet_id` special case for vaccinations and custom top-level `campaign` safety special case for message reports.
- Tests: call params for each affected function.
- Closes: F11/F12.
- Оценка: ≤ 150 строк.

### 140.4 Pagination/truncation semantics

- `get_vaccinations`: expose explicit truncation semantics for the returned page.
- `get_daily_schedule`: expose explicit truncation semantics when total exceeds returned rows.
- `get_medical_cards_by_client_id`: page owner pets beyond first 100.
- Tests: multi-page mocked responses for all three tools.
- Closes: F8/F13/F14.
- Оценка: split implementation internally if local module changes grow beyond 150 runtime LOC.

### 140.5 Timesheet datetime normalization

- Normalize `begin_datetime`/`end_datetime` with VM datetime format before POST.
- Tests: ISO `T` input maps to space-separated VM datetime; VM native format passes unchanged; timezone offset and invalid datetime are rejected before HTTP.
- Closes: F16.
- Оценка: ≤ 80 строк.

### 140.6 Docs/API notes

- Update README/tool count and API notes for removed payment create, vaccination special-case params and truncation semantics.
- Add `artifacts/api_crud_permissions-ru.md` to the local project artifact index if it is still missing there.
- Оценка: docs-only.

### 140.7 Checks, audit, external diff review, commit/push

- Targeted tests, full Docker suite, audit, external code/diff review, commit/push, self-attestation.

## Acceptance

- `create_payment` is no longer advertised or callable as an MCP tool.
- Payment read tools remain available.
- `tools/invoice.py::get_invoices(client_id)` encodes `client_id` via `filter[]`.
- `get_good_sale_params(good_id)`, `get_cities(title)`, `get_streets(city_id)` and `get_combo_manual_items(combo_manual_name_id)` encode list constraints via `filter[]`.
- Verified/safety special-case top-level params are documented in code/tests; `MedicalCards/Vaccinations` keeps top-level `pet_id`, and custom `messages/reports` keeps top-level `campaign` until real API verification proves `filter[]` support.
- `get_vaccinations()` returns `returnedCount`, `totalCount` if known, and `truncated`; docstring no longer promises all records unconditionally.
- If vaccinations upstream omits `totalCount` and returned/raw records reach the caller `limit`, `truncated=True`.
- `get_daily_schedule()` returns `returnedCount`, `totalCount`, and `truncated`; because stage 140 keeps `offset=0`, if `totalCount > returnedCount`, `truncated` is true.
- `get_medical_cards_by_client_id()` fetches owner pets until upstream `totalCount` is exhausted or the 2000-pet safety cap is reached; tests mock at least two pet pages and assert page-2 pet IDs are included in the medical-card IN query.
- If the pet safety cap is reached, `pets_truncated=True`.
- Docstrings and `tool_descriptions` for `get_vaccinations`, `get_daily_schedule` and `get_medical_cards_by_client_id` describe truncation/completeness semantics and do not promise completeness incorrectly.
- `create_timesheet()` sends VM datetime format for valid ISO/VM inputs and rejects invalid datetimes before HTTP.
- Targeted tests and full Docker suite pass.
