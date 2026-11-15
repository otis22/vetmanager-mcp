# Руководство для ИИ-агентов

Краткий указатель правил и артефактов проекта. Агент обязан следовать workflow и обращаться к артефактам при планировании и реализации.

## Онбординг исполнителя и куратора

До задачи прочитать [AGENT_ONBOARDING.md](AGENT_ONBOARDING.md) — обязателен
исполнителю и куратору, дополняет, но не отменяет workflow и гейты ниже.
Правило — короткая фраза; история решений — в `AssumptionLog.md`.

- Исполнитель автономен внутри Roadmap/PRD и действующих гейтов: сам запускает команды, read-only снимки и diagnostics, промежуточных разрешений не просит.
- Куратор назначает задачу, принимает финальные evidence, делает merge, deploy и monitoring. Команды не согласует, диагностику не дублирует, upstream jobs не создаёт.
- Attestation — один раз на сессию: базовый SHA и версия правил. Resume без их изменения attestation не повторяет. Новая сессия после attestation продолжает с текущего шага по PRD, `AssumptionLog.md` и evidence без перепланирования.
- Upstream report jobs: после успешного StartReport retry повторяет только failed poll/download по существующему `file_id`; новый StartReport на retry запрещён. При rate limit — ждать окно, серию jobs не создавать.
- Эскалация — только при противоречии задачи правилам, изменении границ риска или продуктовом решении.
- Финальный self-attestation (`CLAUDE.md` 4.2) — evidence куратору, не вопрос пользователю.

## Cursor Rules

Правила в `.cursor/rules/` (alwaysApply или по контексту):

| Правило | Назначение |
|--------|------------|
| [.cursor/rules/agent-workflow.mdc](.cursor/rules/agent-workflow.mdc) | Тот же workflow, что `CLAUDE.md`: Roadmap, PRD gates, Core Loop, «Слои проверок», «Релизный поезд» |

## Обязательные артефакты

| Файл / папка | Назначение |
|--------------|------------|
| [Roadmap.md](Roadmap.md) | Workplan: только очередь — открытые этапы и закрытые в окне 20 номеров. Единственный источник выбора следующей работы. Статусы — закрытый словарь: `todo`, `in_progress`, `supervisor_pending` (ждёт решения владельца), `done`, `stop`. |
| [Roadmap-archive.md](Roadmap-archive.md) | Append-only история закрытых этапов вне окна в порядке закрытия. Не редактируется; искать запись по номеру. |
| [AssumptionLog.md](AssumptionLog.md) | Журнал допущений, неясностей и архитектурных решений после завершения задач. |
| [PRD/](PRD/) | PRD задач с декомпозицией (подзадачи ≤ 2 ч или ≤ 150 строк). Перед реализацией — создать/прочитать PRD этапа. |

## Справочные артефакты (artifacts/)

Использовать при планировании, декомпозиции и решениях по реализации инструментов MCP:

| Файл | Когда использовать |
|------|--------------------|
| [artifacts/prd-vetmanager-mcp-ru.md](artifacts/prd-vetmanager-mcp-ru.md) | Главный PRD: видение, цели, персоны, требования — отправная точка планирования |
| [artifacts/technical-requirements-vetmanager-mcp-ru.md](artifacts/technical-requirements-vetmanager-mcp-ru.md) | Технические требования: стек, архитектура, структура проекта — перед декомпозицией |
| [artifacts/api_entity_reference-ru.md](artifacts/api_entity_reference-ru.md) | Справочник сущностей Vetmanager API (Client, Pet, Admission и др.) — при реализации инструментов MCP |
| [artifacts/api_crud_permissions-ru.md](artifacts/api_crud_permissions-ru.md) | CRUD permissions по Vetmanager REST controllers — перед добавлением/удалением write tools |
| [artifacts/vetmanager_openapi_v6.json](artifacts/vetmanager_openapi_v6.json) | Спецификация OpenAPI — источник истины для эндпоинтов и схем |
| [artifacts/vetmanager_postman_collection.json](artifacts/vetmanager_postman_collection.json) | Postman-коллекция — вспомогательный материал для запросов к API |

> Агент **не домысливает** поведение API — всё проверяется по OpenAPI или `api_entity_reference-ru.md`.

## Три гейта, которые нельзя пройти намерением

Полные формулировки — `CLAUDE.md` 4.0, 6.1, 6.2.

