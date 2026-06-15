# Этап 171. VmLink personal account link by phone

## Цель

Добавить безопасный MCP tool для получения постоянной ссылки на личный кабинет клиента Vetmanager только по известному телефону клиента.

## Контекст

OpenAPI diff 2026-06-15 показал новые/нормализованные endpoints:

- `GET /rest/api/VmLink/personalAccountLinkByClientId/{clientId}`
- `GET /rest/api/VmLink/personalAccountLinkByPhone/{phone}`

Пользовательское решение: ссылку на ЛК ассистенту можно отдавать только по телефону. Если ассистент знает телефон клиента, это считается безопасным. Ссылка постоянная. Client-ID based tool не добавлять.

Source of truth: `/home/otis/myprojects/vetmanager-extjs`.

Relevant files:

- `rest/protected/controllers/VmLinkController.php`
- `application/src/ServiceIntegration/VmLink.php`
- `rest/protected/config/services.php`
- `rest/protected/config/services_private.php`

## Verified on devtr6

Real API probe on 2026-06-15:

- Existing client with `client.cell_phone` containing formatted characters:
  - raw formatted phone in path returned 404 route-level error;
  - digits-only 10-character phone returned `success=true`;
  - response shape: `data.vetmanagerLink.personal_link`, `data.vetmanagerLink.success=true`.
- Missing digits-only phone returned HTTP 200 with:
  - top-level `success=true`;
  - `message="Client profile not found"`;
  - `data.vetmanagerLink.success=false`;
  - no `personal_link`.
- Returned link host on `devtr6`: `https://link.vetmanager.ru`; link path contains encoded domain/client data and must be treated as sensitive output.

## Scope

1. Add read tool `get_personal_account_link_by_phone`.
   - Input: `phone: str`.
   - Normalize to digits before calling Vetmanager.
   - Call `GET /rest/api/VmLink/personalAccountLinkByPhone/{digits}`.
   - Return link only when `data.vetmanagerLink.success=true` and `personal_link` is present.
   - Return a clear not-found result when `data.vetmanagerLink.success=false`.
2. Tool description must state:
   - Use only when the assistant already knows the client phone.
   - Do not use client ID to obtain a personal-account link.
   - The returned link is persistent and should be shown only in the relevant user context.
3. Add tests/docs/access metadata:
   - phone normalization to digits;
   - not-found response shape;
   - success response shape;
   - no `get_personal_account_link_by_client_id` tool.

## Out of Scope

- `personalAccountLinkByClientId`.
- Any new `get_client_by_id` / `get_pet_by_id` convenience tools.
- Link revocation/rotation; current Vetmanager link is persistent.
- Sending the link via SMS/email/message tools.

## Acceptance Criteria

1. MCP exposes `get_personal_account_link_by_phone` and does not expose a client-ID variant.
2. Formatted phone input is normalized before the upstream call.
3. Missing phone returns a structured not-found result, not a generic exception.
4. Tool docs warn that the link is persistent.
5. Mock tests cover success, not found, route/upstream error, and normalization.
6. Real `devtr6` smoke verifies digits-only phone success and missing phone not-found behavior without logging the full returned link.

## Проверки

During implementation:

```bash
docker compose --profile test run --rm test pytest tests/test_stage171_vmlink_personal_account_link.py -q
docker compose --profile test run --rm test pytest tests/test_tools_list_schema.py tests/test_stage130_access_registry.py -q
docker compose --env-file .env --profile test run --rm test python -m pytest tests/test_e2e_real.py -k 'vmlink' -q
docker compose --profile test run --rm test
git diff --check
python3 scripts/check_no_historical_api_key_literal.py
```
