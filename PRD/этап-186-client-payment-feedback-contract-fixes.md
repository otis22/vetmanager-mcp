# Этап 186. Client and payment feedback contract fixes

## Контекст

Production feedback от 2026-07-08:

- `#22`, `#23`, `#24`: `get_clients(name=...)` returned broad/unfiltered client
  lists. Root cause in MCP: `name` передавался как отдельный query param через
  `extra={"name": name}`, а не как авторитетный Vetmanager `filter`.
- `#25`: `get_payments(client_id=..., date_from=..., date_to=..., status=...)`
  returned HTTP 500.

Цель stage: привести MCP tool contracts к фактической Vetmanager REST-модели,
закрыть оба feedback clusters и не вводить скрытый fallback, который подменяет
одну сущность другой.

## Проверенные факты

Источник: `/home/otis/myprojects/vetmanager-extjs`.

- `rest/protected/models/Payment.php` содержит поля `id`, `amount`, `status`,
  `cassa_id`, `cassaclose_id`, `create_date`, `payed_user`, `description`,
  `payment_type`, `invoice_id`. В модели нет `client_id` и `pet_id`.
- `rest/protected/controllers/PaymentController.php` разрешает только
  `restList`/`restView`; list идёт через стандартный REST filter по model
  attributes.
- `rest/protected/models/Invoice.php` содержит `client_id` и `pet_id`.
- `rest/protected/models/ClosingOfInvoices.php` содержит `client_id`,
  `plus_amount`, `plus_type_document`, `plus_document_id`, `minus_amount`,
  `minus_type_document`, `minus_document_id`, `create_date`; relations:
  `invoice` через `minus_document_id` при `minus_type_document='invoice'`,
  `plus_payment` через `plus_document_id` при `plus_type_document='payment'`.

Источник: real API probe on `devtr6` (read-only, без вывода PII/API key).

- `/rest/api/payment?limit=5` возвращает 200; rows имеют keys:
  `amount`, `cassa`, `cassa_id`, `cassaclose_id`, `create_date`,
  `description`, `id`, `invoice_id`, `parent_id`, `payed_user`,
  `payment_type`, `status`.
- `/rest/api/payment` with filter `client_id = <existing client_id>` returns
  HTTP 500: `Unknown column 't.client_id' in 'where clause'`.
- `/rest/api/payment` with filter `invoice_id = <existing invoice_id>` returns
  200.
- `/rest/api/invoice/{invoice_id}` returns invoice with `client_id`.
- `/rest/api/closingOfInvoices?limit=5` returns 200 with data key
  `closingOfInvoices` and row keys `client_id`, `plus_type_document`,
  `plus_document_id`, `minus_type_document`, `minus_document_id`, `plus_payment`,
  `invoice`, `create_date`, `plus_amount`, `minus_amount`.
- `/rest/api/closingOfInvoices` filters `client_id = ...`,
  `plus_type_document = payment`, and `minus_type_document = invoice` return 200.
- `/rest/api/closingOfInvoices` filters `create_date >= ...`,
  `create_date < ...`, `minus_document_id = ...`, and
  `minus_document_id IN [...]` return 200 on `devtr6`.
- `/rest/api/invoice` list filters `client_id = ...` and
  `client_id = ... + pet_id = ...` return 200 on `devtr6`.
- `/rest/api/client` supports `LIKE` filters on `last_name`, `first_name`, and
  `middle_name` on `devtr6`, including exact, prefix (`xx%`) and contains
  (`%xx%`) patterns.

## Архитектурное решение

### Проблема

Existing MCP contract exposes filters that are not supported by the upstream
Payment model (`client_id`) and uses an unverified `name` query parameter for
client search. This causes privacy-risk broad results and upstream 500 errors.

### Контекст и ограничения

- Do not invent Vetmanager API behavior. Source of truth is extjs source +
  real `devtr6` probes.
- MCP tools should not silently return a partial result while pretending to be a
  direct REST entity wrapper.
- Tool outputs may include client/payment/invoice data; avoid extra PII
  enrichment and do not log raw records.
- Existing `get_payments` callers may use `status`, `date_from/date_to`,
  `filter`, `sort`, `limit`, `offset`. These must keep working.
