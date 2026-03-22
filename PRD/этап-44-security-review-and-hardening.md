# PRD: Этап 44. Security review и hardening

## Контекст

После завершения этапа 43 проект получил более жёсткий CI/test baseline и
стабильную test infrastructure. Следующий этап должен зафиксировать реальную
security-модель сервиса, прежде чем вносить hardening-изменения.

Сервис уже содержит:
- публичный web-контур (`/`, `/register`, `/login`, `/account`, `/account/*`);
- bearer-only MCP runtime;
- хранение Vetmanager credentials в encrypted storage;
- выпуск и revoke service bearer tokens;
- runtime resolution Vetmanager integration через account context;
- audit trail для token lifecycle и auth events.

Это означает, что security review должен охватить не одну точку входа, а
несколько trust boundary одновременно: browser/web, bearer runtime, storage,
upstream Vetmanager API и deployment/config layer.

## Цель этапа 44

Провести security audit bearer/web/runtime/storage контуров, зафиксировать
threat model, затем закрыть найденные риски через hardening fixes и regression tests.

## Цель 44.1

Сформировать актуальный threat model для:
- web UI;
- bearer auth;
- MCP runtime;
- storage и secret handling.

Threat model должен стать входом для подэтапов `44.2–44.6`, а не абстрактным
security-эссе.

## Решение 44.1

- Зафиксировать отдельный security artifact с:
  - активами;
  - trust boundaries;
  - основными акторами и attacker profiles;
  - entry points;
  - threat scenarios;
  - уже существующими controls;
  - приоритетными risk hypotheses для следующих задач этапа 44.
- Обязательно разделять:
  - observed controls из кода;
  - выводы/гипотезы, которые требуют следующей проверки.

## Декомпозиция 44.1

### 44.1.1 Scope capture
- Считать текущую архитектуру security-граней из `web.py`, `web_auth.py`,
  `web_security.py`, `bearer_auth.py`, `runtime_auth.py`, `storage_models.py`,
  `secret_manager.py`, `vetmanager_client.py`,
  `vetmanager_connection_service.py`.

### 44.1.2 Threat model artifact
- Создать отдельный документ threat model.
- Отразить system context, assets, actors, trust boundaries, threat list,
  current controls, open risks.

### 44.1.3 Roadmap handoff
- Явно связать risk hypotheses с подэтапами:
  - `44.2` secrets/session/cookie/CSRF/error handling
  - `44.3` authz/scope model
  - `44.4` logging/audit leakage
  - `44.5` rate limiting/abuse
  - `44.6` SSRF/host resolution/allowlist

### 44.1.4 Validation
- Обновить `Roadmap.md`, `AssumptionLog.md`.
- Прогнать обязательные проверки проекта.

## Критерии готовности 44.1

- В репозитории есть отдельный актуальный threat model artifact.
- Threat model опирается на фактическую реализацию, а не на предполагаемую.
- В документе выделены приоритетные risk hypotheses, которые напрямую
  продолжаются в `44.2–44.6`.

## Цель 44.2

Проверить контур web secrets/session/cookie/CSRF и safe error handling, чтобы
исключить слабую связку между web session secret и storage encryption key и
подтвердить, что web UI не показывает пользователю upstream/internal детали.

## Решение 44.2

- Разделить секреты по назначению:
  - web session signing должен требовать отдельный `WEB_SESSION_SECRET`;
  - `STORAGE_ENCRYPTION_KEY` остаётся только для encrypted storage.
- Зафиксировать regression test на запрет fallback
  `WEB_SESSION_SECRET <- STORAGE_ENCRYPTION_KEY`.
- Перепроверить, что текущие web ошибки остаются safe-by-default:
  - формы логина/интеграции возвращают user-safe сообщения;
  - CSRF/session cookies сохраняют `HttpOnly`/`Secure`/`SameSite` contract;
  - security headers продолжают выставляться на HTML responses.

## Декомпозиция 44.2

### 44.2.1 Secret boundary hardening
- Убрать fallback session secret на `STORAGE_ENCRYPTION_KEY`.
- Оставить явную runtime-ошибку при отсутствии `WEB_SESSION_SECRET`.

### 44.2.2 Regression coverage
- Обновить unit/web tests так, чтобы они ловили попытку неявного reuse storage key
  для web session signing.

### 44.2.3 Validation
- Прогнать целевые web auth tests.
- Прогнать обязательный default contour.

## Критерии готовности 44.2

- Web session signing требует отдельный `WEB_SESSION_SECRET`.
- Тесты покрывают отсутствие fallback на `STORAGE_ENCRYPTION_KEY`.
- Default suite остаётся зелёным без regressions в web auth flow.
