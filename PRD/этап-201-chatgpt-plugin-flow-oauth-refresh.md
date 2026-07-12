# PRD — Этап 201: ChatGPT Plugin flow docs and OAuth refresh compatibility

## Статус

`in_progress`

## Контекст

Пользователь сообщил 2026-07-12, что ChatGPT изменил процесс добавления
плагинов/apps, и попросил обновить инструкцию и выполнить проверку по workflow.

Текущий кабинет в `web_html.py` описывает старый путь:
`Settings → Apps → Developer mode → Create app / connector → add MCP connector`.
Официальные OpenAI docs теперь используют смешанную терминологию
`Apps`/`Plugins`:

- Apps SDK docs: developer mode flow идёт через `Settings → Plugins` или
  `chatgpt.com/plugins`; developer создаёт app/plugin, указывает public MCP URL,
  а затем включает его в новом чате через `+ → More`.
- Help Center: для Business/Enterprise/Edu кастомные MCP apps создаются из
  user/workspace settings, требуют `Scan Tools`, OAuth authorization при
  необходимости, затем попадают в Drafts/Enabled apps; published apps/actions
  обновляются через `Refresh` или пере-создание в зависимости от плана.
- Help Center прямо предупреждает: если OAuth provider не advertises
  `offline_access` или эквивалент refresh-token scope, ChatGPT может потерять
  доступ после истечения первичной авторизации.

## Цель

1. Пользователь кабинета получает актуальную инструкцию подключения ChatGPT
   web через Plugin/App developer-mode flow.
2. OAuth discovery/DCR/authorize/token flow совместим с ChatGPT refresh-token
   ожиданиями: `offline_access` можно запросить, но он не становится MCP
   tool-scope и не ломает существующие scope checks.
3. Изменение покрыто regression tests и production smoke.

## Non-goals

- Не публикуем приложение в Plugin directory.
- Не меняем набор Vetmanager MCP tools.
- Не добавляем write-доступ по умолчанию.
- Не меняем service bearer token flow для Cursor/Claude Code.

## Acceptance Criteria

1. Account UI больше не говорит `Create app` как единственный путь и не
   утверждает, что ChatGPT MCP доступен в mobile/desktop apps; текст явно
   указывает ChatGPT web, Plugins, Scan Tools, Draft/Create, Refresh.
2. Landing copy использует Plugin/App wording вместо устаревшего
   `готовый MCP connector`.
3. `/.well-known/oauth-authorization-server` и
   `/.well-known/openid-configuration` advertise `offline_access` как
   refresh-token scope.
4. DCR принимает `scope` с `offline_access`, сохраняет/возвращает client scope
   с protocol marker, но tool-scope derivation отделяет его от MCP прав.
5. Authorization request принимает `offline_access` вместе с supported tool
   scopes. Authorization code и access/refresh token scope могут содержать
   `offline_access` как OAuth protocol marker; `OAuthGrant.scopes_json` и
   runtime tool checks включают только MCP tool scopes.
6. Refresh token rotation продолжает работать; token response возвращает
   `offline_access` в `scope`, если он был granted, и при этом не расширяет
   MCP tool permissions.
7. Existing OAuth and account UI tests remain green; new tests cover docs copy
   and `offline_access` behavior.

## Архитектурное решение

### Проблема

ChatGPT стал ориентироваться на Plugin/App developer-mode flow и может
запрашивать `offline_access`, чтобы сохранить подключение через refresh token.
Наш runtime refresh tokens уже выдаёт, но discovery не advertises
`offline_access`, а scope validation использует MCP tool scopes как единственный
список допустимых scopes. Если ChatGPT добавит `offline_access` в DCR или
authorize request, текущая валидация может отклонить подключение.

### Контекст и ограничения

- `SUPPORTED_TOKEN_SCOPES` — MCP authorization scopes для tools. Нельзя
  добавлять туда OAuth protocol scope, иначе он попадёт в tool access model.
