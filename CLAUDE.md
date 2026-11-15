# Правила работы Claude Code над проектом

Основной источник workflow для Claude Code; тот же workflow — в `.cursor/rules/agent-workflow.mdc`.
До задачи прочитать [AGENT_ONBOARDING.md](AGENT_ONBOARDING.md) и `AGENTS.md`;
они дополняют, но не отменяют гейты этого файла. История решений — в `AssumptionLog.md`.

---

## 0. Исполнитель и куратор

- Исполнитель автономен внутри Roadmap/PRD и действующих гейтов: сам запускает команды, read-only снимки и diagnostics, промежуточных разрешений не просит.
- Куратор назначает задачу, принимает финальные evidence, делает merge, deploy и monitoring. Команды не согласует, диагностику не дублирует, upstream jobs не создаёт.
- Attestation — один раз на сессию: базовый SHA и версия правил. Resume без их изменения attestation не повторяет. Новая сессия после attestation продолжает с текущего шага по PRD, `AssumptionLog.md` и evidence без перепланирования.
- Upstream report jobs: после успешного StartReport retry повторяет только failed poll/download по существующему `file_id`; новый StartReport на retry запрещён. При rate limit — ждать окно, серию jobs не создавать.
- Эскалация — только при противоречии задачи правилам, изменении границ риска или продуктовом решении.

---

## 1. Workplan

- Workplan хранится в `Roadmap.md` — единственный источник очереди работ; закрытая история вне окна 20 номеров находится в append-only `Roadmap-archive.md`
- Формируется на основе PRD
- Содержит только название этапа/задачи и статус (`todo` / `in_progress` /
  `supervisor_pending` / `done` / `stop`); `supervisor_pending` означает, что
  работа ждёт решения владельца и считается открытой
- Не содержит деталей реализации

---

## 2. Выбор задачи

- Только задачи со статусом `todo`
- Без незавершённых зависимостей
- Самая верхняя в списке

Запрещено:
- брать несколько задач одновременно
- перескакивать через задачи
- создавать задачи вне Workplan

---

## 3. PRD задачи

Перед началом реализации:

- Создать PRD в `/PRD/` с явным разделом `## Цель`
- Выполнить декомпозицию: подзадача ≤ 2 ч или ≤ 150 строк кода
- Изучить связанные `/artifacts` после создания PRD и обновить PRD проверенными фактами
- Провести PRD-review и PRD-review сторонней моделью
- Провести оценку PRD на простоту и повторить PRD-review gates после правок PRD
- Без декомпозиции реализация запрещена

`## Цель` обязателен с этапа 293; более ранние PRD не переписываются
(граница — `PRD_GOAL_REQUIRED_FROM` в `review_workflow_check.sh`).

---

## 3.1. Ревью сторонней моделью и бюджет

`Ревью сторонней моделью` — одновременное ревью Astra и Opus по постоянной схеме ниже; бюджеты PRD, code/diff и визуального гейтов раздельные.

- Spark (`gpt-6-luna`) — candidate-only scout; вспомогательные запуски без лимита, перед конкретным гейтом — до 3.
- Перед Spark — детерминированная проверка inventory/count/fingerprints (`scripts/offline_gate_manifest.py`, `scripts/check_roadmap_structure.py`, валидатор review). Finding Spark, опровергнутый такой проверкой, отклоняется одной строкой rationale в `AssumptionLog.md` и гейт не блокирует.
- Успех Claude review: JSON-конверт разобран, `is_error=false`, непустое `.result` соответствует findings schema; `stop_reason` не участвует (при `--json-schema` result приходит tool call). Валидатор `scripts/validate_review_result.py` вызывать напрямую как исполняемый файл. Infrastructure failure фиксируется в `AssumptionLog.md` как `N/3`; смена prompt/schema счётчик не сбрасывает.

