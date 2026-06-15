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
- `GET /rest/api/good/checkProductData` calculates combination price when called with `good_id=-{tag_id}`, `tag_id={tag_id}`, `qty`, `clinic_id`.

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
   - Fetch more than requested until either `limit` accepted rows is reached, the upstream page is exhausted, or hard cap is hit.
   - Cap must prevent runaway calls.
3. Enrich combination rows via `GET /rest/api/goodTag`.
   - Use bulk lookup if `goodTag` supports id IN in real/mock probe.
   - Otherwise use bounded per-tag lookups with dedupe.
   - Default `include_template_combinations=false` must exclude `is_template=1`.
4. Add MCP tool `get_good_combination`.
   - Parameters: `tag_id: int`, `clinic_id: int = 1`.
   - Use `GET /rest/api/goodTag` filter by `id`.
   - Return combination metadata and `positions[]`.
5. Add MCP tool `calculate_good_combination_price`.
   - Parameters: `tag_id: int`, `quantity: float = 1`, `clinic_id: int = 1`.
   - Use `GET /rest/api/good/checkProductData` with `good_id=-{tag_id}`, `tag_id`, `qty`.
   - Return server-calculated `price`, `amount`, `action_is_possible`, `allowed_quantity`, `message`, and raw payload.
6. Update tool descriptions, access registry, README matrix, and API reference notes for the new read-only tools.

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
9. Real API smoke on `devtr6` covers ordinary combination `tag_id=2`, template filtering for `tag_id=6`, and price calculation.

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
docker compose --env-file .env --profile test run --rm test python -m pytest tests/test_e2e_real.py -k 'invoice_goods or good_combination' -q
docker compose --profile test run --rm test
git diff --check
python3 scripts/check_no_historical_api_key_literal.py
```
