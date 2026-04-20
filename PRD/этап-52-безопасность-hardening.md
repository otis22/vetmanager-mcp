# PRD: Этап 52. Безопасность: hardening

## Цель

Закрыть зафиксированные security gaps вокруг startup secrets, form abuse, password/session policy и безопасного surface web-контура.

## Контекст

Security ревью выявило уязвимости CRITICAL/HIGH/MEDIUM. Основные проблемы:
отсутствие startup-валидации секретов, нет лимита form payload, слабые пароли,
длинные сессии без idle timeout.

## Декомпозиция

### 52.1 Startup-валидация секретов

- 52.1.1: Добавить `validate_required_secrets()` в server.py перед `mcp.run()`.
  Вызывает `get_storage_encryption_key()` и `get_web_session_secret()`.
  При отсутствии — `sys.exit(1)` с понятным сообщением.
- 52.1.2: Тот же вызов, WEB_SESSION_SECRET уже fail-fast.
- 52.1.3: Добавить `STORAGE_ENCRYPTION_KEY` в `.env.example` с комментарием.

### 52.2 Защита от DoS и брутфорса

- 52.2.1: В `_read_form()` (web.py) — проверка `len(body) > MAX_FORM_SIZE`.
- 52.2.2: Account lockout после N failed logins — exponential backoff.
- 52.2.3: Per-email rate limit на registration.

### 52.3 Пароли и сессии

- 52.3.1: Усилить валидацию пароля в `web_auth.py`.
- 52.3.2: Сократить SESSION_MAX_AGE, добавить idle timeout.
- 52.3.3: Server-side session revocation.

### 52.4 Прочее

- 52.4.1: CSP для JSON endpoints.
- 52.4.2: Убрать upstream response text из ошибок.
