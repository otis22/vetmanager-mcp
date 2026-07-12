# PRD — Этап 203: Full patient medical profile with owner and invoices

## Контекст

Пользователь сообщил, что запрос «Покажи медицинский профиль Альфа» вернул
ошибку внутреннего инструмента. Ожидаемый ответ: объект с информацией о
пациенте, владельце, 5 последних записях в медкарте с датой и 5 последних
счетах с датой и списком товаров/услуг в каждом счёте.

Существующий `get_pet_profile(pet_id)` уже агрегирует pet, 5 medical cards и
vaccinations, но не включает owner и invoices.

## Цель

Расширить `get_pet_profile` до полного медицинского профиля пациента:

- patient/pet record;
- owner/client record;
- last 5 medical cards;
- vaccinations with last/next vaccination dates;
- last 5 invoices;
- line items/goods/services for each invoice.

Если вторичная секция недоступна, инструмент должен вернуть `partial: true` и
`section_errors`, а не ломать весь профиль.

## Non-goals

- Не добавлять новые write tools.
- Не менять Vetmanager API.
- Не делать fuzzy search по кличке внутри `get_pet_profile`; upstream caller
  должен передать известный `pet_id`.
- Не менять privacy/depersonalization policy: новые owner/invoice fields должны
  проходить через существующий tool-result sanitizer, когда token/grant
  depersonalized.

## Проверенные факты и артефакты

- `artifacts/technical-requirements-vetmanager-mcp-ru.md` фиксирует текущий
  `resources/pet_profile.py::fetch(pet_id)` как 3-section aggregator:
  pet + MedicalCards by `patient_id` + vaccinations.
- `artifacts/api_entity_reference-ru.md`:
  - `Pet.owner_id` — внешний ключ к `client`.
  - `MedicalCards.patient_id` — внешний ключ к `pet`.
  - `Invoice.pet_id` — внешний ключ к `pet`.
  - `Invoice.invoice_date` — дата счёта.
  - `Invoice.invoiceDocuments` может присутствовать как вложенный массив.
  - `invoiceDocument.document_id` — ID родительского счёта (`invoice.id`);
    stage 161 probe: list filter принимает `document_id`, а
    `invoice_id` / `invoiceId` / `documentId` дают HTTP 500.
- `tools/finance.py::get_invoice_documents()` уже использует
  `/rest/api/invoiceDocument` с filter `document_id = invoice_id`.
- `resources._aggregation.gather_sections()` уже даёт partial-failure pattern:
  sub-request exception превращается в fallback section + structured
  `section_errors`.

## Архитектурное решение

### Проблема

Текущий tool называется и описывается как full pet/patient profile, но фактически
не содержит владельца и финансовый контекст. LLM вынужден делать дополнительные
tool calls или, при ошибке одного участка, сообщает пользователю внутреннюю
ошибку вместо частичного профиля.

### Контекст и ограничения

- `pet` нужен первым, потому что `owner_id` берётся из pet response.
- Medical cards and vaccinations can remain parallel with invoices once pet id
  is known.
- Owner request depends on `owner_id`; if pet section fails or owner_id missing,
  owner should be `{}` and section error/warning should explain missing owner.
- Invoice line items depend on invoice ids; keep bounded fan-out: max 5 invoice
  documents requests, each with limit 50. Each invoice must expose
  `invoice_documents_total`, `invoice_documents_truncated` and
  `invoice_documents_error` when applicable, so line-item truncation or a
  single invoice-doc failure is not silent.
- Owner fetch is two-phase: fetch `pet` first, then fetch owner only when
  `owner_id` is present. Missing `owner_id` is represented as `owner: {}` plus
  a structured section error/warning, not an invalid `/client/0` call.
- Owner/invoices are optional sections by runtime scopes. Tool entry remains
  backward-compatible with the old clinical profile scopes; if token lacks
  `clients.read` or `finance.read`, the corresponding section is skipped with a
  structured `section_errors` entry instead of hard-denying the whole tool.
- Existing response keys (`pet`, `last_medical_cards`, `vaccinations`,
  `last_vaccination_date`, `next_vaccination_date`) must remain.

### Рассмотренные варианты

1. Создать новый tool `get_full_patient_medical_profile`.
   - Плюс: можно не менять старый scope contract.
   - Минус: модель уже выбирает `get_pet_profile`; появится дубль.
2. Расширить `get_pet_profile`.
   - Плюс: соответствует текущему prompt/tool description и пользовательскому
     ожиданию "медицинский профиль".
   - Минус: required scopes расширяются до `clients.read` и `finance.read`.

### Выбранное решение

