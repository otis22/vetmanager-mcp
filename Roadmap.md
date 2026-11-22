# Roadmap

Статусы: `todo` | `in_progress` | `supervisor_pending` | `done` | `stop`.
Структуру проверяет `scripts/check_roadmap_structure.py`.

Актуальная очередь 21.11.2026: **490 → 491 → 492 → 493**. Этап **476**
завершён как design; реализация отложена до нового фидбека. Завершённые 479,
480, 481, 482, 473, 474, 475 и 488 в активную очередь не входят. Этап **487**
остановлен по новым evidence #180: scheduled-запуск не дошёл до MCP.

Независимые поезда, каждый со своим PR:

1. **490** — адресная privacy-safe диагностика `get_invoices`; отдельный
   runtime PR только после красного сторожа и проверки на стенде.
2. **491** — production host security maintenance с snapshot/backup,
   контролируемым restart и отдельным решением о kernel reboot.
3. **492** — воспроизводимые Python dependencies с hashes и регулярный
   `pip-audit`, без автоматической установки обновлений на production.
4. **493** — security release Python base image и `cryptography` с полными
   применимыми release gates.

В верхнем блоке активного поезда фиксировать: состав этапов, ветку, base SHA,
текущий gate, следующее действие и стоп-условия. После завершения блок убрать;
решения и evidence остаются в `AssumptionLog.md`, закрытые этапы архивируются
штатно. Операционные журналы, внешние дашборды и их инструкции в этом
репозитории не хранятся.

## Этап 489. Расследование `get_invoices` errors без traceback — `done`

Во время мониторинга 474 найдены две записи `Error calling tool 'get_invoices'`
без traceback. Деградация workers и связь с релизом не доказаны. Сначала
сопоставить runtime/nginx/audit и получить безопасный error class, correlation
ID и форму параметров. Исправления, retry и изменение таймаутов до установления
причины запрещены. [PRD](PRD/этап-489-расследование-get-invoices-errors.md).

- 489.1 Сопоставить обе записи с runtime трёх workers, nginx и audit; источник
  и класс не определяются существующими полями, подготовить отдельный
  privacy-safe diagnostics PRD. — `done` 21.11.2026

## Этап 490. Узкая диагностика отказов `get_invoices` — `todo`

Read-only расследование 489 подтвердило пробел: в runtime есть имя инструмента
и request ID, но нет безопасного класса исключения, upstream status и формы
параметров. Добавить только allowlisted диагностическое событие и сторожа
приватности; production replay и изменение retry/timeout не нужны.
[PRD](PRD/этап-490-безопасная-диагностика-get-invoices.md).

- 490.1 Показать красный privacy guard, реализовать адресное событие, проверить
  его на стенде и провести применимые release gates. — `todo`

**Общие ограничения evidence 491–493.** Количество обновлений не равно числу
эксплуатируемых уязвимостей. Не все CVE nginx достижимы в текущем конфиге;
`pip-audit` не проверяет host, OS-слои, конфигурацию или фактическую
эксплуатируемость. Отсутствие прямых вызовов затронутых cryptography API не
доказывает безопасность всей транзитивной цепочки. Текущие rollback-код,
snapshot и GHCR tag сами по себе не доказывают восстановимость без потери
данных или происхождение нового образа.

## Этап 491. Production host security maintenance — `in_progress`

Read-only аудит 21.11.2026: nginx `1.24.0-2ubuntu7.6` при candidate
`1.24.0-2ubuntu7.21`, host Python `3.12.3-1ubuntu0.10` при candidate `0.17`;
также доступны обновления OpenSSL, OpenSSH, Docker и kernel. Между версиями
nginx в changelog 28 уникальных CVE, но текущий конфиг не включает HTTP/2,
mail proxy, `ssl_preread`, `try_files`, `alias` и njs: это ограничивает
reachability части проблем и не заменяет патчи. Наличие 220 обновлений, из
которых 140 пришли из security-канала, не означает 140 уязвимостей.

