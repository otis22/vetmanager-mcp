# Roadmap

Статусы: `todo` | `in_progress` | `supervisor_pending` | `done` | `stop`.
Структуру проверяет `scripts/check_roadmap_structure.py`.

Очередь 12.11.2026 (решение владельца): **453 → 454 → 456 → 457 → 458**,
затем merge/deploy, мониторинг и дашборд. Этап 459 — отдельная работа вне поезда.

Очередь 10.11.2026 (решение владельца): **452 → 453 → 454**.
Этап 452 выпустить отдельным релизным поездом; 453–454 пока только в очередь.

Историческая очередь 14.11.2026 (решение куратора по делегированию владельца):
**463 → 459 → 460 → 461 → 462 → 464 → 465**. Поезд был приостановлен
владельцем во время 459; WIP и evidence сохранены. Handoff того состояния —
`artifacts/continuation-2026-11-14.md`. Решение 15.11 ниже обновило порядок
после возобновления работы.

Очередь 15.11.2026 (новейшее решение владельца после Claude Opus review):
**463 → 466 → 467 → 459 → 465 → 460 → 461 → 462 → 464**. Выполнять строго
по одному этапу. Этап 467 завершён; владелец снял паузу и разрешил продолжить
459 с трёх узких исправлений default failures, без рефакторинга suite.
Затем 465 обязан дать быстрый и стабильный контур разработки **до**
продуктовых этапов 460–464: нельзя продолжать разработку на 26-минутном
нестабильном suite. Полный handoff: `artifacts/continuation-2026-11-15-stage459-466.md`.
Этап 465 сохраняет все содержательные риски и отдельно перестраивает слои,
diagnostic mode, дубли и invalidation; эти изменения запрещены в текущем WIP 459.
Production feedback и known issues меняет только куратор после проверки результата.
Монолитный real не служит инструментом диагностики и не повторяется после
каждого fix; обязателен единый aggregate без пропусков на финальном runtime.

Отдельное решение владельца 16.11.2026: до push рабочей ветки выполнить
малый поезд 468, убирающий дубли Tests и Docs Check на `dev/**` при наличии PR.
PR/merge и последующие гейты main выполняет куратор.

Решение владельца 16.11.2026: полное ревью рабочего diff завершается до long
gates; committed-diff review пропускает только блокеры релиза, остальное идёт
в Roadmap. После 464 выполнить 469 для contour-scoped fingerprints; текущий
общий fingerprint до него остаётся обязательным. Очередь: **461 → 462 → 464 → 469**.

## Этап 468. Убрать дублирующийся CI на dev-ветках — `in_progress`

Источник: решение владельца 16.11.2026. На одной SHA ветки `dev/**` push и
pull_request запускали по два комплекта Tests и Docs Check. Для `dev/**`
достаточен pull_request; main push и ручной запуск Tests сохраняются.

- 468.1 PRD, red/green сторож и минимальная правка triggers. — `done`
- 468.2 Проверки, pre-review, commit, committed-diff review и push только в
  `origin dev/ci-pr-dedup`; PR/merge — куратору. — `in_progress`

Старт после компакта: новый исполнитель читает `AGENTS.md`,
`AGENT_ONBOARDING.md` 1.2, применимый workflow и этот Roadmap целиком;
до изменения кода пишет `onboarding-attestation.md` с версией, базовым SHA
и ограничениями. Старый thread не требуется. Работа продолжается поездом
строго по одному этапу; статус Codex куратор проверяет и отправляет владельцу
в терминал и Telegram каждые 10 минут.
После каждого деплоя куратор ведёт 60 минут мониторинга сервера, обновляет
оба дашборда и фиксирует результат наблюдения (решение владельца 14.11.2026).

## Этап 463. Онбординг 1.2 для куратора и исполнителя — `done`

Источник: решение владельца 14.11.2026 — сначала внедрить онбординг, затем
продолжить разработку уже с ним. Основа — версия 1.1 с защитой закрытого
`vetmanager-extjs`, а не устаревшая присланная 1.0.

- 463.1 Добавить `AGENT_ONBOARDING.md` 1.2 и ссылки из AGENTS/CLAUDE:
  OpenAPI — контракт, код — реализация; удаление публичного инструмента —
  отдельное решение владельца; эскалация через куратора; attestation для
  неинтерактивного запуска; измеримый простой через этап 464. — `done`
- 463.2 Docs Check main 43584900777 — success. 14.11.2026 получен attestation
  нового исполнителя: прочитаны правила и онбординг 1.2, подтверждён базовый
  SHA `9ec6dc4`, сохранение WIP и границы безопасности. — `done`

## Этап 460. Медкарты: проекция recommendation теряет текст (#168) — `in_progress`

Источник: #168 (13.11.2026, high). Публичная проекция принимает
`recommendation`, а исходная медкарта содержит `recomendation`; значение
молча пропадает из `get_medical_cards_by_date`. Нужен узкий контрактный
фикс без ослабления очистки ПДн и без непроверенного изменения write-API.

Checkpoint на 14.11.2026: WIP сохранён только в
`/home/otis/myprojects/vetmanager-mcp-460` (`list_projection.py`, PRD 460,
два тестовых файла, Roadmap и AssumptionLog). Онбординг 1.2 и PRD-гейты
подтверждены; красная мутация дала 3 failed, после восстановления 10 passed.
Живая read-only проверка всех трёх инструментов зелёная. Полный mock:
4598 passed, 3 skipped, exit 0. Полный real: 114 passed, 4 failed,
19 skipped-not-configured, exit 1; тест 460 внутри него прошёл. Отказали
`test_real_nonexistent_client_raises`, stage276 export, stage389 pages и
stage396 Report AI. Причинность правкой 460 не установлена, но красный гейт
запрещает commit, committed-diff review и push. Worktree не удалять.

После полного зелёного real suite в этапе 459 вернуться к сохранённому WIP,
повторить требуемые проверки на финальном SHA, выполнить committed-diff
Spark → Astra + Opus и только затем push рабочей ветки. Merge/deploy,
production smoke, час мониторинга, дашборды и исходная проверка #168 — куратору.

Продолжение 16.11.2026: этап возобновлён на чистой ветке от main
`44c7e379a5e5d7d9a788f1038b29aa0ca05e0932`; сохранённый WIP переносится
адресно, все применимые проверки проходят на новом checkout. Прежние
результаты полного mock и real не засчитываются за этот checkout.
Новый red/green и fast пройдены; pre-review Spark → Astra + Opus выявило
и устранило риск вывода клинического текста при отказе live-теста. Полный
default: 4823 passed, exit 0. Все восемь изолированных real групп и
aggregate: 138/138 passed, без skip/failure, cleanup 0; live GET/200 всех
трёх инструментов подтверждён безопасным ответом. Остались финальный
аудит, commit, committed-diff review и push рабочей ветки. После push
PR/merge/deploy/monitoring и исходную проверку #168 выполняет куратор.

- 460.1 PRD и Architecture Critique: безопасная нормализация для всех
  списочных инструментов медкарт, совместимость полного ответа и write
  контрактов. Красный сторож: `fields=[id,recommendation]` возвращает текст
  рекомендации; description и очистка ПДн не регрессируют. PRD и evidence
  гейтов проверены новым исполнителем. — `done`
- 460.2 Реализация, полные проверки, живой read-only вызов на стенде,
  ревью и push рабочей ветки. Merge/deploy и исходная проверка #168 —
  куратору. — `in_progress`

## Этап 461. Report AI: PREVIEW_FAILED / OTHER на выручке филиалов (#163–166) — `done`

Источник: четыре обращения одного аккаунта 12.11.2026 с общим fingerprint.
Это один кластер, а не четыре независимых дефекта. Причина не установлена:
нельзя заранее назначать её MCP или конструктору и нельзя рекомендовать
серию одинаковых jobs без классификации отказа.

- 461.1 Безопасная диагностика без SQL/PII и PRD: класс отказа, граница
  ответственности и проверяемый резервный путь через прямое чтение счетов
  с полной пагинацией. — `done`
- 461.2 По доказанной причине: точечный MCP fix и сторожа либо documented
  upstream escalation. Для PREVIEW_FAILED / OTHER агент получает безопасный
  класс, признак допустимости retry и конкретный mcp_workaround. — `done`

Проверки исполнителя на замороженном runtime пройдены: focused/fast, live,
real runner exit 0 и полный default 4835 passed. Завершение 461.2 ждёт
применимого PR CI и решения куратора по merge/deploy/smoke; 462 не начинать.

## Этап 462. get_clients: повторный drift scalar-проекции (#150/#161) — `done`

Источник: #150 (05.11) и повтор #161 (11.11) на другом подключении.
`fields=[id,status]`, `include=[]` отклоняются на неизвестном вложенном поле;
на devtr6 в этапе 458 не воспроизведено. Глобально снимать fail-closed
проверку запрещено.

- 462.1 Получить разрешённую обезличенную форму затронутого ответа: имена
  ключей, типы и envelope без значений клиентов. Воспроизвести drift,
  подготовить PRD и Architecture Critique узкого правила. — `done`
