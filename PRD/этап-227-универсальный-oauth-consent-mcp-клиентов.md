# Этап 227. Универсальный OAuth consent для MCP-клиентов

## Цель

Устранить блокировку browser CSP при `303` после OAuth consent для любого
зарегистрированного MCP-клиента, не расширяя policy для других origins.

## Scope и декомпозиция

1. Вынести безопасное извлечение origin из уже валидированного `redirect_uri` и
   передавать его в CSP GET authorize, POST consent и финального `303`.
2. Заменить ChatGPT-specific copy consent-страницы на имя OAuth-клиента с
   нейтральным fallback.
3. Добавить в кабинет независимый MCP URL, Claude flow и краткий универсальный
   guidance, сохранив существующие ChatGPT ids и кнопку.
4. Покрыть Claude CSP/UI регрессиями и запустить полный Docker suite.

## Архитектурное решение

Проблема: `form-action` проверяется браузером и для redirect-цепочки формы;
глобальный allowlist ChatGPT блокирует callbacks Claude и допускает origins,
не относящиеся к текущему OAuth-клиенту.

Контекст и ограничения: `validate_oauth_authorize_request` уже проверяет
`redirect_uri`; POST читает подписанный `request_state`. CSP — HTTP header,
поэтому origin обязан быть строго разобран без whitespace, разделителей CSP и
control characters. OAuth, storage, scopes и privacy semantics не меняются.

Варианты: (a) расширять список известных клиентов — отклонён, не универсален и
даёт лишние origins; (b) убрать `form-action` — отклонён, ослабляет CSP;
(c) извлекать origin конкретного валидированного URI — выбран. Разрешён HTTPS;
HTTP допускается только для `localhost` ради локальных OAuth-тестов.

Инварианты: обычные страницы имеют `form-action 'self'`; OAuth response
содержит только `'self'` и origin данного клиента; на POST origin берётся
только из verified signed state. Недопустимый origin не попадает в header.
Rollback: удалить передачу origin, что вернёт строгий `'self'` и прежнее
поведение без изменения OAuth данных.

Architecture Critique: не запущен по прямому ограничению задачи не выполнять
внешние review-gates.

## Acceptance

- Claude `redirect_uri` даёт `https://claude.ai` в CSP GET consent и POST 303;
  ChatGPT/посторонний origin не присутствуют.
- Consent copy использует `client_name`, fallback — «помощник».
- Кабинет содержит секции «Данные MCP», «Подключение Claude» и универсальную
  инструкцию; ChatGPT copy ids остаются.
- `docker compose --profile test run --rm test` завершается с exit code 0.