**Риски и стоп-условия.** High: обновление OpenSSH/nginx/Docker может закрыть
административный или публичный доступ, а reboot дать простой. Critical при
неверном rollback: восстановление host snapshot может потерять записи после
снимка; `rollback_db.sh` намеренно пересоздаёт БД и не является откатом пакетов.
Без независимого console-доступа, окна, изолированного restore-теста и плана
сохранения/сверки новых записей изменения не начинать. Snapshot без такой
проверки не принимать. При неуспешном SSH/nginx/Docker post-check остановиться
на текущем шаге; простой более 30 минут — инцидент.

- 491.1 До изменений создать PRD/runbook: console-доступ, snapshot/backup и
  доказанное восстановление с RPO ≤1 час как верхним пределом и pre-change backup
  не старше 30 минут, точный список и порядок пакетов, симуляция apt,
  `nginx -t`, контролируемый restart, rollback без автоматического возврата
  БД/snapshot, измерение простоя и проверки public smoke, release-state и всех
  MCP workers. Не выполнять unattended полный upgrade. — `done` 21.11.2026
  [PRD](PRD/этап-491.1-production-host-security-preflight.md).
  Вертикальная проверка backup/restore 22.11.2026: свежий `pg_dump -Fc`
  зашифрован потоком и восстановлен из off-host копии на отдельном host в
  новой internal Docker network и новом volume. Схема, constraints,
  агрегаты, запуск приложения и дешифрование проверены; временный restore
  удалён. Независимая console, RPO при реальном переключении и новые
  pre-change копии перед каждой пакетной группой остаются входными gates
  491.2; эта проверка не разрешает начать пакетные шаги.
- 491.2 Выполнить согласованный host security maintenance отдельными
  пакетными шагами и post-checks после каждого затронутого сервиса. Не
  смешивать с application dependency release или kernel reboot. — `in_progress`
  [PRD подготовки и gates](PRD/этап-491.2-подготовка-host-security-maintenance.md).
  Read-only подготовка: четыре группы по 3/2/5/2 пакета, off-host bundle
  прежних и candidate `.deb`, изолированная обратная APT-симуляция и
  независимый монитор проверены. **Package steps не начаты:** gate A
  независимой console и согласованное окно E остаются unconfirmed;
  актуальные pre-change B/C/D проверяются непосредственно перед группой.
- 491.3 Обновление kernel и reboot выполнять только после отдельного решения
  владельца, подтверждённого console-доступа и окна недоступности; проверить
  загрузку, автозапуск контейнеров и повторные public/worker checks. — `todo`

## Этап 492. Воспроизводимые Python dependencies и security audit — `supervisor_pending`

Checkout `dev/stage-492-dependencies`, base `e5d00f92`. Snapshot и
candidate audit реализованы; полный working-diff Astra/Kimi review, default
(5221 passed), PostgreSQL (8 passed) и clean amd64 builds прошли. Внешний
gate приёмки: выделенный read-only production audit credential/forced command
и фактический scan всех работающих workers после обновления в отдельном окне.
До него parity с production не подтверждена; новые advisory или drift — стоп.
Production не обновлён, 493 начинает куратор только после принятия snapshot.
[PRD](PRD/этап-492-python-dependency-snapshot-audit.md).

Исходное расхождение `cryptography` между Dockerfile и `pyproject.toml`
устранено: обе сборки используют экспорты с hashes из одного `uv.lock`.

**Риски и стоп-условия.** High: разные установки в `base`, `production`,
`test` и отдельный `anyio` install могут сохранить расхождение даже при lock;
hashes одной архитектуры/Python ABI могут сломать clean build. Snapshot должен
покрывать весь транзитивный граф нужных production/test окружений и платформ,
включая wheel/sdist правила; production image проверяется отдельно. Medium:
зелёный `pip-audit` не означает полную безопасность. До 493 прежние четыре
finding остаются явно известными и временно принятыми, новые findings без
разбора блокируют release; 492 не выдаётся за security-fix.