- Existing OAuth service хранит `OAuthClient.scope`, auth code scope,
  `OAuthGrant.scopes_json`, access/refresh token scope. Для этапа 201
  `OAuthClient`/code/access/refresh scope может включать OAuth protocol marker
  `offline_access`; `OAuthGrant.scopes_json` остаётся tool-scope-only.
- Runtime access checks ожидают только tool scopes.
- Refresh-token rotation уже реализован и покрыт тестами.
- UI должен оставаться user-facing, без PII/secret output.

### Рассмотренные варианты

1. Добавить `offline_access` в `SUPPORTED_TOKEN_SCOPES`.
   - Плюс: минимальные изменения validation.
   - Минус: смешивает OAuth protocol scope с MCP tool scopes, создаёт риск
     false authorization scope в tools/list/runtime checks.
2. Игнорировать `offline_access` полностью.
   - Плюс: минимальный код.
   - Минус: ChatGPT может считать provider несовместимым с persistent
     connectivity или запросить scope и получить `invalid_scope`.
3. Разделить OAuth protocol scopes и MCP tool scopes.
   - Плюс: совместимо с ChatGPT и не загрязняет MCP access model.
   - Минус: нужно аккуратно нормализовать request/client/token responses.

### Выбранное решение

Ввести локальный OAuth protocol scope `offline_access` в OAuth metadata/service
слое:

- advertise `SUPPORTED_TOKEN_SCOPES + ["offline_access"]` только в OAuth
  discovery metadata;
- DCR/authorize принимают `offline_access` и сохраняют его в OAuth client/code
  scope as granted protocol marker;
- access/refresh token scope и token response echo-ят granted
  `offline_access`, чтобы ChatGPT видел offline access as granted and keeps the
  refresh token;
- `OAuthGrant.scopes_json` and runtime credentials filter protocol scopes out,
  so MCP tool authorization sees only `SUPPORTED_TOKEN_SCOPES`.

### Инварианты

- `offline_access` не появляется в `SUPPORTED_TOKEN_SCOPES`.
- `offline_access` не появляется в `OAuthGrant.scopes_json`.
- `offline_access` может появляться в OAuth client/code/access/refresh token
  scope and token response `scope`, but never grants MCP tool access.
- MCP runtime credentials and tool scope enforcement see only tool scopes.
- Existing clients that do not request `offline_access` keep previous behavior.
- Bearer-token ChatGPT instruction remains OAuth-only; no manual bearer token
  is requested for ChatGPT.

### Rollback / fallback

Если ChatGPT фактически не принимает `offline_access` в custom MCP OAuth flow,
можно откатить protocol-scope acceptance while keeping UI Plugin wording. If
ChatGPT requires a different refresh-token scope name, add it to the OAuth-only
protocol scope allowlist without touching MCP tool scopes.

## Декомпозиция

- 201.1 PRD/research and review gates.
- 201.2 UI/landing copy update.
- 201.3 OAuth metadata/service normalization for `offline_access`.
- 201.4 Regression tests for copy, metadata, DCR, authorize/token/refresh.
- 201.5 Checks, audit, committed-diff review, push/deploy/smoke.

## Проверки

- Targeted:
  `docker compose --profile test run --rm test pytest tests/test_web_auth.py::test_account_token_issue_supports_access_preset_and_depersonalized_policy tests/test_stage173_oauth_metadata.py::test_oauth_authorization_server_metadata_is_dcr_public_client_v1 tests/test_stage173_oauth_metadata.py::test_oauth_token_exchange_refresh_rotation_and_reuse_revocation tests/test_landing_page.py::test_stage177_landing_mentions_chatgpt_connector_plainly -q`