Вариант 2. Расширить `resources/pet_profile.py::fetch` и оставить tool name
`get_pet_profile`. Добавить `owner` и `last_invoices`, где каждый invoice
содержит `invoice_documents` / line items.

### Инварианты

- Existing response keys remain backward compatible.
- `get_pet_profile` entry required scopes remain `pets.read` and
  `medical_cards.read` for backward compatibility; owner section requires
  runtime `clients.read`, invoices section requires runtime `finance.read` and
  degrades to partial when missing.
- Invoice line item filter uses `document_id`, not `invoice_id`.
- Fan-out is bounded to 5 invoice-document requests.
- Returned invoice list is sorted client-side by `invoice_date DESC`, then
  `id DESC` within the bounded fetched page. The fetched page also uses
  server-side `invoice_date DESC`, `id DESC`; real Vetmanager probe on
  2026-07-12 confirmed this sort is accepted by `/rest/api/invoice`.
- Secondary section failures return partial result with `section_errors`.
- Mixed invoice document outcomes preserve successful invoice line items; only
  failed/truncated invoice documents are marked on the affected invoice and in
  `section_errors.invoice_documents`.

### Rollback/fallback

Если invoice line items endpoint нестабилен на production, оставить invoices
без line items как partial section and expose `section_errors.invoice_documents`.
Не откатывать owner/medical cards/vaccinations.

## Декомпозиция

- 203.1 PRD/research and review gates.
- 203.2 Tests: full profile with owner + 5 medical cards + 5 invoices +
  invoice documents.
- 203.3 Tests: partial invoice documents failure keeps pet/owner/medical cards.
- 203.4 Implementation in `resources/pet_profile.py`.
- 203.5 Scope registry/tool description/prompt updates.
- 203.6 Checks, audit, reviews, deploy/smoke.

## Acceptance criteria

- `get_pet_profile(14)` can return `pet.id=14`, owner/client object,
  `last_medical_cards` max 5 sorted recent-first, and `last_invoices` max 5
  client-side sorted by `invoice_date DESC`, `id DESC` within the bounded fetched
  page.
- Each returned invoice has invoice date and `invoice_documents` list with
  goods/services line items from `/rest/api/invoiceDocument` filtered by
  `document_id`, plus `invoice_documents_total` and
  `invoice_documents_truncated`.
- If invoice document section fails for one invoice, profile remains partial
  rather than hard-failing, and successful invoice document sections remain
  attached to their invoices.
- If pet has no `owner_id` or owner request fails, profile remains partial with
  `owner: {}` and structured section error/warning.
- Tool entry scopes are not expanded; clients/finance are optional
  section-level scopes. Missing section scopes produce partial output instead
  of tool denial.
- Tool description and `pet_full_profile` prompt tell the model that owner and
  recent invoices are included.
- Targeted tests and full suite pass.

## Тесты

- `tests/test_e2e_mock_clinical_profiles.py`: real `resources.pet_profile.fetch`
  mock test for full profile shape.
- Partial failure test for invoice document request.
- Missing owner id and owner API failure tests.
- Mixed invoice document success/failure test preserving successful line items.
- `tests/test_stage130_access_registry.py`: preset coverage for read/analytics
  scopes remains correct.
- Scope/partial test: token with old `pets.read + medical_cards.read` can still
  call `get_pet_profile` and receives owner/invoices section errors rather than
  preflight denial.
- `tests/test_stage132_scope_enforcement.py`: aggregate scope enforcement
  expected missing scopes updated if needed.

## Review notes

- Spark PRD review 2026-07-12: accepted findings for explicit invoice sorting,
  invoice document truncation metadata, two-phase owner fetch, mixed per-invoice
  document partial semantics, and missing-owner/owner-failure test coverage.
- Strong PRD review 2026-07-12: accepted findings to keep old entry scopes and
  make owner/invoices optional section-level scope checks; accepted finding to
  verify/filter/sort invoice contract or use bounded client-side fallback;
  accepted finding to rely on existing depersonalization sanitizer for new owner
  fields and test that path.
- Claude Opus code review 2026-07-12: accepted findings to avoid unverified
  server-side sort keys. MedicalCards sort was reverted to the existing `id DESC`
  contract. A follow-up real Vetmanager probe confirmed `/rest/api/invoice`
  accepts `invoice_date DESC`, `id DESC`, so the invoice bounded page uses that
  server-side sort and keeps client-side sorting as a deterministic fallback.

## Оценка простоты

Не добавляем новый tool и не вводим новый abstraction. Расширяется существующий
aggregator с bounded fan-out и существующим `gather_sections` partial pattern.