Каждую попытку Claude strong review запускать через
`scripts/run_claude_review.sh (--range <range> | --file <review-file>) --attempt <N/3>`
(`--range` — diff, `--file` — PRD/Architecture Critique). Runner сохраняет вне
working copy envelope, stderr, prompt, schema и metadata и возвращает non-zero
при invalid verdict. В `AssumptionLog.md` — ссылка на `*.envelope.json` и
`subtype`, `stop_reason`, `output_tokens`, `thinking_tokens`, `len(result)`
даже при пустом stdout; запись только «без output» запрещена.

<!-- stage-343-model-contract:start -->
Постоянная схема моделей (решение владельца 24.09.2026): исполнитель этапа Codex `gpt-6-sol`; Spark/scout `gpt-6-luna` (candidate-only); сильное ревью — `gpt-6-astra` и Claude Opus. Требуется Codex CLI ≥ 0.155. Слаги семейства 5.6 устарели; Terra в GPT-6 нет.

- Перед каждым сильным PRD, Architecture Critique, визуальным и committed diff гейтом выполнить Spark-review; затем запустить Astra и Opus одновременно и дождаться обоих. Spark-бюджет — не более 3 запусков перед конкретным гейтом; если он исчерпан, повтор сильной пары допускается с записанным rationale без четвёртого Spark. Scout для проверки правок после сильного бюджета не тратит предгейтовый Spark-бюджет.
- У Astra и Opus отдельные бюджеты: 2 валидных запуска на каждый гейт у каждого и не более 3 infrastructure attempts у каждого. Architecture Critique делит PRD-бюджет, визуальный гейт имеет отдельный бюджет. Валидный запуск — разбираемый verdict `findings` (включая `[]`). Невалидный ответ не тратит валидный слот. Если любая сторона не дала валидного ответа после трёх неуспешных попыток, гейт blocked и push запрещён. Оба результата обязательны даже на визуальном гейте.
- Astra: `timeout 1800 codex exec -m gpt-6-astra -s danger-full-access -C "$PWD" --output-schema <findings-schema> -o <evidence>/astra-<gate>-attempt-N-of-3.result.json -` с review-only prompt. Сохранять prompt, result, stderr и metadata: модель, объект и reviewed SHA для diff, версия CLI, время начала/конца, exit и validator exit. Проверять результат командой `scripts/validate_review_result.py --plain` с stdin из result; этот режим принимает severity `critical`/`high`/`medium`. Для Claude Opus использовать `scripts/run_claude_review.sh` и прежнюю проверку envelope через `scripts/validate_review_result.py` без изменения поведения runner.
- На визуальном гейте Astra получает скриншоты флагом `-i` и даёт решающее визуальное ревью. Opus запускается с `--image` и получает пиксели скриншотов. Opus `[]` засчитывается только если metadata содержит изображения с совпадающими путями, размерами и SHA-256. Без валидного визуального вердикта Astra гейт blocked.
- Свести findings в `AssumptionLog.md` по гейту: что нашла Astra, что Opus, что оба, что принято/отклонено и почему; приложить пути evidence и время. Неустранённые critical/high блокируют выпуск. Если после исчерпания бюджетов сильного ревью в код внесена любая правка, проверить её Spark (`gpt-6-luna` как отдельный scout) и тестами и отметить отдельной строкой в `AssumptionLog.md`; push разрешён при закрытых critical/high и валидных verdict обоих ревьюеров. Это не замена неуспешному сильному гейту без валидного verdict.
- Если исполнитель — Claude-агент, внешнее сильное ревью делает Codex `gpt-6-astra`; Opus работает как дополнительный параллельный reviewer и его verdict также обязателен для гейта.
<!-- stage-343-model-contract:end -->

<!-- stage-345-visual-contract:start -->
Визуальный гейт: до ревью получить состояния кабинета из веток `compute_activation_state` в коде; отдельно снять bearer/OAuth до первого запроса и после него, разовую выдачу ключа и лендинг. Для каждого состояния делать desktop и phone снимки `full_page`, а первый экран телефона — отдельным PNG. Матрица тем строится по реализованному CSS: тема без реализации не включается. Перед ревью автоматический сторож проверяет полноту состояний, файлов и SHA-256; побайтные дубли и пропуски — ошибка подготовки evidence, гейт не запускать.
Промпт Astra и Opus требует прочитать весь видимый текст на полных страницах и сообщить бессмысленные, склеенные, противоречивые фразы, повторы вопросов/ответов, пустые подписи и элементы вне палитры; оценить также композицию и первый экран телефона. Astra видит PNG через `-i`, Opus через `--image` с проверкой metadata.
<!-- stage-345-visual-contract:end -->


