# Этап 153. Review-followup hardening (Kimi 2026-04-30)

## Цель

Закрыть compact-этапом 6 адекватных high/medium findings из super-review `artifacts/review/2026-04-30-changed-stage-150-152.md` (Kimi orchestrator), которые не покрываются отдельными этапами (151, 154-158) и которые можно сделать одним hardening pass без архитектурных изменений.

Архитектурные findings (F6-F12: god-modules, layering, embedded HTML) и расширенные test-coverage gaps — намеренно вне scope этого этапа; для них при необходимости заведём отдельные стадии.

## Контекст

Stage 150-152 закрыли privacy guardrails и pepper transport. Свежий super-review выявил остаточные defects, которые группируются в две темы (см. systemic observation в отчёте):

1. **Missing timeouts на I/O boundaries** (F15 readiness, F23 deploy step).
2. **Отсутствие concurrency control на shared mutable state** (F4/F5 ORM read-modify-write).

Плюс три точечных bug:

3. **F1**: `scripts/deploy_server.sh:124-128` использует `eval "$(grep ... .env)"` для обратного source POSTGRES_USER/POSTGRES_DB. Если `.env` содержит shell-метасимволы или command substitution — RCE на prod-сервере.
4. **F13**: `agent_feedback_service.match_rules:404-409` для `contains_any`/`contains_all` приводит `actual` к `str()`. Когда `actual` — set (`params_shape` field), `str(set)` даёт repr `"{'foo'}"`, и `"foo" in "{'foo'}"` даёт false-positive на set с подстрокой.
5. **F14**: `agent_feedback_service.build_error_fingerprint_hash:271-276` использует `any([http_status, error_code, normalized_text, params_shape])`. `http_status=0` (connection reset) falsy → возвращается `None` → инцидент не дедуплицируется и не матчится против known issues.

## Scope

### F1 — `scripts/{deploy_server,backup_daily_cron,rollback_db}.sh` без `eval` для `.env`

**Audit-extended scope (2026-05-02)**: тот же `eval "$(grep ... .env)"` обнаружен также в `scripts/backup_daily_cron.sh:20` и `scripts/rollback_db.sh:20` — copy-paste из ранней версии deploy_server. Все три скрипта чинятся одной заменой; F1 расширен на whole class of vulnerabilities этого паттерна.

**Simplicity-eval (§4.1) показал**: текущий `eval` сорсит ВСЕ переменные из `.env`, но фактически в bash-контексте после source используются только `POSTGRES_USER` и `POSTGRES_DB` (см. line 141 `pg_dump`, line 161 `pg_isready`). Остальные значения (`LOG_LEVEL`, `METRICS_AUTH_TOKEN`, `FEEDBACK_FINGERPRINT_PEPPER`, `SITE_BASE_URL`, и т.д.) читаются ВНУТРИ контейнеров через docker compose env — outer bash их не использует. Ergo не нужен общий парсер `.env` — нужно прочитать ровно 2 ключа.

- Заменить `eval "$(grep -v ... .env)"` (lines 124-128) на whitelist-extract двух конкретных ключей:
  ```bash
  if [ -f .env ]; then
    PG_USER_LINE="$(grep -E '^POSTGRES_USER=' .env | head -1 | cut -d= -f2-)"
    PG_DB_LINE="$(grep -E '^POSTGRES_DB=' .env | head -1 | cut -d= -f2-)"
    [ -n "${PG_USER_LINE}" ] && POSTGRES_USER="${PG_USER_LINE%\"}" && POSTGRES_USER="${POSTGRES_USER#\"}"
    [ -n "${PG_DB_LINE}" ] && POSTGRES_DB="${PG_DB_LINE%\"}" && POSTGRES_DB="${POSTGRES_DB#\"}"
  fi
  ```
  Strip парных двойных кавычек (если есть) — на случай `POSTGRES_USER="vetmanager"` записи. Single quotes в `.env` для этих ключей в текущем prod не используются (см. шаблон `.env.example`); если кому-то понадобится — extend trivially.
- Преимущества vs предыдущий вариант general-purpose парсера:
  - **whitelist > blacklist**: только known-needed keys, новые ключи в `.env` не источиваются автоматически (более безопасное поведение by default).
  - **~6 LOC vs ~70 LOC**: нет нужды поддерживать комментарии, BOM, CRLF, escape-sequences, multiline values, KEY regex validation — потому что мы не парсим `.env` целиком.
  - **No eval, no shell-evaluation of `.env` contents**: даже если кто-то запишет в `.env` `MALICIOUS=$(rm -rf /)`, оно не выполнится — `cut -d= -f2-` работает с literal text.
- Если в будущем понадобится sourcing нового ключа — добавить ещё один `grep -E '^NEW_KEY=' ... | cut ...` блок (3 LOC). Это explicit > implicit.
- Регрессия для добавляющих новый key flow задокументирована: README или AssumptionLog запись про whitelist-pattern.

