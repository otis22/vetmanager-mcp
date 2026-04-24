# PRD Этап 137: Token issuance security defaults and no-store HTML

## Цель

Закрыть high findings F1-F2 из full super-review stage 136: исключить cache retention one-time bearer token в HTML response и сделать выпуск bearer token безопасным по умолчанию.

## Источники

- `artifacts/review/2026-04-24-full-stage-136.md` — F1/F2.
- `artifacts/security-threat-model-vetmanager-mcp-ru.md` — bearer token exposure risks.
- `artifacts/technical-requirements-vetmanager-mcp-ru.md` — bearer-only runtime, preset/scopes model.
- `README.md` — user-visible token issuance contract.
- `web.py`, `web_routes_account.py`, `web_html.py`, `service_token_service.py`, `token_scopes.py`.

## Контекст и проверенные факты

- `_json_response` и `_plain_text_response` уже выставляют `Cache-Control: no-store`, но `_html_response` применяет только security headers и request context headers.
- Account dashboard может отрендерить `issued_raw_token` после `POST /account/tokens`; raw token показывается один раз и не хранится в token row.
- Web form placeholder для expiry равен `30`, но server-side обработчик сейчас трактует blank expiry как `None`.
- Web handler default'ит `access_preset` в `full_access`, а `ip_mask` в `*.*.*.*`.
- Legacy token compatibility не должна меняться: существующие токены и прямой service-layer API без новых web flags остаются совместимыми, если это не web issuance path.

## Scope

1. HTML account responses:
   - добавить no-store/no-cache headers для authenticated account HTML pages, включая `GET /account` и `POST /account/tokens`;
   - покрыть тестами обычный account dashboard и response после token issuance;
   - `Pragma: no-cache` и `Expires: 0` добавить как defense-in-depth для старых proxy/browser paths.
2. Web token issuance defaults:
   - server-side default access preset: `read_only`;
   - server-side default expiry: `30` days;
   - blank/missing expiry в web path намеренно меняется с non-expiring на 30 days;
   - `0` или negative expiry должны возвращать 400, а не превращаться в 30;
   - wildcard IP и `full_access` требуют явного confirmation field в form POST;
   - wildcard IP в рамках stage 137 означает только full-open mask `*.*.*.*`; частичные subnet masks вроде `10.*.*.*` остаются обычной валидной IP mask без отдельного confirmation;
   - без подтверждения возвращать 400 с понятным error.
3. UI:
   - default option в select должен соответствовать `read_only`;
   - expiry value/placeholder должен показывать 30;
   - добавить checkbox/confirmation controls для `full_access` и wildcard IP.
4. Tests:
   - default web issuance создаёт read-only token with expiry;
   - blank expiry в web path превращается в 30 days;
   - `0` и negative expiry в web path возвращают 400;
   - `full_access` без confirmation отклоняется;
   - wildcard IP без confirmation отклоняется;
   - подтверждённый wildcard/full_access работает.

## Out of Scope

- Перевыпуск или миграция существующих токенов.
- Изменение service-layer default `issue_service_bearer_token(...)` для non-web callers, если это ломает legacy tests.
- Сохранение прежнего web-form поведения blank expiry -> non-expiring; это intentional breaking change для web issuance path.
- Полная переработка token management UI.
- Rate-limit, Redis, API contract и observability findings других этапов.
- CSRF-механику не менять: новые confirmation fields используют существующую CSRF-защиту формы `/account/tokens`.

## Декомпозиция

### 137.2 HTML no-store

- Добавить helper/cache headers для `_html_response` или account route response.
- Тесты: `GET /account` и `POST /account/tokens` response содержат `Cache-Control` with `no-store`, `Pragma: no-cache`, `Expires: 0`.
- Оценка: ≤ 60 строк.

### 137.3 Safe server-side defaults + form defaults

- В `web_routes_account.py` использовать default expiry `30` и preset `read_only`, если поля отсутствуют/blank.
- Обновить form defaults в `web.py`/`web_html.py`.
- Тесты: blank expiry/default preset creates finite read-only token; `0`/negative expiry returns 400.
- Оценка: ≤ 100 строк.

### 137.4 Explicit high-risk confirmations + checkbox UI

- Добавить form fields `confirm_full_access` и `confirm_wildcard_ip`.
- Reject `full_access` without confirmation.
- Reject full-open wildcard IP `*.*.*.*` without confirmation.
- Positive test for confirmed high-risk issuance.
- Existing web-path tests that intentionally issue broad access must submit the new confirmation fields.
- Оценка: ≤ 150 строк.

### 137.5 Docs/log

- Проверить README user-visible defaults; обновить при drift, иначе зафиксировать отсутствие drift в AssumptionLog.
- Зафиксировать решение в `AssumptionLog.md`.
- Оценка: ≤ 80 строк.

## Acceptance

- Raw bearer token HTML responses are marked no-store/no-cache.
- Authenticated account HTML dashboard responses are marked no-store/no-cache.
- Default web-issued token is `read_only`, expires in 30 days, and is not wildcard-IP unless explicitly confirmed.
- Blank or missing expiry on the web path becomes 30 days; zero/negative expiry returns 400.
- Unconfirmed `full_access` and unconfirmed wildcard IP issuance return 400 with a clear token form error.
- Confirmed `full_access` and confirmed wildcard IP issuance still work.
- Existing non-web token service tests remain compatible or are intentionally updated with rationale.
- Targeted tests and project checks pass.
