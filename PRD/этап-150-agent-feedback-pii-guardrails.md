# Этап 150. Agent feedback PII guardrails

## Цель

Снизить риск попадания персональных данных клиентов, владельцев и пациентов в `agent_feedback_reports` через MCP tool `report_problem`.

Решение должно быть простым: инструкция агенту + детерминированная redaction + операторский флаг риска. Runtime не вызывает LLM/NER, не делает автоисправлений и не блокирует полезный feedback только из-за подозрения на PII.

## Контекст

Stage 149 добавил DB-backed feedback loop:

- `report_problem` сохраняет структурированный feedback в `agent_feedback_reports`;
- `known_issues` возвращает agent-facing советы только после operator verification;
- storage уже проходит sanitizer для secrets/email/phone/token-like values;
- runtime не использует LLM.

Новый риск: модель может прислать в `summary/details/reproduce/suggested_fix/error_excerpt` реальные ФИО владельца, кличку пациента, адрес или raw fragment из Vetmanager. Нужно уменьшить вероятность и сделать такие случаи заметными при triage.

## Scope

1. Обновить FastMCP server instructions и `report_problem` description.
2. Добавить явные placeholders и примеры:
   - вместо ФИО клиента/владельца: `<client>` / `<owner>`;
   - вместо клички/пациента: `<patient>`;
   - вместо телефона: `<phone>`;
   - вместо адреса: `<address>`.
3. Усилить `agent_feedback_service.sanitize_text` для feedback free text:
   - сохранить существующее покрытие bearer/API keys/JWT/hex/base64/email/phone;
   - добавить redaction контекстных персональных фрагментов рядом с сигналами `client`, `owner`, `patient`, `pet`, `клиент`, `владелец`, `пациент`, `питомец`, `кличка`, `адрес`;
   - редактировать очевидные ФИО/инициалы в таких контекстах, не пытаться искать любое русское слово;
   - не редактировать обычную доменную лексику: `client search returns 500`, `patient endpoint contract mismatch`, `ошибка поиска клиента` не являются PII без value-like pattern.
4. Добавить минимальный storage flag:
   - `agent_feedback_reports.possible_pii` boolean, NOT NULL, default false;
   - Alembic production-safe pattern: добавить колонку с `server_default=sa.false()` либо nullable → backfill → `nullable=False`;
   - migration marks existing rows as `possible_pii=true`, потому что они были сохранены до нового contextual sanitizer и не должны выглядеть проверенно безопасными;
   - выставлять true, если sanitizer сделал privacy-like redaction (`email`, `phone`, contextual name/patient/address) или нашёл уже присланные placeholders;
   - literal placeholders (`<client>`, `<owner>`, `<patient>`, `<phone>`, `<address>`) считаются `possible_pii=true`: это сигнал, что реальные данные были у агента до self-redaction; это только human spot-check flag, не блокировка;
   - secret-only redaction (`Bearer`, API key, password, JWT/hex/base64 token) не обязана ставить `possible_pii=true`, но redaction сохраняется.
5. Показывать flag в triage:
   - `recent` row summary;
   - `export-markdown`.

## Sanitizer Interface

Новый metadata contract не должен ломать существующих callers.

- Добавить `SanitizeResult(text: str | None, redactions: frozenset[str])`.
- Добавить новую функцию `sanitize_text_with_metadata(value, *, limit, required=False) -> SanitizeResult`.
- Существующая `sanitize_text(...) -> str | None` остаётся совместимой thin wrapper над новой функцией.
- `create_feedback_report` агрегирует `redactions` по `summary`, `details`, `error_excerpt`, `suggested_fix`, `reproduce`, `related_*` fields и выставляет `possible_pii=True`, если есть privacy-class redaction:
  - `email`;
  - `phone`;
  - `contextual_name`;
  - `contextual_patient`;
  - `contextual_address`;
  - `placeholder_seen`.
- `secret` redactions не являются privacy-class для `possible_pii`, но текст всё равно редактируется.
- Auto-events (`source=auto`) всегда сохраняют `possible_pii=false`: их `summary`/`details` fixed strings, а raw `error_excerpt` не пишется в строку report.
- Exact related fields:
  - `related_tool`, `related_call_id`, `request_id`, `error_code` are opaque identifiers/codes: sanitize for secrets/control chars/truncation only, never set `possible_pii`.
  - `error_excerpt` is free text: sanitize + classify.
- Marker text is `[REDACTED]` for all new privacy-class redactions; existing secret marker remains `[REDACTED]`.
- On sanitizer exception for any free-text field, store `[REDACTED]`, mark `possible_pii=true`, and continue saving the report. Do not fail open by storing raw input.
- Stage 150 sanitizer writes `redaction_version=2`; legacy rows remain version 1 unless re-saved.

