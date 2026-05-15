# Этап 160. Strong feedback trigger instructions

## Цель

Сделать инструкции для LLM-агентов достаточно сильными, чтобы `report_problem` вызывался не только при явной ошибке tool call, но и когда tool call технически успешен, однако результат не позволяет качественно выполнить запрос пользователя.

## Контекст

Stage 159 показал `agent_feedback_reports=0` и `known_issue_match_events=0` в production. Feedback tool есть, но текущие инструкции в `server.py` и descriptions в основном говорят про unclear tool errors. Это не заставляет агента репортить:

- пустой результат там, где релевантные записи ожидались;
- неполный response shape;
- отсутствие нужного фильтра/сортировки/параметра;
- workaround вместо прямого инструмента;
- невозможность ответить на разумный запрос доступными tools;
- mismatch между description/docs и фактическим результатом.

## Scope

1. Усилить FastMCP `instructions` в `server.py`.
2. Усилить `report_problem` special description в `tool_descriptions.py`.
3. Усилить docstring в `tools/feedback.py`.
4. Добавить focused tests, которые проверяют конкретные trigger phrases и privacy boundary.
5. Обновить README Agent feedback section.

## Out of Scope

- Автоматический вызов `report_problem` сервером.
- Новые метрики/таблицы.
- Изменение write-path feedback service.
- Runtime LLM/NER/triage.

## Требования к формулировкам

Формулировки должны быть imperative, не advisory:

- использовать `Call report_problem when...`, а не `you may call...`;
- явно сказать `even when the tool call succeeded`;
- перечислить конкретные triggers;
- сохранить privacy rule: no raw clinic data, placeholders only;
- явно запретить raw tool response bodies, raw record IDs, user's verbatim message, and full error payloads.

Минимальный trigger set:

1. Empty result but relevant records were expected.
2. Response is missing fields needed to answer the user.
3. Tool description/docs promised or implied capability that result does not provide.
4. Missing tool, parameter, filter, sort, pagination, or date semantics blocks a reasonable request.
5. A workaround was necessary because no direct tool or parameter exists for a reasonable user need.
6. Successful response is suspicious, inconsistent, or not enough to answer.

Do-not-report set:

1. Legitimately empty result for a valid query with no matching records.
2. User-supplied invalid input that the tool correctly rejected.
3. Expected end-of-pagination or normal pagination boundary.
4. Normal multi-step composition when existing tools directly support the task.

Category mapping guidance:

- empty result / missing fields / suspicious response → `bug`;
- description/docs mismatch or contract mismatch → `bad_description` or `contract`;
- missing tool/parameter/filter/sort/pagination/date semantics → `missing_tool`;
- workaround because no direct tool/parameter exists → `missing_tool`;
- docs/examples conflict → `docs`.

## Acceptance Criteria

1. `server.py` instructions include strong successful-but-unsatisfactory trigger wording.
2. `SPECIAL_TOOL_DESCRIPTIONS["report_problem"]` includes the same trigger class.
3. `tools/feedback.py::report_problem` docstring includes the same trigger class.
4. Tests assert the exact trigger fragments below appear in all three sources: `server.py` FastMCP instructions, `SPECIAL_TOOL_DESCRIPTIONS["report_problem"]`, and `tools/feedback.py::report_problem` docstring.
   - `even when the tool call succeeded`;
   - `empty result but relevant records were expected`;
   - `response is missing fields needed to answer`;
   - `missing tool, parameter, filter, sort, pagination, or date semantics`;
   - `workaround was necessary because no direct tool or parameter exists`;
   - `successful response is suspicious, inconsistent, or not enough to answer`.
5. Tests assert privacy placeholders remain present and raw-data prohibition remains present in all three sources, including:
   - `Do not paste raw tool response bodies`;
   - `raw record IDs`;
   - `user's verbatim message`;
   - `full error payloads`.
6. Tests assert at least one do-not-report suppression phrase appears in all three sources: `Do not call report_problem for legitimately empty results`.
7. Tests assert category mapping guidance appears in the tool description.
8. README Agent feedback section mentions the same successful-but-unsatisfactory trigger class.
9. Post-deploy product metrics report is checked immediately; if still zero, record a follow-up note that adoption requires real client/agent behavior and schedule a T+7 day product-metrics re-check in AssumptionLog.

## Проверки

- Targeted: `docker compose --profile test run --rm test sh -c "python -m pytest tests/test_stage160_feedback_trigger_instructions.py tests/test_stage150_agent_feedback_privacy.py -q"`
- Full: `docker compose --profile test run --rm test`
- Audit: `git diff --check`