- 492.1 Сделать единый воспроизводимый dependency snapshot с hashes,
  синхронизировать ограничения Dockerfile/pyproject и отдельные anyio install,
  проверить clean production/test builds на целевых архитектурах и применимые
  default/real gates. Несоответствие фактического production окружения
  snapshot — стоп. — `supervisor_pending`
- 492.2 Добавить `pip-audit` фактического зафиксированного production
  окружения в регулярную проверку, закрепить политику известных/новых findings
  и версию самого сканера. Не включать автоматическое обновление production,
  не подавлять findings молча и не выдавать Python audit за полный container
  OS scan. — `supervisor_pending`

## Этап 493. Python 3.12.16 и cryptography 50 security release — `todo`

MCP container использует Python 3.12.15 и `cryptography 46.0.7` с OpenSSL
3.5.6 в wheel. Python 3.12.16 — security release; четыре уникальных finding
`pip-audit` для cryptography полностью закрываются версией 50.0.0. Прямой код
MCP использует только `Fernet`, но это не отменяет обновление. Текущий GHCR
`python:3.12-slim` всё ещё указывает на прежний digest с Python 3.12.15.

**Риски и стоп-условия.** High: новый GHCR digest может изменить не только
Python, но и OS-пакеты; tag не доказывает происхождение. Major upgrade
cryptography может затронуть транзитивных потребителей и ранее зашифрованные
данные. Critical при неверном rollback: deploy запускает `alembic upgrade`, и
возврат старого image не откатывает схему/данные. Остановить выпуск при
непроверенном digest/содержимом, несовпадении версий в production image,
прежних audit findings, ошибках Fernet/OAuth или неподтверждённой
совместимости старого image со схемой. Новые миграции БД выходят за scope;
автоматический DB rollback запрещён.

- 493.1 Сначала опубликовать base image с проверенным источником и Python
  3.12.16, затем обновить immutable digest и `cryptography>=50,<51` в MCP после
  этапа 492. Проверить версии и содержимое именно production image, чтение
  ранее зашифрованных данных, Fernet/OAuth/auth и транзитивные зависимости.
  Сохранить прежний image/digest и rollback manifest; подтвердить, что старый
  image совместим со схемой после deploy. Провести полные default/real gates,
  повторный `pip-audit`, deploy, public smoke и мониторинг; мажорную ветку
  Python одновременно не менять. — `todo`

## Этап 487. Scheduled Claude: диагностика доступности коннектора (#180) — `stop`

По переданной клиентом проверке 12.11 scheduled-запуск в 08:06:40 UTC не дал
запросов `Claude-User` в nginx и завершился без данных. Ручной запуск той же
задачи в 08:32:48 UTC дал такие запросы и данные клиники. Это подтверждает, что
scheduled-запуск не дошёл до MCP, а ручной дошёл; более конкретный внутренний
механизм Anthropic не установлен. Серверная диагностика и implementation не
требуются: runtime, таймауты, токены и retry не меняем. Workaround — ручной
`Run now` или ручное сообщение; повторную проблему эскалировать в Anthropic с
временами запусков. Отдельный timeout `get_medical_cards_by_date` не закрыт и
не относится к этому выводу. #139 с другими транспортными признаками не
привязываем к этому результату.

- 487.1 Контролируемое сопоставление scheduled/manual выполнено клиентом;
  серверные работы прекращены по внешнему владельцу сбоя. — `stop` 21.11.2026

## Этап 488. Report AI: semantic guardrails и классификация услуг (#307/#329) — `done`