## Context-Bound PII Rules

Цель — редактировать value-like fragment после явного label/context, а не любое слово рядом с `client`/`patient`.

- Name/person contexts: `client|owner|клиент|владелец|пациент|patient`.
  Redact only if after keyword/label separator in next 1-4 tokens есть Title-Case Latin/Cyrillic token длиной ≥3, initials pattern `И.И.`/`I.I.`, либо комбинация Title-Case + initials.
- Patient/pet name contexts: `pet|patient|питомец|пациент|кличка`.
  Redact one value-like token after label/colon/phrase if token is Title-Case and ≥3 chars.
- Address contexts: `address|адрес`.
  Redact text after `:`/`=` through the next sentence terminator (`.`, `;`, newline) or 120 chars, whichever comes first. Commas inside the fragment are not terminators because addresses contain commas. Do not scan arbitrary lower-case prose as address.
- Do not redact if the next token is lower-case verb/noun, numeric-only, known domain verb phrase, or no label/value separator is present.
- Phone redaction and phone privacy classifier must avoid generic numeric tokens: numeric IDs, ISO timestamps, long request IDs and version strings remain visible and must not set `possible_pii=true`. Phone-like values require a leading `+`/`8` or phone separators plus at least 10 digits after removing separators.

## Out of Scope

- Runtime LLM/NER для triage.
- Автоматическое исправление кода или данных Vetmanager.
- Hard reject report при `possible_pii=true`.
- Heuristic «плотность кириллицы».
- Полный PII detector для произвольного русского текста.
- `known_issue_match_events` из Stage 149.

`known_issue_match_events` явно переотложен в Stage 151: это отдельная аналитическая таблица, не обязательная для privacy-hardening `report_problem`.

## Acceptance Criteria

1. `tools/list`/description и FastMCP instructions явно говорят: описывать форму проблемы, не данные.
2. `report_problem` docstring содержит placeholders и before/after пример без реальных данных.
3. Sanitizer редактирует очевидные context-bound PII:
   - `клиент Иванов И.И.` → `клиент [REDACTED]`;
   - `owner: John Smith` → `owner: [REDACTED]`;
   - `кличка Барсик` → `кличка [REDACTED]`;
   - `адрес: Москва, ...` → `адрес: [REDACTED]`.
4. Sanitizer не редактирует обычные русские описания без PII-сигнала, например «ошибка при фильтрации оплат за март».
5. Sanitizer не редактирует обычную доменную лексику с entity words без value-like pattern: `client search returns 500`, `patient endpoint contract mismatch`, `ошибка поиска клиента`.
6. Stored report не содержит очевидные PII examples из tests и имеет `possible_pii=true`.
7. Reports с email/phone после redaction имеют `possible_pii=true`; secret-only reports могут иметь `possible_pii=false`.
8. Reports с literal placeholders (`<client>`/`<owner>`/`<patient>`/`<phone>`/`<address>`) имеют `possible_pii=true`, но не rejected.
9. Numeric IDs, ISO timestamps, long request IDs and version strings do not set `possible_pii=true` by themselves.
   They also are not redacted by the phone rule.
10. Auto-event row produced by middleware has `possible_pii=false`.
11. Reports без PII examples сохраняются с `possible_pii=false`.
12. `scripts/triage_agent_feedback.py recent` и `export-markdown` показывают privacy flag.
13. Alembic migration добавляет `possible_pii` production-safe способом и migrations test проверяет колонку.
14. Existing `agent_feedback_reports` rows после upgrade имеют `possible_pii=true`, кроме `source=auto`, где `possible_pii=false`; колонка не nullable.
15. If sanitizer raises for a free-text field, saved field value is `[REDACTED]`, row has `possible_pii=true`, and raw text is not persisted.

## Decomposition

- 150a PRD/review gates and artifacts. ≤2h.
- 150b Storage migration + model field + migration tests. ≤150 LOC.
- 150c Sanitizer result metadata + context-bound PII redaction. ≤150 LOC.
- 150d Tool/server instructions and description tests. ≤150 LOC.
- 150e Triage visibility + CLI tests. ≤150 LOC.
- 150f Full checks, audit, committed-diff reviews, push, AssumptionLog. ≤2h.

## Simplicity Rationale

Выбран минимальный вариант. Description-only снижает частоту ошибок модели, но не гарантирует защиту. Полный NER/LLM дороже, сложнее и добавляет новые privacy риски. Поэтому v1 сочетает instruction, deterministic sanitizer и видимый `possible_pii` flag для оператора.

Флаг не блокирует feedback, потому что ложноположительные случаи неизбежны, а потеря отчётов ухудшит feedback loop. Оператор сможет при triage быстрее увидеть записи, которые требуют ручной проверки.
