# Этап 151. Known issue match analytics events

## Цель

Добавить отдельный privacy-safe persistent store для всех событий «known issue был сматчен» — чтобы operator имел SQL-доступную аналитику «сколько раз каждый issue реально срабатывал» отдельно от saved feedback reports.

Текущий gap (после Stage 149/150/153):

- `known_issues.report_count` (атомарный после Stage 153) считает только saved `agent_feedback_reports` — explicit `report_problem` от агента + дедуплицированные auto-events.
- `augment_tool_error` middleware (`agent_feedback_service.py:710`) при каждом tool error ВСЕГДА вызывает `lookup_known_issue_for_error` и инжектирует playbook в ToolError, но запись `agent_feedback_reports` создаётся только если auto-event прошёл дедуп-окно (`AUTO_EVENT_DEDUP_WINDOW`) И не упёрся в `MAX_AUTO_EVENTS_PER_MINUTE` global cap.
- В результате operator не видит «1 known issue сматчился 1000 раз/час» — видит только дедуплицированные 1-2 saved reports.

## Контекст

Stage 149.2 явно отложил `known_issue_match_events`; Stage 150 переотложил; обе causal chains сводятся к этому этапу.

Ключевые call sites, где известно про match:

1. `agent_feedback_service.augment_tool_error:710-723` — middleware path. Каждый ToolError → `lookup_known_issue_for_error` → если match есть, playbook injected. Это самый частый path, и именно тут сейчас потеря: дедуп/cap могут срезать запись.
2. `agent_feedback_service.create_feedback_report:571` — explicit model report. Match всегда сохраняется через FK на `agent_feedback_reports.known_issue_id`, дополнительный event дублирует.
3. `agent_feedback_service.write_auto_feedback_event:656` — auto-event. После Stage 153 атомарно инкрементирует `report_count`, но сам save может быть пропущен дедупом — тогда event теряется.

## Scope

### S1. Новая таблица `known_issue_match_events`

Минимальная privacy-safe схема:

| column | type | nullable | purpose |
|--------|------|----------|---------|
| `id` | bigint PK | not null | autoincrement |
| `created_at` | timestamptz | not null, default now() | когда матч произошёл |
| `known_issue_id` | int FK→known_issues.id | not null | какой issue сматчен; FK CASCADE on delete |
| `related_tool` | varchar(128) | nullable | tool name, нормализован через `sanitize_text(value, limit=128)` (тот же helper, что в `agent_feedback_reports`) перед INSERT |
| `error_fingerprint_hash` | varchar(96) | nullable | HMAC-fingerprint, не raw error text |
| `account_id` | int FK→accounts.id | nullable | tenant context, nullable для anonymous-token путей |
| `bearer_token_id` | int FK→service_bearer_tokens.id | nullable | token context для tenant analytics |
| `source` | varchar(16) | not null | `injection` / `report` / `auto` (см. CHECK constraint) |

Индексы:
- `ix_known_issue_match_events_known_issue_created` (`known_issue_id`, `created_at`) — для аналитики «events per issue per time window».
- `ix_known_issue_match_events_account_created` (`account_id`, `created_at`) — для tenant-level "topN issues для аккаунта".

CHECK constraint: `source IN ('injection', 'report', 'auto')`.

**Что НЕ хранится по privacy contract** (Stage 150 lessons):
- raw error text / excerpt / details (даже redacted — есть редкий PII risk).
- raw stack trace.
- params_shape (per Stage 149 уже sanitized в reports, но events добавляют новый surface — лучше не дублировать).
- summary / suggested_fix / reproduce text.

Всё, что нужно operator-у для analytics, — это сам факт «issue X сматчен в момент T в контексте tenant Y через tool Z для fingerprint H».

### S2. Write path

Один helper `write_known_issue_match_event(session, *, known_issue_id, related_tool, error_fingerprint_hash, account_id, bearer_token_id, source)` в `agent_feedback_service.py`. Helper делает SINGLE `session.add(KnownIssueMatchEvent(...))` без commit — **commit-семантика контрактно принадлежит caller'у**. Docstring helper'а явно фиксирует это требование: `"""Caller MUST commit the session (or roll back) — this helper only stages the row."""`. `related_tool` нормализуется через `sanitize_text(tool_name, limit=128)` ВНУТРИ helper'а перед INSERT (consistent с существующим redaction в `agent_feedback_reports`). Helper non-throwing для нормальных входов; commit/timeout failures обрабатывает caller.

