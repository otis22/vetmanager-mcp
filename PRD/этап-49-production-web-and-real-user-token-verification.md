# PRD: Этап 49 — production web happy-path и real user-token verification

## Контекст

После hotfix `WEB_SESSION_SECRET` production web-страницы `/register` и `/login`
снова открываются, но реальный сценарий `login/password -> user token` остаётся
сломанный: в production UI сервис пишет `Invalid Vetmanager user token`, хотя
прямой вызов `token_auth.php` с теми же данными возвращает валидный token.

Это означает, что текущий набор opt-in real tests не покрывает фактический
production path этого сценария и не выявляет рассинхрон между прямым
Vetmanager exchange и серверной validation/save-логикой проекта.

## Цель

- локализовать и исправить production/user-token расхождение;
- покрыть его opt-in real e2e tests;
- затем пройти production browser happy-path `/register -> /login -> /account`
  и зафиксировать рабочий контракт.

## Ограничения

- секреты не записываются в репозиторий;
- используются только env-driven `TEST_*` и ручной production verification;
- реализация идёт малыми инкрементами по roadmap.

## Декомпозиция

### 49.3 Reproduce mismatch

- сравнить production web flow и прямой `token_auth.php`;
- выяснить, падает ли exchange, token extraction или subsequent token validation;
- проверить, не отличается ли base URL/host normalization между exchange и validate.

### 49.4 Fix mismatch

- исправить причину `Invalid Vetmanager user token` при валидных данных;
- убедиться, что fix не ломает уже существующий mocked flow и API-key mode.

### 49.5 Add real regression

- добавить opt-in real regression на `login/password -> user token` в test suite;
- использовать `TEST_DOMAIN`, `TEST_USER_TOKEN_BASE_URL`,
  `TEST_USER_LOGIN`, `TEST_USER_PASSWORD`;
- зафиксировать минимальный asserted contract, который реально повторяет
  production path.

### 49.6 Production browser verification

- пройти browser happy-path на production:
  `/register -> /login -> /account -> integration save -> bearer issuance`
- фиксировать только outcome и безопасные артефакты без утечки секретов.

### 49.7 Doc sync

- обновить `README.md`, `Roadmap.md`, `AssumptionLog.md`;
- описать safe opt-in workflow для real browser/user-token verification.

## Итоговый контракт этапа

- `login/password -> user token` считается отдельным auth mode и не должен
  нормализоваться в `X-REST-API-KEY`.
- После `POST /token_auth.php` сервис обязан использовать
  `X-USER-TOKEN` + `X-APP-NAME: vetmanager-mcp`.
- Opt-in regressions должны проверять:
  - exchange реального user token;
  - validation/save flow;
  - browser happy-path;
  - production browser verification как ручной, но воспроизводимый workflow.
