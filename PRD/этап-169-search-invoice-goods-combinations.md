# Этап 169. Invoice-ready goods search with combinations

## Цель

Добавить read-only MCP-инструменты для поиска номенклатуры в формате, пригодном для счёта, с корректной поддержкой обычных комбинаций товаров/услуг (`goodTag`) и серверным расчётом стоимости комбинации.

## Контекст

OpenAPI diff 2026-06-15 показал новый/расширенный `goodTag` surface, но локальная OpenAPI 1.2.0 не описывает custom endpoints `GoodController`. Пользователь уточнил бизнес-семантику: `goodTag` — это комбинации товаров/услуг; write tools не нужны; в списке номенклатуры должны быть видны обычные не-шаблонные комбинации; MCP должен уметь считать стоимость комбинации.

Источники истины:

- `/home/otis/myprojects/vetmanager-extjs/rest/protected/controllers/GoodTagController.php`
- `/home/otis/myprojects/vetmanager-extjs/rest/protected/controllers/GoodController.php`
- `/home/otis/myprojects/vetmanager-extjs/application/src/Entity/GoodEntity.php`
- `/home/otis/myprojects/vetmanager-extjs/application/src/Entity/Goods/Records/GoodTagRow.php`
- `/home/otis/myprojects/vetmanager-extjs/application/src/Entity/Goods/Records/Good2TagRow.php`
- Help article: `https://help.vetmanager.ru/article/25283`

Real API facts verified on `devtr6`:

- `GET /rest/api/good/productsDataForInvoice` accepts `clinic_id`, `limit`, `offset`, `search_query`, optional `category_id`.
- Ordinary combination `tag_id=2` returns as invoice row: `id="-2"`, `good_group="GoodsSets"`, `price=200`, `default_price=200`.
- Template combination `tag_id=6` returns as invoice row too: `id="-6"`, `good_group="GoodsSets"`, `price=151`, `default_price=151`.
- `productsDataForInvoice` does not return `is_template`.
- `exclude_templates`, `excludeTemplates`, `good_sets`, `no_good_sets` did not exclude template combinations in real probe.
- `GET /rest/api/goodTag` with filter by `id` returns `positions[]`, including `quantity`, `sale_param_id`, `price`, `price_formation`, `markup`, nested `good`, nested `good_sale_param`.
- Source check on 2026-06-16 confirmed `GoodTagController::doRestList()` returns all matching tags in one response and loads `positions[]` for the returned tag IDs; enrichment should use a bounded bulk `id IN [...]` request when there are multiple combination rows.
- `GET /rest/api/good/checkProductData` calculates combination price when called with `good_id=-{tag_id}`, `tag_id={tag_id}`, `qty`, `clinic_id`.

## Custom endpoint contract

These endpoints are extjs-source-backed and not present in sanitized local OpenAPI 1.2.0. Implementation must treat this section and `artifacts/stage169-invoice-goods-contract.md` as the Stage 169 contract.

### `GET /rest/api/good/productsDataForInvoice`

Request params:

- `clinic_id` required positive integer.
- `limit` 1..100.
- `offset` 0..10000.
- `search_query` optional string.
- `category_id` optional integer; omit when zero.

Expected response shape:

- Top-level VM envelope with `success`, `message`, `data`.
- `data.good` is an array; `data.totalCount` is optional/endpoint-dependent and must not be the only pagination stop condition.
- Required row fields used by MCP: `id`, `name` or `title`, `good_group`, `price`, `default_price`.
- Combination row detection: `tag_id > 0` or negative numeric `id`; expected `good_group="GoodsSets"`.
- Positive enrichment key: use `tag_id` when present and positive; otherwise derive `abs(int(id))` when `id` is a negative numeric string. If neither yields a positive tag ID, treat the row as ambiguous and apply the enrichment miss/fail-closed policy.
- Optional row fields preserved when present: `tag_id`, `group_id`, `is_active`, `quantity`, `sale_param_id`, `barcode`, `category_id`, `category`, `editable`, `unit_sale_param_title`.
- Do not trust `is_template` from this endpoint for filtering even if future versions include it; enrichment via `goodTag` remains the source for template status.

### `GET /rest/api/goodTag`

Request params:

- `limit`, `offset`, optional `clinic_id`.
- For enrichment, use `filter=[{"property":"id","operator":"IN","value":[...]}]` with deduped positive `tag_id` values.
- Enrichment requests must set `limit` to the number of requested tag IDs, capped at 50, and `offset=0`; otherwise Vetmanager list pagination can silently truncate the metadata response.
- For single combination lookup, use `filter=[{"property":"id","operator":"=","value":tag_id}]`.