- 462.2 Реализация при подтверждённом drift: документированная scalar
  проекция работает на затронутых формах и devtr6; неизвестные отношения
  не попадают в ответ, пагинация и безопасность сохраняются. — `done`

## Этап 469. Контурные fingerprints для offline gates — `todo`

Источник: решение владельца 16.11.2026 — не повторять default/fast после
изменения только real-only теста. Общий fingerprint остаётся обязательным
и строгим до отдельной реализации; ослаблять его в продуктовом поезде нельзя.

- 469.1 Разделить входы default/PostgreSQL/real, сохранив общие
  runtime/config/dependencies и fail-closed инвентаризацию. — `todo`
- 469.2 Красные сторожа инвалидации по контурам, полные проверки и
  committed-diff release-review только блокеров. — `todo`

## Этап 470. Согласовать документацию контурной инвалидации и заголовки журнала — `todo`

Источник: non-blocking findings final pre-freeze review этапа 461 от
16.11.2026. Текущий общий fingerprint остаётся строгим, а default этапа 461
будет выполнен; противоречие формулировок и формат заголовка не меняют
поведение MCP и не блокируют выпуск 461. Workflow/fingerprint в 461 не править.

- 470.1 Согласовать запрет пропуска fast/default после runtime/tests с правилом
  `real-only test — только real` в `CLAUDE.md`, `AGENTS.md`, Cursor rule и
  шаблоне; сохранить обязательность общего fingerprint до 469. — `todo`
- 470.2 Нормализовать заголовок записи 461 в `AssumptionLog.md` до `##`
  и пробел перед ним, сохранив историю текста. — `todo`

## Этап 455. Аналитика пилотов: периодные позиции и ожидание Report AI — `done`

Срочный hotfix по поручению владельца 10.11.2026: лимит20 внутренних GET
обрывал даже дневную выборку, а Report AI прекращал ожидание через30с.
Общий внешний бюджет30000 MCP-вызовов на один запрос задаёт bot-panel;
внутренний предел1000 RESTGET одной периодной выборки — отдельный счётчик.

- 455.1 Контракт и реализация:1000 внутренних GET/1800с периода,
  честный limited, ожидание Report AI до1800с, consent/no-duplicate. — `done`
- 455.2 Проверки, ревью, hotfix в main, зелёный CI, штатный деплой
  и пост-релизная проверка исходного запроса. — `done`

## Этап 452. Кабинет: перезагрузка при опросе активации стирает форму выпуска токена — `done`

Источник: жалоба 10.11.2026, аккаунт 53, ключ 121; повтор фидбека #139.
Страница учитывает использование действующего доступа, а опрос — любое
историческое `auth_succeeded`, включая отозванный или истёкший ключ.
При новом неиспользованном ключе состояния расходятся, перезагрузка каждые
15 секунд стирает введённые данные и сворачивает секцию выпуска ключей.

- 452.1 PRD и архитектурное ревью: единая семантика состояния страницы и
  опроса, безопасное обновление при работе с формами. — `done`
- 452.2 Исправление и красные сторожа: история отозванного ключа не
  активирует новый; заполненная форма не вызывает перезагрузку;
  OAuth и первый запрос сохраняют рабочий переход в ready. — `done`
- 452.3 Проверки, сильное ревью, зелёный CI, merge, штатный деплой и
  пост-релизная проверка без ручных правок production-конфигурации. — `done`

## Этап 453. Диагностика handshake MCP по аккаунту — `done`

Источник: разбор 09.11.2026, аккаунт 53. Нельзя установить, обращалась ли
задача клиента к серверу: initialize/tools/list не привязаны к аккаунту,
причина HTTP 400 не видна в диагностике.

- 453.1 Спроектировать обезличенную диагностику initialize/tools-list:
  метод, канал и исход авторизации, установленный account_id, версия
  протокола, HTTP-код, ограниченная причина отказа, время, request_id;
  без токенов и персональных данных, с метрикой по исходам. — `done`
- 453.2 Проверить приёмку: по account_id и окну времени за минуту видно,
  были ли handshake и чем они закончились. — `done`

## Этап 454. HTTP 401 + WWW-Authenticate на невалидный или истёкший bearer — `done`

Источник: воспроизведение 09.11.2026 с несуществующим bearer: initialize и
tools/list отвечают 200, whoami — 200 с result.isError=true; challenge
присутствует только в `_meta["mcp/www_authenticate"]`, заголовка нет.
Перед реализацией сверить транспортный контракт с MCP Authorization 2025-11-25.

- 454.1 PRD и исправление транспортного отказа: HTTP 401 с
  WWW-Authenticate при невалидном или истёкшем bearer. — `done`
- 454.2 Проверить автоматическое обновление истёкшего OAuth access при
  живом refresh и повтор read-запроса; совместимость постоянных ключей,
  текущих клиентов и публичного discovery. — `done`

## Этап 456. Report AI: ложная маскировка номенклатуры и числовых агрегатов (#156, #160) — `done`

Источник: read-only triage 10.11.2026. #156 сообщает о маске числовых
количеств и названий номенклатуры в строках Report AI; human-feedback #160 —
о маске названий комбинаций, но ещё не установлен слой (строки задания или
CSV). Выпущенный этап 455 снял предел чтения периодных позиций и продлил
ожидание Report AI; он не проверял эти симптомы. Этапы 368/439/450 покрыли
известные числовые формы, однако не доказывают этот случай. Нельзя ослаблять
очистку текста общим флагом: реальный телефон/имя обязан остаться скрытым.

Сообщение владельца №153 от 11.11.2026 — **свидетельство владельца**, а не
воспроизведённый дефект: он сверил полным токеном с исходным отчётом и сообщил,
что MCP скрыл 13 уникальных названий. Девять названий комбинаций, которые
должны войти в тестовый пример ровно в таком виде:

- АСТЕРИОНОМ DHPPi LR (соб) вакцинация
- ИСПОЛЬЗОВАНИЕ Ш РМ НА ПРИЕМЕ
- Мелоксиветом OR 0,2 для кошек лечение
- Мелоксиветом OR 1,0 для собак лечение
- ОБРАБОТКА ОТ ЭКТОПАРАЗИТОВ (СЕЛАФОРТ)
- РЕНТГЕН СЕРИЯ СНИМКОВ (НЕОГРАНИЧЕННОЕ КОЛИЧЕСТВО) С ОПИСАНИЕМ
- СТАЦИОНАРНЫЕ РМ использование
- ТЕСТ-ЭКСПРЕСС НА ПАНЛЕЙКОПЕНИЮ AГ
- ФИКС ОВГ КОШКИ (полостная)

Ещё четыре позиции:

- Анестезия II категории сложности
- Анестезия IV категории сложности
- Катетер ЦВК ТРЕХКАНАЛЬНЫЙ
- ХН Шапочка Шарлотта

Требуемая проверка: в подтверждённой изолированной тестовой БД создать один
фиксированный период с 9 синтетическими строками комбинаций и 4 синтетическими
строками позиций — по одной на каждое название выше. У записей должны быть
только технические идентификаторы, нейтральные даты, количества и суммы; без
реального клиента, питомца, сотрудника, контакта, свободного текста или данных
клиники. До подтверждения этого тестового контура не создавать Report AI job
и не обращаться к production. После подтверждения построить один и тот же
полный отчёт напрямую в источнике и через MCP; сравнить весь результат, а не
наличие выбранных строк: набор и порядок колонок, число и порядок строк, все
безопасные значения, агрегаты и флаги полноты. Допустимы только заранее
зафиксированные транспортные недетерминированные поля и документированное
преобразование числового типа; все 13 строк должны совпасть с источником
посимвольно. Отдельный отрицательный сторож в той же фикстуре обязан
подтверждать маскирование добавленного синтетического телефона и ФИО, чтобы
сохранение номенклатуры не ослабило деперсонализацию.

- 456.1 Снять безопасную форму обоих случаев и определить слой/тип колонки;
  не извлекать строки, имена, контакты или данные клиники в репозиторий. — `done`
- 456.2 Исправить подтверждённую локальную ложную маску: красные сторожа
  «номенклатура и агрегат сохранны» и «телефон/ФИО скрыты», затем точечная
  реализация и живая проверка на подтверждённом devtr6. — `done`

## Этап 457. Report AI: семантическая проверка скидок, периодов и auto-match (#92, #93, #151–154) — `done`

Источник: read-only triage 10.11.2026. Отчёты говорят о разных рисках:
формуле скидки, отклонении/переформулировке intent, календарной границе и
автоматическом подборе прежнего отчёта. Общий fingerprint не доказывает общую
причину; #155 снял лишь гипотезу о потере оплат в день среза. До
воспроизводимого контракта нельзя ни объединять жалобы, ни называть Report AI
источником финансовой истины.

- 457.1 Сопоставить безопасные результаты при одинаковых периоде, статусах,
  зерне и `DISTINCT`; зафиксировать, что принадлежит MCP, а что конструктору
  Ветменеджера. — `done`
- 457.2 Отдельно проверить контракт отказа от `existing_report_matched`:
  текущий `reject_report_ai_job_candidate` объявлен только для
  `needs_confirmation`; не добавлять путь без подтверждённого upstream API. — `done`