Документный этап для prompt helper и связанных инструкций, а не универсальный
классификатор номенклатуры и не исправление upstream. В #307 recognized-структура
посчитала медкарты вместо уникальных дней; в #329 агрегат потребовал
классификации реальной номенклатуры клиники.
[PRD](PRD/этап-488-report-ai-semantic-guardrails.md).

- 488.1 До сохранения или выдачи ответа проверять соответствие recognized-метрики
  запросу. Для уникальных дней требовать явного подтверждения distinct по дате;
  при несоответствии не выдавать количество карт как ответ, а использовать
  проверенный direct-read fallback либо обозначить ограничение. — `done` 21.11.2026
- 488.2 Задокументировать порядок для приёмов, операций и койко-дней: прочитать
  реальную номенклатуру, показать критерии и исключения, неоднозначную
  классификацию уточнить у клиники. Не относить анестезию и расходники к
  операциям и не заменять койко-дни числом медкарт. — `done` 21.11.2026

## Этап 486. Проверяемый live harness stage361 — `done`

[PRD](PRD/этап-486-live-harness-stage361.md). Test-only усиление после controlled
probe, без вывода raw description/PII и без изменений production runtime.

- 486.1 Offline red/green guards и harness. — `done` 21.11.2026
- 486.2 Strong review, focused devtr6, свежий strict real aggregate, commit и
  committed-diff review. — `done` 21.11.2026
  Focused stage361 passed, real aggregate 147/147, восемь свежих групп,
  cleanup 0; оба committed-diff reviewer дали валидные verdict на полном diff.
  Их блокирующие замечания закрыты адресными guards, real aggregate и Spark
  scout после исчерпания strong-бюджета; evidence — AssumptionLog.

## Этап 485. Постоянный upstream contract повторного Report AI intent — `done`

Решение владельца 20.11 заменило временное исключение: ВМ может вернуть
matched старый отчёт с иной recognized structure; MCP принимает его и отдаёт
читаемые данные. [PRD](PRD/этап-485-постоянный-upstream-contract-report-ai.md).
Старые красные JUnit сохраняются как историческое evidence. Stage 420 и 422
используют общий helper. По новому решению владельца после восстановления
сети группы 422, export и workers повторены последовательно и прошли; причина
прежних отказов вероятно сетевая/нагрузочная, но не доказана однозначно.

- 485.1 Обновить live oracle и offline guards, удалить временное aggregate
  исключение, синхронизировать inventory и evidence. — `done` 20.11.2026
- 485.2 Focused/owning/fast/default, сильное ревью, адресные real группы и
  strict aggregate; commit/push только при полностью зелёных gates. — `done` 20.11.2026
  Focused 64 passed, fast 3671 passed, default 5103 passed; real aggregate
  140/140, cleanup 0, без skips. Evidence — AssumptionLog.

## Этап 478. Адресные CI-контуры без повторов длинных suites — `done`

Источник: решение владельца 17.11.2026. До новых продуктовых правок устранить
многочасовую стоимость малых и документных изменений. По разбору 30 последних
закрытых задач 21 могла использовать адресные контуры, 7 требовали полного
набора, 2 не требовали продуктовых suites.

- 478.1 PR 478A: жёсткий docs-only путь; долгие проверки один раз на один tree
  SHA; main не повторяет зелёный PR suite при совпадающем дереве; отмена
  устаревших PR runs; baseline времени и числа запусков. — `done`
  PR #42 merged, merge SHA `c0cb9f9e1d4d5cbf9b3af60a0f75d3f7efd3512e`.
  Локальный default 4922 passed, PostgreSQL 8 passed; PR и main Tests success.
  Main получил обязательный `force_full`, поскольку изменилась CI decision
  surface. Позднее reuse без `force_full` подтверждён run `44273986008`.