Session ownership — три call site, три разных pattern:

- **`augment_tool_error`** (line 710-734, hot path): открывает СОБСТВЕННУЮ session через `async with get_session_factory()()` исключительно для match event — НЕ переиспользует session из `lookup_known_issue_for_error` (она уже закрыта after return). Если `lookup` вернул match, открыть session, write event с `source="injection"`, commit. Wrap в `asyncio.wait_for(timeout=AUTO_EVENT_WRITE_TIMEOUT_SECONDS)` + `try/except` (best-effort, не блокирует ToolError flow). Source-of-truth для частоты «issue был injected в ToolError».
- **`create_feedback_report`** (line 571): использует УЖЕ ОТКРЫТУЮ outer session. После `find_known_issue_match` — `session.add(KnownIssueMatchEvent(...))` в том же `async with` блоке ПЕРЕД `session.commit()`. Атомарно с report insert: либо оба, либо ничего (что корректно — explicit report без event-а не имеет смысла; rollback rate-limit или validation ничего не оставит).
- **`write_auto_feedback_event`** (line 656-707): event `source="auto"` пишется в ОТДЕЛЬНОЙ committed sub-transaction ПЕРЕД dedup/cap query. Структура:
  ```
  async with get_session_factory()() as event_session:
      event_session.add(KnownIssueMatchEvent(...))   # source="auto"
      await event_session.commit()
  # Затем существующая session для report:
  async with get_session_factory()() as session:
      ... dedup query / cap check / report insert / report_count UPDATE ...
  ```
  Так match event persists даже если auto-report skipped дедупом или global cap (S2 invariant). Match event и auto-report логически независимы; только match event — source-of-truth для аналитики.

Все три integration point защищаются от exception propagation: best-effort write, ошибка → `RUNTIME_LOGGER.warning("known_issue_match_event_write_failed", exc_info=True)`, не пробрасывается. Для `create_feedback_report` это означает: исключение write event'а внутри outer session → rollback ВСЕЙ транзакции (включая report) — что приемлемо, потому что без event report теряет analytics value, и operator увидит exception для retry.

### S3. Retention

Subcommand в существующем `scripts/triage_agent_feedback.py`:
- `match-events-cleanup --days N` — удаляет `WHERE created_at < now() - N days`. Default 90 дней. Naming имитирует существующий `retention-cleanup` (`<scope>-cleanup` шаблон). Cutoff вычисляется в **UTC**: `cutoff = datetime.now(timezone.utc) - timedelta(days=N)` через существующий `_now()` helper в `triage_agent_feedback.py`. Boundary тест: row с `created_at = cutoff` НЕ удаляется (строгое `<`), row с `created_at = cutoff - 1ms` удаляется.
- Существующий `retention-cleanup` для reports не трогаем — он по другой таблице.

Размер: при 100 events/день и 90 дней retention — 9k rows ~1MB. При 10k/день — 900k rows ~100MB. PG справляется тривиально с обоими.

### S4. Operator analytics CLI

Subcommand в `scripts/triage_agent_feedback.py`:
- `match-events-stats --days N --top K` — выводит markdown table:
  ```
  | known_issue_id | title | source | events | distinct_accounts | distinct_tokens |
  ```
  GROUP BY (`known_issue_id`, `source`), ORDER BY `events DESC, known_issue_id ASC, source ASC` (deterministic tie-break, чтобы snapshot-тесты не флакали), LIMIT K. JOIN на `known_issues.title`. Окно — last N days, default 7. **Note**: `distinct_accounts` использует `COUNT(DISTINCT account_id)` который SQL-семантически skip'ает NULL — для anonymous-token paths (account_id=NULL) tenant footprint виден через `distinct_tokens` (`COUNT(DISTINCT bearer_token_id)`); operator интерпретирует обе колонки совместно. Если оба нулевые но `events>0` — путь полностью anonymous, footprint виден только по `events`. CLI `--help` явно документирует эту интерпретацию, чтобы operator не читал `distinct_accounts=0` как «нет anonymous-трафика».