В пользовательском тексте и чеклистах используй формулировку **«ревью сторонней моделью»**, а не имя конкретного CLI, кроме Evidence/Notes.

---

## 4. Core Loop

Агент работает строго по циклу; проверки — по лестнице 4.3:

1. **Выбрать задачу** из Roadmap
2. **Создать / обновить PRD** (раздел 3) — scope, подзадачи, acceptance, out-of-scope
3. **Изучить `/artifacts`** и внести в PRD проверенные факты, убрать неподтверждённые допущения
4. **PRD-review** — устранить адекватные findings, повторять до отсутствия адекватных critical/high
5. **Детерминированная проверка → Spark → PRD-review сторонней моделью** (3.1) — повтор после существенных правок в пределах бюджета
6. **Оценка PRD на простоту** (4.1) — после правок PRD повторить PRD-review gates; зафиксировать финальную версию PRD
7. **Тесты (test-first) → focused red** только на новых/затронутых тестах
8. **Red → Green:** каждый ранее красный node отдельно до зелёного → owning file/suite → fast
9. **Проверки shell** при изменении `scripts/*.sh`: `find scripts/ -name '*.sh' -type f -print0 | xargs -0 docker run --rm -v "$PWD:/mnt" -w /mnt koalaman/shellcheck:v0.9.0 --severity=warning` и `find scripts/ -name '*.sh' -type f -print0 | while IFS= read -r -d '' f; do bash -n "$f"; done`
10. **Аудит изменений** — legacy-паттерны, дублирование, рассинхрон с контрактом; если аудит изменил runtime/tests — повторить шаг 8
11. **Финальные проверки этапа** — один полный default `docker compose --profile test run --rm test`; по применимости PostgreSQL, browser, живой вызов (6.1); real aggregate — на финише поезда
12. **Обновить `Roadmap.md` и `AssumptionLog.md`** с evidence
13. **Архивировать и проверить структуру** строго по порядку: `python3 scripts/archive_roadmap.py`, затем `python3 scripts/check_roadmap_structure.py`; оба exit code 0
14. **Commit** — только при зелёных шагах 8–13; красный WIP не коммитится
15. **Детерминированная проверка → Spark → ревью сторонней моделью на committed diff** (раздел 5); после правок — повтор лестницы, commit и review в пределах бюджета
16. **Push** — после валидных verdict обоих ревьюеров и закрытых адекватных critical/high; medium после исчерпания бюджета — только с rationale
17. **Self-attestation** (4.2) — evidence куратору после push

### Запрещено:
- писать код без тестов; коммитить или пушить без зелёных проверок и аудита
- пушить без валидных verdict Astra и Opus на committed diff; исчерпание infrastructure attempts не разрешает push
- пропускать focused + fast и финальный default после правки runtime/tests
- получать первый red полным suite, real, browser или PostgreSQL; использовать их как цикл разработки
- превышать stop-loss (4.3); смешивать в одном изменении независимые causal classes
- пропускать PRD-review gates после правок PRD и оценку простоты для нетривиального кода
- завершать задачу без self-attestation

### 4.0 Тест-сторож принимается только красным

Любой тест, существующий ради поимки регресса (guard, сторож апстрима,
проверка текста, линтер, статический чекер), до приёмки ломается вместе с тем,
что он охраняет, и обязан упасть; после отката — снова зелёный. В
self-attestation шаг 7 указывается, **чем именно его сломали**.

### 4.1 Оценка простоты PRD

**Обязательный шаг после artifacts и PRD-review, перед написанием кода.** Цель — поймать over-engineering до реализации, когда изменить направление дёшево, а не после 500 LOC кода.

Задать PRD три вопроса:

