# PRD: Этапы 38–40. Account wizard, browser E2E и production hardening

## Контекст

После этапов 36–37 у проекта уже есть:
- landing для клиник;
- account registration/login;
- Vetmanager integration через `/account`;
- выпуск service bearer token;
- security baseline для web UI.

Но текущий кабинет всё ещё слишком технический для нетехнического пользователя:
- форма integration показывает все auth-поля сразу;
- user не понимает, какой способ авторизации выбирать;
- новый raw bearer token легко потерять после submit;
- нет оформленного browser-level regression на полный happy-path;
- `login/password -> user token` на предоставленном контуре `devtr6` требует
  отдельного расследования и более точной диагностики.

## Цели

### Этап 38
- Переделать integration setup в wizard.
- Показать только релевантные auth-поля для выбранного способа подключения.
- Улучшить onboarding в кабинете.
- Сделать выдачу bearer token заметной и удобной сразу после создания.
- Расследовать login/password token exchange на `devtr6`.

### Этап 39
- Подтвердить в браузере главный сценарий:
  регистрация -> login -> integration -> bearer -> MCP call.
- Зафиксировать реальные ограничения happy-path и release-check.

### Этап 40
- Зафиксировать production-grade hardening plan там, где текущая реализация
  остаётся process-local или single-instance oriented.

## Нецели

- Полноценный SPA или frontend framework migration.
- Новая система email verification / invitations.
- Полный distributed implementation для rate limit и sessions в этом же проходе.
- Полноценный secret manager вне текущего storage/env контракта.

## Продуктовые решения

### 1. Wizard авторизации

- Вместо единой технической формы в кабинете появляется wizard/stepper:
  - шаг выбора способа подключения;
  - шаг ввода только нужных полей;
  - шаг подтверждения/сохранения.
- Два режима:
  - `API key`
  - `Логин и пароль`
- Для `API key` показываются только:
  - `domain`
  - `api_key`
- Для `Логин и пароль` показываются только:
  - `domain`
  - `api_key`
  - `login`
  - `password`

### 2. UX выпуска bearer token

- После успешного создания raw token должен появляться сразу в видимой части
  страницы, а не только внутри нижнего блока после перерендера.
- Новый token показывается в отдельной заметной success-card.
- Карточка содержит:
  - имя токена;
  - raw bearer token;
  - явное предупреждение `Скопируйте сейчас`;
  - кнопку копирования.
- Страница должна автоматически переводить пользователя к success-card:
  - через якорь/scroll;
  - или через расположение блока в верхней части рендера.

### 3. Диагностика `login/password -> user token`

- Для `devtr6` нужно подтвердить один из вариантов:
  - credentials реально невалидны;
  - API key не подходит для token exchange;
  - на контуре отключён/ограничен `token_auth.php`;
  - response shape отличается от уже поддерживаемых вариантов;
  - есть host/env mismatch.
- В UI должны остаться безопасные ошибки без утечки credentials.
- В `AssumptionLog.md` нужно зафиксировать абсолютный факт по `devtr6`.

### 4. Browser E2E главного сценария

- Обязательный happy-path:
  - регистрация;
  - login;
  - integration;
  - выпуск bearer token;
  - реальный MCP вызов этим bearer token;
  - проверка, что token сразу виден после выпуска.
- Если login/password flow на `devtr6` не проходит по внешним причинам,
  основной browser happy-path всё равно закрывается через рабочий API-key flow,
  а ограничение отдельно фиксируется.

### 5. Production hardening

- На текущем этапе достаточно оформить:
  - shared/edge strategy для rate limiting;
  - multi-instance notes для CSRF/session;
  - deployment security checklist;
  - docs sync.

## Технические решения

### Web UI

- Остаться на server-rendered HTML.
- Wizard реализовать через:
  - server-rendered radio/button choice;
  - минимальный inline JS для переключения видимых секций;
  - server-side fallback через `form_auth_mode`.
- Success-card для token issuance рендерить выше основного token form.

### Tests

- Добавить HTTP tests на:
  - wizard copy и видимые режимы;
  - token success-card и copy affordance;
  - onboarding empty state.
- Browser E2E выполнить через существующий browser tool/manual scripted flow.
- Real checks:
  - использовать `devtr6` API-key contour для happy-path;
  - отдельно прогнать `token_auth.php` для login/password investigation.

## Декомпозиция

### Этап 38
- 38.1 PRD и red tests на wizard/account UX.
- 38.2 Реализовать wizard и onboarding copy.
- 38.3 Реализовать улучшенный token success-card и copy UX.
- 38.4 Расследовать `devtr6` login/password exchange.
- 38.5 Обновить diagnostics/messages.

### Этап 39
- 39.1 Поднять локальный контур.
- 39.2 Прогнать browser E2E регистрации и login.
- 39.3 Прогнать browser E2E integration + token issuance.
- 39.4 Проверить MCP call с bearer.
- 39.5 Зафиксировать результаты и ограничения.

### Этап 40
- 40.1 Описать production hardening plan.
- 40.2 Обновить README/AssumptionLog/Roadmap при необходимости.

## Критерии готовности

- `/account` показывает wizard вместо перегруженной формы.
- Для каждого auth mode видны только нужные поля.
- Новый raw bearer token сразу виден после создания без ручного поиска по странице.
- Кнопка copy/визуальный affordance присутствуют.
- Browser happy-path от регистрации до MCP call подтверждён.
- Investigation по `devtr6` зафиксирована с конкретным выводом.
- README, Roadmap и AssumptionLog синхронизированы.