- 478.2 PR 478B-1: ранний inventory preflight и CI-only deploy scope. Проверять
  drift versioned inventory до pre-freeze review и долгого default, включая
  новые nodes и переименования. Не запускать production deploy для строго
  классифицированных CI-only workflows/scripts/tests; unknown путь — fail-closed
  на deploy. Добавить guards для unknown путей и новых test nodes. Отдельный
  обязательный сценарий: отменённый CI-only deploy, затем docs-only merge.
  До исправления diff от последнего успешного deploy накапливал отменённые
  CI-изменения и запускал rollout на следующем docs-only PR. Baseline edge case
  закрыт классификацией всего накопленного diff и marker фактического SHA.
  [PRD](PRD/этап-478-2-ранний-inventory-и-ci-only-deploy.md), evidence —
  AssumptionLog. — `done` 18.11.2026
- 478.3 PR 478B-2: версионируемая `test_impact_map.json`; fast + owning +
  затронутые контуры; shared/unknown fail-closed на полный набор; исключение
  повтора fast внутри default с полным aggregate/coverage. В `super-review`
  добавить роль `test-contours` для проверки карты, fail-closed выбора,
  отсутствия потери nodes/skip, инвалидации и границ PR/main/nightly. — `done` 18.11.2026
  [PRD](PRD/этап-478-3-адресные-ci-контуры.md); fast3588 + remainder1432 =
  full5020 без потерь/дублей, штатный default5020, PostgreSQL8; все обязательные
  локальные gates exit0. Review evidence и handoff — AssumptionLog.
  EOF whitespace blocker закрыт узким follow-up: AST/bytecode без изменений,
  focused29 exit0; release-review follow-up сохранён в AssumptionLog.
- 478.4 PR 478B-3: nightly полный regression, сохранение JUnit/outcome и
  измерение фактического сокращения времени и числа запусков относительно
  baseline. [PRD](PRD/этап-478-4-nightly-regression.md). Локально: default
  5035 passed (resume1), PostgreSQL 8 passed, cleanup 0. Nightly
  `44274336409` на main подтвердил полный aggregate 138/138; измеренный эффект
  отдельных CI runs записан в AssumptionLog. — `done` 18.11.2026
- 478.5 Приёмка на docs-only, isolated tool, shared runtime и unknown file;
  ручной запуск nightly. `PR validated-tree → main reuse` проверен без
  `force_full` на обычном изменении, которое не меняет CI decision surface.
  Одинаковый долгий suite не выполняется дважды на одном tree SHA; обязательные
  GitHub checks и полнота покрытия сохраняются. Локальная матрица selector
  совпала с PRD; main exact-tree reuse подтверждён run `44273986008`.
  Isolated whoami PR #49 merged; PR run `44309201311` successful. После
  исправления перегруженного fast(0) PR #51 merged (`20feea8`): run
  `44354585778` successful, max fast wall 101 с при пороге 110 с.
  Follow-up PR #52: три корневые инструкции (`AGENTS.md`,
  `AGENT_ONBOARDING.md`, `CLAUDE.md`) добавлены в жёсткий docs-only путь двух
  селекторов; unknown остаётся full. PR #52 merged (`46e8e4f`), а docs-only
  PR #50 merged (`4dd3104`): run `44371753784` successful, product jobs skipped.
  Production `20feea8` deployed, 30 минут healthy по переданному evidence.
  Измерения и границы проверки — AssumptionLog. — `done` 18.11.2026
- 478.6 Follow-up: дополнить fail-closed deploy scope подтверждёнными CI-only
  входами и агентскими документами после Deploy Prod `44375497970`.
  [PRD](PRD/этап-478-6-deploy-scope-ci-inputs.md). Red/green, fast, полный
  default, ShellCheck и pre-review завершены; evidence — AssumptionLog. — `done` 18.11.2026

Nightly запускается из main по расписанию `17 23 * * *` (около 02:17 МСК) и
вручную через `workflow_dispatch`: один Docker image, полный
default/PostgreSQL и изолированные real/browser-группы, последовательный
devtr6, cleanup и единый aggregate без пропусков. Production не меняется;
JUnit/outcome сохраняются для утреннего triage.

