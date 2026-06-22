# Этап 177. ChatGPT connection instructions and OAuth access presets

## Контекст

Stage 173 подтвердил, что ChatGPT Developer Mode connector подключается к `https://vetmanager-mcp.vromanichev.ru/mcp` через OAuth и вызывает MCP tools. После проверки осталось два product/security gaps:

- обычному пользователю непонятно, как подключить ChatGPT: в `/account` нет короткой инструкции и copyable MCP URL, а на лендинге возможность не заявлена человеческим языком;
- ChatGPT OAuth flow сейчас может унаследовать слишком широкий набор scopes из DCR/requested scope, без понятного выбора прав пользователем на consent screen.

## Цель

Сделать подключение ChatGPT понятным и безопасным:

- в `/account` показать короткую инструкцию подключения ChatGPT и MCP URL;
- на landing page добавить понятный блок, что сервис можно подключить к ChatGPT;
- на OAuth consent screen дать пользователю выбрать уровень доступа для ChatGPT grant;
- по умолчанию выдавать `Read only`, а не `Full access`;
- не позволять OAuth client расширять права сверх выбранного пользователем preset.

## Non-goals

- Не делать custom per-tool/per-scope builder.
- Не менять service bearer token issuance flow.
- Не добавлять публичный OAuth revoke endpoint.
- Не менять список MCP tools или scope registry.
- Не делать бесконтрольную смену scopes у уже выданных OAuth grants. Legacy broad ChatGPT grants должны быть обработаны явно: либо force re-link/reconnect, либо server-side downgrade до safe default с понятным account UI сигналом.

## Архитектурное решение

### Проблема

DCR/authorize path может работать с широким `client.scope` и `requested_scope`. Если просто принять requested scopes, ChatGPT grant может получить доступ шире, чем ожидает владелец клиники.

### Контекст и ограничения

- Runtime enforcement уже построен на `TOOL_REQUIRED_SCOPES`.
- User-facing preset matrix уже есть в `tool_access_registry.py`: `Read only`, `Front desk`, `Doctor`, `Finance`, `Inventory`, `Analytics`, `Full access`.
- Для ChatGPT нужны простые preset'ы, а не тонкая RBAC настройка.
- OAuth authorization code уже хранит `scope`, token exchange и refresh наследуют этот scope.
- Existing service bearer tokens не должны измениться.

### Рассмотренные варианты

1. **Доверять requested scopes от ChatGPT.**
   - Плюс: минимально.
   - Минус: пользователь не управляет правами; возможен слишком широкий grant.

2. **Ограничить DCR default до `Read only`.**
   - Плюс: безопасный default.
   - Минус: если OAuth client зарегистрирован только с read-only scopes, пользователь не сможет выбрать `Analytics` без новой регистрации; DCR becomes product-policy bottleneck.

3. **Выбор preset на consent screen и server-side narrowing.**
   - Плюс: пользователь явно выбирает права; OAuth client не может расширить grant; существующий token exchange продолжает работать, потому что authorization code уже несёт финальный scope.
   - Минус: нужно аккуратно объяснить, что выбранный preset может быть сужен requested scopes.

Выбран вариант 3.

### Выбранное решение

- `validate_oauth_authorize_request()` продолжает валидировать requested scopes against registered client scopes.
- Consent page получает список доступных ChatGPT access presets и default `Read only`.
- POST `/oauth/authorize/consent` принимает `access_preset`.
- `access_preset` валидируется только серверным whitelist (`Read only`, `Analytics`, `Front desk`, `Full access`) через существующую preset registry; любые неизвестные/пустые значения отвергаются.
- `access_preset` обязателен для code issuance: если consent POST не передал валидный preset, authorization code не создаётся. Нельзя выпускать code напрямую из raw requested scopes.
- Сервер вычисляет final scopes как пересечение `requested_scopes` и scopes выбранного preset.
- Если final scopes пустой — вернуть понятную ошибку.
- Если выбранный preset шире requested scopes и пересечение непустое, consent/ошибка должны явно показать, что grant будет уже выбранного preset. Нельзя молча писать `Analytics`, если реально выданы только `clients.read`.
- Если выбран `Full access`, требовать отдельный checkbox `confirm_full_access`.
- Единый источник истины для authorization code и tokens — строковое поле `scope`; list `scopes` в request data должен быть синхронизирован из этой строки после narrowing. Тест обязан проверять, что `scope` и `scopes` не расходятся.
- В signed authorization request перед созданием authorization code заменить `scope`/`scopes` на final narrowed scopes. `/account` label всегда выводится из фактических final scopes через `infer_token_preset()`/derived label, а не из requested/selected preset, чтобы narrowed grant не показывался как `Analytics`, если фактически выданы только `clients.read`.
- Token exchange и refresh остаются без новой логики: они наследуют scope из authorization code/token.
- Refresh/token exchange не принимает scope из client form и не может расширить scope относительно сохранённого code/refresh token scope; добавить regression test.
- Legacy broad grants from Stage 173: при рендере `/account` выводить warning "Reconnect to choose access level"; refresh для legacy full-scope grant отклонять с `invalid_grant` и re-link guidance вместо молчаливого downgrade. Это делает потерю широкого доступа явной и требует operator-visible reconnect.
- `/account` показывает ChatGPT grant access label, scope summary, dates и disconnect. Для старых grants без stored preset label выводится derived label from scopes (`Read only`, `Analytics`, `Full access` или `Custom/legacy`) без падения render.