### S5. Tests

В новом `tests/test_stage151_known_issue_match_events.py`:
- migration apply+rollback (alembic upgrade head → downgrade -1 → upgrade +1 round-trip).
- write_known_issue_match_event записывает event с правильными полями.
- write_known_issue_match_event никогда не сохраняет raw error text (assertion: row не содержит `details`/`error_excerpt` колонок by schema).
- `augment_tool_error` пишет `source="injection"` event при наличии match.
- `augment_tool_error` НЕ пишет event если match=None.
- `augment_tool_error` НЕ падает если write фейлит (write moked to raise).
- `write_auto_feedback_event` пишет `source="auto"` event ДАЖЕ если auto-report пропущен дедупом.
- `create_feedback_report` пишет `source="report"` event атомарно с saved report (rollback теста: оба или ничего).
- retention-cleanup удаляет старые events, оставляет свежие.
- match-events-stats выводит ожидаемые поля для seeded fixture.

## Out of Scope

- Изменения в `agent_feedback_reports` schema (Stage 153 закончил атомарным `report_count`; events — отдельный store).
- Аналитика на стороне UI (admin-page graphs) — events существуют только в DB, CLI-доступны.
- Deduplication match events по короткому окну (events specifically NOT deduplicated — это смысл существования отдельного store).
- Cross-account analytics dashboard — Prometheus-side, не в scope этого этапа.
- Автоматическая ротация match_rules_json в `known_issues` если event count = 0 (могут быть future stage).
- Storage encryption для events (содержимое не PII — id/tool/hash/account_id, шифрование избыточно).

## Acceptance Criteria

1. Alembic migration `20260502_000012_known_issue_match_events.py` (или следующий timestamp): `op.create_table("known_issue_match_events", ...)` с колонками S1, FK CASCADE на known_issues, FK SET NULL на accounts/service_bearer_tokens. Round-trip upgrade/downgrade green.
2. SQLAlchemy model `KnownIssueMatchEvent` в `storage_models.py` с CHECK constraint на source и двумя индексами из S1.
3. Helper `write_known_issue_match_event(session, ...)` в `agent_feedback_service.py` — single INSERT, idempotency не требуется (events намеренно non-dedup).
4. `augment_tool_error` пишет event при match (`source="injection"`); тест с моком `lookup_known_issue_for_error → KnownIssueMatch(...)` подтверждает наличие row после вызова.
5. `write_auto_feedback_event` пишет event ДО проверок дедупа/cap (даже при отказе от report insert) — assertion: при rapid-fire 5 одинаковых auto-events в 1 секунду создаётся 5 events, но 1 report (благодаря Stage 153 atomic + Stage 149 dedup).
6. `create_feedback_report` пишет event атомарно с report — assertion: row event есть iff report saved.
7. **Helper non-throwing для нормальных входов** — unit-тест helper'а с валидными аргументами не поднимает exception (sanitize/normalize безопасны). **Caller best-effort** — отдельный тест: `monkeypatch.setattr(session, "commit", AsyncMock(side_effect=DatabaseError))` подтверждает что `augment_tool_error` middleware path продолжает работу с warn-log "known_issue_match_event_write_failed". Эти два теста отдельны — helper и caller responsibilities разделены.
8. `triage_agent_feedback.py match-events-retention --days 1` удаляет события старше 1 дня.
9. `triage_agent_feedback.py match-events-stats --days 7 --top 10` выводит непустую таблицу по seeded fixture.
10. По схеме нет колонок для raw text (`summary`, `details`, `error_excerpt`, `params_shape_json`); тест-introspection через `KnownIssueMatchEvent.__table__.columns` проверяет whitelist полей.
11. Полный suite `docker compose --profile test run --rm test` — green.
12. Committed diff проходит ревью сторонней моделью или явный exhaust бюджета с rationale.

## Decomposition