## Этап 479. Количества Report AI без ложной маски телефона — `done`

Подтверждённый локальный класс #156: [PRD](PRD/этап-479-количества-report-ai.md).
Отдельный поезд по решению владельца 19.11.2026; граница числового исключения
проверена, контактные данные остаются под маской. Владелец 19.11 разрешил
выпуск с исключением одного красного real-узла
`test_stage420_live_dedup_repeated_intent`: старый upstream match дал 0 строк,
seed — 12 строк с zero-fill. Raw evidence сохраняется; исключение нельзя
распространять на другие узлы или считать зелёным прохождением 483.
Выпускная сверка: 131/132 passed, 1 явно исключённый failed, 0 skips;
6 optional-auth узлов не настроены. Семь остальных real групп зелёные.

- 479.1 По отдельному PRD показать красные сторожа количества и настоящего
  телефона; исправить локальную очистку и провести живую проверку на стенде.
  PR #59 merged `fabfa8a6`; production smoke и мониторинг чистые.
  — `done` 21.11.2026

## Этап 483. Устойчивый критерий live dedup stage 420 — `done`

По решению владельца до выпуска 479 уточнить критерий повторного intent на
основании сохранённых jobs: [PRD](PRD/этап-483-стабильный-dedup-stage420.md).
Положительный exact-intent guard сохраняется; `ready_to_save` требует
доказанно отличающуюся структуру. Для `existing_report_matched` новое
решение владельца 20.11 задаёт постоянный upstream contract в этапе 485:
старый отчёт с иной recognized structure принимается и читается.

- 483.1 Красный oracle и адресные проверки выполнены; прежнее ожидание
  ответа ВМ заменено решением владельца этапа 485. — `done`

## Этап 484. Пригодность existing_report_matched на стороне MCP — `done`

[PRD](PRD/этап-484-пригодность-existing-report-match.md). Решение владельца
20.11.2026 — вариант В, совместимый с постоянным контрактом 485: старый
matched-отчёт с другой recognized structure и корректный пустой результат
остаются успешными; fail-closed
только на явной непригодности чтения данных или ссылки. Выбор upstream-кандидата
остаётся вопросом ВМ.

- 484.1 Контракт/runtime, guards и PRD согласованы с решением владельца.
  На base 486: inventory 5140, owning 191, fast 3708, default 5140, live GET
  корректного пустого match успешен; real aggregate 147/147, восемь групп,
  cleanup 0, skips 0. Commit `b50ce6c7` прошёл committed-diff review Spark,
  Astra и Kimi без findings и отправлен в `origin/dev/stage-484-match-suitability`.
  PR/merge/deploy — куратор. — `done` 21.11.2026

## Этап 480. Названия номенклатуры Report AI без ложной маски имени — `done` 21.11.2026

Подтверждённый локальный класс #177 и гипотеза о связи с #160:
[PRD](PRD/этап-480-номенклатура-report-ai.md). Вне поезда 479. Владелец
21.11 утвердил доверенные источники `good.title`, `goodTag.title`,
`goodGroup.title`, `unit.title`, `comboManualName.title`. Разрешена только
точная сверка полного значения с каталогом; только общий шаблон трёх
прописных слов может быть отменён по решению владельца, остальные сторожа ПДн
сохраняются. Остаточный риск неизвестного ФИО в каталоге принят владельцем.

- 480.1 По отдельному PRD показать красные сторожа названия номенклатуры и
  настоящего имени; исправить локальную очистку и провести живую проверку на
  стенде. JSON/CSV parity, default 5207/5207, real aggregate 143/143 и
  read-only live HTTP 200 подтверждены; committed review и push — release gate.
  — `done` 21.11.2026

## Этап 481. Новый intent #170 после terminal failed — `done` 21.11.2026