**Сторож принимается только красным.** Guard, сторож апстрима, линтер, проверка
текста до приёмки ломаются вместе с охраняемым и обязаны упасть; в
self-attestation — **чем именно сломали**.

**Изменил инструмент — вызови его вживую на стенде и приложи ответ:** код и
тело. Мок не заменяет. Строка о живой проверке обязательна в `AssumptionLog.md`.

**Стендов два:** `TEST_DOMAIN`/`TEST_API_KEY` из `.env` и стенд под
bearer-токеном. Нужный выбирается до запуска.

## Что не уезжает в публичный репозиторий

Репозиторий **публичный с 27.02.2026**; `Roadmap.md`, `AssumptionLog.md` и
`PRD/` публикуются вместе с кодом. Из чужих исходников переносится
**контракт, а не реализация** — проверка: **это можно узнать, вызывая API
снаружи?** Ключи, токены, внутренние адреса и обходы защиты не публикуются ни
в каком виде; утёкший ключ ротируется. Полностью — `CLAUDE.md` 6.2.

## Деперсонализация и выгрузки

Разобрано этапами 275–278. Условия для любого инструмента, который отдаёт
данные клиники наружу:

- **Отчётные данные проходят слои очистки.** Ключи колонок и значения чистятся
  на нашей стороне; право на отчёты не выдаётся группе без полного набора
  условий деперсонализации — связь закреплена сторожем.
- **Выгрузка идёт через нас, а не мимо.** Инструмент отдаёт ссылку, а не
  локатор апстрима; исходник живёт в памяти запроса и на диск не попадает.
  Инструмент получения локаторов снят намеренно — не заводить заново.
- **Чужой локатор не попадает в наш лог.** Журнал транспортной библиотеки
  приглушён, сторож ловит адрес выгрузки в записях логгера. Добавляешь
  логирование запросов — проверь, что адрес не поедет вместе с ним.
- **Правило регистра.** Без общего флага регистронезависимости: формы
  перечисляются явно; после правки словаря прогоняется матрица личных и
  не-личных значений.

## Модель доступа — правила, которые нельзя переоткрыть

Разобрано этапами 268–274 по пользовательской ревизии прав. Это не история, а
условия, которым обязан удовлетворять любой новый или изменённый инструмент.
Каждое закреплено сторожем в `tests/`; правило меняется вместе со сторожем,
а сторож принимается только показанным красным.

1. **Инструмент без строки в реестре прав не существует.** Права живут в
   `tool_access_registry.py`, набор скоупов — в `token_scopes.py`. Пустой набор
   прав допустим только для инструмента, внесённого в поимённый список: иначе
   он рекламируется всем группам и отказывает на вызове.
2. **Удаление — отдельное право `records.delete`, никогда не `*.write`.**
   Создание и удаление разными правами не по вкусу, а потому что «Регистратура»
   должна заводить клиента и не должна его стирать. Право входит только в
   «Полный доступ». Второй слой требует его на любой `DELETE` под
   `/rest/api/`, включая пути, которых сегодня не касается ни один инструмент.
3. **Свободный текст, по которому строится выборка, — это запись.** Запуск
   отчётов требует `report_ai.write`, а не `analytics.read`: иначе группа,
   которой отказано в медкартах напрямую, получает их отчётом. Читающее по
   имени, но запускающее по сути — тоже запись.
4. **Состав группы не описывается вторым списком.** Он считается из прав тем же
   правилом, которое применяет проверка вызова. Отдельный «обещанный состав»
   расходится с реальным молча; заводить его заново нельзя.
5. **Второй слой fail-closed на запись.** Неизвестный пишущий путь и метод вне
   разбора отклоняются до обращения к Ветменеджеру. Добавил вызов по новому
   REST-пути — внеси его в карту, иначе он не поедет. Полнота карты проверяется
   разбором `tools/` и `resources/` через AST, а не регуляркой по литералам.
6. **`tools/list` фильтруется теми же правами, что и отказ на вызов.** Каталог
   не рекламирует то, что не даст вызвать. Права для каталога читаются в обход
   журнала активаций — список инструментов не работа с данными. Сбой чтения
   прав оставляет каталог полным и пишет запись в лог, но не смягчает
   аутентификацию.
7. **Отказ называет все дающие группы, узкие раньше широких, полный доступ
   последним.** Подсказка не должна толкать к полному ключу.
