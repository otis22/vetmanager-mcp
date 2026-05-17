# Этап 167. Feedback report fixed resolution visibility

## Цель

Добавить безопасный операторский путь для закрытия feedback report как fixed, когда кодовый fix уже сделан отдельным этапом.

## Контекст

Prod feedback report `#2` по `vetmanager__get_invoice_documents` был причиной Stage 161. Кодовый fix уже задеплоен: public `invoice_id` сохраняется, internal `/rest/api/invoiceDocument` filter использует `document_id`.

Оставшееся неудобство: `scripts/triage_agent_feedback.py recent` показывает report как `new`, а существующий `promote` может создать `known_issues`, но не дает прямого operator-friendly resolution flow и не делает fixed status видимым в `recent`.

## Scope

1. Добавить CLI subcommand `resolve-report <report_id>`:
   - создает `known_issues` row, если report еще не связан;
   - обновляет существующий linked `known_issues` row, если связь уже есть;
   - при update сохраняет existing `title`, `public_summary`, `workaround`, если оператор явно не передал соответствующий CLI flag;
   - explicit empty `--title ""`, `--public-summary ""`, `--workaround ""` считаются отсутствующим значением и не очищают curated text;
   - ставит `known_issues.status` в allowed value, default `fixed`;
   - переводит `agent_feedback_reports.status` в `linked`;
   - сохраняет sanitized `title`, `public_summary`, `workaround`.
2. Обновить `recent`, чтобы linked report показывал `known_issue=#<id>/<status>`.
3. Не добавлять новый report status `fixed`: это потребовало бы миграции и смешало бы report lifecycle с issue lifecycle. Fixed status принадлежит `known_issues`.
4. Не выводить raw `details`, account id, bearer token id, raw request/response bodies.
   `summary` в triage output считается sanitized-at-ingest: `create_feedback_report`
   сохраняет его через `sanitize_text_with_metadata(..., required=True)`. Stage 167
   не расширяет raw-text surface beyond existing `recent`, а только добавляет
   linked known issue id/status.
5. После деплоя обработать prod report `#2` как fixed by Stage 161.

## Simplicity rationale

Рассмотренные альтернативы:

- Extend `promote` with `--update`: rejected because `promote` is issue-creation
  flow with optional playbook/match rules; adding update semantics would make
  destructive overwrite behavior less obvious.
- Extend `mark` with `--report-id`: rejected because `mark` today changes only
  `known_issues.status`; linking a report and creating an issue is a different
  data operation.
- Add small `resolve-report`: chosen because it is explicit, operator-facing,
  testable, and keeps fixed status on `known_issues` without schema migration.

The added helper surface is intentionally narrow: one CLI command, one recent
output join, no new tables, no new report status, no runtime MCP behavior.

## Acceptance Criteria

1. `resolve-report <id> --status fixed` создает или обновляет linked known issue.
2. Report получает status `linked` и `known_issue_id`.
3. `recent` выводит `known_issue=#<id>/fixed` для связанного report.
4. Invalid status отклоняется до DB commit.
5. Operator-provided text sanitizes/truncates via existing feedback sanitizer.
6. Existing known issue `title`, `public_summary`, `workaround` are preserved unless the corresponding CLI flag is explicitly provided with a non-empty value.
7. Tests cover create, update/preserve, invalid status and `recent` visibility.
8. Full workflow: targeted tests, full suite where feasible, review gates, commit, push, deploy, smoke, prod report `#2` resolved.

## Проверки

- `docker compose --profile test run --rm test pytest tests/test_stage167_feedback_report_resolution.py -q`
- `docker compose --profile test run --rm test pytest tests/test_stage150_agent_feedback_privacy.py tests/test_stage151_known_issue_match_events.py tests/test_stage159_feedback_product_metrics.py tests/test_stage167_feedback_report_resolution.py -q`
- `docker compose --profile test run --rm test`
- `git diff --check`
