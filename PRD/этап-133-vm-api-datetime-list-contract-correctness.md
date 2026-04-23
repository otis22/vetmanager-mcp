# Этап 133. VM API datetime/list contract correctness

## Цель

Убрать drift между MCP tool inputs, mock tests и фактическим Vetmanager API contract для datetime payloads, timesheet day filtering и message reports.

## Контекст

Источник задачи: `artifacts/review/2026-04-23-full-stage-130.md`, H3/M6.

Проверенные факты из артефактов и кода:
- `artifacts/api_entity_reference-ru.md` фиксирует `Admission.admission_date` как `YYYY-MM-DD HH:MM:SS`.
- `artifacts/api_entity_reference-ru.md` фиксирует `Hospital.date_in` как `YYYY-MM-DD HH:MM:SS`; `date_out` также datetime-like discharge field.
- `artifacts/vetmanager_postman_collection.json` примеры `admission`, `hospital`, `timesheet` используют space-separated datetime, не ISO `T`.
- До stage 133 `tools/admission.py` напрямую отправлял external `date` в `admission_date`.
- До stage 133 `tools/clinical.py` напрямую отправлял `date_in`/`date_out`.
- До stage 133 `tools/operations.py::get_timesheets(date=...)` фильтровал `begin_datetime >= day_start` и `end_datetime <= day_end`, что пропускало ночные смены, пересекающие день.
- Strict filter operators `<`/`>` уже поддержаны project-level `filters.py::FilterOp` и используются в `tools/schedule.py` для VM `begin_datetime`/`end_datetime` overlap query в `get_doctor_free_slots`; stage 133 переносит тот же predicate на `get_timesheets`.
- `artifacts/api_entity_reference-ru.md` и `AssumptionLog.md` фиксируют, что `GET /rest/api/messages/reports` фактически требует непустой `campaign`; без него real API может вернуть `Campaign name cannot be empty`.

## Scope

- Добавить общий helper нормализации VM datetime: принимать `YYYY-MM-DD HH:MM:SS`, `YYYY-MM-DDTHH:MM:SS`, допускаемые ISO minutes/seconds/microseconds без timezone; отправлять в VM строго `YYYY-MM-DD HH:MM:SS`.
- Accepted input whitelist:
  - `YYYY-MM-DD HH:MM:SS` -> `YYYY-MM-DD HH:MM:SS`;
  - `YYYY-MM-DDTHH:MM` -> `YYYY-MM-DD HH:MM:00`;
  - `YYYY-MM-DDTHH:MM:SS` -> `YYYY-MM-DD HH:MM:SS`;
  - `YYYY-MM-DDTHH:MM:SS.ffffff` -> `YYYY-MM-DD HH:MM:SS`.
- Fractional seconds/microseconds на входе truncate to seconds без rounding, потому что VM wire contract second-granularity.
- Date-only input (`YYYY-MM-DD`) не принимать для create/update datetime fields, чтобы не создавать silent midnight appointments/hospitalizations.
- Timezone-aware input (`Z`, `+03:00`) не принимать в stage 133: VM contract в артефактах naive local datetime, а timezone conversion без clinic timezone policy опасен.
- Невалидные даты/время отклонять до HTTP-вызова через `ValueError`/`ToolError` path; пустые optional fields не отправлять.
- Применить helper к `create_admission`/`update_admission` для outbound `admission_date`.
- Применить helper к `create_hospitalization`/`update_hospitalization` для outbound `date_in`/`date_out`.
- Исправить `get_timesheets(date=...)` поверх stage 122.5: не возвращаться к несуществующему field `date`/`extra={"date": ...}`, а изменить только range predicate на overlap semantics: `begin_datetime < next_day 00:00:00` и `end_datetime > day_start 00:00:00`.
- Сделать `get_message_reports(campaign=...)` locally required/non-empty после trim. Внешнее имя параметра остаётся `campaign`; общий list-query contract (`limit`, `offset`, `sort`, `filter`) сохраняется.
- Обновить `artifacts/api-research-notes-ru.md` или создать его, если отсутствует, с подтверждёнными datetime/report деталями.

## Вне Scope

- Не менять внешние имена MCP параметров (`date`, `date_in`, `date_out`, `campaign`).
- Не добавлять destructive real API create/update smoke без явных `TEST_DOMAIN`/`TEST_API_KEY` и безопасного rollback сценария. Если credentials недоступны или safe rollback нельзя гарантировать, stage 133.4 фиксируется как skipped с rationale.
- Не менять schedule/free-slots алгоритм, кроме shared helper use only если потребуется.
- Не вводить timezone conversion: naive VM local datetime остаётся naive.

## Acceptance Criteria

- Contract tests падают, если `create_admission` или `update_admission` отправляют ISO `T` в VM payload.
- Contract tests падают, если `create_hospitalization` или `update_hospitalization` отправляют ISO `T` в VM payload.
- Existing space-separated `YYYY-MM-DD HH:MM:SS` input reaches VM unchanged.
- Minute-precision ISO input `YYYY-MM-DDTHH:MM` is accepted and padded to `YYYY-MM-DD HH:MM:00`.
- Fractional seconds are truncated to whole seconds in outbound VM payload.
- Invalid datetime format отклоняется до HTTP-вызова.
- Date-only input отклоняется до HTTP-вызова.
- Timezone-aware input с `Z` и с explicit offset (`+03:00`) отклоняется до HTTP-вызова.
- Empty optional update datetime fields, especially `update_hospitalization(date_out="")`, are omitted from VM payload.
- `get_timesheets(date=...)` возвращает ночные смены, пересекающие выбранный день: фильтр использует `< next_day` и `> day_start`; смена `22:00→06:00` попадает в запросы обоих дней, обычная дневная смена не дублируется.
- `get_message_reports` с пустым/whitespace `campaign` отклоняется локально до HTTP-вызова.
- Полный suite `docker compose --profile test run --rm test` зелёный.
- Если `TEST_DOMAIN`/`TEST_API_KEY` недоступны, real API smoke stage 133.4 фиксируется как skipped с rationale.

## Оценка PRD на простоту

Триггер: можно исправить datetime inline в каждом tool.

Более простой inline-вариант создаёт дублирование и риск, что следующий create/update tool снова начнёт отправлять ISO `T`. Общий helper минимален, потому что меняет только outbound VM boundary и не затрагивает доменную модель. Timezone parsing намеренно не добавляется: VM contract в артефактах naive local datetime.

## Декомпозиция

- 133.1 Добавить failing tests на ISO-in → space-separated payload для admission create/update и hospitalization create/update.
- 133.2 Добавить failing tests на existing space-separated passthrough, minute-only ISO padding и fractional seconds truncate.
- 133.3 Добавить failing tests на datetime rejection до HTTP-вызова: invalid format, date-only, timezone `Z`, timezone offset `+03:00`.
- 133.4 Добавить failing test на `update_hospitalization(date_out="")` omission.
- 133.5 Добавить failing tests на `get_timesheets(date=...)` overlap filters для ночной смены и обычной дневной смены.
- 133.6 Добавить failing test на `get_message_reports` empty/whitespace campaign rejection.
- 133.7 Выполнить real API smoke/probe только при `TEST_DOMAIN`/`TEST_API_KEY` и safe rollback; иначе зафиксировать skipped rationale.
- 133.8 Реализовать shared VM datetime helper и применить к admission/clinical tools.
- 133.9 Исправить timesheet filters и message report validation.
- 133.10 Обновить research notes, Roadmap, AssumptionLog, work log; прогнать targeted/full checks, audit, commit, external review, push.