8. **`delete_invoice` и `delete_invoice_document` сняты навсегда.** REST-удаление
   счёта идёт мимо предметной логики продукта: мягкое удаление, откат складских
   документов, пометка вакцинаций и журнал остаются несделанными. Инструменты
   с этими именами не регистрируются, вызов снятого имени читается как
   «инструмента нет», а не «не хватает прав». Возврат — решение владельца
   продукта после появления честного метода на стороне Ветменеджера, а не
   разработчика по ходу задачи.
9. **Интерфейс обязан говорить, что даёт уровень доступа.** Сводка по областям
   (чтение / изменение / удаление) считается из прав и показывается и в
   кабинете, и на экране согласия OAuth. Строка «Удаление: нет» показывается
   всегда — именно её отсутствие и породило исходный репорт.

Сторожа: `tests/test_stage268_invoice_delete_tools_removed.py`,
`test_stage269_report_launch_scope.py`, `test_stage270_delete_right.py`,
`test_stage271_tool_list_visibility.py`, `test_stage271_peek_scopes_matches_auth.py`,
`test_stage272_preset_composition.py`, `test_stage273_access_summary_ui.py`,
`test_stage274_rest_layer_fail_closed.py`, `test_stage264_scope_denial_is_explained.py`.

**Известный незакрытый край:** чтение по неизвестному REST-пути пока проходит и
считается метрикой `vetmanager_rest_unmapped_read_total`. Закрывается отдельным
этапом по её значению на проде — не «забыто», но и не сделано.

## Тесты и проверки

- ShellCheck и синтаксис Bash (обязательны перед commit при изменении `scripts/*.sh`): `find scripts/ -name '*.sh' -type f -print0 | xargs -0 docker run --rm -v "$PWD:/mnt" -w /mnt koalaman/shellcheck:v0.9.0 --severity=warning` и `find scripts/ -name '*.sh' -type f -print0 | while IFS= read -r -d '' f; do bash -n "$f"; done`. Первая команда сама скачивает официальный образ при чистой Docker-сессии и фиксирована на версии CI.
- Структура роадмапа: `scripts/check_roadmap_structure.py` (запускается и сам по себе, и из набора)
- Итерации (fast-контур без browser/real_api/real_browser/postgres/offline_integration и coverage): `docker compose --profile test run --rm test python scripts/run_fast_test_suite.py`
- Unit + mock e2e (один раз на финиш этапа): `docker compose --profile test run --rm test`
- Real API e2e (только если в `.env` есть test `TEST_DOMAIN` и `TEST_API_KEY`; секреты не печатать): `docker compose --env-file .env --profile test run --rm test python scripts/run_opt_in_real_test_suite.py`
- CI: `.github/workflows/test.yml` (unit + mock); `test-real.yml` — ручной запуск с секретом.

Задача не считается завершённой без прохождения проверок и записи в AssumptionLog.

Бюджет хода агента — 90 минут (таймаут MCP-инструмента 5400 с). Порядок
проверок — `CLAUDE.md` 4.3 и «Слои проверок» в `.cursor/rules/agent-workflow.mdc`;
красная обязательная проверка запрещает commit и push.

- **Лестница:** focused red → каждый ранее красный node отдельно до зелёного →
  owning file/suite → fast → аудит → pre-review рабочего diff (Spark → Astra + Opus)
  и исправления → один полный default; по применимости PostgreSQL, browser, живой
  вызов; real aggregate — перед push-merge поезда → commit → финальное committed-diff
  review. Долгие gates запускаются после закрытия замечаний pre-review; полный
  suite/real/browser/PostgreSQL ради red не запускать.
- **Debug после широкого failure:** сохранить failing nodes/evidence,
  классифицировать product/harness/flaky, широкие прогоны остановить; один
  causal class на изменение; `--maxfail=1` — только в широком debug-прогоне.
- **Инвалидация:** docs-only не повторяет suites; иначе — затронутые проверки
  по fingerprints `scripts/offline_gate_manifest.py`.
- **Диагностика:** read-only снимки и diagnostics делает исполнитель, адресно на
  failing node; scoped mode — `scripts/run_scoped_diagnostic.py`. Один
  инструментированный JUnit-профиль допустим, если даёт новую информацию;
  повтор без новой информации запрещён; профиль не заменяет release gate.
