# Stage 169 Invoice Goods Custom Endpoint Contract — 2026-06-16

This artifact documents the extjs-source-backed custom endpoints used by Stage 169. They are not present in the sanitized local OpenAPI 1.2.0 artifact.

## Sources

- `/home/otis/myprojects/vetmanager-extjs/rest/protected/controllers/GoodTagController.php`
- `/home/otis/myprojects/vetmanager-extjs/rest/protected/controllers/GoodController.php`
- `/home/otis/myprojects/vetmanager-extjs/application/src/Entity/GoodEntity.php`
- `AssumptionLog.md` entries from 2026-06-15 for `search_invoice_goods` and template-combination recheck.

## `GET /rest/api/good/productsDataForInvoice`

Request params:

- `clinic_id`: required positive integer.
- `limit`: 1..100.
- `offset`: 0..10000.
- `search_query`: optional string.
- `category_id`: optional integer; omit when zero.

Expected response:

- VM envelope: `success`, `message`, `data`.
- Rows under `data.good`.
- `data.totalCount` may exist but must not be the only pagination stop condition.
- MCP required row fields: `id`, `name` or `title`, `good_group`, `price`, `default_price`.
- Combination row: `tag_id > 0` or negative numeric `id`; expected `good_group="GoodsSets"`.
- Positive enrichment key: use `tag_id` when present and positive; otherwise derive `abs(int(id))` when `id` is a negative numeric string. If neither yields a positive tag ID, treat the row as ambiguous and apply the enrichment miss/failure policy.
- Preserve optional row fields when present: `tag_id`, `group_id`, `is_active`, `quantity`, `sale_param_id`, `barcode`, `category_id`, `category`, `editable`, `unit_sale_param_title`.
- Do not trust this endpoint as the template-status source. Template filtering uses `goodTag` enrichment.

## `GET /rest/api/goodTag`

Request params:

- `limit`, `offset`, optional `clinic_id`.
- Bulk enrichment filter: `filter=[{"property":"id","operator":"IN","value":[...]}]`.
- Bulk enrichment must set `limit` to the number of requested tag IDs, capped at 50, and `offset=0`.
- Single lookup filter: `filter=[{"property":"id","operator":"=","value":tag_id}]`.

Expected response:

- VM envelope with rows under `data.goodTag`.
- Required tag fields: `id`, `title`, `is_template`.
- Template normalization: true iff `str(is_template).strip() == "1"` or `is_template is True`; false iff `str(is_template).strip() == "0"` or `is_template is False`; missing/empty/null becomes ambiguous `null`.
- `positions[]` may be absent/empty; when present, preserve:
  `tag_id`, `quantity`, `sale_param_id`, `price`, `price_formation`, `markup`,
  nested `good`, nested `good_sale_param`.

Enrichment miss/failure policy:

- Default `include_template_combinations=false`: fail closed by excluding ambiguous combination rows and adding warning metadata.
- `include_template_combinations=true`: return ambiguous combination rows with `is_template=null` and warning metadata.

## `GET /rest/api/good/checkProductData`

Request params for combinations:

- `good_id=-{tag_id}`.
- `tag_id={tag_id}`.
- `qty`: positive number.
- `clinic_id`: positive integer.

Expected response:

- VM envelope with `data.good`, `data.action_is_possible`, `data.allowed_quantity`.
- Preserve server-calculated `price`, `amount`, `qty`, `default_price`, `party_accounts`, `party_accounts_count`, `unit_sale_param_title`.
- Preserve optional top-level or `data` message fields.
- MCP must not calculate price manually from `positions[]`.

## Bounds

- `search_invoice_goods` fetches at most 5 upstream product pages.
- Overfetch product page size is fixed at 100 rows, independent of MCP `limit`.
- It inspects at most 500 upstream product rows per MCP call.
- It enriches at most 50 distinct combination `tag_id` values per MCP call.
- Response metadata must include `requested_limit`, `accepted_count`, `inspected_count`, `upstream_pages_fetched`, `overfetch_cap_reached`, and `warnings[]`.