- 457.3 По результату выбрать один исход: MCP-PRD, known issue с обходом или
  эскалация владельцу конструктора. — `done`

## Этап 458. get_clients: минимальная scalar-проекция не проходит (#150) — `done`

Источник: #150 (05.11.2026): `fields=[id,status]`, `include=[]`, limit=1
отказывает на неизвестном вложенном поле на двух подключениях, тогда как
`compact=true` даёт счётчик. Нельзя снимать fail-closed проверку неизвестной
структуры без воспроизведения её безопасной формы.

- 458.1 Воспроизвести на заранее выбранных контурах и определить поле/форму
  drift без выгрузки клиентских данных. — `done`
- 458.2 При подтверждении: PRD, красный сторож минимальной проекции и
  отрицательный сторож неожиданного вложенного поля; затем точечная правка. — `done`

## Этап 466. Групповой real gate вместо монолитных повторов — `done`

Источник: новейшее решение владельца 14.11.2026. Два полных isolated gate
после возобновления дали красный real; всего по сохранённой истории 459 —
четыре завершённых штатных красных real и пятый с failure/skip. Монолитные
повторы по 30–40 минут создают новые jobs/exports на общем devtr6 и не являются
допустимым способом диагностики. Нельзя удалять сценарии, ослаблять assertions,
принимать skip или смешивать evidence разных runtime.

Последний монолит: default 4661 passed, PostgreSQL 6 passed; real 134 passed,
2 failed, 1 skipped-error. Оба failure — ResourceWarning незакрытых
transport/socket; stage385 export guard отклонил безопасный тестовый отчёт.
Cleanup и внешние JUnit/outcome сохранены. Это последний монолитный запуск
перед перестройкой; новый процесс не должен начинать с его повтора.

- 466.1 Прочитать PRD 466 и выполнить inventory всех real nodes: каждый node
  ровно в одной группе по общему ресурсу/риску (read, auth/web/browser, writes
  с restore, Report AI, export, workers). Длинные Report AI/export сценарии
  изолировать. Зафиксировать runtime/test fingerprints, invalidation, manifest
  и точные команды; пройти PRD/Architecture Critique гейты. — `done`
- 466.2 Реализовать групповой runner и aggregate: отдельный изолированный
  Compose project на группу, последовательный доступ к общим upstream guards,
  JUnit+outcome вне репозитория, ноль skipped-not-configured/skipped-error и
  ноль JUnit skip, warnings-as-errors, cleanup. Красные mock-сторожа на потерю
  node, дубликат, missing XML, skip/failure, смешение runtime и неполный
  aggregate. Не повторять монолит после failure — только затронутую группу и
  её зависимости. — `done`
- 466.3 Получить первый baseline каждой группы на текущем runtime и проверить,
  что runner честно собирает manifest и fail-closed результат. Первый baseline
  выполняется заново для всех nodes, старые монолитные passes не импортировать.
  Красные продуктовые/тестовые сценарии передать в 459 с конкретным evidence;
  инфраструктурный этап не считается оправданием их пропуска. — `done`

После 466 этап 459 продолжается только через полный зелёный aggregate на
неизменном runtime. Изменение runtime инвалидирует все группы; изменение
test-only инвалидирует затронутую группу и shared-helper зависимости. Для 459
по-прежнему обязательны default/PostgreSQL, review, push, merge/deploy и
пострелизный контроль; частичный aggregate не разрешает выпуск.


Первый baseline 466.3 остановлен после `read`: 75 passed, 1 failed, 0 skipped, cleanup 0. Runner неверно определил image tag и не записал shard; исправление test-first меняет shared test fingerprint. Остальные группы не запускались, aggregate честно красный из-за отсутствующего shard. В том ходе read не повторялся; позднее куратор разрешил причинную новую попытку после исправления image resolution.



Продолжение baseline после исправления image resolution: новая `read` 76 passed, 0 failed/skip, cleanup 0; `auth-web` 20/0/0; `write-restore` 6/0/0; `workers` 14/0/0; `report-ai` 15/0/0; `report-ai-420` 2/0/0; `report-ai-422` 1/0/0 — все с JUnit/outcome/shard и cleanup 0. `export`: 1 passed, 1 failed (stage276 download), 1 skipped-error (stage385 export outcome: guard refusal), cleanup 0, shard красный. Сумма последних попыток: 135 passed, 1 failed, 1 skipped-error из 137. Aggregate collect-only/cleanup прошли, но aggregator упал на отсутствующем shard исторической первой `read` попытки вместо выбора последней; это новый инфраструктурный дефект, поэтому 466.3 остаётся `in_progress`, 459 — `supervisor_pending`, release заблокирован. Повторов групп нет.

Узкая правка aggregate загрузила только последние shards из append-only index; focused 53 passed, намеренные red guards подтвердили выбор последней и отказ на красном export. Запуск aggregate после правки: collect-only/cleanup 0, exit 1 на `stale test_fingerprint` у всех восьми групп, поскольку изменённые `real_group_gate.py` и isolated runner входят в shared test fingerprint. Export-красный пока не проверен aggregate до конца. 466.3 остаётся `in_progress`; 459 — `supervisor_pending`.

Финальный baseline после консервативной invalidation shared runner: все восемь групп получили новые последние shards на неизменном коде, каждая cleanup 0. Read 75 passed/1 failed (`stage412`, ResourceWarning), auth-web 19/1 (`validate_user_token`, ResourceWarning), write-restore 6/0, workers 14/0, report-ai 15/0, report-ai-420 2/0, report-ai-422 1/0, export 2 passed/1 skipped-error (`stage385`, guard refused); stage276 в этой попытке прошёл. Всего 134 passed, 2 failed, 1 skipped-error из 137. Aggregate collect-only/cleanup 0, exit 1 на красном read; read-only сверка последних восьми shards подтвердила совпадение manifest/runtime/test fingerprints и единую dependency. Условие куратора «красный только export» не выполнено: 466/466.3 остаются `in_progress`, 459 `supervisor_pending`, выпуск блокирован. Счётчик новых непреднамеренно красных групп 7/10; повторов не было.


Решение куратора по приёмке 466: инфраструктурный гейт выполнен — восемь последних shards загружены, manifest/runtime/test/dependency совпадают, cleanup везде 0, aggregate честно отказал на красных outcomes. Продуктовые отказы переданы в 459; условие «только export» отозвано как избыточное. Фактический итог 134 passed, 2 failed, 1 skipped-error из 137. Release остаётся заблокированным.

## Этап 467. Быстрый итерационный test workflow — `done`

Источник: решение владельца 15.11.2026 после независимого Claude Opus
approach review. Онбординг 463 не откатывается: он менял только документацию.
Текущие default 26 минут и последовательный real около 30 минут плюс setup
не должны быть ценой каждой мелкой итерации. Этот этап меняет только
`AGENTS.md`, `CLAUDE.md`, `.cursor/rules/agent-workflow.mdc` и управленческие
артефакты; production code, tests, fingerprints и production не меняются.

- 467.1 Claude Opus внёс в инструкции: первый red только focused;
  focused green + существующий fast contour на итерации; полный default и
  адресные live/browser/PostgreSQL по затронутой зоне на финиш этапа; полный
  real aggregate на финиш поезда; fingerprint-based повторы; stop-loss на
  класс сбоя; диагностика не становится штатным gate без отдельного режима.
  Обязательный живой вызов изменённого инструмента и все security/privacy
  gates сохранены. Куратор исправил fast command на штатный Docker Compose
  вызов вместо недоступного host Python. — `done`
- 467.2 Согласованность трёх инструкций и отсутствие изменений кода/tests
  проверены; focused docs guards **114 passed**, Roadmap structure и diff-check
  зелёные. Следующий процесс начинает 459 с трёх узких правок: wheel allowlist,
  billing fake recorder, невалидный pending candidate. Затем focused →
  default/PostgreSQL → восемь real groups → aggregate → review/release.
  Сразу после 459 выполняется 465 до быстрого стабильного контура; 460–464
  не начинать раньше завершения 465. Поезд остановлен на паузу. — `done`

## Этап 459. Стабилизация real suite devtr6 — `done`

15.11.2026, после трёх узких исправлений четыре ранее красных узла
прошли отдельно (4 × 1 passed), focused — 5 passed. Fast:
**4772 passed/3 skipped/162 deselected за 668,43 с**; это baseline для
465, не выполнение цели ≤3 минут. Полный default после аудита:
**4791 passed/3 skipped/143 deselected за 1522,21 с**; PostgreSQL:
**6 passed/0 skipped**. Восемь новых real groups последовательно:
read 76, auth-web 20, write-restore 6, workers 14, report-ai 15,
report-ai-420 2, report-ai-422 1, export 3; aggregate **137/137 unique**,
0 failures/skips, cleanup 0. Общий runtime fingerprint:
`c19194f590033195965b1c5b77f072361b82ed0617f2f49e68da312f0b46e4a4`.
Evidence: `stage459-resume-20261115/` и `stage466/baseline/` во внешнем
review-evidence каталоге. Следующий обязательный этап — 465 до 460–464.

