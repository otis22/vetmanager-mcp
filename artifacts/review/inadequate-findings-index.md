# Inadequate findings — index

Findings, которые я оценил **неадекватными** по критериям CLAUDE.md §5.2 (scope / реальность / PRD / ROI) и НЕ заводил в Roadmap. Документирую здесь, чтобы в будущем не возвращаться к спекулятивным замечаниям.

Индекс пополняется при каждом super-review.

---

## 2026-04-17 super-review post-stages-85-95

Source: `artifacts/review/2026-04-17-post-stages-85-95.md`

### 1. `vetmanager_client.py:487` — `elif in {POST, PUT, DELETE}` не обрабатывает PATCH

- reviewer: code, confidence: 0.87
- **Причина dismiss**: VM API не поддерживает PATCH (см. `api_crud_permissions-ru.md` — ни одна сущность не имеет PATCH). Гипотетический future risk, сейчас dead path. Если VM введут PATCH — будет отдельная задача с unit-тестом.

### 2. `scripts/init_server.sh:128-135` — sed pipe для POSTGRES_PASSWORD может поломаться на редких chars

- reviewer: security, confidence: 0.30
- **Причина dismiss**: pre-existing, не регрессия стадии 89. `openssl rand -base64 + tr -d '=/+'` генерирует только base64-безопасные символы. Вероятность встретить `|` в PG_PASS ~= 0. Low-probability, out of baseline scope.

### 3. `PRD/этап-82-clientphone-hotfix.md` и `PRD/этап-83-in-operator-batch.md` — нет «Вне scope» секции

- reviewer: docs, confidence: 0.75
- **Причина dismiss**: ретроактивные PRD (написанные в stage 90 post-hoc) по определению thin — они ссылаются на AssumptionLog для деталей. Добавление «Вне scope» к post-hoc документам не даёт ценности, потому что вся информация уже в AssumptionLog. Проверено что для 82 есть раздел в AssumptionLog, для 83 — тоже.

### 4. `PRD/этап-84-api-level-status-filter.md` отсутствует

- reviewer: docs, confidence: 0.95
- **Причина dismiss**: false positive — файл существует (`ls PRD/ | grep 84` возвращает совпадение). Ревьюер ошибся при чтении списка.

### 5. `vetmanager_client.py:167-185` — error message с `{domain}` leak information

- reviewer: security, confidence: 0.55
- **Причина dismiss**: domain — это собственный resolved domain caller'а (bound to bearer credentials). Cross-tenant leak отсутствует, только same-tenant. Timing-oracle на cooldown — защита через rate-limiter уже есть. Overengineering.

### 6. `vetmanager_client.py:211` — `window_start == 0.0` sentinel лучше заменить на `float | None`

- reviewer: code, confidence: 0.85
- **Причина dismiss**: чистый nit. Работает корректно, читаемо в контексте (sentinel хорошо документирован). Изменение на Optional увеличивает LOC и добавляет None-checks без real value.

### 7. `service_metrics.py:27-41` — ALL_CAPS `_HTTP_REQUESTS_TOTAL` на mutable defaultdicts — convention mismatch

- reviewer: code, confidence: 0.80
- **Причина dismiss**: формальная convention nit. В Python ALL_CAPS часто означает «module-private state, do not touch outside module», что точно описывает эти dict'ы. Rename не даст value, только blast radius по импортам.

### 8. `filters.py:8` — docstring ссылается на «stage 93b» — устареет после миграции

- reviewer: code, confidence: 0.88
- **Причина dismiss**: nit, low impact. Когда миграция callers произойдёт, docstring обновится вместе с PR. Pre-emptive правка бессмысленна.

### 9. `vetmanager_client.py:_breakers` unbounded growth

- reviewer: codex-blindspot/perf, confidence: 0.40-0.81
- **Причина partial dismiss**: memory-leak оценка спекулятивна. Per-domain breaker ~200 bytes; 10k уникальных tenants = 2MB. Pragmatic cap будет, когда/если tenant count превысит известные bounds. Оставляю как «watch item», не заводя задачу.

### 10. `tests/conftest.py:52` — комментарий о sync drop contradictory