- Required regression cases:
  - discovery metadata includes `offline_access`, while `SUPPORTED_TOKEN_SCOPES`
    does not;
  - DCR accepts `clients.read offline_access`, returns/stores the granted
    client scope with `offline_access`, and rejects unknown scopes even when
    `offline_access` is present;
  - authorize accepts `clients.read offline_access`, stores authorization code
    scope with `offline_access`, creates `OAuthGrant.scopes_json` with
    `clients.read` only, and rejects unsupported tool scopes;
  - token exchange and refresh rotation return `clients.read offline_access`
    scope, issue/rotate refresh tokens, and OAuth runtime credentials expose
    `clients.read` only to tool authorization;
  - existing clients that omit `offline_access` keep previous behavior.
- Full:
  `docker compose --profile test run --rm test`
- Production smoke:
  public `/healthz`, `/readyz`, `/mcp` expected 406 without SSE Accept;
  OAuth discovery metadata contains `offline_access`; MCP agent smoke
  `tools/list` + safe authenticated tool call; real prod OAuth
  DCR/authorize/token/refresh smoke requesting `clients.read offline_access`.

### Фактические локальные проверки

- Targeted regression:
  `docker compose --profile test run --rm test pytest tests/test_stage173_oauth_metadata.py::test_oauth_authorization_server_metadata_is_dcr_public_client_v1 tests/test_stage173_oauth_metadata.py::test_openid_configuration_alias_matches_authorization_server_metadata tests/test_stage173_oauth_metadata.py::test_oauth_dcr_registers_public_client tests/test_stage173_oauth_metadata.py::test_oauth_dcr_accepts_offline_access_without_tool_scope_expansion tests/test_stage173_oauth_metadata.py::test_oauth_token_exchange_refresh_rotation_and_reuse_revocation tests/test_stage173_oauth_metadata.py::test_oauth_tool_call_redacts_personal_fields_by_default tests/test_web_auth.py::test_account_token_issue_supports_access_preset_and_depersonalized_policy tests/test_landing_page.py::test_stage177_landing_mentions_chatgpt_connector_plainly -q`
  — `8 passed`.
- Full suite initially exposed a pre-existing flaky timing assertion in
  `tests/test_rate_limit_backend.py::test_check_rate_limit_calls_backend_interleaved`:
  the functional interleaving assertion passed, but the wall-clock latency cap
  failed under full docker load. The test was hardened to assert the direct
  concurrency signal (`backend.max_active >= 2`) without a fragile elapsed-time
  threshold.
- Targeted test-hardening check:
  `docker compose --profile test run --rm test pytest tests/test_rate_limit_backend.py::test_check_rate_limit_calls_backend_interleaved -q`
  — `1 passed`.
- Full final:
  `docker compose --profile test run --rm test` —
  `1352 passed, 2 skipped, 65 deselected`.

## Review Findings

- Spark architecture/PRD review (fallback after read-only `bwrap` hang):
  accepted finding to make `offline_access` contract explicit and accepted
  finding to add DCR/authorize/refresh regression tests.
- Claude Opus architecture/PRD review:
  accepted finding that stripping `offline_access` from token response can
  defeat ChatGPT refresh persistence; updated design to echo protocol scope in
  OAuth token scope while filtering it before runtime tool checks.
  Accepted simpler enforcement-point finding: runtime boundary filters protocol
  scopes instead of trying to make every OAuth persistence layer tool-only.
  Accepted prod smoke finding: add authorize/token/refresh smoke with
  `offline_access`.
  Partially accepted OpenID metadata finding: keep `/.well-known/openid-configuration`
  alias behavior for current compatibility, but tests must pin that both
  metadata surfaces expose identical OAuth metadata and no `id_token` support is
  claimed.
- Spark committed-diff review accepted one medium backward-compatibility
  finding: legacy DCR clients registered before `offline_access` advertisement
  could request `offline_access` at authorize time and be rejected because their
  stored client scope did not include the protocol marker. Fixed by checking
  client subset only for MCP tool scopes while allowing known OAuth protocol
  scopes, and added a legacy-client regression test.