15.11.2026, финальный после transport.abort runtime baseline: семь
последовательных новых групп auth-web 20, write-restore 6, workers 14,
report-ai 15, report-ai-420 2, report-ai-422 1, export 3 — все passed,
0 skips, cleanup 0, ownership errors пусты. Вместе с read 76 aggregate
`aggregate-collect-be6366666fd8` green: **137/137 unique, 0 skips**,
один runtime/dependency/manifest, cleanup 0. Standard default/mock затем
**4789 passed/4 failed/1 skipped/143 deselected**, cleanup 0: wheel
allowlist, billing fake и известный красный pending-loop candidate guard.
PostgreSQL **6 passed**, cleanup 0. Default gate блокирует 459/release;
неповторённый красный запуск увеличил счётчик до **7/10**. Исправлений,
real монолита, commit/push/deploy не было.

15.11.2026, ровно одна адресная real `read` после resolver transport.abort
fix: `stage466/baseline/read-48b5bfd95018`, **76 passed/0 failed/0 skips**,
JUnit/outcome/shard/summary полные, все runner steps и cleanup exit 0.
Прежний warning node прошёл; ResourceWarning 0, session ownership errors
пусты, 76 per-node transport и resource diagnostics 0600. На этой попытке
TLS cancellation warning устранён; live proxy tunnel/SOCKS и диапазон
версий остаются непроверенными. Старые семь shards runtime-stale, passes
не импортировать. Счётчик 6/10, release blocked; других групп не было.

15.11.2026, v5 resolver-only transport backend после чистого post-budget
Spark design scout реализован test-first. Исходный TLS handshake red
1 failed/2 passed стал **3 passed**, 0 socket identities/ResourceWarning;
abort mutation red 1 failed, backend guards 5 passed, совмещённые
closed-loop/inflight/reset/AnyIO **26 passed**. Code Spark scout valid `[]`.
Стандартный AsyncClient/proxy mounts сохранены; deadline/VM pool не менялись.
Runtime fix инвалидирует все real shards; real read не запускалась.
6/10, release blocked до одной адресной read и остальных gate.

15.11.2026, v4 post-budget Spark scout подтвердил high: публичный
`TransportSocket.shutdown(SHUT_RDWR)` не закрывает fd/asyncio transport,
поэтому не устраняет ResourceWarning от unclosed socket/transport.
`stage459-transport-backend-v4/design.md` отклонён до runtime/tests;
сильную пару не запускали. Счётчик 6/10, release blocked. Следующее
решение должно управлять самим transport ownership, а не только shutdown.

15.11.2026, v3 post-budget Spark scout подтвердил high до реализации:
`SocketAttribute.raw_socket` на установленном AnyIO/asyncio возвращает
`TransportSocket` без `close()`, поэтому предложенное синхронное raw close
невыполнимо. Внешний `stage459-transport-backend-v3/design.md` и scout
evidence сохранены; сильную пару после исчерпания бюджета не запускали.
Runtime/tests/real не менялись, 6/10, release blocked. `transport.abort()`
требует отдельного причинного design/решения куратора.

15.11.2026, Architecture Critique v2 остановлен до runtime: standard
AsyncClient + замена `_network_backend` прямого/proxy pool сохраняет env
proxy discovery в установленном HTTPX, но cleanup дизайн не закрыт.
Spark valid high/medium, Astra valid `[]`, Opus valid **3 high/4 medium**.
Подтверждённые high: нет времени на close в уже истекшем deadline,
конфликт re-raise cancellation с cleanup failure, отсутствует владелец
pending close task до reset/loop shutdown. Оба валидных strong слота
Architecture/PRD gate (v1/v2) потрачены; третий запрещён. Runtime/tests/real
не менялись, 6/10, release blocked. Следующий design требует решения куратора.

15.11.2026, transport-level architecture gate остановлен до runtime:
внешний `stage459-transport-backend/design.md`, Spark candidate medium,
Astra valid `[]`, Opus valid **high**: HTTPX отключает env proxies при
`transport=`, resolver-only adapter меняет production routing. High
подтверждён исходником установленной 0.28.1, поэтому design отклонён;
остальные Opus medium требуют уточнений. Runtime/tests/real не менялись,
6/10, release blocked. Следующий design должен сохранять proxy semantics.

15.11.2026, предложенный перенос deadline во внутренний HTTPX timeout
test-first проверен и **не принят**: аргументный guard 2 red → 2 green,
но полный локальный TLS guard остался 1 failed/2 passed. После двух
последовательных handshake один клиентский socket ещё оставался и дал
ResourceWarning: внутренний timeout первого источника не закрывает stream,
отменённый reset во втором. Runtime-кандидат откатан, прежний красный
candidate guard удалён из WIP, evidence сохранён. Real read не запускалась,
счётчик 6/10, release blocked; нужен transport-boundary fix.

15.11.2026, разрешённый минимальный `_bounded_get` close-on-cancel
test-first кандидат **не прошёл** решающий TLS guard: unit red 3 failed,
кандидат unit green 3 passed, но настоящий handshake **1 failed/2 passed**,
две клиентские sockets и 4 ResourceWarning после успешного reset сохранились.
Кандидат runtime полностью снят, real read/другие группы не запускались.
Требуется решение куратора об исправлении cancellation cleanup на границе
transport/httpcore или совместимой зависимости; 6/10, release blocked.

15.11.2026, offline TLS loopback guard локализовал новый причинный путь:
handshake timeout через `_bounded_get`/`asyncio.wait_for` оставляет две
клиентские socket/transport после успешного resolver reset без ExceptionGroup;
GC/unraisable даёт 4 ResourceWarning. Headers-timeout и успешный TLS контроль
зелёные (2 passed). Test-only закрытие stream при `CancelledError` в
httpcore `AnyIOStream.start_tls` делает handshake guard зелёным (1 passed),
0 оставшихся sockets/warnings. Runtime/dependency не менялись; real warning
может иметь этот же класс, но точное тождество случая не доказано. 6/10,
release blocked; решение о минимальном fix — следующий шаг куратора.

15.11.2026, офлайн loopback integration настоящего resolver path: два
последовательных источника через httpx/AnyIO, отмена shielded caller при
ожидании второго ответа, затем успешный reset без ExceptionGroup. Финальный
изолированный тест **1 passed**, три новых socket inode исчезли, GC/pytest
unraisable не дали ResourceWarning; JSON 0600. Реальный warning этим не
воспроизведён и owner не доказан. Один промежуточный непреднамеренный red
произошёл только из-за повторной записи append-only evidence filename;
итоговый счётчик **6/10**. Runtime без изменений, новых real groups нет.

15.11.2026, диагностика красной read без новых real запусков: warning fd 10
совпадает с resolver connection/task, VM connection имеет иной fd.
В JUnit нет `Billing resolver client cleanup failed` или `inflight cleanup
did not finish`; момент предупреждения относительно reset не установлен.
Офлайн candidate guard с cancel-resistant task и двумя соединениями на owning
loop после bounded wait намеренно красный (1 failed): после явного cleanup failure задача и
client сохранены, поэтому закрытие owning loop в таком состоянии опасно.
Это структурный риск, не доказанная причина данной read. Существующие
resolver/closed-loop/reset guards 21 passed. Runtime не менялся; 5/10,
release blocked. Следующая real read только после причинного решения куратора.

15.11.2026, новый baseline после runtime invalidation остановлен на первой
`read`: `stage466/baseline/read-0b140abb0663`, **75 passed/1 failed/0 skips**
из 76, real-group/CLI exit 1, cleanup 0; JUnit/outcome/shard/summary и
153 technical JSON 0600 сохранены. Красный node
`test_missing_client_marker_is_not_returned_as_client` получил
`ResourceWarning` через pytest unraisable collector; session ownership
errors пусты. По стоп-условию остальные семь groups и aggregate не
запускались, read не повторялась. Счётчик **5/10** (было 4/10), release
blocked; прежние real passes не импортированы.

15.11.2026, test-only fake billing Client получил `close()` с
`is_closed=True`; TLS assertions сохранены, production reset не менялся.
Исходные три адресных tests: 1 passed/3 errors (первый teardown,
два следующих setup), после правки вместе с reset guards **18 passed**;
Ruff/structure/diff 0. Один полный isolated default/mock теперь
**4783 passed, 1 skipped, 143 deselected**, exit/cleanup 0; PostgreSQL
**6 passed, 0 skipped**, exit/cleanup 0. Счётчик **4/10** без изменения.
Manifest fingerprint: `test_stage448_billing_fallback.py` не входит ни в
одну real group; изменение fake не делает read stale. Однако предыдущая
runtime правка reset оставила **все восемь** latest real shards stale по
runtime fingerprint (test fingerprints всех восьми совпадают). Одна read
не сделала бы aggregate валидным; лишний real запуск и заведомо красный
aggregate не выполнялись. Исторический 137/137 остаётся evidence прошлого
runtime, release blocked до восьми свежих shards и aggregate.

