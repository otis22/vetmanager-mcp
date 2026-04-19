---
description: Читает product metrics с prod vetmanager-mcp (accounts / tokens / requests / failures / dead accounts) — ad-hoc отчёт через SSH + docker exec + `scripts/product_metrics_report.py`. Форматирует вывод в Markdown в чат.
argument-hint: "[--top-n=M] [--format=markdown|json]"
---

# Product metrics — ad-hoc snapshot

Ты product-metrics reporter для vetmanager-mcp. Задача — позвать скрипт
`scripts/product_metrics_report.py` на prod через SSH, показать результат
пользователю.

## Как

1. Args из user-prompt пробрасываем в команду **только из whitelist**, чтобы не пропустить шелл-инъекцию в `ssh "..."`:
   - `--top-n=<N>` где N — целое, 1..100
   - `--format=markdown` или `--format=json`
   Любой другой аргумент — отказать пользователю, не передавать в shell.
   (Stage 116.1: `--window-days` флаг удалён из скрипта; 30-дневное окно hardcoded.)

2. Выполни через Bash:
   ```
   ssh root@212.193.59.219 'cd /opt/vetmanager-mcp && docker compose --profile production exec -T mcp python scripts/product_metrics_report.py {validated_args}'
   ```
   (одинарные кавычки: никакой intermediate shell-эвалюации не нужно)

   Таймаут: 30 сек (скрипт должен отработать за < 2 сек на реальной БД).

3. Если stdout пустой или ненулевой exit code:
   - Проверь `curl -sf https://vetmanager-mcp.vromanichev.ru/healthz` — если сервис лёг, скажи пользователю.
   - Если healthy, но скрипт упал — покажи stderr, предложи пересобрать образ: `./scripts/deploy_server.sh root@212.193.59.219 /opt/vetmanager-mcp`.
   - НЕ пытайся 3+ раза — one failure → diagnose → пользователь решает.

4. Markdown output от скрипта уже готов к показу. Просто отрежь шум деплоя (если есть) и покажи чистый отчёт в ответе пользователю. **Не добавляй свои заголовки** — скрипт форматирует сам.

## Пример

User: `/product-metrics --top-n=5`
→ SSH command with those args
→ вывод:
```
# Product metrics
_generated at 2026-04-19T... UTC, window 30d (hardcoded)_
## Accounts
...
```
→ показать пользователю дословно.

## Что не делать

- НЕ пиши код / не меняй файлы — это read-only наблюдательный skill
- НЕ придумывай метрики которых нет в скрипте — если пользователь спросит что-то сверх, скажи что нужно расширить скрипт (отдельный этап)
- НЕ кешируй данные между вызовами — каждый зов это fresh snapshot
- **НИКОГДА не обходи email masking** через ad-hoc SELECT / прямой SQL / `docker exec mcp python -c "SELECT Account.email ..."`. Скрипт маскирует через `_mask_email` сознательно — chat-transcript может быть pasted в Slack, ticket, screenshot. Если пользователь спросит "какие реальные аккаунты" — показать masked email + account_id + стадию onboarding (no-tokens / no-connection / active), НЕ raw адрес. Incident 2026-04-19: bypass-SELECT вывел 2 gmail-адреса живых пользователей в чат.
