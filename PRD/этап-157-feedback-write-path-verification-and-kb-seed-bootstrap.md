# Этап 157. Feedback write-path verification + KB seed bootstrap

**Дата:** 2026-05-03
**Статус:** implemented; production apply/diagnostic blocked on operator-supplied identity/secrets

## Цель

Подтвердить, что feedback write-path действительно пишет строки при known-issue match, и заполнить `known_issues` минимальным verified seed-набором из уже накопленных Vetmanager API quirks. Без seed KB runtime middleware не может вернуть deterministic playbook, а `write_auto_feedback_event` не пишет auto-report для unmatched failures.

## Контекст

Prod snapshot 2026-05-02 показал:

- `agent_feedback_reports`: `0 rows`;
- `known_issues`: `0 rows`;
- при этом за последние 30 дней было `4467` runtime requests.

Возможные объяснения:

1. ошибок, совпадающих с known issues, реально не было;
2. `known_issues` пуст, поэтому auto-event path не имеет match и корректно ничего не пишет;
3. write-path сломан и молчит даже при known issue.

Stage 157 закрывает только проверку write-path и bootstrap KB. Он не делает LLM-suggestion, не превращает raw reports в KB автоматически и не меняет privacy модель Stage 149/150/151.

## Проверенные факты по коду и артефактам

- `agent_feedback_service.write_auto_feedback_event(credentials, tool_name, exc)`:
  - строит `FeedbackIncident` из `tool_name` + exception class/message;
  - считает fingerprint через `build_error_fingerprint_hash`, если есть `FEEDBACK_FINGERPRINT_PEPPER`;
  - ничего не пишет, если нет account/token identity;
  - ищет `KnownIssue` со статусом `open|acknowledged|workaround_available`;
  - при match пишет `known_issue_match_events(source="auto")` до dedup/cap;
  - пишет `agent_feedback_reports(source="auto")` только если нет recent duplicate и не превышен global cap.
- `find_known_issue_match` возвращает agent-facing playbook только для `known_issues.status == "workaround_available"` и валидного `agent_playbook_json`.
- `validate_match_rules_json` поддерживает поля `related_tool`, `error_fingerprint_hash`, `http_status`, `error_code`, `normalized_error_text`, `params_shape` и ops `eq`, `in`, `contains_any`, `contains_all`, `has_keys`, `missing_keys`.
- `validate_agent_playbook` требует `version=1`, `summary`, списки `steps`, `do_not_do`, `recommended_tool_sequence`, `safe_to_retry`; `recommended_tool_sequence` может ссылаться только на известные MCP tools.
- `known_issues` уже содержит поля `status/category/severity/priority/title/related_tool/error_fingerprint_hash/match_rules_json/agent_playbook_json/public_summary/workaround/report_count`.
- `scripts/triage_agent_feedback.py promote` уже умеет валидировать JSON и создавать one-off `KnownIssue`, но нет idempotent seed bootstrap.
- `artifacts/api-research-notes-ru.md` содержит verified quirks:
  - standard list constraints должны идти через `filter[]`;
  - `MedicalCards/Vaccinations` использует top-level `pet_id`, ответ `data.medicalcards`, не generic list;
  - `messages/reports` требует top-level `campaign`;
  - `Admission` create payload использует `admission_date`, а не `date`;
  - `MedicalCards` CRUD pet filter — `patient_id`, а specialized actions — `pet_id`;
  - `Hospital` create/update использует `hospital_block_id`, `date_in`, `date_out`;
  - `Breed` filter по типу животного — `pet_type_id`;
  - `Timesheet` day filter должен быть overlap predicate по `begin_datetime`/`end_datetime`.
- `artifacts/api_entity_reference-ru.md` подтверждает datetime formats (`YYYY-MM-DD HH:MM:SS` для appointment/invoice/hospital/timesheet-like полей) и special-case endpoint notes для stock balance, vaccinations, messages reports.

## Scope

1. Добавить idempotent seed CLI:
   - `scripts/seed_known_issues.py`;
   - subcommand или flags: `--dry-run`, `--apply`;
   - повторный запуск не создаёт duplicates;
   - выводит machine-readable summary: `created=N updated=N unchanged=N skipped=N`.
2. Seed dataset 5-10 verified issues:
   - хранить рядом со script как structured constants или JSON fixture в repo;
   - каждый issue проходит `validate_match_rules_json` и `validate_agent_playbook`;
   - статус seed issues: `workaround_available`, чтобы injection мог отдавать playbook;
   - no raw clinic data, no domain/email/token/API-key/IP/PII.
3. Diagnostic command для write-path verification:
   - безопасно вызывает production-like wrapper path `augment_tool_error`, который внутри ограничивает `write_auto_feedback_event` через `AUTO_EVENT_WRITE_TIMEOUT_SECONDS`;
   - работает через локальную DB/session factory;
   - не требует raw production secrets в аргументах;
   - fail-closed проверяет наличие `FEEDBACK_FINGERPRINT_PEPPER` перед `--apply`;
   - по результату проверяет прирост только для run-specific `error_fingerprint_hash` + supplied identity, а не глобальный count `source="auto"`;
   - выводит disambiguated статус `agent_feedback_reports(source="auto")` (`created`, `dedup_or_cap_suppressed`, `skipped_reason`).