Expected response shape:

- `data.goodTag` array.
- Required tag fields used by MCP: `id`, `title`, `is_template`.
- Template normalization: `is_template` is true only when `str(value).strip() == "1"` or `value is True`; false when `str(value).strip() == "0"` or `value is False`; missing/empty/null is ambiguous and normalized to `null`.
- `positions[]` may be absent/empty, but when present must be preserved. Required position fields to preserve: `tag_id`, `quantity`, `sale_param_id`, `price`, `price_formation`, `markup`, nested `good`, nested `good_sale_param`.
- Enrichment miss/failure policy: default search must fail closed for ambiguous combination rows. If a row is a combination and its tag metadata is missing, exclude it when `include_template_combinations=false` and include warning metadata; when `include_template_combinations=true`, return the row with `is_template=null` and warning metadata.

### `GET /rest/api/good/checkProductData`

Request params:

- `good_id=-{tag_id}`.
- `tag_id={tag_id}`.
- `qty` positive number.
- `clinic_id` positive integer.

Expected response shape:

- Top-level VM envelope with `success`, `message`, `data`.
- `data.good` includes server-calculated `price`, `amount`, `qty`, `default_price`, and combination identifiers when returned.
- `data.action_is_possible`, `data.allowed_quantity`, and optional `data.message`/top-level `message` are preserved.
- MCP does not calculate price manually from `positions[]`.

## Scope

1. Add MCP tool `search_invoice_goods`.
   - Use `GET /rest/api/good/productsDataForInvoice`.
   - Parameters:
     - `query: str = ""` mapped to `search_query`;
     - `clinic_id: int = 1`;
     - `limit: LimitParam = 20`;
     - `offset: int = 0`;
     - `category_id: int = 0`;
     - `include_template_combinations: bool = false`.
   - Return invoice-ready goods/services and ordinary combinations.
   - Mark rows with normalized fields:
     - `is_combination`;
     - `combination_tag_id`;
     - `is_template` for combination rows after enrichment;
     - `invoice_good_id` preserving API row `id` (`494_968_0`, `-2`, etc.).
2. Use overfetch for `search_invoice_goods`.
   - Because template combinations are filtered after `productsDataForInvoice` pagination.
   - Use fixed upstream page size `100` for `productsDataForInvoice` overfetch, independent of MCP `limit` (which remains `LimitParam`, 1..100).
   - Fetch more than requested until either `limit` accepted rows is reached, the upstream page is exhausted, or hard cap is hit.
   - Hard caps: at most 5 upstream `productsDataForInvoice` pages, at most 500 upstream product rows inspected, and at most 50 distinct combination `tag_id` values enriched per MCP call.
   - Return metadata: `requested_limit`, `accepted_count`, `inspected_count`, `upstream_pages_fetched`, `overfetch_cap_reached`, `warnings[]`.
3. Enrich combination rows via `GET /rest/api/goodTag`.
   - Use bounded bulk lookup with `filter=[{"property":"id","operator":"IN","value":[...]}]` for deduped `tag_id` values.
   - Keep a hard cap on enriched tag IDs to prevent runaway secondary requests.
   - Default `include_template_combinations=false` must exclude `is_template=1`.
   - Default fail-closed on missing tag metadata: exclude ambiguous combination rows and add a warning; do not leak possible template combinations into default results.
   - With `include_template_combinations=true`, return ambiguous combination rows with `is_template=null` and warning metadata because the caller explicitly requested all combinations.
4. Add MCP tool `get_good_combination`.
   - Parameters: `tag_id: int`, `clinic_id: int = 1`.
   - Use `GET /rest/api/goodTag` filter by `id`.
   - Return combination metadata and `positions[]`.
5. Add MCP tool `calculate_good_combination_price`.
   - Parameters: `tag_id: int`, `quantity: float = 1`, `clinic_id: int = 1`.
   - Use `GET /rest/api/good/checkProductData` with `good_id=-{tag_id}`, `tag_id`, `qty`.
   - Return server-calculated `price`, `amount`, `action_is_possible`, `allowed_quantity`, `message`, and raw payload.
6. Update tool descriptions, access registry, README matrix, and API reference notes for the new read-only tools.

## Scope mapping

All Stage 169 tools are read-only inventory/catalog operations:

- `search_invoice_goods` -> `inventory.read`
- `get_good_combination` -> `inventory.read`
- `calculate_good_combination_price` -> `inventory.read`

Implementation must update:

- `tool_access_registry.py::TOOL_REQUIRED_SCOPES`
- `token_scopes.py::required_scope_for_request`: `GET /rest/api/good/productsDataForInvoice` and `GET /rest/api/good/checkProductData` are already covered by entity `good` -> `inventory.read`; add lowercase entity key `goodtag` -> `inventory.read` for `GET /rest/api/goodTag`.
- marketed preset coverage if inventory preset should expose the tools
- tests for sufficient-scope pass and insufficient-scope preflight failure

## Out of Scope

- `create_good_tag`, `update_good_tag`, `delete_good_tag`.
- Any invoice creation or invoice document mutation.
- Replacing existing `get_goods` behavior.
- Manual price calculation in MCP from `positions[]`.
- Full OpenAPI artifact replacement from the published YAML.
- Solving clinic context discovery beyond explicit/default `clinic_id`.

## Acceptance Criteria

1. `search_invoice_goods(query="ggg", clinic_id=1)` returns ordinary combination rows and marks them as `is_combination=true`, `is_template=false`.
2. `search_invoice_goods(query="Тест1", clinic_id=1, include_template_combinations=false)` does not return the template combination `tag_id=6` on `devtr6`.
3. `search_invoice_goods(query="Тест1", clinic_id=1, include_template_combinations=true)` can return template combination rows marked `is_template=true`.
4. Overfetch fills pages after filtering template combinations up to requested `limit` when upstream data allows it, without unbounded calls.
5. `get_good_combination(tag_id=2, clinic_id=1)` returns `positions[]` and preserves `quantity`, `sale_param_id`, `price_formation`, nested `good`, nested `good_sale_param`.
6. `calculate_good_combination_price(tag_id=2, quantity=2, clinic_id=1)` returns server-calculated `amount` and availability fields.
7. New tools are read-only and have explicit access registry mappings.
8. Mock e2e tests cover ordinary combination, template filtering, template inclusion, overfetch, empty result, and price calculation.
9. Mock tests cover explicit caps: max 5 product pages, max 500 inspected rows, max 50 enriched tag IDs, and missing/partial `goodTag` enrichment fail-closed behavior.
10. Scope tests cover all three tools and direct request-scope mapping for all three upstream paths.
11. Real API smoke on `devtr6` first verifies current fixture availability. If known fixture IDs still exist, cover ordinary combination `tag_id=2`, template filtering for `tag_id=6`, template-included mode, and price calculation. If fixture IDs changed, skip exact-id assertions and assert structural invariants for whatever GoodsSets rows are available without creating/modifying data.

## Decomposition

- 169.1 PRD/research review: validate extjs-source-backed custom endpoint contract and overfetch design.
- 169.2 Add low-level helpers for invoice-goods search, combination row detection, `goodTag` enrichment, and bounded overfetch.
- 169.3 Add `search_invoice_goods` MCP tool with tests.
- 169.4 Add `get_good_combination` MCP tool with tests.
- 169.5 Add `calculate_good_combination_price` MCP tool with tests.
- 169.6 Update tool descriptions, access registry, README, API reference/research notes.
- 169.7 Run targeted tests, real `devtr6` smoke, full suite, audit, review gates, AssumptionLog, commit/push/deploy if implementation is requested.

## Simplicity rationale

- Add a separate `search_invoice_goods` instead of changing `get_goods`, preserving the existing catalog contract.
- Reuse Vetmanager server calculation via `checkProductData`; do not duplicate price/stock logic in MCP.
- Filter templates by `goodTag` enrichment because `productsDataForInvoice` does not expose `is_template` and ignores tested template-exclusion params.
- Use bounded overfetch rather than returning predictably short pages after filtering.

## Проверки

During implementation:

```bash
docker compose --profile test run --rm test pytest tests/test_stage169_invoice_goods_combinations.py -q
docker compose --profile test run --rm test pytest tests/test_e2e_mock_entities.py tests/test_tools_list_schema.py tests/test_stage130_access_registry.py -q
docker compose --env-file .env --profile test run --rm test python -m pytest tests/test_e2e_real.py -k 'stage169_invoice_goods or stage169_good_combination' -q
docker compose --profile test run --rm test
git diff --check
python3 scripts/check_no_historical_api_key_literal.py
```