- 151a PRD/review/simplicity gates. ≤2h.
- 151b Migration + model + storage_models tests (round-trip). ≤2h, ~80 LOC migration + ~30 LOC model + ~50 LOC test.
- 151c write_known_issue_match_event helper + 3 integration points + tests. ≤2h, ~30 LOC helper + ~15 LOC × 3 sites + ~150 LOC tests.
- 151d retention CLI + analytics CLI + tests. ≤1.5h, ~40 LOC retention + ~50 LOC stats + ~80 LOC tests.
- 151e full suite + audit + commit. ≤1h.
- 151f code/diff review (Sonnet + Codex 1/1 budget) + push + AssumptionLog + self-attestation. ≤1h.

Итого ≤9.5 LOC-часов, ~600 LOC прод/тест-кода.

## Risks

- **High-volume on busy account**: при 10k tool errors / день матч пишет 10k events × 90d = 900k rows. PG справляется, но индексы растут. Mitigation: retention default 90д даёт ceiling; operator может уменьшить.
- **Atomicity со Stage 153 UPDATE — split per call site**:
  - `create_feedback_report`: match event пишется в ТОЙ ЖЕ session что и report+`KnownIssue.report_count` UPDATE. Rollback (исключение в любом из шагов) откатывает все три consistently. Acceptable: explicit report без match event теряет analytics value, лучше fail и retry.
  - `write_auto_feedback_event`: match event пишется в **ОТДЕЛЬНОЙ committed sub-transaction ПЕРЕД** dedup query. Если auto-report skipped по `existing != 0` (line 672) или `_auto_event_global_allowed=False` (line 674) — event уже committed, persists. Это invariant S2.
  - `augment_tool_error`: match event использует свою отдельную session, isolated from any outer flow. Best-effort.
- **Privacy regression risk**: если в будущем кто-то добавит `error_excerpt` в schema под предлогом «for triage» — это обходит весь Stage 150 redaction effort. Mitigation: тест #10 фиксирует schema whitelist.
- **augment_tool_error latency**: добавление write event на hot path. Mitigation: `asyncio.wait_for(..., timeout=AUTO_EVENT_WRITE_TIMEOUT_SECONDS=0.5s)` + best-effort try/except. Tool error всё равно ВСЕГДА вернётся клиенту, даже если event write завис.
- **Cascade DELETE on known_issues — audit trade-off**: если operator делает `DELETE FROM known_issues WHERE id=X` (manual psql или future CLI), все связанные events для X пропадают безвозвратно. Это **намеренный** trade-off:
  - Альтернатива (`ON DELETE RESTRICT`) запретила бы DELETE при наличии events — operator должен был бы сначала вычистить events, что превращает каждое seed-исправление (создал issue, опечатался, хочу удалить) в multi-step ритуал.
  - С CASCADE: match history становится **non-auditable** для удалённых issues. Если operator хочет сохранить evidence «issue X срабатывал в день Y», обязан использовать **soft-delete** — менять `status='fixed'` или `status='wontfix'` (оба уже в `KNOWN_ISSUE_STATUSES`), а не DELETE.
  - Operator runbook (S4 CLI help): «не используй `DELETE FROM known_issues` — используй `triage_agent_feedback.py mark <id> wontfix` для retire issue с сохранением events».
- **Match event vs report_count divergence (intentional)**: после Stage 153 `known_issues.report_count` инкрементируется атомарным UPDATE для каждого saved auto/model report. После Stage 151 match_events пишется ВСЕГДА при match, включая случаи дедупа auto-event. Result: `count(match_events WHERE known_issue_id=X) >= report_count`. Это **не corruption** — два метрики измеряют разное:
  - `report_count` — «сколько раз был сохранён persistent report attached to issue» (narrower, для operator-facing «issue popularity»).
  - `match_events` — source-of-truth для частоты матчинга (broader, для analytics «как часто injection реально срабатывает»).
  - Также: orphan event возможен если `write_auto_feedback_event` event-sub-transaction commit'нулась, а report sub-transaction упала по DB error (не по dedup). Это редкий случай, не corruption — event просто фиксирует факт матча.

## Rationale для выбранной сложности