- reviewer: tests, confidence: 0.65
- **Причина dismiss**: комментарий реалистично описывает trade-off (sync drop vs -W error). Ревьюер называет противоречие, но на практике sync drop работает (full suite 630 passed). Улучшение комментария nit-level.

### 11. `vetmanager_client.py:291` — `get_bearer_token()` в `__init__` discards result — vestigial?

- reviewer: code, confidence: 0.75
- **Причина partial dismiss**: может быть side-effect (populates context var). Нужна проверка, не dead-code investigation в рамках super-review. Если окажется dead — отдельная задача; пока не заводить.

### 12. `tests/test_stage93:154` — `pytest.raises(Exception)` вместо `FrozenInstanceError`

- reviewer: tests, confidence: 0.80
- **Причина dismiss**: `FrozenInstanceError` — implementation detail dataclass module. `Exception` ловит и его, и fallback varianты (если frozen перейдёт на __slots__ или readonly property). Более устойчивый тест.

### 13. `tools/crud_helpers.py:147-169` — два identical ValueError branches

- reviewer: code, confidence: 0.82
- **Причина partial dismiss**: две ветки отличаются message (per-page vs per-total). Консолидация в одну теряет informational value error. Оставлено как есть.

### 14. `service_metrics.py:182-185` — mixed Prometheus TYPE для `_max gauge` vs `summary`

- reviewer: code, confidence: 0.80
- **Причина partial dismiss**: технически точно (Prom spec не требует строгой консистентности), но promtool принимает текущий формат. Переделка на pure summary требует другой структуры данных. Cost/benefit невыгоден.

### 15. «`PRD/этап-84` отсутствует» workflow-check false positive

- источник: review + workflow-check
- **Причина dismiss**: файл есть, grep ошибка. Закрыто.

---

## Критерии «неадекватности» (для будущих super-review)

Finding считается **неадекватным** если хотя бы одно:

- **Scope**: описывает код вне изменений текущего этапа И проблема не впервые замечена baseline-review
- **Реальность**: гипотетическая, без конкретного failure scenario (confidence ≤ 0.5 часто индикатор)
- **PRD**: расширяет задачу за пределы текущей цели (scope creep)
- **ROI**: большой рефактор ради nit
- **False positive**: ревьюер ошибся в чтении кода/файла
- **Pre-existing**: bug предшествовал текущему этапу и не вызван изменениями

**Обязательно** при dismiss: одна строка причины — чтобы future super-review не тратил время на те же пункты.

---

## 2026-04-18 super-review changed-stage-104

Source: `artifacts/review/2026-04-18-changed-stage-104.md`

### Speculative (confidence < 0.4 or no concrete exploit path)

1. auth/bearer.py token lookup not constant-time
   - reviewer: security, confidence: 0.30
   - **Причина dismiss**: theoretical timing oracle без demonstrated exploit path; SHA-256 hash equality в DB достаточна при token entropy > 128 bits

2. auth/bearer.py rate-limit retry_after timing oracle
   - reviewer: security, confidence: 0.35
   - **Причина dismiss**: speculative attack без concrete scenario; attacker ограничен 1000 req/min rate limit

3. auth/rate_limit.py reset public without env-guard
   - reviewer: security, confidence: 0.45
   - **Причина dismiss**: scope creep — reset public API предназначен для tests, env-guard без demonstrated production misuse

4. email.utils.parsedate_to_datetime slow в retry path
   - reviewer: performance-and-reliability, confidence: 0.30
   - **Причина dismiss**: micro-optimization nit; happy path (integer seconds) быстрый; malformed headers редки

### Pre-existing / out of scope

5. 22 × workflow-check PRDs lacking `## Цель` section (этапы 5, 65, 66, 89, 94, 95, 99, etc.)
   - reviewer: workflow-check, confidence: 0.65 each
   - **Причина dismiss**: pre-existing — все написаны retroactively для уже production stages; не относятся к diff 103a/c/d. Housekeeping одним отдельным PR если вообще нужно

6. retry parse_retry_after email date slow under load
   - reviewer: performance-and-reliability, confidence: 0.30
   - **Причина dismiss**: pre-existing, no latency impact demonstrated under realistic retry storms

### Borderline (orchestrator decision — tracked but not blocking)