1. **Читаемость** — за сколько секунд новый читатель поймёт намерение? Если решение требует длинного prose-объяснения «почему так сложно» в PRD — оно, скорее всего, слишком сложное.
2. **Поддерживаемость** — сколько файлов/мест придётся трогать при разумном изменении требований (новая сущность, новое поле, новый auth mode)? Если > 5 — red flag.
3. **Очевидность** — делает ли реализация ровно то, что обещает её сигнатура, без скрытых side-effects, магических хуков, циркулярных импортов, multi-hop indirection?

**Конкретные triggers на упрощение** (если один из них есть — попробовать simpler вариант):

- **Abstraction без 2+ call-sites**: класс / generic / protocol для одного клиента → замени на функцию / прямой вызов
- **Premature flexibility**: configurable-everything, factory-for-one-type → hardcoded + rename позже если нужно
- **Indirection > 2 hops**: caller → shim → canonical → impl — обычно хватает 1 hop'а или прямого пути
- **Dual-API surface**: "new code should use X, but Y keeps working" — признак незавершённой миграции; либо добей миграцию сейчас, либо оставь только Y
- **Sync mechanisms paired**: manual cache sync + event listener + fallback rebuild — один из трёх обычно лишний
- **State machine > 3 states** там где `is_ready: bool` хватает
- **Lazy imports для не-циклического случая** — чаще всего признак, что разбиение на модули неверное
- **Heavy framework где stdlib достаточно**: pydantic model для 2-поля dict, asyncio.Queue где dict работает
- **Helper вызывается из 1 места** — inline его

**Процедура:**

1. Записать PRD как есть (текущий вариант).
2. Пройтись по triggers выше. Для каждого совпадения — спросить: «а если заменить на ___?».
3. Если simpler вариант реально покрывает все acceptance criteria — переписать PRD. Если не покрывает — зафиксировать в PRD блоком **«Rationale для выбранной сложности»**, почему simpler вариант отклонён (concrete use case, measured performance, security requirement).
4. После любых правок PRD повторить обычный PRD-review.
5. После существенных правок PRD повторить ревью сторонней моделью, если остался бюджет PRD-review.
6. Зафиксировать финальную PRD-версию до того, как начнётся код.

**Критерий пропуска:** только тривиальный bug fix (< 50 LOC, 0 новых абстракций).

### 4.2 Self-attestation workflow checklist

**Обязательный шаг после push.** Заполненный чеклист — финальное evidence для куратора, а не вопрос пользователю.

**Формат (Markdown, заполнить реальными значениями):**

```markdown
## Workflow self-attestation — этап {N.N} {краткое название}

| # | Step | Status | Evidence / Notes |
|---|------|--------|------------------|
| 1 | Задача выбрана из Roadmap | ✓/✗ | {строка Roadmap, до изменений status} |
| 2 | PRD создан / обновлён | ✓/✗ | {путь к файлу `PRD/этап-N-*.md`} |
| 3 | Связанные artifacts изучены | ✓/✗ | {api-research-notes §X, technical requirements §Y, OpenAPI/API reference, другие источники} |
| 4 | PRD-review выполнен | ✓/✗ | {N findings; N адекватных; повтор после правок если был} |
| 5 | PRD-review сторонней моделью выполнен | ✓/✗/N-A | {Astra и Opus: отдельные запуски 1/2 или 2/2, findings и сведение, rationale если budget exhausted/skipped} |
| 6 | Оценка PRD на простоту | ✓/✗/N-A | {triggers проверены; результат; повторные PRD-review gates после правок} |
| 7 | Тесты написаны (test-first), focused red | ✓/✗ | {файлы tests/test_*.py, количество новых тестов, focused red; для сторожей — чем сломали} |
| 8 | Red → Green: focused green + fast | ✓/✗ | {что реализовано; focused N passed; `docker compose --profile test run --rm test python scripts/run_fast_test_suite.py` N passed} |
| 9 | Финальный полный default после последней правки и аудита | ✓/✗/N-A | {N passed / M failed, команда: `docker compose --profile test run --rm test`; N-A только для docs-only} |
| 10 | Аудит изменений выполнен | ✓/✗ | {legacy patterns, duplication, field-name contract; если аудит менял runtime/tests — повторные focused + fast до финального default} |
| 11 | Адресные и release gates по применимости | ✓/✗/N-A | {живой вызов изменённого инструмента: код + тело; browser для UI; PostgreSQL для storage; real aggregate — на финиш поезда; N-A с причиной} |
| 12 | Commit выполнен | ✓/✗ | {commit SHA} |
| 13 | Ревью сторонней моделью на committed diff выполнено | ✓/✗/N-A | {Astra и Opus: отдельные запуски 1/2 или 2/2, findings и сведение, rationale если budget exhausted/skipped} |
| 14 | Адекватные findings устранены | ✓/✗/N-A | {commits/изменения; либо N-A если 0 адекватных} |
| 15 | Push выполнен | ✓/✗ | {remote/branch, commit SHA} |
| 16 | Этот чеклист заполнен | ✓ | передан куратору после push |

### Summary
- **Файлов изменено**: X
- **LOC diff**: +Y / -Z
- **Тесты**: N passed
- **Ревью сторонней моделью**: PRD Astra X/2, Opus Y/2; code Astra Z/2, Opus W/2; blocker=0, high=0 after fixes
- **PRD**: `PRD/этап-N-*.md`
- **Commit message draft**: {одна-две строки}

### Отклонения от workflow
{Если что-то пропущено или отклонение — явно перечислить с обоснованием. Если отклонений нет — «Отклонений нет.»}
```