15.11.2026, runtime fix reset VM pool/billing resolver: async clients закрываются
через `aclose`, sync test clients через `close`; без метода/при ошибке client
остаётся для retry и cleanup явно красный. Test-first red 4 failed/4 passed,
focused green 21 passed, Ruff/structure/diff 0. Один полный isolated
`default` после правки: **4781 passed, 1 skipped, 3 teardown errors**,
default exit 1, cleanup 0; прежние 537 errors устранены, но три тестовых
resolver clients без обоих close методов честно дают cleanup failure.
Счётчик **4/10** (было 3/10 + один красный default). По стоп-условию
PostgreSQL и real groups не запускались. Runtime change инвалидирует все
восемь прежних real shards; исторический aggregate 137/137 не актуален.
Release blocked, 459 in_progress.

15.11.2026, финальная групповая серия на неизменном WIP: report-ai 15/15,
report-ai-420 2/2, report-ai-422 1/1, export 3/3, все cleanup 0,
ownership errors 0, ноль skips. Перед aggregate обнаружен stale test
fingerprint только у auth-web после общего child env helper; по правилу
причинной invalidation обновлена одна auth-web 20/20, cleanup 0. Read,
write-restore и workers не повторялись. Последние shards всех восьми групп
совпали по runtime/test fingerprints: aggregate exit 0, **137/137 passed**,
0 skips, collect/cleanup 0. Стандартный isolated PostgreSQL: 6 passed,
0 skips, exit/cleanup 0. Стандартный isolated default/mock: **4239 passed,
1 skipped, 537 errors**, default exit 1, cleanup 0; ошибки массово в
setup/teardown, причина ещё не установлена. Счётчик **3/10** (было 2/10 +
один непреднамеренно красный default запуск). 459 и release остаются
заблокированы default gate; commit/review/push/deploy не выполнялись.

15.11.2026, отдельно доказан DB worker `multiprocessing.spawn` overhead:
`_save_in_slot` выставляет ready только после импорта storage и connection
service, до DB save. В offline контейнере без сети с синтетическим account ID
tracer=5 дал ready через 21,697 с (1 child), 24,369/24,420 с (2);
без tracer — 1,934 с и 2,146/2,086 с. Узкий test-only helper убирает
переменную только на время `process.start()` с `finally` восстановлением
parent env; parent tracemalloc оставался active в offline control. Guard red
3 failed/2 passed, focused green 19 passed, Ruff/structure/diff 0.
Одна workers `stage466/baseline/workers-8fc6d6bc112e`: **14 passed,
0 failed/skips**, cleanup 0, ownership errors 0. Группу не повторяли.
Счётчик новой серии **2/10** без изменения; другие real groups/export/aggregate
не запускались, release blocked до полного зелёного gate.

15.11.2026, полный test-only inventory child launchers: 12 MCP server
`Popen` callsites, из них 9 наследовали `PYTHONTRACEMALLOC` до правки;
ещё 1 DB worker через `multiprocessing.spawn`, 1 явное import measurement
и 61 вспомогательный/диагностический process call. AST guard red 1 failed
на девяти server callsites, green focused 38 passed; Ruff/structure/diff 0.
Все 12 MCP server launchers теперь берут env из общего helper; production,
parent tracing/`-W error`, child warnings и readiness budgets не менялись.
Одна новая workers `stage466/baseline/workers-9f0df8164539`: **13 passed,
1 failed, 0 skips**, cleanup 0, ownership errors 0. Семь прежних server
readiness failures прошли; остался `test_two_slots_save_one_account_without_lost_connection`:
родитель не дождался `ready` от DB `multiprocessing.spawn` за 10 с.
Это отдельный непроверенный путь, не доказанный общий owner. Счётчик **2/10**,
release blocked; других real groups/export/aggregate и retry не было.

15.11.2026, новая последовательная серия на неизменном WIP: `write-restore`
`stage466/baseline/write-restore-9834d70d873d` — 6 passed/0 failed/skips,
cleanup 0, ownership errors 0. Следующая `workers`
`stage466/baseline/workers-14a0b97edbc6` — **6 passed/8 failed/0 skips**,
real-group exit 1, cleanup 0, ownership errors 0. JUnit/outcome/shard/summary
обеих сохранены. В workers красные nodes сосредоточены на readiness/timeout
трёхслотовых MCP workers и смежном drain/restart; единый owner ещё не доказан.
По стоп-условию куратора оставшиеся report-ai/report-ai-420/report-ai-422/export,
aggregate и default/PostgreSQL не запускались. Счётчик новой серии **1/10**,
release blocked; код, runner и assertions не менялись.

15.11.2026, после валидного Claude auth readiness review счётчик новой серии
**0/10** (историческая 10/10 сохранена). Offline import auth child в test image,
без сети/API: с `PYTHONTRACEMALLOC=5` 24,732 с (один) и 35,727–36,243 с
(три); без него 2,089 с и 2,533–2,717 с. Launcher наследовал tracer,
прежний real failure был readiness после 100 попыток; фазового marker в том
node не было, exact real import phase не утверждается. Test-only helper
удаляет tracer только из копии env трёх подтверждённых child launchers;
`PYTHONWARNINGS`, parent `-W error`, production runtime и readiness limit
сохранены. Intentional red 4 failed/4 passed, focused green 25 passed,
Ruff/structure/diff 0. Одна новая auth-web `stage466/baseline/auth-web-d9063b59a0fe`:
**20 passed, 0 failed/skips, cleanup 0**, ownership errors 0. Фикс
согласуется с offline timing; другие причины непостоянного readiness не
исключены. Latest read/auth-web fingerprints совпадают, export test fingerprint
stale из-за общего helper; пять остальных групп stale по runtime и test.
Release blocked, другие groups/aggregate не запускались.

15.11.2026, test-only устранение диагностического overhead: stage385 child
processes больше не наследуют `PYTHONTRACEMALLOC=5` от pytest runner;
родительский tracemalloc и `-W error`, фазовая диагностика, 100 попыток
readiness и production runtime сохранены. Guard до правки: 2 failed; после:
26 passed, Ruff/structure/diff exit 0. Одна разрешённая export
`stage466/baseline/export-7465761f0237`: 3 passed/0 failed/0 skips,
real-group/cleanup exit 0; оба stage385 nodes готовы (slot 0 на попытках
28 и 26, остальные slots на первой), все шесть children дошли до post_bind
за 2,537–2,815 с. Общий StartReport/file ID сохранён, второго callsite нет.
Это подтверждает устранение наблюдавшегося diagnostic import timeout в этой
попытке, но прежние security/ResourceWarning причины и остальные real groups
не объявляются закрытыми. Test-only fingerprint инвалидирует export shard;
счётчик непреднамеренных красных запусков **9/10**, release blocked.

Import timing без real API/jobs: fresh test container, `tests/measure_server_import.py`, private JSON 0600. Без tracemalloc: 1 child 2,095 с; 3 child 1,946/3,538/5,154 с; 6 child 2,493–10,476 с (два nodes реально не параллельны). С runner-фактором `PYTHONTRACEMALLOC=5`, без profiler: 1 child 23,667 с, 3 child 32,220/32,740/33,049 с; все exit 0. Последняя real readiness упала за ~12,9 с, так что даже одиночный measured import дольше текущего бюджета. Профиль с tracemalloc даёт 23,829 с (1), 27,350–61,284 с (3), 40,830–121,855 с (6); `-X importtime` добавляет overhead, по одному модулю причину не объявлять. Mock budget/order 5 passed, intentional mutation 1 failed; один непреднамеренный красный AST guard исправлен, новый счётчик **9/10**. Рекомендация: test-only строгий wall readiness deadline около 40 с с fail-closed evidence после отдельного red guard; runtime import не менять по догадке, release blocked.

Одна export с child phase trace: `stage466/baseline/export-0ef2f8761a4a`, 1 passed (stage276), 2 failed (stage385), 0 skips, cleanup 0. Все 6 child phase JSON и оба readiness JSON mode 0600. Каждый child достиг `process_start` 0 мс → `before_import` 1 мс; `after_import` отсутствует. Первые проверенные slots обоих nodes дали 100/100 `connect_error`, listener=false, child не вышел, stderr empty. Конкретная стадия — **import server до lifespan/Redis/DB/bind**; какой импорт или задержка внутри него — неизвестно. Индексы readiness теперь корректны 0/1/2. Stage276 и общий ID прошли, второй StartReport не вызывался; security/RUN_RATE_LIMITED/ResourceWarning нет. Красную export не повторять, счётчик **8/10**, release blocked. Следующий причинный ход — test-only детализация import phase/ресурсной конкуренции с red guard, без runtime fix по догадке.

Test-only phase ход после `export-d17d92753de4`: красный guard `red-stage385-slot-index.txt` поймал stale metrics index=2, второй цикл теперь `enumerate(zip(...))` при неизменных slots и 100 попытках. Статический bind/probe используют один loopback host и один env `PORT`; оба nodes стартуют три child до проверки, SQLite per-node, Redis общий. Причина alive/no-listener по коду не доказана. Новый test-only child wrapper сохраняет JSON 0600 с process/import/server/Redis/DB/pre-bind/post-bind фазами и временем, без raw данных; readiness trace хранит ready/HTTP классы. Red phase classes 5 failed, итог focused **37 passed**, Ruff 0. Real/export не запускались; счётчик **7/10**, release blocked. Следующая одна export только после решения куратора.