**Альтернатива 1: только Prometheus counter** (`vetmanager_known_issue_match_total{known_issue_id, source}`). Pros: ноль schema overhead, существующий `service_metrics.py` infra, лёгкое масштабирование. **Cons (отвергнуто)**:
- Текущий prod не имеет долгосрочного Prometheus scrape stack — counter теряется на restart. (`product_metrics_report.py` показывает, что счётчики читаются ad-hoc через `/metrics` без time-series storage.)
- High-cardinality labels (`known_issue_id` × `account_id`) ломают Prometheus на любом не-тривиальном объёме issues.
- Нет audit trail для compliance (нельзя доказать «такой-то tenant столкнулся с такой-то issue в такой-то день» через счётчик).

**Альтернатива 2: новый `source="injection_only"` enum в `agent_feedback_reports`**. Pros: ноль новых таблиц, существующая retention/triage CLI работает. **Cons (отвергнуто)**:
- Размывание семантики: `agent_feedback_reports` сейчас «human/agent-curated bug reports». Добавление injection-only записей делает таблицу dual-purpose, и существующие фильтры (`status IN ('new', 'triaged', ...)`) перестают давать meaningful counts.
- `agent_feedback_reports.summary` / `details` are NOT NULL — придётся либо stub-strings («[injection]»), либо migration на nullable. И то и другое — workaround вместо clean store.
- Размер: `agent_feedback_reports` уже содержит много полей (15+). Каждый row — overhead. Match events нужны компактные.

**Альтернатива 3: structured log only** (без persistent DB). Pros: ноль schema. **Cons (отвергнуто)**:
- `docker compose logs` ротируются (default 100MB), longer-term retention требует отдельной log aggregation infra (loki/elastic) — её сейчас нет в проекте.
- SQL queries «top 10 issues для account=X за месяц» — невозможны через grep на JSON-lines logs.
- Audit-ready proof невозможен.

**Выбранный путь — отдельная узкая таблица** даёт:
- Чёткое separation of concerns (reports = curated; events = raw match log).
- SQL-аналитика out of the box (operator уже знает psql).
- Persistent compliance trail.
- Privacy-safe by schema design (whitelist полей в test #10).
- Минимальный footprint: 7 колонок vs 22 в `agent_feedback_reports`.

Cost: одна migration + ~30 LOC model + ~80 LOC integration. ROI: даёт persistent visibility в самый частый path (injection middleware), который сегодня invisible.

### Simplicity-eval pass (§4.1) применён, без изменений PRD

Триггеры проверены:

- **Abstraction без 2+ call-sites**: `write_known_issue_match_event` имеет 3 call sites (augment_tool_error, create_feedback_report, write_auto_feedback_event). Helper justified.
- **Premature flexibility**: source enum 3 значения (injection/report/auto) — minimal viable; 4-е значение (например `replay`) добавит лёгкая migration, не предвыбираем.
- **Indirection > 2 hops**: helper → session.add → ORM → SQL — стандартный SQLAlchemy pattern, не дополнительный indirection.
- **Dual-API surface**: `match_events` vs `report_count` — это **deliberate separation of concerns** (broader matches log vs narrower saved-reports counter), не dual-API workaround. Документировано в Risks.
- **Sync mechanisms paired**: session ownership split (3 разных pattern на 3 sites) — не «paired sync», а явная семантика per-site (atomic vs separate sub-transaction vs isolated).
- **Helper вызывается из 1 места**: 3 call sites, не 1. ОК.
- **Schema simplification check**: 7 колонок все используются (id/timestamp для retention, known_issue_id для FK+аналитики, related_tool/fingerprint для группировки, account_id+bearer_token_id для tenant analytics, source для разделения путей). Удаление любой ломает заявленный analytics use case.
- **Index simplification check**: 2 индекса покрывают 2 разных query pattern (by issue × by account); один не покрыл бы оба. Stays.

Альтернативы (Prometheus counter / `source="injection_only"` enum / structured log only) уже подробно разобраны выше. Дальнейшее упрощение PRD сделает scope недостаточным для заявленных acceptance criteria.

PRD финализирован — переходим к коду.