**Правила заполнения:**

1. **Не ставить ✓ за несделанный шаг.**
2. **N-A** — только с причиной в Notes.
3. **Evidence конкретное**: файл, строка Roadmap, команда/путь evidence ревью, SHA. Не «ок».
4. **Отклонения от workflow** — отдельной секцией; «Отклонений нет» валидно.
5. Чеклист — Markdown-блок в отчёте куратору, не в коммите и не в отдельном файле.

**Критерий пропуска:** docs-only commits (*.md) используют сокращённый чеклист: PRD/artifacts/review/test/code шаги — N-A со ссылкой на §5.5.

### 4.3 Слои проверок: итерация, финиш этапа, финиш поезда

Слои меняют **когда** запускается проверка, а не **что** обязательно: красная
обязательная проверка запрещает commit и push. Core Loop (раздел 4) следует этой лестнице.

1. **Обычный цикл.** Focused red на новых/затронутых тестах (сторож — только
   с доказанным red/mutation, 4.0) → реализация → каждый ранее красный node
   отдельно до зелёного → owning file/suite → fast
   `docker compose --profile test run --rm test python scripts/run_fast_test_suite.py`
   → аудит → финальные gates → commit → committed-diff review. Полный
   suite/real/browser/PostgreSQL ради первого red не запускать. Fast исключает
   `browser`, `real_api`, `real_browser`, `postgres`, `offline_integration` и coverage.
2. **Debug после failure/error широкого набора.** Сохранить failing
   nodes/evidence, классифицировать product/harness/flaky по фактам, широкие
   прогоны остановить. Один causal class на изменение/коммит; ранее красные
   nodes по одному до зелёного → owning file/suite → fast → только
   инвалидированные полные слои. Real — затронутая группа и финальный aggregate
   по существующим fingerprints. `--maxfail=1` — только в широком
   debug-прогоне; финальный полный — без maxfail.
3. **Финальные gates.** После последней кодовой правки и аудита — один полный
   default `docker compose --profile test run --rm test`; по применимости
   PostgreSQL (storage), browser (UI), живой вызов изменённого MCP-инструмента
   с кодом и телом (6.1). Финиш поезда / перед push-merge — полный real
   aggregate и остальные release gates. Быстрый pre-review до полного набора
   допустим; обязательное committed-diff review — после зелёных финальных
   gates. После review-правок повторить соответствующую лестницу.
4. **Инвалидация.** Docs-only не повторяет suites; runtime/test/dependency
   changes повторяют затронутые проверки по доказанной карте. Real и
   default/PostgreSQL проверяют versioned node inventory, JUnit и fingerprint
   исходников/конфигурации/зависимостей через `scripts/offline_gate_manifest.py`;
   устаревший gate не засчитывается.