Одна разрешённая export с readiness trace: `stage466/baseline/export-d17d92753de4`, 1 passed (stage276), 2 failed (stage385 poll/metrics), 0 skips, cleanup 0. Оба readiness JSON mode 0600: 100/100 `connect_error`, child не вышел, listener закрыт, HTTP status none, stderr class empty; зависимость Redis/SQLite не локализована. Metrics JSON имеет неверную метку `slot_index=2` для первого проверенного child: test-only integration использует stale `index` из предыдущего цикла, поэтому позиционные метки этого файла недостоверны. Фактический порядок по коду: оба nodes стартуют три child перед последовательной проверкой. Security/RUN_RATE_LIMITED/ResourceWarning не наблюдались; stage276 прошёл, общий file ID получен stage385 до readiness. Группу не повторять. Счётчик **7/10**, release blocked. Следующий ход — test-first исправление метки и безопасная pre-listen диагностика, без нового real export до решения куратора.

Readiness mock-only ход после красной export: сохранённые два отказа `MCP slot did not become ready` не содержат `/readyz` status, transport exception class, port/listen или безопасный stderr class; точный owner пока unknown. Оба stage385 nodes запускают 3 child до проверок, затем проверяют их последовательно; nodes идут один за другим, каждый получает отдельный SQLite файл от `prepared_web_db`, Redis общий, PostgreSQL не используется этими children. Добавлен test-only bounded readiness trace для обоих nodes без изменения 100 попыток/0,1 с: фиксированные class counts, child exit, HTTP status/timeout, listener и stderr class, JSON 0600 без raw. Исходный red 6 failed, три красные мутации, focused **30 passed**, Ruff/collect/diff exit 0. Real export/groups не запускались; счётчик **6/10**, release blocked. Следующая export только после решения куратора, один раз с новой диагностикой.

Одна разрешённая real `export` после single-StartReport test-only правки: `stage466/baseline/export-361d77c30f5f`, 1 passed (stage276), 2 failed (stage385 poll outcome и независимый metrics node), 0 skips; real-group exit 1, cleanup 0. Stage276 успешно получил общий file ID, выполнил poll/download/depersonalization; stage385 получил тот же ID, но его MCP slots и слоты metrics не достигли `/readyz`, до poll/download не дошли. `RUN_RATE_LIMITED` и security policy отказов в этой попытке нет. Отдельный startup/readiness class остаётся без владельца; группу не повторять. JUnit/outcome/shard/summary и ownership diagnostics сохранены. Счётчик **6/10**, release blocked; следующий ход — test-only диагностика readiness без нового export.

Export test-only дизайн после зелёной read: session fixture внутри isolated export process сохраняет один явный StartReport outcome; stage276 вызывает `start_once` в своём loop, stage385 использует тот же `report_file_id` без второго StartReport, metrics node независим. Guard refusal и истёкшее poll window теперь failed, не skipped; security policy и download/depersonalization assertions сохранены. Намеренные red guards для второго старта, skip, скрытого download failure, неверного storage host и fixture scope; focused **106 passed**, Ruff/diff/collect-only exit 0. Production runtime не менялся, новый test fingerprint инвалидирует export group; счётчик **5/10**, real export не запускался, release blocked. Подробности и нерешённая причина security refusal — в PRD 459/AssumptionLog.

Одна разрешённая `read` после resolver inflight runtime fix: `stage466/baseline/read-5b509d97081a`, 76 passed/0 failed/0 skips, real-group и cleanup exit 0; JUnit/outcome/shard/summary и 153 resource/transport JSON сохранены, technical JSON mode 0600. Per-node и session-final ownership errors 0, ResourceWarning/unraisable warning 0; fd-diff только diagnostic. Это подтверждает отсутствие наблюдаемого warning в одной попытке, но не доказывает, что отмена shielded task произошла на реальном стенде. Счётчик остаётся **5/10**; все прежние shards stale по runtime fingerprint, остальные группы и aggregate не запускались, release blocked.

Shielded resolver lifecycle: test-first no-network red 2 failed доказал dropped inflight task и client close до task completion. `host_resolver.reset_billing_resolver()` теперь отменяет и ограниченно ожидает все owned tasks до client close, сохраняет pending task/client/lock при явном cleanup failure и поддерживает успешный повторный reset. Identity callback, отмена всех tasks и completed foreign-loop record проверены отдельными красными мутациями; focused 26 passed, Ruff/structure/diff exit 0. Два непреднамеренно красных mock запуска: счётчик **5/10**. Все real shards stale по runtime fingerprint; следующая одна read только после решения куратора, release blocked. Фактура и предел доказательства — в PRD 459 и AssumptionLog.

Одна read после object oracle: 74 passed/2 failed/0 skips из 76, cleanup 0; runner steps зелёные. Красные hospital_blocks и missing_client на ResourceWarning socket/transport; AnyIO connect_tcp allocation и per-node resolver fd/client/task correlation, но точный socket owner не доказан из-за fd reuse. Session ownership errors 0; fd-diff диагностический. Evidence `stage466/baseline/read-6d46bb41311d`; красную группу не повторять. Новый счётчик 3/10, release blocked; остальные shards stale.

Вторая Claude review: fd-diff переведён только в typed diagnostic; release gate — per-node/session GC+unraisable warnings и object ownership WeakSet/registry/tasks. Шесть nested сценариев стабильно прошли 3 раза (outer exit 0, inner 3 expected red/7 green каждый); focused 25 passed после test-first runner PYTHONTRACEMALLOC=5 и live-task guard; три nested final runs exit 0, Ruff/structure/diff 0. Новый счётчик 2/10 (timeout ранней mutation + mock focused failure), прежние серии сохранены. Production runtime и real groups не менялись/не запускались; следующая read только по решению куратора, release blocked.

Typed-fd oracle test-only: red 3 failed, focused typed guards 3 passed, safe type/domain/SO_TYPE/identity и 0600 evidence. Nested pytest подтвердил порядок VM/resolver reset до oracle, но интеграция остаётся красной на extra socket/anon_inode fd; ожидаемый долгоживущий инвентарь и owner не доказаны. Шесть непреднамеренно красных mock запусков довели новый счётчик с 4/10 до **10/10**: остановка для Claude review подхода, без новой real read. Старые fd12–16 ретроспективно не типизируются; fd14 связан с resolver, остальные unknown. Release blocked.

Одна адресная read после retry-safe reset: 72 passed/4 failed/0 skips из 76, cleanup 0, runner steps 0; четыре per-node oracle extra-fd outcomes. Один fd сопоставлен resolver client/task, остальные fd без доказанного owner, ResourceWarning не воспроизвёлся. Evidence `stage466/baseline/read-751bf98263ca`; без повторов и правок после запуска. Новая шкала 4/10, историческая 10/10, release blocked. Нужна безопасная типизация fd/test-first attribution до следующего real решения куратора.

Разрешённый retry-safe runtime fix VM/resolver: failed close сохраняет client/lock и поднимает ExceptionGroup; успешный retry очищает. Closed-loop red 2 failed, green 2 passed; synthetic cancel/timeout/pre-send mutation red 6 failed, green 9 passed включая прежний AnyIO guard. Per-node pytest unraisable oracle теперь относит warning текущему node (integration green 1), FD/transport guard итоговый focused 40 passed, compatibility 30 passed. Три непреднамеренных красных mock запуска при отладке collector: новый счётчик 3/10, исторический 10/10. Runtime изменён, все восемь real shards stale; следующая адресная read только после решения куратора. Release blocked.

Claude approach review принят: per-node GC oracle и раздельные VM/resolver lifecycle guards; fingerprint split отложен в 465, export — отдельный ход, WIP commits отклонены по решению куратора. Test-only oracle red 2 failed/5 passed, green 7 passed. Closed-loop guard VM/resolver red 2 failed: reset теряет незакрытый client после `aclose` exception. Runtime fix не применён, остановка для куратора; остальные lifecycle paths ещё не закрыты. Новый счётчик 0/10, исторический 10/10; release blocked.

Единственный diagnostic export: 1 passed/1 failed/1 skipped-error из 3, cleanup 0. Stage276 отклонён policy адреса хранилища; stage385 start имеет machine code `RUN_RATE_LIMITED`, возможная самоколлизия двух StartReport на одном report ID. Evidence `stage466/baseline/export-410739c086c2`. Счётчик **10/10**; тесты и fixes остановлены для Claude approach review. Release blocked.

Последняя разрешённая client/socket correlation: mock red, затем focused 27 passed; одна новая read 76 passed/0 skips, cleanup 0. 76 technical JSON 0600, 141 connection records, privacy scan 0. Warning не воспроизвёлся, конкретный owner прежнего socket не установлен; release blocked. Счётчик 9/10, другие groups не запускались. Evidence и ограничения — в PRD/AssumptionLog.