4. Тесты:
   - seed idempotency;
   - валидность всех seed `match_rules_json` / `agent_playbook_json`;
   - injection middleware подбирает seed issue по matching incident;
   - diagnostic write-path создаёт auto match event/report на synthetic issue.
5. Документация:
   - README или runbook: как запускать dry-run/apply/diagnostic;
   - AssumptionLog: результат локального diagnostic и инструкция для prod diagnostic.

## Out of Scope

- Автоматический импорт из `agent_feedback_reports` в `known_issues`.
- LLM-generated playbooks или natural-language summarization.
- Новые таблицы/миграции.
- Изменение privacy/redaction модели `agent_feedback_reports`.
- Автоматический запуск seed на production deploy без явного operator action.
- Хранение production account/token identifiers в repo.

## Дизайн

### Seed record contract

Каждый seed issue задаётся структурой:

```python
{
    "slug": "admission-create-date-field",
    "title": "[seed:admission-create-date-field] Admission create uses admission_date",
    "category": "contract",
    "severity": "medium",
    "priority": 40,
    "related_tool": "create_admission",
    "match_rules": {"version": 1, "all": [...]},
    "agent_playbook": {"version": 1, ...},
    "public_summary": "...",
    "workaround": "...",
}
```

`slug` сохраняется без новой миграции как immutable prefix-marker в `KnownIssue.title`:

- `title.startswith("[seed:{slug}] ")`;
- короткий human-readable title остаётся после marker, чтобы operator-facing tables (`triage_agent_feedback.py match-events-stats`) не показывали только opaque slug;
- полное human-readable wording живёт в `public_summary`, `workaround` и `agent_playbook_json.summary`;
- seed script ищет rows by prefix marker and refuses to update if count > 1.

Это сознательный компромисс без schema change: stable seed key есть, но DB schema не расширяется. Если позже понадобится richer seed metadata, отдельный этап может добавить `known_issues.seed_slug`.

Seed apply behavior:

- if missing: create row;
- if existing with same marker: update only seed-owned mutable fields (`status`, `category`, `severity`, `priority`, `related_tool`, `match_rules_json`, `agent_playbook_json`, `public_summary`, `workaround`);
- update title only if exactly one row has the marker prefix; never change the marker itself;
- if more than one row matches a seed marker: exit non-zero with `duplicate_seed_rows` and require manual cleanup;
- never reset `report_count`, `first_seen_at`, `last_seen_at`, `created_at`;
- never delete rows.

### Diagnostic

Add a script subcommand:

```bash
python scripts/seed_known_issues.py diagnostic-auto-event --apply
```

Behavior:

1. require explicit identity flags for write mode: `--account-id` and/or `--bearer-token-id`;
2. require `FEEDBACK_FINGERPRINT_PEPPER` before any `--apply` write; if absent, fail closed with `skipped_reason=missing_feedback_fingerprint_pepper`;
3. require `--run-id` or generate a safe marker that survives `normalize_error_text` uniquely:
   - lowercase alphabetic groups plus UUID-derived hex split so there are no ISO-date substrings and no 6+ consecutive digits;
   - test must assert two generated run ids remain distinct after `normalize_error_text`;
4. ensure a synthetic known issue exists with `related_tool="__stage157_diagnostic__"` and stable rule matching `error_code="ToolError"` + normalized text marker `stage157 synthetic feedback diagnostic`;
   - `match_rules_json` is stable and does not include `run_id`;
   - `run_id` is appended only to the emitted `ToolError` message, so every diagnostic invocation gets a unique HMAC fingerprint and bypasses the 15-minute auto dedup window;
   - status `acknowledged` is enough for `write_auto_feedback_event` (`AUTO_EVENT_STATUSES`) but not agent-facing `find_known_issue_match`;
   - this avoids poisoning real tool KB/injection paths such as `get_payments`;
5. call `augment_tool_error("__stage157_diagnostic__", credentials, ToolError("stage157 synthetic feedback diagnostic {run_id}"))` with synthetic credentials object containing only the explicitly supplied non-secret identity values;
6. compare pre/post counts for `known_issue_match_events(source="auto")` and `agent_feedback_reports(source="auto")`; if `augment_tool_error` swallows a timeout/failure and no event appears, diagnostic exits non-zero with `skipped_reason=wrapper_auto_event_missing`.
   - counts must be filtered by the diagnostic fingerprint produced from `run_id`, `related_tool="__stage157_diagnostic__"`, and the supplied `account_id`/`bearer_token_id`;
   - do not infer success from global `source="auto"` count increases, because live traffic may create unrelated rows.