5. **Диагностика и stop-loss.** Diagnostics и read-only снимки делает
   исполнитель. tracemalloc/fd/connection hooks/подробные logs — адресно на
   failing node, не глобально; scoped offline diagnostic —
   `scripts/run_scoped_diagnostic.py`, дорогие offline integration файлы
   остаются в обязательном default. Один инструментированный JUnit-профиль
   допустим, если даёт новую информацию; повтор без новой информации запрещён;
   профиль не заменяет release gate. Никаких skip/xfail, suppression warnings,
   скрытых timeout и повторов ради зелёного; `-W error`, ownership,
   security/privacy и live gates сохраняются. На causal class — максимум две
   причинные real-попытки, затем offline-воспроизведение либо эскалация; новых
   diagnostic guards в тот же WIP не добавлять. Счётчик 7/10 непреднамеренных
   failures после review не сбрасывать; содержательный нестабильный тест не
   удалять. Параллелить только независимые изолированные контуры; real на
   общем devtr6 и группы с общими upstream resources — последовательно.

---

## 5. Ревью сторонней моделью

Обязательный code/diff gate **после commit и перед push**: Astra и Opus одновременно, бюджет и blocked — по 3.1.

### 5.1 Порядок вызова

1. Собрать контекст:
   ```bash
   git show --stat --oneline HEAD
   git show --find-renames --find-copies --format=fuller HEAD
   git status --short
   ```