### F4/F5 — atomic `report_count` increment

- В `agent_feedback_service.create_feedback_report` (line ~548-554):
  - Удалить `known_issue_row = await session.get(KnownIssue, known_issue.id)` и блок мутаций `known_issue_row.report_count += 1; first_seen_at = ... ; last_seen_at = now`.
  - Заменить на `await session.execute(update(KnownIssue).where(KnownIssue.id == known_issue.id).values(report_count=KnownIssue.report_count + 1, first_seen_at=func.coalesce(KnownIssue.first_seen_at, now), last_seen_at=now))`.
  - Response не пострадает: `known_issue.as_response()` возвращается из dataclass `KnownIssueMatch` (line 124-136), не из ORM-instance — поэтому stale-managed-instance проблема исключена by design.
- В `agent_feedback_service.write_auto_feedback_event` (line ~648-650):
  - Заменить `known_issue.report_count += 1; first_seen_at = ... ; last_seen_at = now` на `session.execute(update(...))` с теми же values, используя `known_issue.id`.
  - `find_known_issue_for_auto_event` остаётся возвращать `KnownIssue` (ORM), потому что нужен `known_issue.id` для FK на новом `AgentFeedbackReport(known_issue_id=known_issue.id)`. Сам ORM-instance больше не мутируется.
