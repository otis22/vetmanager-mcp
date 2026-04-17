# Stage workflow template

Пошаговый чек-лист для нового этапа. Копируется и отмечается ✓ по ходу работы. Root причины пропусков (update_admission, phantom enum, AssumptionLog missing, baseline unresolved) закрываются механическими гейтами на шагах 7, 11, 13, 14.

---

## Чек-лист

### 1. Выбор задачи
- [ ] Задача из `Roadmap.md`, статус `todo`
- [ ] Нет незавершённых зависимостей
- [ ] Самая верхняя в списке (не перескакиваем)
- [ ] Обновил Roadmap: строка задачи → `in_progress`

### 2. Research
- [ ] Прочитал соответствующие PRD этапа и предыдущих этапов
- [ ] Прочитал релевантные разделы `artifacts/`: `prd-*`, `technical-requirements-*`, `api_entity_reference-*`, `api-research-notes-*`
- [ ] Если задача про VM API: **прочитал чеклист полей** в `artifacts/api-research-notes-ru.md` (секция «Поля и их реальные имена»)
- [ ] Identified все call sites, которые могут быть затронуты (grep по pattern, не только очевидные)

### 3. Написание PRD
- [ ] Создал `PRD/этап-N-<slug>.md`
- [ ] Явный раздел «Цель» (1 абзац)
- [ ] Раздел «Scope» с **явным списком Вне scope** — чтобы не было scope creep
- [ ] Декомпозиция: подзадачи ≤ 2 ч или ≤ 150 LOC каждая
- [ ] Раздел «Acceptance»: что проверяет завершение

### 4. Написание тестов (test-first)
- [ ] Создал/расширил `tests/test_stage{N}_*.py`
- [ ] Happy path + boundary + unhappy path
- [ ] **Для API-changes**: structural JSON asserts (не substring); pin int vs string; verify actual wire format
- [ ] **Для sibling patterns**: если fix'ишь create_X, написал тест ТАКЖЕ для update_X/delete_X если они есть (защита от update_admission-типа пропуска)
- [ ] Тесты сначала падают (Red)

### 5. Реализация (Red → Green)
- [ ] Минимальная реализация, чтобы тесты прошли
- [ ] **Phantom-enum check**: если используешь `{"property": "status", "value": "X"}` — cross-reference X с authoritative enum (ExtJS entity class или api-research-notes)
- [ ] **Field-mapping check**: если строишь payload — cross-reference каждый ключ с actual entity field list

### 6. Run tests
```bash
docker compose --profile test build test   # если менялись deps
docker compose --profile test run --rm test
```
- [ ] Full suite зелёный
- [ ] Новые тесты проходят

### 7. Аудит изменений
- [ ] Grep sibling patterns: если ты поменял `create_X` — grep для `update_X`, `delete_X`, `get_Xs` в том же модуле
- [ ] Grep для других cal sites: может быть дубль того же паттерна в `tools/*.py` / `prompts.py`
- [ ] Legacy patterns: остались ли `json.dumps([{"property"...}])` там где должен быть FilterBuilder?
- [ ] Docstring: перечислены ли ВСЕ valid enum values параметров?

### 8. Повторный прогон
- [ ] Если в шаге 7 что-то правил — снова `docker compose --profile test run --rm test`

### 9. Codex review
- [ ] `/codex rescue` с inline self-contained промптом (не расчитывая на чтение файлов)
- [ ] В промпт вложены: PRD (5-10 строк), API contract facts (relevant subset из api-research-notes), полный `git diff`, новые файлы inline, test results
- [ ] Явное «Do NOT touch filesystem»

### 10. Оценка адекватности замечаний
- [ ] Каждый finding прошёл через таблицу CLAUDE.md §5.2 (scope / реальность / PRD / ROI)
- [ ] Адекватные critical — исправить
- [ ] Неадекватные — задокументировать отказ в AssumptionLog

### 11. Исправление + повторный codex
- [ ] Fix адекватных critical
- [ ] Re-run tests
- [ ] 2-я итерация Codex (лимит)
- [ ] Если после 2-й итерации остались адекватные critical: STOP, задокументировать как tech debt в AssumptionLog + спросить пользователя

### 12. **Update AssumptionLog** (ОБЯЗАТЕЛЬНО — блокирует commit)
- [ ] Добавил раздел `## Этап N. <title>`
- [ ] Секции: «Что сделано» / «Архитектурные решения» / «Codex-ревью» / «Тесты» / «Breaking changes» (если есть)
- [ ] Если отложил subtask'и — явный список «Отложено в этап Nb» с rationale

### 13. **Update Roadmap status** (ОБЯЗАТЕЛЬНО)
- [ ] Каждая подзадача `N.x` имеет `— \`done\`` или `— \`stop\`` (не `todo`/`in_progress`)
- [ ] Заголовок этапа — `— \`done\`` или канонический `частично done` (если поддерживается)

### 14. **Resolution note для baseline/super-review findings** (если применимо)
- [ ] Если текущий этап закрывает finding из `artifacts/review/*.md` — добавил resolution line в сам review document
- [ ] Если это был blocker — отметил в Verdict секции этого review как «superseded by stage N»

### 15. Commit
- [ ] Commit message начинается с `Stage N: <short>` — для automated детекции
- [ ] В commit body: что сделано, Codex review outcome (или обоснование skip'а), breaking changes, deferred items
- [ ] Co-Authored-By trailer

### 16. Push
```bash
git push origin main
```

### 17. **Run stage completion check** (ОБЯЗАТЕЛЬНО после commit)
```bash
./scripts/check_stage_completion.sh N
```
- [ ] Exit code 0 (no high findings)
- [ ] Если есть medium findings — оценить, стоит ли follow-up commit

---

## Anti-patterns (не делать)

- ❌ Fix только в одном месте, когда тот же паттерн есть ещё в 3 файлах (sweep discipline gap)
- ❌ Использовать `{"property": "status", "value": "<literal>"}` без сверки с authoritative enum
- ❌ Commit без AssumptionLog entry (workflow-check и stage-completion скрипт поймают)
- ❌ Пропустить Codex review без явного skip в AssumptionLog
- ❌ Закрыть baseline finding без resolution note в review artifact
- ❌ Оставить subtask в `in_progress` статусе в Roadmap после merge
- ❌ Commit с 200+ LOC diff без разбиения на subtasks

## Mechanical gates

Стадии 17 + AssumptionLog hook + field-mapping lint автоматически детектят большинство пропусков. Если что-то прорвалось — добавить в `scripts/check_stage_completion.sh` или `.github/workflows/` в следующем этапе workflow discipline.