Владелец 21.11 свёл этап к unit-тесту без реального ВМ. Защищаем только MCP:
новый более простой intent после failed отправляется отдельным POST, не
блокируется локально и не подменяет ответ upstream. Изменчивое поведение ВМ и
реальный recovery не проверяются. Прежний devtr6 exact-dedup сценарий —
историческое evidence, не gate.

- 481.1 Добавить синтетические unit-случаи recovery и upstream rejection,
  доказать их красными мутациями; real API, live ВМ и новые jobs не нужны.
  [PRD](PRD/этап-481-повтор-report-ai-после-failed.md). — `done` 21.11.2026

## Этап 482. Docs-only main: проверка предыдущего успешного Tests run — `done`

После merge 471+472 `previous_main_success` с `status=success` вернул пустой
список при существующем успешном run без этого фильтра. Fail-closed селектор
запустил полный suite: безопасная избыточность, а не пропуск проверок.

- 482.1 Отдельным техническим поездом установить причину расхождения API,
  добавить красный guard на существующий success и на отсутствие/ошибку
  evidence; исправить селектор без fail-open. Проверить docs-only main и
  обязательные CI-контуры по отдельному PRD. — `done`

## Этап 474. Данные для черновика выписки из медкарты (#159) — `done`

- 474.1 Read-сценарий доступной истории одного пациента за период. Агент
  составляет текст; сохранение только отдельно по желанию через
  `create_medical_card`. Чтение вложений не входит до API ВМ.
  На base `e12f97c` default 5191/5191, живой READ 1/1 с девятью GET 200,
  strict real aggregate 149/149 по восьми свежим группам, cleanup 0.
  Первый export был ограничен upstream; после полного guard window адресный
  повтор прошёл 3/3. Evidence — AssumptionLog.
  [PRD](PRD/этап-474-черновик-выписки-из-медкарты.md). — `done` 21.11.2026

## Этап 475. Изменение статуса пациента (#162) — `done`

- 475.1 Отдельная чувствительная write-операция: PRD, права, двойное
  подтверждение, read-back, красные сторожа и живая проверка. — `done` 21.11.2026
  [PRD](PRD/этап-475-статус-пациента.md): решения владельца от 20.11 получены.
  На base 32e5b97: default 5164/5164; живой 475 и cleanup passed; свежий
  strict real aggregate 142/142 по восьми группам. Ревью и evidence — AssumptionLog.

## Этап 476. Security design автоматизированного доступа (#175/#176) — `done`

- 476.1 Только product/security design server-to-server/local CLI, scoped
  credentials и bulk access. По решению владельца 21.11 реализация отложена до
  нового фидбека; отдельного этапа в очереди нет. — `done`

Вне очереди: корневые исправления ВМ #151–154, PREVIEW_FAILED (#179, #264,
#328), распознавание уникальных дней (#307), чтение сохранённого отчёта (#312),
чтение вложений #159, Telegram #167/#169. Владелец явно отмечается как ВМ;
активного ожидания нет, новый MCP-этап возможен только при самостоятельной
работе или новом контракте. Для #307 этап 488 ограничен проверкой результата
и безопасным fallback.

Без нового этапа: #316 — оценка без комментария, причина неизвестна;
#173/#174 — ждут повторного воспроизведения после диагностики 472;
#264 — специальный финансовый агрегат по решению владельца не делаем.
Универсальный классификатор услуг по #329 не строим. Для timeout медкарт #180
новой работы нет: tool-specific timeout отсутствует, общий read timeout 20 с
без доказанной причины не увеличиваем.

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
в Roadmap. Каждый pre-freeze strong review проверяет весь актуальный diff.
После завершённого 464 этапы **469 + 470 идут одним поездом и одним PR**;
текущий общий fingerprint до 469 остаётся обязательным. После deploy — 60
минут мониторинга каждые 10 минут, обновление дашбордов и разбор нового фидбека.
Очередь: **461 → 462 → 464 → (469 + 470)**.

