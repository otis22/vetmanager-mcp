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
   - Reject input with fewer than 7 digits as not a usable phone number.
   - Call `GET /rest/api/VmLink/personalAccountLinkByPhone/{digits}`.
   - Classification order:
     - the transport client must catch `VetmanagerError` subclasses, including timeout/network/upstream errors, and convert them to the fixed generic `ToolError` for this endpoint;
     - any non-HTTP-200 response, transport error, top-level `success=false`, or malformed envelope is `ToolError`;
     - require a well-formed envelope before business classification: payload is a dict, `data` is a dict, and `data.vetmanagerLink` is a dict;
     - after the envelope is well-formed, return link only when top-level `success=true`, `data.vetmanagerLink.success=true`, and `personal_link` is present;
     - after the envelope is well-formed, return a clear not-found result when top-level `success=true` and `data.vetmanagerLink.success=false` or `personal_link` is missing.
   - Return shape:
     - success/found: `data.found=true`, `data.personal_link`, `data.link_is_persistent=true`, `data.warning`;
     - not found: `data.found=false`, `data.personal_link=null`, `data.warning`, fixed `message="Client profile not found"`.
   - Treat `personal_link` and the input phone as sensitive output: return the link only in the successful tool payload, never include the link, raw upstream body, full request URL, or phone digits in exception text, debug messages, or test/log output.
   - Tool-level upstream errors must use a fixed generic `ToolError` message for this endpoint, not `str(exc)` or arbitrary upstream `message`.
   - The success `personal_link` value must survive the tool wrapper and depersonalization mode byte-for-byte; `personal_link` is an intentional output field, not a generic free-text field.
2. Tool description must state:
   - Use only when the assistant already knows the client phone.
   - Do not use client ID to obtain a personal-account link.
   - The returned link is persistent and should be shown only in the relevant user context.
3. Add tests/docs/access metadata:
   - phone normalization to digits;
   - too-short phone rejection before upstream;
   - not-found response shape;
   - success response shape;
   - route/upstream error propagation;
   - upstream error payload containing a link-like value does not leak that value in `ToolError`;
   - timeout/transport error does not leak the request URL or phone digits in `ToolError`;
   - not-found message is the fixed safe message and cannot echo the input phone;
   - depersonalized runtime credentials still return the exact successful `personal_link`;
   - no `get_personal_account_link_by_client_id` tool.

## Scope mapping

- `get_personal_account_link_by_phone` -> `clients.read`.
- Direct upstream path `GET /rest/api/VmLink/personalAccountLinkByPhone/{digits}` -> `clients.read` via lowercase entity key `vmlink`.
- Do not map or expose `personalAccountLinkByClientId` as an MCP tool in Stage 171.
- Rationale: the user-approved privacy boundary is "assistant already knows the phone"; the operation is a client read capability that does not disclose data by client ID and fits the existing coarse scope model. Adding a new `vmlink.read` scope would require token/preset migration and is intentionally out of scope for this narrow tool.
- Accepted risk: with `clients.read`, this tool can be used as a phone-existence oracle and can mint a persistent personal-account link for a known phone. This is accepted for Stage 171 because bearer tokens are trusted clinic-side integration credentials, the user explicitly approved phone-known access, and Stage 166 owns the broader production rate-limit/abuse-control decision. Implementation still rejects too-short inputs to avoid accidental broad probes.
- The scope grant is entity-coarse: adding `vmlink -> clients.read` authorizes direct `GET /rest/api/VmLink/...` requests inside `VetmanagerClient`, including the client-ID sub-path at the scope layer. Stage 171 enforces the product boundary by exposing no generic REST passthrough and no client-ID MCP tool; do not add such passthroughs without revisiting this boundary.

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
5. Mock tests cover success, not found, route/upstream error, timeout/transport error, normalization, too-short phone rejection, error-message redaction of link-like upstream payloads and phone/request URL, fixed safe not-found message, and no client-id variant.
6. Mock tests cover malformed/top-level-failed envelopes as `ToolError`, and depersonalized success keeps the exact link value.
7. Scope tests cover the tool-level registry and direct `VmLink` request mapping.
8. Real `devtr6` smoke verifies digits-only phone success and missing phone not-found behavior without logging the phone or full returned link. The success phone must come from env/test config or be discovered at runtime from the authenticated account; do not hardcode real PII in committed source.
9. `artifacts/api-research-notes-ru.md` records the verified VmLink endpoint envelope, PHP source references, phone-format behavior, and top-level-vs-nested success quirk.

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
