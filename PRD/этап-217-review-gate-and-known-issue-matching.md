# Этап 217. Тестируемый review-gate и сопоставление known issues

## Цель

Вынести проверку structured review из markdown `jq` в тестируемый скрипт и
устранить SQL-предфильтр, который отбрасывает точные fingerprint matches.

## Архитектурное решение

- Review gate — исполняемый stdlib Python script с shebang, читающий Claude
  JSON-envelope из stdin, печатающий extracted verdict и возвращающий non-zero
  при нарушении схемы. Это заменяет не покрытое CI многострочное jq-выражение
  и не зависит от имени команды интерпретатора.
- Candidate query ограничивает rules-based candidates тем же `related_tool`
  или отсутствием tool scope, но дополнительно допускает точное совпадение
  fingerprint. Поэтому multi-tool issue проходит для exact fingerprint, а
  нестрогие rules не выдают playbook инциденту от чужого инструмента.
- Architecture Critique: not required — изменения локальны, не меняют public
  MCP contract или storage schema.

## Acceptance criteria

- Gate проходит два валидных и отвергает три заданных невалидных случая; CI
  запускает эти fixtures и smoke исполняемой документированной команды.
- Документационный пример вызывает скрипт, а не содержит jq validation logic.
- Incident `create_report_ai_job` с точным fingerprint матчится с issue
  `create_report_ai_job/get_report_ai_job`.
- Issue чужого инструмента с нестрогими match rules не матчится с incident.
- Аудит других candidate prefilters выполнен.
