# PRD: Этап 30. Расширить real e2e tests на предоставленные тестовые данные

## Цель

Расширить real API smoke tests на выделенный контур `devtr6` для обоих auth
flows и формализовать env-контракт тестового окружения.

## Решение

- Сохранить backward-compatible поддержку `TEST_USER_TOKEN`.
- Добавить login/password exchange path через env:
  - `TEST_USER_TOKEN_BASE_URL`
  - `TEST_USER_LOGIN`
  - `TEST_USER_PASSWORD`
- Добавить missing real smoke для:
  - `validate_domain_api_key_connection()`
  - login/password -> token exchange
  - `validate_user_token_connection()` на полученном token

## Важное ограничение

Если login/password contour возвращает явный auth rejection, real smoke должен
skip'аться с диагностикой, а не ломать весь suite без объяснения.

## Критерии готовности

- `tests/test_e2e_real.py` поддерживает оба пути получения user token.
- `.env.example`, `docker-compose.yml` и `test-real.yml` знают про новый env-контракт.
- README объясняет запуск real e2e для обоих flows.