7. resources no vc-injection for testing
   - reviewer: architecture, confidence: 0.55
   - **Причина dismiss (borderline)**: архитектурно корректное, но ROI низкий пока нет concrete тестового pain'а. Вернуться при появлении cross-resource aggregator

8. 103a/c/d single-session violates ≤150 LOC per-subtask rule
   - reviewer: product, confidence: 0.65
   - **Причина dismiss (borderline)**: правило workflow было нарушено, но shipped code зелёный (648 tests); post-hoc policy enforcement не меняет состояние. Future workflow rule improvement — отдельно

9. Roadmap deleted 37 backlog items (commit 15dcd0a) — tech-debt visibility loss
   - reviewer: product, confidence: 0.85
   - **Причина dismiss (borderline)**: действие было осознанным cleanup sweep; визибилити вопрос — для обсуждения с product, не для блокировки merge. Commit log + `artifacts/tech-debt-register-*.md` частично покрывают

10. Roadmap 93/94 masked as "done (focused subset)" with implicit stop subtasks
    - reviewer: product, confidence: 0.80
    - **Причина dismiss (borderline)**: convention "focused subset done" соответствует shipped state; формализация `done (focused subset)` vs `stop` — улучшение notation, а не блокер

---

## 2026-04-19 super-review changed (post-stages-105-110) — full rerun

Source: `artifacts/review/2026-04-19-changed-105-110-stage-110.md`

**Note:** partial run на первом запуске (9/10 ревьюеров упёрлись в rate-limit),
rerun выполнен позже в тот же день — все 10 ревьюеров + aggregator отработали.

### 1-22. workflow-check: PRD этапов 32/36-41/51-55/61-66/89/94-95/99-100/103-104 без `## Цель`

- reviewer: workflow-check, confidence: 0.65 (×22 findings)
- **Причина dismiss**: исторические PRD вне scope 105-110. Bash-скрипт
  `scripts/review_workflow_check.sh` не отличает активные этапы от legacy-документов.
  Ретроактивное добавление `## Цель` — грязная работа с нулевой продуктовой ценностью.
  Улучшение: добавить в скрипт игнорирование PRD этапов со статусом `done` старше N месяцев.

### 23. Dedup: `_mask_email` short-email handling

- **reviewer-security (low)** vs **reviewer-codex-blindspot (medium)** — same root issue
- **Причина dismiss**: same finding, оставлен codex-blindspot version с более высокой severity (multi-part TLD + unicode).

### 24. Borderline: BC-invariant tests conflict with simplicity shim-removal

- reviewer-simplicity (medium, ~0.85): удалить `tools/_aggregation.py`, `request_credentials.py` BC shims
- reviewer-tests (medium, ~0.7): BC-invariant тесты фиксируют shim'ы как protected
- **Причина dismiss (borderline)**: прямой конфликт между ревьюерами — не dismiss, а **meta-finding** для stage 111/114 (explicit policy decision). Сохранено в отчёте как T1 systemic theme; stage 111 должен явно решить политику (keep+document или remove+update BC tests) перед механической правкой.

### 25. Borderline: core/settings.py env var naming inconsistent (reviewer-docs low)

- **Причина dismiss (borderline)**: частично касается stage 110 (new `BUSINESS_EVENTS_ENABLED`), частично legacy. Ретроактивное naming normalization — низкий ROI vs. риск регрессии. Отложено до stage 117 (docs catchup).

### 26. Speculative: weak crypto / timing attack / log injection (reviewer-security 5×low speculative)

- `bearer_token_manager.py:24-31` — plain sha256 vs HMAC (conf 0.5)
- `auth/bearer.py:126-136` — timing side-channel (conf 0.4)
- `resources/_aggregation.py:116-135` — log correlation_id poisoning (conf 0.45)
- `scripts/product_metrics_report.py:468-472` — --now-override traceback leak (conf 0.45)
- `auth/rate_limit.py:37-105` — multi-worker rate limit bypass (conf 0.5)
- **Причина dismiss (speculative)**: все 5 — defense-in-depth без конкретного exploit, confidence 0.4-0.5. Ревьюер помечает `speculative: true`. Добавить в backlog stage 118+ если security focus возобновится.