2. Промпт содержит: цель/scope PRD, проверенные по artifacts факты API-контракта,
   committed diff (inline или доступный reviewer'у локально), новые файлы inline
   для reviewer без файловой системы, passed/failed/skipped и exit code
   **полного** прогона (`-k`/`-m`-выборка отчётом не является), явные вопросы,
   запрет правок и формат findings JSON: severity (critical/high/medium), file, line, reason.
3. Sandbox/пустой ответ до чтения контекста — infrastructure attempt; повторить с
   контекстом inline в пределах `N/3`. Без валидного verdict — blocked в
   AssumptionLog и self-attestation, push запрещён.

### 5.2 Оценка адекватности замечаний

Сторонняя модель может предлагать улучшения, которые **выходят за scope текущей задачи** или относятся к гипотетическим проблемам. Перед исправлением каждого замечания провести оценку:

| Критерий | Адекватно | Неадекватно |
|----------|-----------|-------------|
| **Scope** | Относится к коду в diff | Касается legacy кода или соседних модулей |
| **Реальность** | Указывает на конкретную ошибку или риск | Гипотетический "может быть в будущем" |
| **PRD** | Соответствует целям этапа | Расширяет задачу за пределы PRD |
| **ROI** | Fix маленький, риск регрессии низкий | Большой рефакторинг для nit |

**Адекватные** — исправлять обязательно (если critical/high) или по приоритету (medium).
**Неадекватные** — задокументировать в commit message или AssumptionLog с обоснованием отказа, не делать.

### 5.3 Severity reaction

- **critical/high** (адекватный) — обязательно исправить → тесты → аудит → commit → повторное ревью сторонней моделью (см. лимит в 5.4)
- **critical** (неадекватный) — задокументировать почему отклонено в AssumptionLog, продолжить
- **high** (неадекватный) — задокументировать почему отклонено в AssumptionLog, продолжить
- **medium** (адекватный) — исправить если разумно
- **medium** (неадекватный) — пропустить с пояснением

### 5.4 Лимит итераций ревью

Бюджет — по 3.1 (2 валидных запуска и до 3 infrastructure attempts у каждого ревьюера). Если после 2 валидных итераций остаются адекватные critical/high:
- **STOP**: 3-й валидный review не запускать, push не делать до устранения;
- оставшиеся findings записать в AssumptionLog; medium откладывать только с rationale;
- правку после исчерпания бюджета проверить Spark и тестами, отдельная строка в AssumptionLog.

### 5.5 Когда можно пропустить ревью сторонней моделью

- Изменения только в документации (`.md` файлы, без кода)
- Изменения только в конфигах CI/CD без логики

---

## 5a. Deep Review — `/super-review` (по требованию)

Многоплановый ревью через skill `/super-review`. **Только по явному запросу пользователя**: не в Core Loop, не после merge, не «на всякий случай».

**Что запускается (в параллель):**
- 9 специализированных ревьюеров: `code`, `architecture`, `docs`, `security`, `performance-and-reliability`, `observability`, `tests`, `product`, `simplicity` + `codex-blindspot` (параллельный Codex pass) + `aggregator` = 11 subagent'ов в `.claude/agents/`
- `codex-blindspot`: один Codex-пробег с анти-корреляционным промптом (ищет то, что Claude-модели системно пропускают)
- `scripts/review_workflow_check.sh` — по умолчанию read-only механические проверки (PRD файл, Roadmap статус, AssumptionLog, diff size); явный `--prepare-roadmap` добавляет архивирование перед structural gate для предкоммитной подготовки
- Агрегатор (`reviewer-aggregator`) — дедупликация, ранжирование, итоговый verdict
- Финальный Codex-арбитраж на top-10 blocker+high findings

**Scope (аргумент skill):**
- `changed` (дефолт) — `git diff` с main + uncommitted
- `related` — changed + 1 уровень импортов
- `full` — весь кодбейз
- `stage:N` — файлы из PRD/этап-N-*.md

**Codex-интеграция:**
- Default on (флаг `--no-codex` для отключения)
- Каждый субагент может эскалировать **до 2 findings** с confidence 0.4-0.7 в Codex для валидации
- Финальный арбитраж — один промпт с inline snippets top-10 (≤ 50k токенов)
- Fallback при sandbox fail: retry × 1, затем секция «codex skipped» в отчёте

**Отчёт:** `artifacts/review/{YYYY-MM-DD}-{scope}-stage-{N}.md`, коммитится с остальным кодом.

**Файлы инфраструктуры:**
- `.claude/agents/reviewer-*.md` — определения 10 агентов
- `.claude/commands/super-review.md` — skill
- `scripts/review_workflow_check.sh` — mechanical checks

---

## 6. Завершение задачи

После выполнения:

- Обновить статус в `Roadmap.md`
- Записать в `AssumptionLog.md`:
  - допущения
  - неясности
  - архитектурные решения
  - результат ревью сторонней моделью (если были значимые замечания)

Задача считается завершённой только после записи в AssumptionLog.

### 6.0 Выкат, меняющий смысл выданных учётных данных, несёт их миграцию

Если выкат меняет трактовку **уже выданных** токенов, ключей, масок или прав,
их миграция идёт **тем же ходом**. У защиты, которая никогда не срабатывала,
есть пользователи, держащиеся на её бездействии (история — этапы 285/289 в
AssumptionLog). Проверка перед выкатом:

1. Меняет ли выкат трактовку уже выданных данных?
2. Если да — сколько записей на бою держится на прежней трактовке?
3. Что с ними произойдёт в момент выката, и мигрируем ли мы их этим же ходом?

Ответы записываются в `AssumptionLog.md`. «Не меняет» — тоже ответ.

### 6.1 Живой вызов изменённого инструмента

**Изменил инструмент — вызови его вживую на тестовом стенде и приложи ответ:
код ответа и тело. Мок этого не заменяет.**

Строка о живой проверке обязательна в `AssumptionLog.md`. Контур —
`scripts/run_opt_in_real_test_suite.py`, `TEST_DOMAIN`/`TEST_API_KEY` из `.env`.
Моки проверяют убеждение автора о контракте; только живой вызов проверяет сам контракт.

### 6.2 Что не переносится в репозиторий

Репозиторий **публичный с 27.02.2026**: `Roadmap.md`, `AssumptionLog.md` и
`PRD/` публикуются тем же коммитом, что и код.

**Из чужих исходников переносится контракт, а не реализация.** Контракт — что
API требует и отвечает: поля, коды, тексты ошибок, обязательность. Реализация —
код, имена классов и методов, порядок внутренних проверок, устройство слияния
данных. Проверка: **это можно узнать, вызывая API снаружи?** Да — пиши; нет —
опиши наблюдаемое поведение, разбор оставь задаче для команды продукта.

Строже — **всё, что помогает получить доступ**: ключи, токены, внутренние
адреса, обходы защиты, способы извлечь чужие данные. Не публикуется ни в каком
виде, включая примеры и фикстуры. Утёкший ключ чинится ротацией: история git публична.

---

## 7. Артефакты проекта

Все управленческие артефакты — в Markdown.

| Файл / папка | Назначение |
|--------------|------------|
| `Roadmap.md` | Workplan-очередь — открытые этапы и закрытые в окне 20 номеров |
| `Roadmap-archive.md` | Append-only история закрытых этапов вне окна в порядке закрытия; не редактировать, искать по номеру |
| `/PRD/*.md` | PRD задач с декомпозицией |
| `AssumptionLog.md` | Журнал допущений и решений |

---

## 8. Справочные артефакты (artifacts/)

Обращаться при планировании, декомпозиции и реализации:

| Файл | Когда использовать |
|------|--------------------|
| `artifacts/prd-vetmanager-mcp-ru.md` | Главный PRD: видение, цели, персоны, требования |
| `artifacts/technical-requirements-vetmanager-mcp-ru.md` | Технические требования: стек, архитектура, структура |
| `artifacts/api_entity_reference-ru.md` | Справочник сущностей API |
| `artifacts/api-research-notes-ru.md` | Накопленные неочевидные знания об API: расхождения, limitations, выводы из legacy PHP. Читать при планировании новых tools, дополнять при каждом ресёрче |
| `artifacts/vetmanager_openapi_v6.json` | OpenAPI спецификация — источник истины |
| `artifacts/vetmanager_postman_collection.json` | Postman-коллекция — вспомогательный материал |

> Агент **не домысливает** поведение API — всё проверяется по OpenAPI или `api_entity_reference-ru.md`.

---

## 9. Тесты и проверки

- ShellCheck и синтаксис Bash (обязательны перед commit при изменении `scripts/*.sh`): `find scripts/ -name '*.sh' -type f -print0 | xargs -0 docker run --rm -v "$PWD:/mnt" -w /mnt koalaman/shellcheck:v0.9.0 --severity=warning` и `find scripts/ -name '*.sh' -type f -print0 | while IFS= read -r -d '' f; do bash -n "$f"; done`. Образ скачивается автоматически, если его нет локально, и фиксирован на версии CI.
- Итерации (fast-контур без browser/real_api/real_browser/postgres/offline_integration и coverage): `docker compose --profile test run --rm test python scripts/run_fast_test_suite.py`; порядок слоёв — 4.3
- Unit + mock e2e (финиш этапа): `docker compose --profile test run --rm test`
- Real API (только если в `.env` есть test `TEST_DOMAIN` и `TEST_API_KEY`; секреты не печатать): `docker compose --env-file .env --profile test run --rm test python scripts/run_opt_in_real_test_suite.py`
- CI: `.github/workflows/test.yml` (unit + mock); `test-real.yml` — ручной запуск

### 9.1 Изменения зависимостей → обязательный rebuild

Если в commit меняется любой из файлов:
- `Dockerfile` (особенно секции `pip install`, добавление/удаление upper bounds)
- `requirements.txt` / `pyproject.toml` (если появятся)
- `docker-compose.yml` (image config)

то **обязательно** перед прогоном тестов сделать:
```bash
docker compose --profile test build test
```

Иначе тесты проходят на устаревшем образе из layer cache и скрывают откат версии пакета.

### 9.2 Pre-commit чеклист для dependency changes

Перед commit любого изменения зависимостей:
1. Узнать **текущую** установленную версию: `docker run --rm <prod_image> pip show <package>`
2. Убедиться что новый pin **включает** текущую версию (не откатывает)
3. `docker compose --profile test build test` — fresh rebuild
4. `docker compose --profile test run --rm test` — полный прогон
5. Только после этого — commit → ревью сторонней моделью → push
