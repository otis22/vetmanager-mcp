# Этап 217. Тестируемый review-gate и сопоставление known issues

## Цель

Вынести проверку structured review из markdown `jq` в тестируемый скрипт и
устранить SQL-предфильтр, который отбрасывает точные fingerprint matches.

## Архитектурное решение

- Review gate — stdlib Python script, читающий Claude JSON-envelope из stdin,
  печатающий extracted verdict и возвращающий non-zero при нарушении схемы.
  Это заменяет не покрытое CI многострочное jq-выражение.
- Candidate query выбирает issues только по status; точное сопоставление
  fingerprint и `match_rules` остаётся в существующей упорядоченной логике.
  Число known issues мало, поэтому correctness важнее прежнего узкого SQL
  фильтра. Rollback — вернуть индексы/безопасный prefilter только после
  замеров, не исключающий exact fingerprint.
- Architecture Critique: not required — изменения локальны, не меняют public
  MCP contract или storage schema.

## Acceptance criteria

- Gate проходит два валидных и отвергает три заданных невалидных случая; CI
  запускает эти fixtures.
- Документационный пример вызывает скрипт, а не содержит jq validation logic.
- Incident `create_report_ai_job` с точным fingerprint матчится с issue
  `create_report_ai_job/get_report_ai_job`.
- Аудит других candidate prefilters выполнен.