- `get_clients` name search is a convenience MCP contract; Vetmanager REST
  filters do not expose OR across properties, so MCP must merge multiple
  bounded requests.
- Existing `get_payments(client_id=...)` is documented locally but broken in
  production (upstream HTTP 500). A local validation error is an intentional
  safer failure mode, not a silent behavior change.
- Merged OR name search cannot provide stable deep pagination because each
  field query has independent ordering. The supported contract is first-page
  lookup, with a clear local error for `name` plus `offset > 0`.

### Рассмотренные варианты

1. Keep `get_payments(client_id)` and fallback through invoices.
   - Pros: same user-facing tool name.
   - Cons: hidden semantic substitution, can miss payments without invoice
     binding or with pagination; returned data would not be a direct Payment
     list. Rejected.

2. Stop supporting `client_id` as an HTTP filter in `get_payments` and add
   `get_client_payment_applications`.
   - Pros: honest contracts; `get_payments` remains a direct Payment REST list;
     business query uses the join entity that actually has `client_id`.
   - Cons: new tool and docs/tests needed. Selected. For backward schema
     compatibility, the deprecated `client_id` argument may remain visible but
     must fail locally before any `/rest/api/payment` HTTP call.

3. Implement `get_client_payment_applications` by invoices -> payment
   `invoice_id IN`.
   - Pros: simple for invoice-bound payments.
   - Cons: misses balance/advance closing operations; ignores
     `closingOfInvoices` relation that explicitly models client/payment/invoice.
     Rejected.

### Выбранное решение

- `get_clients(name=...)`: issue three parallel `/rest/api/client` requests with
  filters `last_name LIKE name`, `first_name LIKE name`,
  `middle_name LIKE name`; merge by `id`; do not send query param `name`.
  The merge path rejects `offset > 0` with a clear local error because stable
  deep pagination cannot be guaranteed across three independent OR queries. To
  keep requests bounded, each field query fetches at most 100 rows.
- `get_payments`: keep as direct `/rest/api/payment` wrapper; reject
  `client_id` before HTTP with a clear error that Payment REST has no
  `client_id` filter and `get_client_payment_applications` should be used.
  The public schema may keep `client_id` as deprecated compatibility surface,
  but descriptions must not present it as a supported Payment filter.
- Add `get_client_payment_applications`: list client payment applications through
  `/rest/api/closingOfInvoices` with filters:
  - required `client_id = ...`;
  - `plus_type_document = payment`;
  - optional `date_from/date_to` on `create_date` as half-open local day range;
  - optional `pet_id` via prefetching invoice IDs from `/rest/api/invoice`
    filtered by `client_id + pet_id`, then `minus_type_document=invoice` and
    `minus_document_id IN invoice_ids`. This path is capped at 100 invoice IDs;
    if upstream reports more, return a clear error asking for a narrower date
    range/client-pet context instead of issuing an unbounded `IN`;
  - optional `payment_status` filters nested `plus_payment.status` only if
    upstream relation filtering is proven safe; otherwise out of scope for v1.
- Return upstream `closingOfInvoices` rows, preserving nested `plus_payment`
  and `invoice`, with metadata: `client_id`, `pet_id`, `date_from`, `date_to`,
  `total`, `count`, `limit`, `offset`, `truncated`. The tool name intentionally
  says `payment_applications`: unapplied/advance payments that are not represented
  in `closingOfInvoices` are out of scope and must not be implied as complete.

### Инварианты

- `get_payments(client_id=...)` must not send HTTP to `/rest/api/payment`.
- `get_payments` without `client_id` preserves existing date/status/filter
  behavior.
- `get_client_payment_applications` must not expose raw API keys or extra
  unbounded PII joins.
- `pet_id` path must short-circuit to an empty result when no invoices match,
  not build `IN []`.
- `pet_id` path must not build `IN` with more than 100 invoice IDs.
- If upstream omits `totalCount`, result metadata must not claim completeness.

### Rollback / fallback

- If `closingOfInvoices` contract changes, disable or remove
  `get_client_payment_applications` while keeping `get_payments` direct Payment
  wrapper.
- If future Payment REST gains real `client_id`, add it back only after a real
  API probe and tests; do not infer from OpenAPI alone.

## Scope

### 186.1 PRD/research