- Эта правка устраняет lost-update под параллельными feedback reports/auto-events на одном `known_issue_id` без необходимости `with_for_update` row-level lock (атомарный UPDATE на single row сериализуется PostgreSQL'ом сам).

### F13 — collection-aware `contains_any`/`contains_all`

- В `agent_feedback_service.match_rules` для ops `contains_any`/`contains_all`:
  - Если `actual` — **iterable collection** (`set`/`frozenset`/`list`/`tuple`, в том числе `dict_keys`/`dict_values`), но НЕ `str`/`bytes`/`dict` → проверять membership напрямую: `any(item in actual for item in expected)` / `all(item in actual for item in expected)`.
  - Если `actual` — строка (`str`) → текущая `str(item) in actual` логика остаётся (legacy semantics для текстовых полей).
  - Если `actual` — `dict` → False для `contains_any`/`contains_all` (semantics dict-keys vs dict-values неоднозначны; явно скажем «не поддерживается»). Текущий код этот случай не имеет, но защитимся on-purpose.
  - Если `actual` — `None` → False для `contains_any`, True для `contains_all` с пустым `expected` (текущее поведение `not all(...)` сохраняется).
- Discriminator: `isinstance(actual, (set, frozenset, list, tuple))` для collection-path. `isinstance(actual, str)` — для legacy text-path. Остальные типы (dict, None, числа) — False/skip.
- Это убирает false-positive когда `params_shape={"foobar"}` и rule `contains_any: ["foo"]` — сейчас матчится через `"foo" in "{'foobar'}"`, должно быть `False`.

### F14 — explicit `is not None` в `build_error_fingerprint_hash`

- Заменить `any([incident.http_status, incident.error_code, normalized_text, incident.params_shape])` на `incident.http_status is not None or incident.error_code or normalized_text or incident.params_shape`.
- `http_status=0` теперь даст fingerprint вместо `None`. Остальные поля сохраняют truthy-проверку (пустая строка / пустой set значит «нет данных», что корректно).
- Type contract: `FeedbackIncident.http_status: int | None` (line 111 service file) и boundary `create_feedback_report` принимает `int | None` — string `"0"` исключён by typing. Дополнительная нормализация не нужна.

### F15 — `/readyz` timeout

- В `web_routes_system.readiness_check` обернуть `await check_storage_readiness()` в `asyncio.wait_for(..., timeout=3.0)`. На `asyncio.TimeoutError` — вернуть 503 с `status="degraded"`, `checks.storage.status="failed"`, `checks.storage.reason="storage_check_timeout"` (соответствует существующему контракту 503-response из `test_readyz_returns_503_when_storage_is_unavailable`).
- Catch ТОЛЬКО `asyncio.TimeoutError`. `asyncio.CancelledError` (parent task cancellation на shutdown / client disconnect) должен пробрасываться неизменённым — не превращать в 503.
- Timeout 3s — достаточно: типичный `SELECT 1` < 50ms; всё, что > 1s — уже degraded; 3s оставляет запас на холодный pool, но не позволяет повиснуть навсегда.

### F23 — `deploy-prod.yml` step timeout

- В `.github/workflows/deploy-prod.yml` для шага запуска `deploy_server.sh` (lines 80-93 в момент ревью) добавить `timeout-minutes: 10`. Текущий deploy на здоровом хосте укладывается в 3-5 минут; 10 — щедрый верхний предел, после которого step должен быть прерван и пересобран, а не висеть до 6-часового workflow limit.

## Out of Scope

- F6, F7 — `storage_models.py` бизнес-логика и upper-layer imports (архитектурный refactor; отдельный этап если возьмёмся).
- F8 — `host_resolver.py` дублирует `pool.py` pattern (extract shared per-loop client factory; архитектурный, отдельно).
- F9 — `agent_feedback_service.py` god-module split (большой refactor).
- F10 — feedback service ↔ tool_access_registry coupling.
- F11 — `MARKETED_PRESET_TOOLS` дедупликация.
- F12 — landing_page.py 2k LOC HTML extraction в template файл.
- Все medium findings, не входящие в 6 выбранных (host_resolver hardening, ServiceBearerToken IP mask default, docker healthcheck, pg_dump/alembic timeouts) — покрываются отдельными этапами 155, 156 либо остаются для будущего sweep.
- F2 — `vm_transport/pool.py` cross-loop lock (dismissed как спекулятивный, см. inadequate-findings-index.md запись 2026-04-30).
- Расширенное test coverage за пределами regression-тестов на 6 фиксов (отдельный этап если возьмёмся).
- Изменение схемы БД, миграции (не требуются для этих фиксов).

## Acceptance Criteria

1. `scripts/deploy_server.sh` не содержит `eval` для парсинга `.env`. Static check в новом тесте подтверждает.
2. Whitelist-extract двух ключей из `.env` работает: тест прогоняет deploy-script-fragment с fixture `.env` содержащим `POSTGRES_USER=vetuser`, `POSTGRES_DB="vetdb"`, `MALICIOUS=$(rm -rf /)`, `OTHER_KEY=ignored`. Ассертит: (a) `POSTGRES_USER` извлечён как `vetuser`; (b) `POSTGRES_DB` извлечён как `vetdb` (кавычки strip'нуты); (c) `MALICIOUS` substitution НЕ выполнен, переменная не создана в bash env; (d) `OTHER_KEY` не sourced (whitelist behavior); (e) `eval` отсутствует в `deploy_server.sh` (static grep check).
3. `agent_feedback_service.create_feedback_report` и `write_auto_feedback_event` используют SQL `UPDATE ... SET report_count = report_count + 1, ...` через `session.execute(update(...))`. SQL-shape тест на SQLite (фикстура in-memory): подтверждает, что после `create_feedback_report` row в `known_issues` имеет `report_count` инкрементированным на 1 и `last_seen_at` обновлённым (без concurrency). Concurrency тест (двумя параллельными tasks через `asyncio.gather` + 2 sessions, итог +2) — **PostgreSQL-only через pytest marker `@pytest.mark.postgres_only`** и `pytestmark = pytest.mark.skipif(...)` или fixture-level skip; SQLite WAL даёт нерепрезентативную сериализацию, тест не должен flaky под SQLite. Поведение при `rowcount=0` (known_issue удалён concurrent транзакцией): silently no-op в UPDATE — это безопасно, потому что FK constraint на `agent_feedback_reports.known_issue_id` всё равно поднимет `IntegrityError` при попытке вставить report; rollback транзакции отдаст ошибку наверх. Дополнительно проверять rowcount в коде не требуется.
4. `match_rules` с `contains_any: ["foo"]` и `params_shape={"foobar"}` возвращает `False`. Тест с `params_shape={"foo", "bar"}` и `contains_any: ["foo"]` возвращает `True`. Дополнительные тесты: tuple/frozenset работают так же как set; dict как actual возвращает False для contains_any/all (по convention); str-актуал сохраняет legacy substring-логику (regression test).
5. `build_error_fingerprint_hash(FeedbackIncident(http_status=0))` возвращает не-None hash. `build_error_fingerprint_hash(FeedbackIncident())` (всё None/пустое) — возвращает `None` (поведение для пустого инцидента сохранено).
6. `/readyz` под мокнутым `check_storage_readiness` (зависает на 5s) возвращает 503 с `reason="storage_check_timeout"` за <4s. Отдельный тест: `CancelledError`, поднятый внутри `check_storage_readiness`, пробрасывается из handler'а наверх (не превращается в 503/200) — moc-stub raises `asyncio.CancelledError`, тест ждёт `pytest.raises(asyncio.CancelledError)` через TestClient/httpx ASGI с `cancellation_propagates=True`-style проверкой (либо просто unit-test handler'а напрямую с awaited mock).
7. `.github/workflows/deploy-prod.yml` deploy step содержит `timeout-minutes: 10`. YAML-парс тест подтверждает.
8. Полный suite `docker compose --profile test run --rm test` зелёный.
9. Targeted regression tests из задачи 153.8 зелёные.
10. Committed diff проходит ревью сторонней моделью (Codex gpt-5.5, бюджет 2) или явно exhausted с rationale.

## Decomposition

- 153a PRD/review/simplicity gates. ≤2h. Эта секция, плюс review subagents.
- 153b F1 deploy_server.sh whitelist-extract POSTGRES_USER/DB + tests. ≤1h, ~6 LOC bash + ~50 LOC pytest fixture.
- 153c F4/F5 atomic report_count + tests. ≤2h, ~30 LOC service + ~60 LOC concurrency test.
- 153d F13 + F14 agent_feedback_service логика + tests. ≤1h, ~15 LOC fix + ~40 LOC tests.
- 153e F15 /readyz timeout + tests. ≤1h, ~10 LOC + ~30 LOC test.
- 153f F23 GitHub Actions timeout + test. ≤30min, 1 LOC YAML + ~15 LOC YAML-parse test.
- 153g full suite + audit + commit. ≤1h.
- 153h external diff review + push + AssumptionLog + self-attestation. ≤1h.

Всего ≤8 LOC-часов, ~200 LOC прод/тест-кода.

## Risks

- F4/F5 atomic UPDATE: подтверждено, что `KnownIssueMatch.as_response()` отдаёт snapshot из dataclass, а не stale-ORM поля → риск отсутствует. Удаляемый `session.get(KnownIssue, known_issue.id)` в `create_feedback_report` сейчас не нужен ни для чего, кроме мутации, поэтому удаляется целиком.
- F1 whitelist-extract: если другая часть `deploy_server.sh` или sub-script (`scripts/post_deploy_smoke_checks.sh`) тихо полагается на sourced `.env` var (например `LOG_LEVEL` для последующего bash-выражения) — она перестанет работать. Mitigation: grep по `deploy_server.sh` и связанным под-скриптам на `\$\{?(LOG_LEVEL|METRICS_AUTH_TOKEN|FEEDBACK_FINGERPRINT_PEPPER|SITE_BASE_URL|MCP_PATH|VM_HTTP_)` после изменения; если найдём usage в outer bash — добавить ещё один grep+cut блок для этого ключа. Подтверждено: текущий `deploy_server.sh` использует только `${POSTGRES_USER}` и `${POSTGRES_DB}` в outer bash; `${FEEDBACK_FINGERPRINT_PEPPER}` упоминается только внутри single-quoted command для `compose exec` (line 208), которое expand'ится уже внутри контейнера, не в outer bash.
- F15 timeout=3.0: smoke-check (`scripts/post_deploy_smoke_checks.sh`) требует `status==200` от `/readyz` через `ready_is_ok`. Если deploy происходит на холодный pool и `check_storage_readiness` legitimately занимает >3s — smoke check провалится → deploy step упадёт. Это правильное поведение (медленный storage = degraded service нельзя пускать в prod), но требует, чтобы retry внутри `retry_request` (текущий smoke-script делает 3 попытки) дал warm pool время прогреться. Если в practice 3s окажется слишком жёстким — поднять до 5s, не выше.

## Rationale для выбранной сложности

Все 6 фиксов — точечные, < 50 LOC каждый, не вводят новых абстракций. Совмещение в один этап вместо 6 отдельных этапов оправдано:

- common context (один super-review артефакт);
- общий review/test/deploy gate;
- ни один из 6 не зависит от другого, можно валидировать по отдельности;
- альтернатива (6 stages по 30-90 минут) даст 6× cycle overhead PRD/review/commit/push без content benefit.

Тривиальная альтернатива «делать каждый из 6 в смежных этапах когда руки касаются файла» отвергнута: F1 (deploy RCE) — security-relevant, не должен ждать случайной правки `deploy_server.sh`.

### Simplicity-eval pass (§4.1) применён к F1

Изначальный draft предлагал общий «безопасный bash-парсер `.env`» с поддержкой кавычек, BOM, CRLF, comments, KEY-validation regex (~70 LOC). Simplicity-trigger «abstraction без 2+ call-sites» + «premature flexibility» + «helper вызывается из 1 места» сошлись: парсер был бы для одного call-site и поддерживал бы возможности, реально не нужные текущему коду.

Замена: whitelist-extract двух конкретных ключей (POSTGRES_USER, POSTGRES_DB) через `grep | cut` (~6 LOC). Покрывает все acceptance criteria по F1, более безопасное поведение by default (whitelist > blacklist), снижает test fixture сложность (нет квотинг-тестов), удаляет 11× LOC. Trade-off: при добавлении нового sourced-ключа нужно добавить 1 строку — это explicit > implicit и предпочтительнее «парсера который автоматически source'ит всё, что выглядит как `KEY=VALUE`».

Остальные 5 фиксов (F4/F5, F13, F14, F15, F23) simplicity-eval прошли без изменений: каждый — minimum-viable изменение текущего поведения, не вводит абстракций, не имеет dual-API surface.
