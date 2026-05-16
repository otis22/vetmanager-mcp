# Этап 161. InvoiceDocument document_id filter hotfix

## Цель

Исправить `get_invoice_documents(invoice_id=...)`, чтобы tool искал строки счета через реальное поле Vetmanager API `invoiceDocument.document_id`.

## Контекст

Feedback report `#2` показал HTTP 500 на `get_invoice_documents` для существующих счетов. Проверка на `devtr6` с тестовым ключом подтвердила contract mismatch:

- `filter=[{"property":"invoice_id","value":2,"operator":"="}]` -> HTTP 500;
- `filter=[{"property":"invoiceId","value":2,"operator":"="}]` -> HTTP 500;
- `filter=[{"property":"documentId","value":2,"operator":"="}]` -> HTTP 500;
- `filter=[{"property":"document_id","value":2,"operator":"="}]` -> HTTP 200, `totalCount=1`, returned row has `document_id=2`.

`document_id` is the parent invoice id for `invoiceDocument`. The public MCP parameter should remain `invoice_id`, because users and agents ask for invoice line items by invoice id.

## Scope

1. Change `tools/finance.py::get_invoice_documents` internal filter from `invoice_id` to `document_id`.
2. Rename/update `tests/test_api_contracts_hotfix.py::test_get_invoice_documents_uses_invoice_id_filter_not_legacy_query_param` to assert `document_id` wire filter for public `invoice_id`.
3. Add explicit pytest assertions that the tool-generated filter properties are exactly `document_id` and none of `invoice_id`, `invoiceId`, or `documentId` appear.
4. Add contract assertion that the public MCP input remains `invoice_id` and does not expose `document_id`; user-facing tool text must not tell agents to pass `document_id`.
5. Reject caller-supplied conflicting filters (`invoice_id`, `invoiceId`, `documentId`, duplicate `document_id`) before HTTP with a clear validation error, instead of forwarding a known-500 shape upstream.
6. Update reference artifacts that currently codify the superseded Stage 122 contract:
   - `artifacts/api_entity_reference-ru.md`;
   - `artifacts/api-research-notes-ru.md`;
   - `AssumptionLog.md` with explicit "Stage 161 supersedes Stage 122 invoiceDocument list-filter finding".
7. Search the codebase for other `/rest/api/invoiceDocument` list filters using `invoice_id` and include the result in the stage log.
8. Run a gated read-only real probe only on the non-production `devtr6` test domain using `.env` test credentials.

## Out of Scope

- Changing the public tool parameter name.
- Rewriting `get_invoice_document_by_id`.
- Adding fallback through `/rest/api/invoice/{id}`.
- Running probes on non-test Vetmanager domains.
- Write-path probing or changing `add_invoice_document`; Stage 161 is read-path only. Any POST contract verification needs a separate explicit stage because it can mutate even `devtr6`.

## Acceptance Criteria

1. `get_invoice_documents(invoice_id=50)` calls `/rest/api/invoiceDocument` with filter property `document_id` and value `50`.
2. The generated request does not include top-level `invoiceId`.
3. The generated filter does not include `invoice_id`, `invoiceId`, or `documentId`.
4. Caller-supplied `filter` entries with `invoice_id`, `invoiceId`, `documentId`, or `document_id` are rejected before HTTP with a clear message telling the caller to use the `invoice_id` argument.
5. Existing caller contract remains `invoice_id`.
6. Tool schema/descriptor tests prove `get_invoice_documents` still exposes public input `invoice_id` and does not expose `document_id` or `documentId` as public input or user-facing instruction.
7. No other tool constructs an `invoice_id`, `invoiceId`, or `documentId` filter against `/rest/api/invoiceDocument`.
8. A gated `devtr6` probe verifies sanitized contract evidence with the exact request shape emitted by the tool (`limit`, `offset`, JSON `filter`): `document_id` succeeds on at least two invoice ids, returned aggregate counts are plausible, and `invoice_id`/`invoiceId`/`documentId` are documented only as failing control probes. Probe output stored in logs/AssumptionLog must include only endpoint path, HTTP status code, filter property/operator/value, `totalCount`, and response field names; no raw request/response bodies, no secrets, no prices, no party data, no clinic PII.
9. Targeted tests, full Docker suite, `git diff --check`, review gates, commit, push, deploy and smoke checks complete.

## Проверки

- Red/targeted: `docker compose --profile test run --rm test sh -c "python -m pytest tests/test_api_contracts_hotfix.py::test_get_invoice_documents_uses_document_id_filter_for_invoice_id -q"`
- Regression/static: `docker compose --profile test run --rm test sh -c "python -m py_compile tools/finance.py && python -m pytest tests/test_api_contracts_hotfix.py tests/test_e2e_mock_finance_warehouse.py tests/test_tools_list_schema.py -q"`
- Gated real probe: `docker compose --env-file .env --profile test run --rm test python <read-only devtr6 probe>`; requires `TEST_DOMAIN=devtr6` and `TEST_API_KEY`; allowed HTTP verb is GET only.
- Full: `docker compose --profile test run --rm test`
- Audit: `git diff --check`