Production diagnostic must not fabricate FK ids that violate PostgreSQL constraints. Therefore prod-safe command should:

- require `--account-id` and/or `--bearer-token-id` for real DB diagnostic;
- print an explicit machine-readable `status=skipped` reason if no identity is supplied in dry-run mode; this is not a successful write-path validation;
- fail closed before writing if `--apply` is used without identity.
- output explicit skip/suppression reasons: `missing_feedback_fingerprint_pepper`, `missing_identity`, `no_known_issue_match`, `dedup_or_cap_suppressed`, `write_failed`.
- output `elapsed_ms`; if diagnostic wrapper path takes longer than `AUTO_EVENT_WRITE_TIMEOUT_SECONDS`, fail with `skipped_reason=auto_event_timeout_risk`.

Local tests use fixture-created `Account` + `ServiceBearerToken` and pass their real ids explicitly.

### Matching strategy

Seed issues should prefer broad deterministic `match_rules_json` over exact HMAC fingerprints, because seed issues describe known API contract quirks, not one production exception instance. Examples:

- `related_tool == create_admission` + `normalized_error_text contains_any ["admission_date", "date field", "date ignored"]`;
- `related_tool == get_vaccinations` + `normalized_error_text contains_any ["medicalcards", "pet_id", "vaccination"]`;
- `related_tool == get_doctor_free_slots` + `normalized_error_text contains_any ["begin_datetime", "end_datetime", "night shift", "overlap"]`.

`agent_playbook_json` must be concise and actionable: what parameter/format to use, what not to use, whether retry is safe.

## Acceptance Criteria

1. `scripts/seed_known_issues.py --dry-run` validates all seed issues and reports planned changes without DB writes.
2. `scripts/seed_known_issues.py --apply` creates missing seed known issues.
3. Re-running `--apply` is idempotent: no duplicate rows for the same seed key.
4. Existing seed rows keep `report_count`, `first_seen_at`, `last_seen_at`.
5. Every seed `match_rules_json` passes `validate_match_rules_json`.
6. Every seed `agent_playbook_json` passes `validate_agent_playbook`.
7. At least one seeded issue is selected by `find_known_issue_match` / `augment_tool_error` for a matching incident and returns a playbook.
8. Diagnostic path exercises `augment_tool_error` and can create a synthetic auto `known_issue_match_events(source="auto")` for the run-specific fingerprint when a real account/token identity is supplied.
9. Diagnostic report result is deterministic: it uses a unique `run_id` marker so the first run creates `agent_feedback_reports(source="auto")`; if dedup/cap still suppresses a report, output must say `report_created=false` with reason rather than treating the whole write-path as broken when the match event was written.
10. Diagnostic path is safe-by-default: without `--apply`, or without required identity on PostgreSQL/prod, it does not write.
    - dry-run without identity returns `status=skipped`, not `status=ok`;
    - `status=ok` is reserved for completed validation with run-specific evidence.
11. Diagnostic `--apply` fails closed with a clear reason when `FEEDBACK_FINGERPRINT_PEPPER` is absent.
12. Seed apply refuses to proceed when more than one `known_issues.title` matches a seed marker prefix.
13. Upstream wiring verification is documented and test-backed where local code allows it:
    - static test/grep confirms `augment_tool_error` is still wired in the shared tool wrapper;
    - runbook asks operator to check recent runtime logs for `feedback_auto_event_failed`, `known_issue_lookup_failed`, `known_issue_match_event_write_failed`;
    - diagnostic output includes supplied `account_id`/`bearer_token_id` presence and `elapsed_ms` so operator can confirm identity reached write-path and wrapper timing is below timeout risk.
14. README/runbook documents dry-run, apply and prod diagnostic commands without exposing secrets.
15. Full Docker suite remains green.

## Декомпозиция

- 157a PRD + reference review gates. ≤2h, docs only.
- 157b Seed dataset + validation helpers in `scripts/seed_known_issues.py`. ≤2h, ~150 LOC.
- 157c Diagnostic auto-event command. ≤2h, ~120 LOC.
- 157d Tests for validation/idempotency/injection/diagnostic. ≤2h, ~150 LOC.
- 157e README/runbook + full checks + audit + review gates. ≤2h.

## Simplicity Review

- Reuse existing `known_issues` schema and validators; no migration.
- One script is enough: combining seed + diagnostic keeps operator workflow discoverable.
- Seed records stay in code constants unless review shows a JSON fixture is cleaner; external YAML/JSON would add parsing surface without clear benefit for 5-10 rows.
- Stable seed identity is encoded as `[seed:{slug}] ` title prefix instead of a migration, because Stage 157 explicitly avoids schema changes and only manages operator-owned bootstrap rows. The prefix keeps idempotency stable; the suffix keeps operator tables readable.
- No deploy automation in Stage 157: production seed apply should remain explicit operator action.
- No exact fingerprint seeds for API quirks: rule-based matching is more stable and does not require pepper-specific precomputed hashes.
