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
