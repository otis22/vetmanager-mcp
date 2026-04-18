# Этап 103a — Auth package split (focused subset)

## Цель

Свернуть 5 разрозненных auth-модулей в структурированный `auth/` package. После стадии 103.1 (focused) — где был вынесен `_reject` helper в `bearer_auth.py` — осталась задача физически сгруппировать все auth-концепции в одном namespace'е. Это убирает путаницу "какой из 5 модулей делает что" и готовит почву для будущего расширения (MFA, API key rotation, SSO).

## Scope (focused)

Переложить код в новые места с сохранением BC через top-level re-exports:

1. `auth/__init__.py` — пакет-маркер + doc-pointer на submodule'ы.
2. `auth/context.py` — `VetmanagerAuthContext` dataclass + связанные константы (`VETMANAGER_AUTH_MODE_*`, `VETMANAGER_*_HEADER`, `DEFAULT_USER_TOKEN_APP_NAME`).
3. `auth/vetmanager.py` — `resolve_vetmanager_credentials()` (auth mode resolver).
4. `auth/bearer.py` — `BearerAuthContext` + `resolve_bearer_auth_context()` pipeline + `_reject` helper (текущий `bearer_auth.py`).
5. `auth/request.py` — `get_bearer_token()` header parser (текущий `request_auth.py`).
6. `auth/rate_limit.py` — bearer rate limiter (текущий `bearer_rate_limiter.py`).

Top-level файлы (`bearer_auth.py`, `vetmanager_auth.py`, `request_auth.py`, `bearer_rate_limiter.py`) становятся однострочными re-export shim'ами — тесты и callers продолжают импортировать с оригинальных путей без изменений.

## Non-scope

- Pipeline Validator-class conversion for `resolve_bearer_auth_context` — `_reject` уже сделал pipeline линейным; дальнейшая декомпозиция на классы без concrete use case не добавляет testability.
- Rate-limiter namespace consolidation на `rate_limit_backend` — substantial refactor (namespace change, test migration), отдельный этап.
- Удаление `request_credentials.py` shim — 11 тестов патчат `request_credentials._get_request_headers` напрямую; миграция всей тест-базы — отдельная задача.

## Критические BC факты

1. **Import paths:** `bearer_auth`, `vetmanager_auth`, `request_auth`, `bearer_rate_limiter` должны оставаться валидными импорт-путями. Для этого top-level shim'ы делают `from auth.<X> import *` + `__all__`.
2. **`BEARER_RATE_LIMITER` module-level singleton**: тесты вызывают `bearer_rate_limiter.reset_bearer_rate_limiter()` — должно работать через shim.
3. **`bearer_auth` module-level import** в `bearer_auth.py` (`import bearer_rate_limiter`) — нужно обновить на `auth.rate_limit`, но сохранить shim-path `bearer_rate_limiter.BEARER_RATE_LIMITER` для тестов.
4. **Monkeypatch contract**: тесты патчат `vetmanager_auth.resolve_vetmanager_credentials` и `bearer_auth.resolve_bearer_auth_context` — shim'ы должны re-экспортировать эти функции по точным именам.

## План работы

1. Создать `auth/` + 6 submodule'ей, физически переместить код.
2. Заменить top-level файлы на shim'ы с `from auth.X import *`.
3. Обновить внутренние import'ы (`bearer_auth.py::import bearer_rate_limiter` → `auth.rate_limit`) где это не breaking.
4. Full suite test.
5. Codex review.
6. Commit.

## Acceptance

- 648 tests passed.
- Все top-level shim-файлы ≤ 10 LOC.
- Codex review: 0 critical, 0 warning после 1 итерации.
- Все monkeypatches в тестах продолжают работать без edits.