Финальный разрешённый ранний warning probe: test-first red 1 failed/3 passed, focused green 26 passed, Ruff 0. Новая read 75 passed/1 failed (stage169 selector socket), cleanup 0; auth-web 20 passed, warning не повторился, cleanup 0. Tracemalloc установил allocation socket в AnyIO connect_tcp, но конкретный pooled client/lifecycle owner пока неизвестен. 96 technical JSON 0600, без запрещённых маркеров. Счётчик 9/10; release blocked. Другие real groups/export/Report AI/aggregate не запускались. Подробности и evidence — в PRD 459 и AssumptionLog.

Диагностические группы после test-only 0600 probe: read 75 passed/1 failed (`test_real_get_message_reports`, selector socket warning до stage412), cleanup 0; auth-web 20 passed, warning не повторился, cleanup 0. Auth probe показал открытые VM/resolver clients на selector loop до autouse cleanup, но не owner прежнего socket. Read stage412 probe увидел пустые пулы; точный allocation owner не установлен. Mock privacy/permission guards намеренно красные, затем focused 35 passed. Runtime не менялся; test fingerprints по рекурсивным импортам stale у workers/report-ai/report-ai-420/report-ai-422/export. Новых exports нет. Счётчик 8/10, release blocked; план следующего адресного real только после ранней instrumentation и решения куратора — в PRD 459.


После приёмки инфраструктуры 466 начата причинная диагностика 459 без real-повторов. Два ResourceWarning: stage412 — uvloop transport при live server, user-token validation — selector socket в pytest loop; точный allocation owner не установлен по JUnit. Export stage276 прошёл перед stage385 skip на том же report ID; самоколлизия tenant guard вероятна, machine code не сохранён. Test-only классификация stage385 теперь отличает guard/not-ready от прочих ошибок, focused mock/lifecycle 33 passed, Ruff 0; invalidation только export. План адресных real-групп и границы доказанного — в PRD 459; release остаётся заблокированным, счётчик 7/10.


14.11.2026, финальный одиночный isolated gate на WIP: default/mock 4661 passed,
1 skipped, exit 0; PostgreSQL 6 passed, exit 0; real group 1 — 133 passed,
2 failed, 1 skipped-error из 136, group 2 — 1 passed. Общий real и real JUnit
validator — exit 1, cleanup — exit 0. Два failure вызваны unraisable
ResourceWarning незакрытых transport/socket в `test_real_validate_domain_api_key_connection`
и stage429; stage385 export guard отклонил тестовый отчёт. Stage276 и stage389
явно passed; stage383 timeout в этом проходе не повторился. Повторять полный
набор без причинного исправления нельзя. Commit, committed review и push
запрещены до нового зелёного полного gate; evidence — внешний каталог
`stage459-final-gate`.

14.11.2026, причинный focused-разбор после полного real exit 1: уникальная
метка в Report AI seed устранила зависимость тестовой фикстуры от накопленных
jobs; stage420/stage422 вместе прошли без skip. Тестовый web client получил
60-секундный ограниченный timeout и прошёл. Real runner сохраняет JUnit и
outcome обеих групп во внешнем evidence; валидатор требует все collected cases,
успех без skip и обязательные stage276/stage389. Stage385, stage383 и два
warning-сценария прошли адресно, однако первопричина их непостоянных отказов
в полном наборе не доказана. Полный gate здесь не повторялся; следующий шаг —
один штатный полный isolated gate по окончательному WIP, затем причинный probe
только по оставшимся отказам. Commit и push в этом ходе не выполнялись.

Исходная задача 12.11.2026 — устранить нестабильность devtr6/billing из
Docker и восстановить зелёный штатный real suite без маскировки падений.
Comparative gate прежнего поезда не закрывал техническую задолженность.
14.11.2026 новый полный real дал 114 passed, 4 failed,
19 skipped-not-configured. Текущие тогда отказы:
`test_real_nonexistent_client_raises`, stage276 export, stage389 pages и
stage396 Report AI; прежние 245, 361, 422 и 449/451 оставались в
диагностическом контексте, а не списке доказанных причин.
14.11.2026 этап поднят перед 460 по условию блокировки приёмки. Исправлены
ложный success `get_client_by_id`, billing lookup 5.6 с с общим пределом
27.6 с, web retry, AnyIO cancellation leak через `anyio>=4.16,<5` и worker
cleanup stage431. Стандартные test/production builds и строгий e2e зелёные;
полный mock: 4598 passed, 3 skipped. Полный real: 114 passed, 4 failed,
19 skipped-not-configured; export и stage389/390 прошли. Остались редкие
uvloop warnings без установленного владельца и upstream timeout stage383.
Commit, committed-diff review и push не выполнялись.

- 459.1 По сохранённым traceback воспроизвести сетевые/контрактные причины,
  подготовить PRD и Architecture Critique, стабилизировать контур/тесты без
  ослабления assertions и получить полный зелёный real suite штатной командой.
  Не трогать WIP 460 и не использовать skip для маскировки сбоев. — `done`

14.11.2026: красный полный real после адресных исправлений. Исходные четыре
сценария и новый live-вызов инструмента прошли, но в разных полных прогонах
падали web integration и другие live-сценарии на нестабильном test-контуре.
Evidence и точный итог — в AssumptionLog. Без зелёного полного real
commit/push запрещены; требуется устранение внешнего blocker или решение
куратора о дальнейшей диагностике.
Дополнительная read-only диагностика 14.11 подтвердила переменную задержку
Docker→billing (TLS до 4,24 с; GET до 5,51 с при ответе 200), но не её
низкоуровневую причину. Stage420 dedup и stage445 первый GET 401 остаются
отдельными неподтверждёнными контрактными расхождениями. Статус
`supervisor_pending` сохраняется; случайный повтор полного suite не является
причинным исправлением.
Измеренный billing deadline 5,6 с при коротких clinic probe прошёл адресный
red/green/live; полный mock зелёный (4597 passed). Новый полный real дал
116 passed, 2 failed: export, stage389/390, stage420/445 и live 459 прошли,
но незакрытые socket/asyncio transports снова вызвали ResourceWarning в
двух других тестах. Общий exit 1 оставляет этап `supervisor_pending`;
commit/push не выполняются до причинной локализации cleanup.
Диагностика с `PYTHONTRACEMALLOC=25` воспроизвела предупреждение уже при
`test_real_get_clients_name_search`: сокет выделен через `anyio.connect_tcp`,
но allocation stack не различает общий HTTP-клиент Vetmanager и billing.
Оба исходно упавших теста в изоляции прошли; короткая последовательность
до Report AI тоже прошла. Владелец сокета и путь потери cleanup не доказаны,
поэтому runtime fix, новые полные suite и выпуск не выполняются;
`supervisor_pending` сохраняется до причинной локализации.

Проверка AnyIO 4.16.0 на стандартно собранных test и production образах:
обе сборки exit 0, строгий `test_e2e_real.py` — 59 passed, 6 skipped,
полный mock — 4598 passed, 3 skipped. Полный real остаётся красным:
114 passed, 4 failed, 19 skipped-not-configured. Stage276 export и
stage389/390 явно прошли. Два отказа содержат ResourceWarning незакрытого
uvloop transport, ещё один — ошибку закрытия loop после предупреждения;
stage383 получил upstream timeout вместо ожидаемого 404. Адресный повтор
четырёх stage-файлов с tracemalloc дал 5 passed без предупреждений, поэтому
владелец новых transport-событий не доказан. Exit 1 сохраняет
`supervisor_pending`; commit/push запрещены. Полные логи и exit — во внешнем
evidence `stage459/verify-*`.
Диагностический полный проход с tracemalloc внутри контейнера также exit 1:
113 passed, 4 failed, 19 skipped-not-configured, 1 skipped-error.
Прежние uvloop warnings не повторились; в этом проходе три теста не дождались
готовности локального worker, четвёртый получил ResourceWarning работающего
subprocess. Его allocation traceback указывает на определение `Popen.__del__`,
а не на создателя процесса. Причина исходных uvloop предупреждений остаётся
неизвестной; диагностический проход не заменяет штатный real gate.
Адресная диагностика live fixture 14.11: четыре проблемных stage-файла дали
5 passed, а последовательность stage374–376 — 3 passed без warnings.
В двух отдельно прослеженных shutdown loop серверные transport уже закрывались,
исходящие transport не оставались живыми; это не воспроизвело исходный дефект.
Отдельно установлен startup leak stage431: при недоступном worker `Popen`
выходил из helper без terminate/wait, а ResourceWarning проявлялся в stage436.
Красный/зелёный сторож и адресный live stage431/436 прошли после точечной
правки; она не объясняет более ранний uvloop warning stage375/420. Stage383
по сохранённому traceback — upstream timeout, не HTTP 404. Полный real exit 0
ещё не получен; 459/459.1 остаются `supervisor_pending`, commit/push запрещены.

Порядок продолжения согласован владельцем 14.11.2026: не повторять полный
suite на неизменённом WIP; сначала выборочно перенести в этот WIP loop/process
cleanup, изолированный Docker-контур и guards из
`origin/dev/test-contours-resource-cleanup`, сохранив наши AnyIO, billing,
stage396, stage431 и строгий missing-client. Затем выполнить focused guards и
stage375/376/420, отдельно классифицировать stage383 и только после этого
запустить полные default + PostgreSQL + real на объединённом WIP. Всю исходную
ветку не merge: её база старше, слабый `assert_client_absent`, статусы `done`
и отчёты не переносить. После зелёных проверок и сохранения перенесённого кода
в рабочей ветке 459 удалить `origin/dev/test-contours-resource-cleanup`;
локальные worktree 459/460 это действие не затрагивает.