### Инварианты

- `Full access` не выдаётся по умолчанию.
- OAuth grant scopes не шире выбранного preset.
- OAuth grant scopes не шире requested/client-allowed scopes.
- `scope` string и `scopes` list не расходятся после narrowing.
- Refresh не расширяет scope.
- Existing service bearer tokens и `vm_st_` flow не меняются.
- Revoked OAuth grants продолжают отзывать access + refresh family.

### Rollback/fallback

Если ChatGPT UI плохо переносит narrowed scopes, fallback — оставить DCR/authorize compatible path, но default consent preset `Read only` и документировать, что для `Analytics` нужен re-link. Код rollback ограничен consent narrowing function и render параметрами.

Rollout guard:

- Post-deploy smoke должен проверить новый consent page и существующий OAuth metadata/tool-call path.
- Account UI должен сразу показывать legacy/broad ChatGPT grants, чтобы оператор мог disconnect/reconnect.
- Если ChatGPT linking ломается после deploy, откат ограничен consent narrowing/render changes; уже выданные narrowed grants остаются безопаснее broad grants.

## UX

### `/account`

Добавить блок “Подключить ChatGPT”:

- коротко: “Откройте ChatGPT → Developer Mode / Connectors → добавьте MCP URL”;
- URL: `https://vetmanager-mcp.vromanichev.ru/mcp`;
- copy button;
- объяснение: “ChatGPT подключается через защищённый вход, Bearer token копировать не нужно”;
- рядом с grants показывать уровень доступа.

### Landing page

Добавить простой блок:

- “Можно подключить к ChatGPT”;
- “ChatGPT сможет отвечать по расписанию, клиентам, долгам и отчётам через защищённое подключение”;
- “Права выбираются при подключении; полный доступ не выдаётся по умолчанию”;
- CTA в `/register` или `/login`.

### OAuth consent

Добавить выбор:

- `Read only` default;
- `Analytics`;
- `Front desk`;
- `Full access` с отдельным подтверждением.
- если выбранный preset не полностью доступен из requested/client scopes, показать понятное сообщение: "ChatGPT requested fewer permissions than this preset; reconnect/re-register if you need Analytics".

`Doctor`, `Finance`, `Inventory` можно не рекламировать для ChatGPT v1, чтобы не перегружать consent.

## Acceptance criteria

- `/account` содержит ChatGPT connection instructions, MCP URL и copy control.
- Landing содержит user-facing ChatGPT block.
- Consent page default preset — `Read only`.
- Authorization code stores narrowed final scopes.
- Token response returns narrowed final scope.
- Selecting `Full access` without confirmation fails before code issue.
- Empty intersection between requested scopes and selected preset fails with clear error.
- Non-empty requested/preset intersection that is narrower than selected preset is visible to the user and tested.
- Account OAuth grants list shows access label and scope summary.
- Account OAuth grants list handles legacy grants without stored preset and flags broad legacy grants.
- Refresh path cannot expand scope; legacy broad full-scope refresh is rejected with re-link guidance.
- Existing OAuth exchange/refresh/revoke tests remain green.
- Full suite passes.
- Post-deploy smoke passes.

## Тесты

- account page renders ChatGPT instructions and MCP URL;
- landing page renders ChatGPT connection block;
- consent page renders preset selector with default `Read only`;
- requested `SUPPORTED_TOKEN_SCOPES` + default consent produces `Read only` code/token scope;
- selected `Analytics` produces analytics preset intersection when requested scopes allow it;
- selected `Full access` without confirmation returns error and no code;
- selected preset with empty requested-scope intersection returns error and no code;
- selected preset broader than requested scopes returns a visible narrowed-scope warning or error;
- `scope` string and `scopes` list are consistent after narrowing;
- refresh cannot accept or create broader scopes than stored refresh token scope;
- legacy full-scope refresh returns `invalid_grant` with reconnect/re-link guidance;
- legacy broad grant render shows derived label/warning and does not crash;
- OAuth grant list shows `Read only`/`Analytics` label and scope summary;
- insufficient-scope challenge still works for ChatGPT token.

## Architecture Critique

Required: stage touches OAuth authz, public/account UI, MCP security contract and production behavior.

Prompt target: challenge consent narrowing boundary, requested-scope intersection, default preset, `Full access` confirmation, compatibility with ChatGPT DCR/authorize, and whether a simpler safe option exists.

## Review notes

To be filled during workflow:

- Spark PRD review: accepted findings for explicit scope of consent changes, mandatory server-side preset whitelist/full confirmation, refresh no-escalation invariant, legacy grant compatibility, rollout guard; follow-up accepted mandatory preset and data-plane legacy handling.
- Strong PRD/Architecture Critique: accepted findings for legacy broad grants handling, non-empty downgrade UX, `scope`/`scopes` consistency, legacy label fallback, empty/intersection tests; follow-up accepted derived label from final scopes and reject-not-silent-downgrade legacy refresh.
- Spark code review:
- Strong code review:
