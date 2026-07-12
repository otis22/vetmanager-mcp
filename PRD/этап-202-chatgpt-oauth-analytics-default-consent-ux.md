# PRD — Этап 202: ChatGPT OAuth Analytics default и friendly consent UX

## Контекст

Пользователь сообщил, что при авторизации ChatGPT видит ошибку о неполном
наборе прав: ChatGPT запрашивает один набор scopes, а на consent screen по
умолчанию выбран `Analytics`. Текущая реализация сужает выдачу до пересечения
requested scopes и выбранного preset, поэтому итоговый токен может получить
меньше прав, чем ожидает ChatGPT или пользователь.

Вторая проблема — consent page недружелюбна: technical scopes на английском
видны слишком крупно, а уровни доступа не объяснены простым русским языком.

## Цель

Сделать ChatGPT OAuth flow предсказуемым и понятным:

- ChatGPT по умолчанию получает `Analytics`.
- Если ChatGPT явно запрашивает scopes шире `Analytics`, consent page выбирает
  минимальный preset, покрывающий requested scopes, и честно объясняет это
  пользователю; если нужен `Full access`, требуется checkbox.
- Если пользователь выбирает больший preset, токен получает выбранный preset
  после обычных safety checks.
- `Read only` честно покрывает весь read-only tool surface.
- `Analytics` = `Read only` + работа с отчётами.
- Consent page понятна владельцу клиники: русские названия, короткие
  пояснения, technical scopes вторичны. Concrete granted scopes доступны в
  мелком техническом блоке, чтобы escalation шире запроса ChatGPT был явно
  раскрыт без перегруза primary UX.

## Non-goals

- Не менять Vetmanager auth modes.
- Не расширять write permissions без явного выбора пользователя.
- Не смешивать OAuth protocol scope `offline_access` с MCP tool scopes.
- Не менять runtime enforcement для tool scopes, кроме выравнивания preset
  coverage.
- Не превращать `/oauth/register` в general-purpose third-party OAuth platform:
  этот flow остаётся ChatGPT-compatible connector flow для владельца аккаунта.

## Проверенные факты и артефакты

- `PRD/этап-201-chatgpt-plugin-flow-oauth-refresh.md` зафиксировал:
  `offline_access` является OAuth protocol scope, не входит в
  `SUPPORTED_TOKEN_SCOPES`, не попадает в `OAuthGrant.scopes_json`, но может
  присутствовать в OAuth client/code/access/refresh token `scope`.
- `PRD/этап-177-chatgpt-onboarding-oauth-access-presets.md` ранее выбрал
  модель "preset narrows requested scopes"; stage 202 меняет это решение по
  пользовательскому требованию, потому что фактический UX сужения оказался
  непонятным и ломает ожидание "выбран preset = выданы права preset-а".
- В `oauth_service.py` текущий `_validate_scope()` при DCR без `scope`
  возвращает `" ".join(SUPPORTED_TOKEN_SCOPES)`, то есть full tool scope set.
- В `oauth_service.py` текущий `narrow_oauth_authorize_request_scope()`
  вычисляет `final_scopes` как пересечение requested tool scopes и selected
  preset scopes, а при пустом пересечении возвращает exposed error
  `Selected access level does not include any requested scopes...`.
- В `web_html.py` текущий `render_oauth_consent_page()` уже выбирает
  `PRESET_REPORT_AI` по умолчанию, но показывает английские заголовки
  `ChatGPT access`, `Requested scopes`, `Effective scopes by access level`,
  `Access level`, `Confirm Full access`, `Allow`.
- В `tool_access_registry.py` `CHATGPT_OAUTH_ACCESS_PRESETS` фактически
  ограничены четырьмя preset-ами: `Analytics`, `Read only`, `Front desk`,
  `Full access`.
- В `tests/test_stage130_access_registry.py` уже есть базовые snapshot tests
  preset scopes и marketed tools, но нет invariant test, что `Read only`
  покрывает весь read-only surface, а `Analytics` является superset
  `Read only` + report capabilities.
- Фактический scope set, который присылает production ChatGPT в момент
  `/oauth/authorize`, пока не зафиксирован в артефактах. Stage 202 должен
  проверить это в prod smoke или через безопасный request/audit сигнал без
  токенов/секретов. Если ChatGPT реально запрашивает scopes шире `Analytics`,
  implementation не должна скрывать это: consent page показывает technical
  requested scopes и effective selected preset, а token response честно
  возвращает фактически granted scopes.
- Чтобы не воспроизвести исходную ошибку, если ChatGPT требует
  `granted scopes >= requested scopes`, default selected preset должен быть:
  `Analytics`, когда requested tool scopes пустые или subset Analytics; иначе
  минимальный available ChatGPT OAuth preset, покрывающий requested scopes.
  Если таким preset-ом является `Full access`, выдача всё равно невозможна без
  явного checkbox.

## Архитектурное решение

### Проблема

OAuth DCR/authorize scopes сейчас используются как верхняя граница выдачи, а
consent preset — как фильтр. Для ChatGPT это создаёт плохой UX: пользователь
выбирает понятный уровень доступа, но фактически получает пересечение с
техническим requested scope, что может быть неожиданно узким.

### Контекст и ограничения

- OAuth protocol scope `offline_access` нужен для refresh-token compatibility
  и не должен становиться MCP tool permission.
- `Full access` должен оставаться опасным действием с отдельным checkbox.
- Runtime tool enforcement должен продолжать смотреть только на stored MCP tool
  scopes.
- Existing account/token presets живут в `tool_access_registry.py`.
- Для этого продукта authority на выдачу MCP прав — владелец аккаунта на нашем
  consent screen. External OAuth client/DCR не должен расширять права без
  пользователя, но пользователь может явно выбрать preset шире requested
  technical scopes.
- Public OAuth DCR здесь не является самостоятельной доверенной политикой
  доступа для произвольных third-party apps. Он нужен для ChatGPT-compatible
  connector registration; поэтому user consent в account session является
  решающей границей выдачи MCP прав.

### Рассмотренные варианты

1. Оставить пересечение requested scopes и preset, но сделать текст понятнее.
   - Плюс: минимальное изменение.
   - Минус: не решает ошибку и не соответствует ожиданию пользователя.
2. Доверять requested scopes от ChatGPT.
   - Плюс: просто для OAuth client.
   - Минус: права выбирает внешний client, а не владелец аккаунта.
3. Сделать выбранный пользователем preset источником MCP прав, сохранив
   `offline_access` как protocol marker.
   - Плюс: понятный UX и сохраняется security boundary.
   - Минус: нужно обновить тесты и coverage preset-ов.

### Выбранное решение

Вариант 3. На consent screen пользователь выбирает access preset; этот preset
становится источником MCP tool scopes. Requested OAuth scopes остаются
диагностическим/technical context и источником protocol scopes вроде
`offline_access`, но не ограничивают выбранный preset. Чтобы это не было
молчаливым privilege inflation, consent page обязан показывать выбранный
access level и его простой смысл до отправки формы; token response `scope`,
authorization code scope, stored grant scopes и runtime credentials должны
совпадать по MCP tool scopes.

OAuth client может получить granted scope, отличный от requested scope, но это
не должно быть скрытым: token endpoint возвращает effective `scope`, а tests
проверяют, что response, stored grant и runtime enforcement согласованы. Если
requested scopes шире `Analytics`, GET consent выбирает минимальный preset,
который покрывает requested scopes, чтобы не вернуть token уже requested. Если
prod ChatGPT не принимает granted scope как superset requested, rollback
возвращает intersection semantics целиком только для случаев, где requested
subset выбранного preset; для broader-than-Analytics request default covering
preset остаётся safety contingency.

### Инварианты

- `offline_access` может быть в OAuth token response scope, но не попадает в
  `OAuthGrant.scopes_json`.
- OAuth token response `scope` и stored MCP grant scopes не расходятся по MCP
  tool scopes: что вернули ChatGPT как granted tool scopes, то и enforce-ится
  runtime.
- Default selected preset algorithm:
  - requested tool scopes empty/subset `Analytics` → selected `Analytics`;
  - requested tool scopes exceed `Analytics` → selected smallest available
    ChatGPT OAuth preset covering requested scopes;
  - if only `Full access` covers requested scopes, UI must require explicit
    `confirm_full_access` before code issuance.
- DCR без `scope` intentionally получает global safer default `Analytics`.
  Это уменьшает прежний blast radius full-scope default для всех public OAuth
  DCR clients в рамках ChatGPT-compatible OAuth surface; изменение должно быть
  покрыто тестом и отражено как сознательная security-default смена.
- `Full access` невозможен без `confirm_full_access`.
- `Read only` покрывает все tools, которым нужны только read scopes.
- `Analytics` является superset `Read only` и включает report/report export/
  report save capabilities.
- Consent page не скрывает technical scopes полностью, но делает их вторичными.

### Rollback/fallback

Если ChatGPT требует exact echo requested scopes, rollback должен вернуть
intersection semantics целиком для authorization code, token response, stored
grant и runtime credentials. Нельзя делать режим, где token response показывает
одно, а runtime enforce-ит другое.

## Декомпозиция

- 202.1 PRD/research и review gates.
- 202.2 OAuth semantics: DCR default `Analytics`, consent grants selected
  preset, protocol scopes preserved, and GET consent preselects smallest preset
  covering requested scopes when requested exceeds Analytics.
