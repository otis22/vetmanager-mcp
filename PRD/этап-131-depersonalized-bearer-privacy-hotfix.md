# Этап 131. Depersonalized bearer privacy hotfix

## Цель

Закрыть privacy blocker после super-review stage 130: depersonalized bearer token не должен получать raw PII payload при ошибке определения policy или неполном sanitizer coverage.

## Контекст

Источник задачи: `artifacts/review/2026-04-23-full-stage-130.md`.

Основные findings:
- B1: depersonalization wrapper выполняет tool до повторного auth lookup и при `AuthError` возвращает raw result.
- H1: structured phone redaction не покрывает реальные VM поля `home_phone`, `work_phone`, `owner_phone`.
- H2: free-text whitelist не покрывает VM-native поля `diagnos`, `recomendation`, `note` и похожие поля.

Проверенные факты из артефактов:
- `artifacts/api_entity_reference-ru.md` подтверждает для `Client`: `home_phone`, `work_phone`, `cell_phone`, `phone_prefix`.
- `artifacts/api_entity_reference-ru.md` подтверждает для `MedicalCards`: `diagnos`, `diagnos_type_text`, `recommendation`.
- `artifacts/vetmanager_openapi_v6.json` подтверждает `diagnos`, `diagnos_text`, `diagnos_type_text`, `recomendation`, `deathnote`, `home_phone`, `work_phone`, `cell_phone`, `phone`, `phone_prefix`.
- `artifacts/review/2026-04-23-full-stage-130.md` указывает `owner_phone` как leak-risk в denormalized owner payloads; OpenAPI/reference не подтверждают отдельное canonical field, поэтому покрывается как normalized alias для агрегированных payloads.
- `anamnes`/`anamnez` в текущих reference/OpenAPI артефактах не подтверждены, поэтому не добавляются в whitelist на этом этапе.

## Scope

- Перенести определение bearer/depersonalization policy до выполнения tool через единый request-local resolved credentials context.
- Обеспечить один runtime auth lookup на MCP tool call: wrapper разрешает credentials до выполнения tool, кладёт их в request-local context, а `VetmanagerClient` читает тот же context.
- Убрать fail-open поведение `except AuthError: return result`.
- Расширить structured redaction для phone-like fields.
- Расширить curated free-text whitelist на подтверждённые VM поля.
- Ужесточить false-positive corpus для clinical free text.
- Добавить regression tests для privacy boundary и sanitizer coverage.
- Обновить `AssumptionLog.md` и закрыть stage 131 в `Roadmap.md`.

## Вне scope

- Полная генерация sanitizer schema из OpenAPI.
- Полный `TOOL_REQUIRED_SCOPES` preflight для aggregate tools: это scope stage 132. На stage 131 сохраняется существующий path-level `_require_scope` и закрывается только fail-closed privacy boundary.
- Datetime/list contract fixes stage 133.
- Observability/reliability hardening stage 134.
- `anamnes`/`anamnez` free-text keys до подтверждения в OpenAPI/reference.

## Acceptance Criteria

- Depersonalized token не получает raw result, если depersonalization policy невозможно определить.
- Если policy/credentials невозможно разрешить, wrapper поднимает MCP `ToolError` до выполнения tool; сам tool не выполняется.
- Fail-closed `ToolError` использует generic message и не раскрывает raw token, tenant id, bearer context или детали исходного `AuthError`.
- Sanitizer маскирует `home_phone`, `work_phone`, `owner_phone`, `cell_phone` и normalized aliases.
- Sanitizer scrub'ит PII в подтверждённых free-text fields: `diagnos`, `diagnos_text`, `diagnosis`, `diagnos_type_text`, `recomendation`, `recommendation`, `note`, `notes`, `deathnote`, `description`, `treatment`, `comment`.
- Clinical title-case phrases без явного PII-сигнала не редактируются как ФИО: `Acute Otitis`, `Chronic Bronchitis`, `Острый Отит`, `Хронический Гастрит`, `Средний Отит Уха`.
- Явные PII-сигналы всё ещё редактируются: `owner John Smith`, `владелец Иван Иванов`, `Иванов И.И.`, phone, email.
- Tests покрывают fail-closed wrapper path и реальные tool payload shapes.
- Tests подтверждают, что wrapper не делает второй auth lookup после tool execution и `VetmanagerClient` берёт credentials из request-local context.
- Tests подтверждают isolation: параллельные tool calls с разными resolved credentials не видят чужой request-local context.
- Tests подтверждают cleanup: request-local credentials context сбрасывается через `try/finally` или context manager даже если tool/sanitizer падает, и следующий вызов не наследует прошлые credentials.
- Полный suite `docker compose --profile test run --rm test` зелёный.

## Оценка PRD на простоту

Триггер: нужен новый request-local credentials context, который читают wrapper и `VetmanagerClient`.

Более простой вариант `resolve before tool + second resolve inside VetmanagerClient` закрывает fail-open, но сохраняет race/revocation окно и двойной auth lookup. Передача credentials аргументом в каждый tool требует менять сигнатуры всех зарегистрированных tool'ов и хуже ложится на FastMCP decorator pattern.

Выбранный вариант с `ContextVar` минимален для текущей архитектуры: одна обёртка вокруг регистрации tool'ов задаёт credentials на время вызова, `VetmanagerClient` переиспользует их без изменения публичных tool signatures, а reset token в `try/finally` закрывает cross-call leakage. Обязательные tests на concurrent isolation и cleanup after failure фиксируют риск неправильного reset.

## Декомпозиция

- 131.1 Research artifacts и подтвердить список VM PII/free-text fields. — done in PRD
- 131.2 Добавить tests для fail-open wrapper regression.
- 131.3 Добавить tests для structured phone/note/medical-card redaction.
- 131.4 Реализовать request-level fail-closed depersonalization wrapper.
- 131.5 Расширить sanitizer key coverage и false-positive corpus.
- 131.6 Добавить tests на context isolation/cleanup и generic fail-closed error.
- 131.7 Обновить `AssumptionLog.md`, прогнать tests, audit, external review, commit/push.
