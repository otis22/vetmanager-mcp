# PRD: Этапы 32–35. Privacy messaging, auth transparency, token health и security audit

## Контекст

После этапов 24–31 у проекта уже есть:
- публичный лендинг;
- web account с регистрацией и login/logout;
- сохранение Vetmanager integration;
- выпуск и revoke service bearer-токенов;
- browser/real e2e подтверждение основного API-key сценария.

Но остаются продуктовые и security-разрывы:
- на лендинге и в кабинете нет чётких формулировок о том, что именно сервис не хранит из Vetmanager;
- текущий web UI для режима `user_token` просит уже готовый `user_token`, а не логин/пароль для exchange;
- статус работоспособности Vetmanager integration не показан пользователю явно;
- нет полноценного re-auth UX при инвалидированном user token;
- нужен отдельный security audit с remediation backlog.

## Цели

1. Явно и точно объяснить пользователю:
   - сервис не хранит бизнес-данные Vetmanager для постоянного хранения;
   - логин/пароль не сохраняются и используются только для получения user token;
   - при смене пароля в Vetmanager user token может стать невалидным и потребуется повторная авторизация.
2. Довести web UI до реального login/password exchange flow для user-token режима.
3. Показывать health/status активной Vetmanager integration и давать понятный CTA на re-auth.
4. Провести аудит security-sensitive мест и зафиксировать оставшиеся риски и backlog.

## Нецели

- Полноценный background scheduler для периодической проверки токенов.
- Полное enforcement будущих scopes/RBAC beyond already planned storage model.
- Юридическая политика/Terms of Service вне рамок продуктовых текстов интерфейса и README.

## Решения

### 1. Privacy messaging

- На лендинге добавить отдельный блок privacy/auth transparency.
- На странице кабинета рядом с Vetmanager integration добавить:
  - что сервис хранит только технические данные интеграции;
  - логин и пароль не сохраняются;
  - после exchange хранится только user token в encrypted storage;
  - данные Vetmanager не кэшируются и не сохраняются как база сервиса.

### 2. Web flow для `login/password -> user token`

- Для auth mode `user_token` web UI должен принимать:
  - `clinic domain`
  - `Vetmanager API key`
  - `Vetmanager login`
  - `Vetmanager password`
- Backend выполняет `POST /token_auth.php`, получает user token и сохраняет только token.
- Login/password не записываются в storage, audit logs и safe error messages.
- Для exchange использовать `application/x-www-form-urlencoded`, поля `login` и `password`, заголовки:
  - `Accept: application/json`
  - `Content-Type: application/x-www-form-urlencoded`
  - `X-REST-API-KEY: <rest_api_key>`

### 3. Integration health и re-auth UX

- Ввести модель состояний integration health:
  - `active`
  - `reauth_required`
  - `invalid`
  - `unknown`
- Не перегружать storage отдельной сложной таблицей health-check history.
- На первом шаге вычислять health on-demand:
  - при открытии `/account`;
  - после сохранения integration;
  - после явного re-auth / rotate action.
- Для `domain_api_key` проверка health выполняется через validation probe.
- Для `user_token` проверка health выполняется через validation probe на текущем stored token.
- При `401` для user-token connection показывать `reauth_required`.

### 4. Token rotation / re-auth UX

- Для active connection добавить отдельную форму `Повторная авторизация / обновить токен`.
- Для режима `user_token` форма снова принимает `API key + login + password`.
- Для режима `domain_api_key` форма допускает замену API key.
- Старые active connections переводятся в `disabled`, новая активная connection создаётся заново по текущему паттерну проекта.

### 5. Security audit scope

- Проверить и зафиксировать:
  - хранение секретов в storage;
  - отсутствие login/password в response body, HTML, audit log, exception details;
  - cookie/session defaults и session invalidation;
  - token revoke/expired/error-paths;
  - logging/error handling без утечки секретов.
- Результаты аудита зафиксировать в `AssumptionLog.md`.
- Если остаются улучшения вне текущего объёма, добавить отдельный remediation backlog в `Roadmap.md`.

## Декомпозиция

### Этап 32

- 32.1 Добавить tests на landing privacy notice.
- 32.2 Добавить tests на account integration privacy/auth notes.
- 32.3 Обновить landing/account UI тексты.
- 32.4 Обновить README и AssumptionLog.

### Этап 33

- 33.1 Добавить tests на integration health state и re-auth CTA.
- 33.2 Реализовать on-demand integration health evaluation.
- 33.3 Отобразить статус и причину в кабинете.
- 33.4 Добавить re-auth/rotate форму и submit handler.
- 33.5 Добавить тесты на invalid token / reauth required.

### Этап 34

- 34.1 Добавить tests на web `login/password -> token` flow.
- 34.2 Реализовать token exchange service.
- 34.3 Подключить новый flow к `/account/integration` и `/account/integration/reauth`.
- 34.4 Добавить safe error mapping без утечки credentials.
- 34.5 Проверить отсутствие login/password в storage и HTML.

### Этап 35

- 35.1 Провести targeted code audit security-sensitive модулей.
- 35.2 Зафиксировать findings и remediation backlog.
- 35.3 Обновить Roadmap/AssumptionLog/README при необходимости.

## Критерии готовности

- Landing page явно объясняет privacy boundaries.
- В web UI для user-token режима есть login/password exchange, а не только raw token field.
- Login/password не сохраняются и не отражаются в HTML или audit logs.
- Кабинет показывает health/status integration и CTA на повторную авторизацию.
- Тесты покрывают privacy messaging, exchange flow, invalid token / re-auth сценарии.
- `AssumptionLog.md` содержит security audit findings и решение по каждому high-risk наблюдению в рамках текущего этапа.
