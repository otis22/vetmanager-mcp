# Архитектурное ревью vetmanager-mcp

Дата: 2026-03-22

## 1. Снимок системы

Текущая система состоит из пяти основных bounded contexts:

1. `web`:
   HTML UI, account session flow, onboarding, bearer token management,
   health/metrics endpoints и browser-oriented routes.
2. `auth/runtime auth`:
   bearer extraction, runtime context resolution, token scopes,
   audit/security checks, web security helpers.
3. `storage`:
   SQLAlchemy foundation, models, migrations, token/integration persistence.
4. `client`:
   `vetmanager_client.py`, host resolution, caching, pacing, upstream requests.
5. `tools`:
   entity-specific MCP tools, регистрируемые через общий `tools.register_all`.

## 2. Модульные границы

### 2.1 Что отделено хорошо

- `storage.py` и `storage_models.py` отделяют DB foundation от предметных flows.
- `request_auth.py`, `runtime_auth.py`, `bearer_auth.py` формируют понятную auth chain:
  header -> bearer token -> runtime credentials.
- `service_metrics.py`, `structured_logging.py`, `observability_logging.py`,
  `error_tracking.py` уже образуют отдельный observability slice.
- `tools/` изолирует MCP entity surface от web и account provisioning.

### 2.2 Где границы уже текут

- `web.py` перегружен и фактически совмещает:
  - route registration;
  - HTML rendering;
  - onboarding orchestration;
  - integration save/reauth flow;
  - bearer issuance/revoke flow;
  - health/metrics endpoints;
  - request instrumentation.
- `auth_audit.py` зависит от `web_security.resolve_client_ip`, то есть audit layer
  знает о web-specific IP extraction.
- `vetmanager_client.py` совмещает:
  - runtime credential bootstrap;
  - host resolution;
  - scope enforcement;
  - cache invalidation policy;
  - retry/timeout policy;
  - upstream transport.
- `vetmanager_connection_service.py` смешивает persistence, credential validation
  и часть domain policy.

## 3. Hotspots и связность

Крупные модули:
- `web.py`: 1453 LOC
- `vetmanager_connection_service.py`: 354 LOC
- `vetmanager_client.py`: 302 LOC
- `storage_models.py`: 234 LOC
- `web_auth.py`: 202 LOC
- `bearer_auth.py`: 201 LOC

Вывод:
- главный architectural hotspot сейчас `web.py`;
- второй hotspot — связка `vetmanager_client.py` + `vetmanager_connection_service.py`;
- auth/runtime контур логически понятен, но размазан по нескольким модулям.

## 4. Дублирование и неявные контракты

### 4.1 Явное/скрытое дублирование

- Похожая логика HTTP response decoration размазана между `_html_response`,
  `_json_response`, `_plain_text_response`, `_redirect_response`.
- Повторяется pattern “read form -> validate csrf -> business action -> render same page”.
- В web flows есть повторяемый pattern получения `account_id`, redirect на `/login`
  и `clear_account_session_cookie`.
- В tests повторяется локальный bootstrap для isolated web DB.

### 4.2 Неявные контракты

- `VetmanagerClient()` требует наличия bearer header уже в конструкторе, хотя
  concrete runtime credentials разрешаются лениво позже.
- Observability contract во многом держится на label name stability, но большая
  часть этого stability contract пока зафиксирована только тестами и артефактами.
- Tool modules implicitly предполагают единый contract `VetmanagerClient`.
- `web.py` implicitly знает, какие ошибки `vetmanager_connection_service` можно
  безопасно показать пользователю как user-facing text.

## 5. Test architecture и стоимость поддержки

Текущая архитектура тестов сильная, но не дешёвая:

- `default contour`: 297 passed, 56 deselected
- есть unit слой, mock e2e, live localhost browser suite, opt-in real contour
- крупнейшие test hotspots:
  - `tests/test_e2e_mock.py`: 118 тестов
  - `tests/test_e2e_real.py`: 54 теста
  - `tests/test_web_auth.py`: 24 теста
  - `tests/test_client_multitenancy.py`: 19 тестов

Плюсы:
- высокое regression coverage на security/auth/runtime/browser paths
- хороший split между default и opt-in real contour

Риски:
- `tests/test_e2e_mock.py` уже стал монолитным regression bucket
- web/browser coverage частично расползается между `test_web_auth.py`,
  browser happy paths и live harness tests
- изменение `web.py` дорого по количеству затрагиваемых тестов

## 6. Оценка текущей архитектуры

Итоговая оценка:
- система уже достаточно зрелая по security/test/ops baseline;
- главная проблема не в отсутствии слоёв, а в концентрации orchestration logic
  в нескольких крупных модулях;
- refactor pressure сейчас structural, а не feature-driven.

## 7. Рекомендованные направления рефакторинга

### Quick wins

- вынести web route guards и common response helpers в отдельный web support module
- вынести account dashboard/token/integration subflows из `web.py` по модулям
- выделить shared test helpers для web DB bootstrap и authenticated client setup
- разрезать `tests/test_e2e_mock.py` по доменным срезам

### Medium refactors

- выделить transport policy из `vetmanager_client.py`
- отделить connection validation от connection persistence в
  `vetmanager_connection_service.py`
- отвязать audit metadata extraction от web-specific helper

### Long-term refactors

- перейти от “single giant web module” к feature packages:
  `web/account`, `web/auth`, `web/integration`, `web/observability`
- сформировать explicit internal service interfaces для:
  - runtime auth context
  - connection validation
  - token issuance/audit

## 8. Архитектурные решения

- Не делать большой переписывательский refactor без feature pressure.
- Следующий рефакторинг должен идти инкрементами с measurable blast radius.
- Приоритет номер один: уменьшить размер и ответственность `web.py`.