14.11.2026, выборочный перенос: loop/process cleanup, отдельный Compose
project с PostgreSQL 16/Redis 7, ownership/JUnit guards и прямой recovery
cleanup перенесены из пяти выбранных коммитов. Focused mock 55 passed;
изолированные focused real stage375/376/420 — 4 passed, stage383 — 1 passed,
новый live клиент — 1 passed. Полный gate отложен на следующий чистый ход;
`TEST_USER_LOGIN` и `TEST_USER_PASSWORD` отсутствуют в доступной тестовой
конфигурации, поэтому 459/459.1 ждут её дополнения куратором. Commit/push нет.

## Этап 464. Наблюдение всех workers и измеримый простой — `in_progress`

Источник: онбординг 1.2 и текущий дашборд. Docker health доступен для трёх
workers, но Prometheus scrape охватывает один, поэтому история простоя всего
сервиса и отдельных workers не измеряется.

- 464.1 Добавить наблюдение всех workers, определить начало и восстановление
  недоступности и получить историческую проверку правила «более 30 минут —
  ненормальный инцидент» без выдуманной точности при пробелах данных. — `in_progress`

Неблокирующее замечание strong review 464.1 для будущего UI-этапа: Kimi K3
пока получает только текст через `-p`; визуальный гейт останется blocked, пока
не доказаны передача PNG-пикселей и metadata по контракту stage345. Кабинет
и лендинг в 464.1 не менялись.

## Этап 465. Пересмотр состава и надёжности test suite — `done`

Источник: решение владельца 14–15.11.2026 после стабилизации 459 и Claude
Opus approach review. Нужно ускорить итерации, не удаляя полезные проверки,
не ослабляя assertions и не скрывая реальные дефекты. До этого этапа менять
resolver, conftest diagnostics, Dockerfile и общий reset helper запрещено.

- 465.1 Подготовить PRD и карту unit/mock, offline integration, browser,
  PostgreSQL и real-сценариев: назначение, стоимость, внешние зависимости,
  доказанные причины нестабильности и более дешёвый oracle. Предложить
  детерминированный release gate и отдельный diagnostic mode; удаление или
  перенос проверки — только с rationale и сохранением покрытия риска. — `done`
- 465.2 После Architecture Critique и red/green evidence реализовать
  `offline_integration`, diagnostic-only tracemalloc/connection hooks/fd/phase
  diagnostics, объединение доказанных дублей и поведенческие guards вместо
  source-text checks. Распространить fingerprint-invalidation на default/PG.
  TLS-loopback, warnings-as-errors, object ownership, security/privacy и
  обязательные живые вызовы сохранить в соответствующем финальном gate.
  Приёмка: fast contour в стандартном контейнере занимает ≤3 минут и три
  последовательных запуска дают одинаковый зелёный результат без пропусков;
  полные финальные gates остаются зелёными. Если ≤3 минут недостижимо без
  потери покрытия, остановиться и показать владельцу измерения вместо
  удаления содержательных тестов. После cooldown обязательная real export
  group прошла без изменения политики; итоговый real aggregate — 137/137.
  — `done`

## Этап 451. Report AI: 403 с кодом FORBIDDEN уходит агенту как unknown (PYTHON-1C) — `done`

Источник: Sentry PYTHON-1C, событие 31.10.2026 17:59 UTC, аккаунт 55. В логе
`report_ai_outcome_code code=FORBIDDEN`, а агент получил «Report AI request
failed (unknown).» Маппинг этапа 442 закрыл голый HTTP 403 без машинного кода;
403 с наблюдённым кодом FORBIDDEN, по всей видимости, до ветки FORBIDDEN не
доходит. Гипотезу проверить в коде до правки.

- 451.1 Любой отказ доступа Report AI (HTTP 403 с кодом FORBIDDEN или без
  кода, на создании и на чтении задания) отдавать агенту понятной ошибкой
  «нет доступа к Report AI, проверьте права с администратором клиники».
  Остальные коды не меняются. Красный сторож: 403 с кодом FORBIDDEN на
  create_report_ai_job → не `unknown`. — `done` 05.11.2026

Реализация и отдельные живые вызовы проверены в ветке `dev/roadmap-449-451`;
после зелёного real suite и merge владелец проверяет событие PYTHON-1C на
production и отсутствие нового `unknown` для `FORBIDDEN`.

## Этап 446. Разбор #146: get_store_documents для помесячных закупочных итогов — `supervisor_pending`

Источник: обезличенный ответ владельца по фидбеку #146 (29.10): неизвестная
ошибка конструктора отчётов, затем исчерпание бюджета листинга складских
документов. Нужны помесячные суммы закупок по категориям товаров на уровне
позиций; `params_shape_json` пуст. Пробел подтверждён: `StoreDocument.total`
не делится по категориям, а операции содержат исторические версии.
[PRD/этап-446-помесячные-закупки-по-категориям.md](PRD/этап-446-помесячные-закупки-по-категориям.md)
фиксирует безопасный узкий листинг и предел точного расчёта.

- 446.1 Расследование фидбека и сопоставление с 433. — `done` 30.10.2026
- 446.2 Подсказка узкого листинга и честного предела категорий; сторож,
  живой вызов, ревью и выпуск поездом. — `done` 30.10.2026
- 446.3 Точный агрегат после подтверждения ВМ: правило актуальной версии
  операции, поле категории, учётная дата и возвраты. — `supervisor_pending`

## Этап 432. Файлы пациента: инструмент чтения вложений (ждёт API ВМ) — `todo`

Источник: фидбек #143 (22.10.2026, account 51) — при разборе истории питомца
нужны лабораторные вложения из раздела «Файлы»; медкарты и профиль пациента
не содержат списка файлов, ссылок, содержимого. Проверка по коду
vetmanager-extjs 23.10.2026: таблица `client_files` существует (поле `url`),
но REST-контроллера для файлов нет — API Ветменеджера файлы не отдаёт.
Блокер на стороне ВМ.

- 432.1 Когда в REST ВМ появится endpoint списка файлов: read-only инструмент
  `get_pet_files` (client_id/pet_id → url, имя, тип, размер, дата,
  file_category, uploaded_by). Контент агент читает по публичной ссылке сам;
  отдельный fetch/конвертация PDF→текст — отдельным решением позже. — `todo`
- 432.2 До появления API — описания инструментов медкарт и профиля пациента
  (get_medical_cards, get_medical_cards_by_date, get_medical_cards_by_client_id,
  get_medical_card_by_id, get_pet_profile): файлы могут быть встроены прямо в
  текст карты (description) как HTML-ссылки `<a href>` на хранилище — такие
  ссылки открывать и использовать; отдельного списка файлов API не даёт,
  не ретраить поиск несуществующего инструмента (решение владельца
  23.10.2026; факт: MCP отдаёт description без обрезки HTML). — `done`

## Этап 358. Превью строк Report AI до сохранения — `todo`

Решение Владимира 02.10.2026 (репорты #94, #110): у Ветменеджера просим превью строк до
сохранения, а не удаление сохранённого отчёта (удаляющие инструменты не возвращаем). Ждёт API
со стороны конструктора (Сирота, пункт 11 от 23.09, повтор 02.10). Когда появится — агент
сверяет превью с прямым чтением **до** сохранения, а мусорных отчётов больше не остаётся.

Дополнение 08.10.2026 (супервизор): Сироте (TeamLead Vetmedical) передано расширенное ТЗ
по репортам #129 и #130 — (1) read-only доступ к определению/запуску существующих отчётов
Report Constructor (gross/net выручка врача), которые не экспортируются по REST;
(2) чтение деперсонализированных строк готового экспорта (пагинация или серверная
агрегация); (3) публичная схема filter_json со стандартными date_from/date_to.
Репорты разобраны и привязаны: #129 → KI-45, #130 → KI-73 (обе [vm-side], дата передачи
зафиксирована в playbook). Складская семантика отчётов (инвентаризация #124 → KI-71,
поступления #125 → KI-72) также передана Ветменеджеру; read-only разбор фидбека
08.10.2026: новых репортов со статусом `new` не осталось.

Дополнение 09.10.2026 (супервизор): Сироте передан запрос count-only probe —
endpoint, принимающий filter_json и возвращающий только число строк результата
без построения отчёта. Это дешёвая первая часть ТЗ: валидация фильтров до
запуска закрывает самый массовый класс жалоб на Report AI — пустое превью при
живых исходных данных (#72/KI-72, #125, #131 от 09.10). Наш мост до него —
этап 373.

- 358.1 Дождаться контракта превью строк от Ветменеджера, сверить на devtr6. — `todo`
- 358.2 Инструмент/поле превью, подсказка «проверь до сохранения», сторожа, выпуск с зелёным CI. — `todo`