- **Стоп-правила:** никаких skip/xfail, suppression warnings, скрытых timeout или
  повторов ради зелёного; `-W error`, ownership, security/privacy и live gates
  сохраняются. Real stop-loss — две причинные попытки на класс; счётчик 7/10
  непреднамеренных failures после review не сбрасывать; содержательный
  нестабильный тест не удалять. Real на общем devtr6 и группы с общими
  upstream resources — последовательно.
- Этап с ожидаемыми двумя раундами сильного ревью планируется в два хода:
  реализация до коммита в первом, ревью + push + CI во втором.

Guard-скрипты и миграции production-данных:

- формат полей (`error_fingerprint_hash` = `hmac-sha256:<64 hex>`, статусы,
  ссылки) берётся из кода и реального снимка, а не из синтетических фикстур;
  сторож на формат обязателен, если скрипт валидирует значение регуляркой;
- PRD этапа, который меняет known_issues/правила/связи на проде, начинается с
  read-only снимка (`show-known-issue-config`, `show-feedback-fingerprint`,
  `show`), снятого исполнителем и приложенного как факт; проектировать по
  памяти или по тексту отказа предыдущего запуска запрещено.

Дополнение к workflow:
- Перед `commit`/`push` — аудит изменений; если он изменил runtime/tests, снова focused + fast, затем один полный default.
- Команда попадает в процессную документацию только после запуска в точно записанном виде с проверкой реального exit code; эквивалентная команда не заменяет эту проверку.
- Перед Spark — детерминированная проверка inventory/count/fingerprints (`scripts/offline_gate_manifest.py`, `scripts/check_roadmap_structure.py`, валидатор review). Spark candidate-only: finding, опровергнутый такой проверкой, отклоняется одной строкой rationale в AssumptionLog и не блокирует; принимаются только важные и проверяемые замечания.
- Spark-review prompt узкий: объект (PRD, uncommitted или committed diff), severity, формат, запрет правок.
- Вызов Spark-review из Codex runtime (`-s read-only` не читает репозиторий): `timeout 1200 codex exec -m gpt-6-luna -s danger-full-access -C "$PWD" -` с prompt `Review only. Do not edit files. Do not run write commands.` и обязательным `files_read`; `[]` без прочитанных файлов невалиден и слот не расходует. Fallback — только при явной model/provider failure. Итог Spark — в AssumptionLog.
- Claude Opus review из Codex runtime: shell timeout ≥ 2× prompt deadline (default `timeout 1200` и `Finish this review within 600 seconds`; реальный timeout Claude не сообщать). Для inline context: `--strict-mcp-config --mcp-config '{"mcpServers":{}}' --tools ""`, запрет правок/commands, `--output-format json` + schema, `Think briefly, then return JSON matching the schema immediately`. Успех: JSON-конверт разобран, `is_error=false`, непустое `.result` соответствует schema; `stop_reason` не участвует (при `--json-schema` result приходит tool call). Валидатор `scripts/validate_review_result.py` вызывать напрямую как исполняемый файл; CI проверяет этот вызов. Иначе — infrastructure failure `N/3` в AssumptionLog; счётчики Opus и Astra независимы, после трёх — `blocked`, push запрещён.

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


### Evidence Claude review

Каждую попытку Claude strong review запускать через
`scripts/run_claude_review.sh (--range <range> | --file <review-file>) --attempt <N/3>`
(`--range` — diff, `--file` — PRD/Architecture Critique). Runner независимо от
exit сохраняет envelope, stderr, prompt, schema и metadata в
`${XDG_DATA_HOME:-~/.local/share}/vetmanager-mcp-review-evidence` (или
`--evidence-dir`) и возвращает non-zero при invalid verdict. В `AssumptionLog` —
путь к `*.envelope.json` и `subtype`, `stop_reason`, `output_tokens`,
`thinking_tokens`, `len(result)`; запись только «без output» запрещена.

## Feedback triage и `known_issues`

Triage (`agent_feedback_reports`, `known_issues`, link/resolve, `agent_playbook_json`/`match_rules_json`) — операционная работа: факты — из production DB, ход — во внешнем work log, который служит только triage и не является источником правил. Файлы репозитория, включая `AssumptionLog.md`, `README.md`, `artifacts/report-ai-*` и ad-hoc research, меняются только при явном product/code intent: code fix, regression test, Roadmap/PRD-задача или документация по прямой просьбе пользователя. Перед commit — `git status --short` и `git diff --stat`; diff только из разбора feedback или правок `known_issues` не коммитится.