- Read extjs models/controllers.
- Probe `devtr6` for Payment/ClosingOfInvoices filter and shape.
- Update PRD with exact facts.

### 186.2 `get_clients` name search

- Replace `extra={"name": name}` with filters across
  `last_name/first_name/middle_name`.
- Tokenize whitespace-separated names. For one token, search that token across
  `last_name/first_name/middle_name`. For multiple tokens, search each token
  across fields and return clients whose combined name text contains every
  token case-insensitively after the bounded fetch.
- Merge by `id`, cap by `limit`, keep per-field upstream fetch bounded to max
  100 rows. Reject `name` search with `offset > 0` until a stable indexed
  upstream search exists.
- Add regression test proving `name` query param is absent.

### 186.3 `get_payments` contract

- Reject `client_id` before HTTP.
- Update docs/descriptions/schema tests.
- Replace old test that expected `client_id` filter.

### 186.4 `get_client_payment_applications`

- Add MCP tool in finance module.
- Register access scope.
- Cover date range, client filter, pet filter, no invoice short-circuit,
  pagination metadata.

### 186.5 Artifacts/docs/tests

- Update `api_entity_reference-ru.md` for Payment and ClosingOfInvoices.
- Update `tool_descriptions.py` and README/tool schema expectations if needed.
- Add opt-in real `devtr6` smoke for `get_client_payment_applications`.

### 186.6 Workflow closure

- Targeted tests, full Docker test suite, audit, review gates, commit/push,
  deploy/smoke.
- Mark feedback/known issues fixed only after deployed smoke confirms behavior.

## Acceptance criteria

- `get_clients(name="...")` sends only `filter`, never query param `name`.
- `get_payments(client_id=42)` raises a clear local error and makes no upstream
  `/payment` call.
- `get_clients(name="...")` regression test includes a nonmatching broad row and
  asserts it is not returned after MCP merge/filtering.
- `get_clients(name="Last First")` multi-token regression returns only clients
  whose combined name text contains every token.
- `get_client_payment_applications(client_id=existing)` returns
  `closingOfInvoices` rows on `devtr6` with nested payment/invoice context when
  upstream provides it, and documentation states it is not a complete list of
  unapplied/advance payments.
- `get_client_payment_applications(date_from/date_to)` sends verified
  half-open `create_date` filters and is covered by tests.
- `get_client_payment_applications(client_id, pet_id)` filters through invoices
  and does not return rows for other pets.
- `get_client_payment_applications(client_id, pet_id)` refuses unbounded
  invoice-ID fanout above 100 IDs.
- `api_entity_reference-ru.md` no longer claims `Payment.client_id`.
- Production feedback `#24/#25` are linked to fixed known issues after deploy.

## Review findings log

- Spark PRD review (`gpt-5.3-codex-spark`, first read-only run hung in sandbox;
  repeated once with `-s danger-full-access`, review-only): accepted bounded
  `pet_id` invoice fanout and explicit merged-name offset handling.
- Rejected Spark finding about needing a deprecation path for
  `get_payments(client_id)`: production behavior is already HTTP 500, so local
  validation is safer and more actionable than preserving a broken call path.
- Claude Opus Architecture/PRD review 1 accepted findings: verify client LIKE
  behavior on `devtr6`, support multi-token names, avoid pretending merged OR
  search has stable deep pagination, assert behavior-level narrowing in tests,
  and rename/scope the new client payment tool as payment applications rather
  than complete payments.
- Claude Opus Architecture/PRD review 2 accepted findings: verify
  `middle_name LIKE`, remove contradictory offset wording, and standardize the
  new tool name to `get_client_payment_applications`.
- Claude Opus Architecture/PRD review 3 accepted findings: verify
  `closingOfInvoices` date and `minus_document_id IN` filters, verify invoice
  list `client_id + pet_id`, and add explicit acceptance for multi-token client
  names and date-range payment applications.

## Architecture Critique

Required: yes. This changes public MCP contracts and production behavior.

## Simplicity check

Keep v1 narrow:

- No hidden fallback inside `get_payments`.
- No aggregation/summing in `get_client_payment_applications`.
- No broad N+1 enrichment; rely on upstream nested relations.
- No nested relation filtering unless proven by real API.