- 202.3 Preset coverage: `Read only` = весь read-only surface, `Analytics` =
  `Read only` + отчёты.
- 202.4 Consent UX: русский user-facing текст, пояснения preset-ов, compact
  technical scopes.
- 202.5 Tests: OAuth flow, registry coverage, HTML contract.
- 202.5a Edge tests: narrow requested scope + broader selected preset,
  protocol-only `offline_access`, token response scope vs stored grant equality,
  Full access confirmation.
- 202.6 Technical UX review: HTML/CSS/accessibility/layout check.
- 202.7 Marketing/user-facing review: понятность текстов и выбора прав.
- 202.8 Prod smoke artifact: проверить OAuth authorize/consent/token на
  production и сохранить в work log/AssumptionLog redacted факт
  requested/effective scopes без токенов, codes, client secret (public client)
  и Vetmanager secrets; если доступ к реальному ChatGPT UI недоступен агенту,
  выполнить синтетический smoke того же `/oauth/authorize` contract и явно
  указать limitation.
- 202.9 Full checks, audit, reviews, commit/push/deploy/smoke.

## Acceptance criteria

- OAuth DCR без явного `scope` регистрирует `Analytics` tool scopes.
- Consent с omitted/Analytics-subset requested scopes defaults to `Analytics`
  and выдаёт полный Analytics preset.
- Consent с requested scopes шире `Analytics` preselects the smallest available
  covering preset; `Full access` coverage still requires explicit checkbox.
- Consent с явным большим preset выдаёт выбранный preset.
- `Full access` без checkbox отклоняется.
- `offline_access` сохраняется в OAuth protocol scope и не расширяет MCP tool
  permissions.
- Token response scope, authorization code tool scopes, stored grant scopes and
  runtime credentials stay consistent for MCP tool scopes.
- DCR без явного `scope` покрыт regression test как intentional global
  Analytics default для public OAuth clients.
- Edge case с narrow requested scope + broader user-selected preset покрыт
  тестом: token response сообщает effective granted scope и stored grant
  совпадает с ним.
- Edge case с broader-than-Analytics requested scope покрыт тестом: consent
  preselects covering preset and never silently returns granted scopes narrower
  than requested.
- Prod smoke фиксирует фактические requested/effective scopes; если реальный
  ChatGPT UI недоступен агенту, это указано как limitation, а synthetic OAuth
  smoke проходит. Smoke evidence записан в work log/AssumptionLog без секретов.
- Registry test доказывает, что `Read only` покрывает все read-only tools.
- Registry test доказывает, что `Analytics` является superset `Read only` +
  report/report-ai scopes.
- Consent page на русском, с понятными описаниями preset-ов.
- Technical scopes визуально вторичны и мелкие.
- Consent page проверена дважды: технически и как пользовательско-маркетинговый
  текст.

## Тесты

- Targeted OAuth tests в `tests/test_stage173_oauth_metadata.py` или новом
  stage 202 test file.
- Registry coverage tests в `tests/test_stage130_access_registry.py` или новом
  stage 202 test file.
- HTML contract tests для consent copy/technical scopes.
- OAuth edge tests: omitted scope, narrow requested scope + broader selected
  preset, protocol-only `offline_access` rejection/handling, token response vs
  stored grant equality.
- Full suite: `docker compose --profile test run --rm test`.

## Review notes

- Spark PRD review 2026-07-12: accepted findings to make token response,
  stored grant and runtime scopes consistent; accepted edge-test coverage for
  narrow/protocol-only requested scopes; rejected strict requested-scope
  intersection as primary design because user consent is the product authority.
- Strong architecture/PRD review 2026-07-12: accepted high finding that actual
  ChatGPT requested scopes must be verified in prod smoke or limitation stated;
  accepted finding to make global DCR default reduction explicit and tested;
  accepted finding to test granted-superset behavior and keep token response
  honest.
- Spark re-review 2026-07-12: rejected strict intersection for non-ChatGPT
  clients because this service's OAuth surface is ChatGPT-compatible connector
  flow, not a general third-party OAuth platform; accepted finding to make smoke
  evidence reproducible via redacted work log/AssumptionLog artifact.
- Strong re-review 2026-07-12: accepted high finding that fixed Analytics
  default can still fail if production ChatGPT requests broader scopes and
  requires granted >= requested. PRD changed to preselect the smallest preset
  covering requested scopes, with Full access still requiring checkbox.

## Оценка простоты

Плановое изменение затрагивает auth/public UX и registry invariants, поэтому
упрощение обязательно. Самый простой вариант — не добавлять новый preset layer,
а поменять только semantics существующей функции
`narrow_oauth_authorize_request_scope` и существующий renderer
`render_oauth_consent_page`.
