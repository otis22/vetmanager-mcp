# Этап 228. Полировка OAuth consent и MCP-кабинета

## Цель

Восстановить визуальную иерархию consent, показывать подтверждение полного
доступа только когда оно нужно и сделать MCP-инструкции удобными для демо.

## Scope

1. Ограничить крупный metric-стиль прямым дочерним `strong` плитки.
2. Добавить nonce-защищённый inline handler: full-access checkbox скрыт и
   сбрасывается вне `full_access`; серверная валидация остаётся прежней.
3. Переставить MCP details и добавить copy в Claude section с существующим
   `mcp_url` telemetry kind.
4. Добавить regressions и запустить полный Docker suite.

## Архитектурное решение

Проблема: общий descendant selector `.metric strong` влияет на nested copy
consent, а CSP блокирует inline JavaScript без nonce. Выбран прямой-child
selector и nonce, генерируемый для каждого OAuth consent response тем же
response helper, что добавляет его в CSP. Client-side код только скрывает и
сбрасывает checkbox; POST validation сохраняет обязанность confirmation.

Альтернативы — отключить CSP или принимать confirmation только на клиенте —
отклонены как security regression. Инварианты: цифры прямых metric children в
кабинете остаются крупными; script nonce совпадает в CSP и HTML; ChatGPT
copy ids не меняются; любые новые copy buttons используют `mcp_url`.

Rollback: удалить handler и nonce plumbing, что возвращает прежний UI без
изменения OAuth данных или server-side authorization semantics.

Architecture Critique: не запущен по прямому ограничению задачи не выполнять
внешние review-gates.
