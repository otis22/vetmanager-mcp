# PRD 478.4/478.5 — nightly regression и приёмка CI

## Цель

Каждую ночь на `main` выполнять полный regression без потери test nodes,
сохранять проверяемые JUnit/outcome и давать утренний triage. Подготовить
приёмку адресных PR-контуров и точного reuse дерева. Ветка
`dev/roadmap-478b-3`, base `6ea4fe30b7d1bcce0a4630a0d3dd61feecf548f1`.
Куратор запускает manual nightly, проверяет GitHub/CI и выполняет merge.

## Проверенные факты и baseline

- `test.yml`: inventory preflight до default, versioned impact plan, fast +
  remainder с JUnit union и coverage; `validated-tree` только после full PR.
  `ci_scope.py` сверяет exact tree и workflow blob; main меняет решение при
  изменении CI decision surface.
- `run_isolated_test_suite.py` создаёт отдельный Compose project, очищает его
  через `down -v`, закрепляет image ID для групп и валидирует real shards.
  `real_group_gate.py` требует ровно все группы, JUnit без skip/failure/error,
  outcome без пропусков, совпадающие fingerprints и успешный cleanup.
- `test-real.yml` использует GitHub secrets тестового контура; nightly повторяет
  имена secrets, не публикуя значения. Нужны API key и login/password для
  `prepare_real_test_auth.py --require-all`.
- PR #46: default 9m22s, fast shards 1m0s–2m6s, fast aggregate 52s,
  inventory 52s, PostgreSQL 1m23s. PR #45: default 17m9s, fast 3m34s,
  PostgreSQL 2m20s. Это baseline отдельных jobs, не измерение экономии.
- Главный PRD и technical requirements сохраняют Docker тестовым runtime;
  MCP API, продуктовый runtime и production данные в этом этапе не меняются.

## Архитектурное решение

Отдельный `nightly.yml` с `schedule: '17 23 * * *'` (UTC) и `workflow_dispatch`
запускается на `main` в одном job с проверкой `github.ref == refs/heads/main`
для обоих событий. Строит один test image, выполняет ранний
inventory preflight и затем полный default, PostgreSQL и все группы
`real_group_manifest.json` последовательно. Все real/browser группы идут
через существующий isolated runner с отдельными Compose projects и cleanup.
Nightly orchestration продолжает независимые группы после безопасного отказа.
Если `write-restore` failed, cleanup не подтверждён, shard/outcome отсутствует
или состояние upstream неизвестно, следующие real/browser группы не стартуют;
они отмечаются blocked. Источник решения — exit/summary и shard isolated runner;
всякая ошибка чтения считается небезопасной.
Aggregate затем возвращает nonzero. Aggregate
никогда не превращает failed group в success. Artifact загрузить с `always()`:
только очищенные JUnit/outcome и summary по allowlist. Raw logs и исходные
JUnit остаются на эфемерном runner и не загружаются: JUnit экспортируется как
testcase ID/status без stdout, stderr, failure body/attributes; outcome —
только counts и статусы статических node IDs. При невозможности очистить
или проверить allowlist artifact отсутствует, job failed. Секретные auth/runtime
env, key и raw evidence не входят в artifact. Retention — 7 дней; artifact
содержит только данные из публичных статических test IDs и фиксированные
категории, доступные читателям Actions репозитория. Workflow permissions —
`contents: read`. Console steps получают только
краткие статусы: stdout/stderr runner пишутся в приватные файлы, не в GitHub
Actions logs. Очищенный JUnit сохраняет node ID, status и категорию ошибки
из закрытого словаря; triage находит failing node и назначает адресный повтор.
Markdown summary показывает status/exit каждой группы, длительность и
aggregate. Обязательные DOMAIN/API_KEY и image проверяются fail-closed;
optional user-auth coverage учитывается явно по контракту resume2 ниже.

Оба workflow, `nightly.yml` и ручной `test-real.yml`, используют общий
concurrency group для devtr6/общих upstream resources; даже ручной запуск
на другом test domain сериализуется консервативно. `cancel-in-progress: false`.

Один runner и один image дают простую привязку image ID для всех групп и
последовательный доступ к общему devtr6. Параллельные jobs нарушили бы
upstream ownership. Объединённый `--suite all` не подходит: real nodes там
не сверяются с полным group manifest.

## Декомпозиция

1. PRD, Architecture Critique и deterministic gates (≤2 ч).
2. Test-first guards для schedule, последовательности, единого image,
   aggregate, artifact privacy и exit semantics (≤150 строк за шаг).
3. Nightly orchestration и workflow; JUnit/default и PG manifest evidence
   без ослабления `-W error`/coverage (≤150 строк за шаг).
4. Локальная матрица 478.5, финальные gates, review, commit и handoff (≤2 ч).

## Acceptance и guards

- Schedule и manual dispatch только с main; один image build и один image ID
  для default/PG/real, ранний inventory до дорогих suites.
- Default и PG — полные штатные контуры, JUnit и fingerprint/coverage.
  Real/browser manifest покрыт полностью, группы строго по очереди; devtr6
  никогда не используется параллельно в этом workflow.
- Каждый isolated project очищен; aggregate требует все groups, no skip,
  valid JUnit/outcome и fingerprints. Missing/failed group, cleanup,
  artifact или aggregate дают failed job и понятный summary.
- Сырые real logs/JUnit не выгружаются. Artifact sanitizer удаляет тела и
  произвольные атрибуты; allowlist и статические node IDs проверяются тестом.
- Ручной test-real и nightly не пересекаются во времени на общем стенде.
- Отказ `write-restore` или неподтверждённый cleanup блокирует дальнейший
  upstream; guard ловит продолжение. Manual dispatch на иной ref отвергается
  до сборки. Job имеет timeout; следующий запуск использует новый runner.
- Guard намеренно красный при удалённой группе, skip/failure JUnit, неверном
  image ID, переставленной последовательности, исчезнувшем cleanup и
  успехе aggregate поверх failed group.
- Приёмочная матрица: docs-only; isolated tool; shared runtime; unknown file;
  manual nightly; full PR validated-tree → main reuse на обычном change без
  `force_full`. Установить по реальным GitHub jobs/tree SHA, что долгий suite
  не повторяется на том же дереве. Mandatory checks/coverage сохраняются.
- Длительность и число запусков измерить по GitHub job timestamps и runs
  после merge; привести к baseline #45/#46 по сопоставимым сценариям. До
  реальных run не объявлять процент экономии.

## Приёмочная матрица 478.5

| Сценарий | PR | main | Evidence куратора |
| --- | --- | --- | --- |
| docs-only | product jobs отсутствуют; structural check success | product jobs отсутствуют при previous green | changed paths, scope output, job list |
| isolated tool + owning test | fast shards/aggregate, owning remainder, coverage; PostgreSQL только по карте | full suite, поскольку marker для isolated PR отсутствует | impact-plan, JUnit union, coverage XML, job list |
| shared runtime | fast + полный remainder/default + PostgreSQL, validated-tree | exact-tree reuse при одинаковом tree/workflow blob и зелёном PR | tree SHA, PR run ID, marker, main scope output и отсутствие повторных долгих jobs |
| unknown file | fail-closed full offline + PostgreSQL | full или exact-tree reuse только при доказанном full PR | impact-plan reason, job list |
| manual nightly | полный default/PG и все real/browser группы последовательно | запуск только main | run ID, image ID, JUnit/outcome/summary, все группы и cleanup |

Отдельный обычный PR после merge B-3 проверяет `PR validated-tree → main reuse`
без `force_full`: B-3 сам меняет CI decision surface и ожидаемо заставит
main сделать полный проход. Куратор сравнивает tree SHA, `validated-tree`
artifact, workflow blob и job IDs/длительности. На одинаковом tree SHA
долгий suite имеет один фактический запуск; обязательные GitHub checks и
coverage XML проверяются отдельно. Локально проверяются решения selector и
guard; GitHub evidence после merge собирает куратор.

Для измерения взять `started_at`/`completed_at` GitHub jobs и число jobs
каждого контура в PR и main для каждого сценария; отдельно записать критический
путь от trigger до окончания обязательных checks. Сравнивать PR #45/#46 только
с эквивалентным сценарием и тем же набором checks, указав SHA/run IDs. Число
сэкономленных запусков и времени вычислить после реальных прогонов.

## Rollout и rollback

Workflow появляется в main после merge; первый manual nightly и schedule
проверяет куратор. Если нет полных credentials или real group падает, workflow
остаётся failed с артефактом; исправление отдельным PR после triage. Rollback
— revert nightly workflow и orchestration; текущий PR/main `test.yml` и
обязательные checks продолжают работать. Production deploy не нужен.

## Оценка простоты

Один job и reuse существующего isolated runner минимизируют новую логику.
Orchestration нужна для продолжения после отказа и единого nonzero результата;
одних YAML `continue-on-error` и `always()` недостаточно для полного aggregate.

## Resume2: контракт доступной auth-конфигурации после первого manual run

Факт: PR #47 merged, base follow-up `d9fccf93277b7b255c96a837120d86b83e8129a2`.
Manual nightly `44259134829` собрал image, но остановился на preflight: имеются
только TEST_DOMAIN/API_KEY; optional token/login/password отсутствуют. Значения
GitHub secrets не запрашивались. Текущий test-real и opt-in runner поддерживают
API-key-only; требование login/password для всего nightly ошибочно.

Исправление: preflight требует только DOMAIN/API_KEY и валидный image. Для
isolated group auth preparation использует `--require-api`, сохраняет получение
user token из login/password, если они заданы. Для шести existing user-auth
nodes в auth-web план по фактическим credentials явно различает configured
и not-configured: пять login/password nodes (включая browser) и один direct-token
node. Login/password также могут дать token для direct-node через существующий
prepare helper. Восемь групп и все API-key nodes, включая write-restore,
остаются обязательными. Неизвестные auth requirements, пустая группа или
исключение обязательного node — fail-closed.

Полная collection всё ещё сверяется с оригинальным manifest. Исполняемый
manifest содержит configured nodes; исходный набор равен их точному union
с явными not-configured nodes. Plan сохраняется в очищенный artifact и summary;
aggregate проверяет все группы выбранного manifest строго без пропусков,
с JUnit/outcome/fingerprints/image/cleanup. Его успех обозначает успех всех
configured tests, не полную проверку отсутствующего auth. Изменение credentials
меняет plan hash и contour identity, поэтому старые shards не переиспользуются.
Partial login/password — явная ошибка конфигурации, как в opt-in runner.
Общий nongroup `--suite real/all` контракт не меняется.

Guards: API-key-only/image проходит preflight; отсутствие DOMAIN/API_KEY/image
отклоняется; optional пустые значения не блокируют API nodes; partial login
отклоняется; шесть not-configured nodes перечислены, write-restore сохранён;
полный auth возвращает весь исходный набор; malformed auth map и исключение
required node отклоняются; aggregate не принимает skip в configured node или
неполную группу. Rollout: новый CI-only PR, повторный manual nightly main
куратором; rollback follow-up возвращает strict failure с понятным отчётом.

Уточнение источника плана: isolated runner получает Compose-effective test
service environment через captured `docker compose config --format json`, включая
переданные env-files и host precedence; результат с credentials не печатается.
До selection проверяется полный исходный manifest; shard записывает hash
именно effective manifest с not-configured mapping. Aggregate заново получает
конфигурацию, выводит тот же план и сверяет effective hash, exact nodes и
contour identity. Исходный manifest и selector уже входят в fingerprint через
shared helpers/контурные входы. Для preflight основной nightly поддерживает
только фиксированные TEST_DOMAIN/API_KEY и optional TEST_USER_*; никакие иные
имена credentials не вводятся. Следующие разделы resume2 заменяют прежнее
требование всех optional secrets: обязательны только API settings/image;
optional auth coverage отражается отдельно от успеха configured suites.
Collection-only API-key-only проверяется локально без живых запросов.

Интеграционные точки (обязательные acceptance): `configured_manifest` возвращает
effective manifest и полный not-configured map. Его `groups` используется не
только aggregate: group nodes JSON, shard nodes/hash, finally validate_shard,
nightly group_evidence_complete и оба artifact sanitizer получают именно
выбранные nodes. Оригинал остаётся только для полной collection/проверки карты.
По Compose-effective environment selector считает user-token доступным при
наличии token **или обеих LOGIN/PASSWORD**, поскольку существующий prepare
обязательно получает token до исполнения; сбой exchange завершает группу,
а не переводит node в not-configured. LOGIN/PASSWORD неполная пара вызывает
ошибку selection до запуска suites. BASE_URL может быть получен prepare,
поэтому отсутствие BASE_URL при полной паре не исключает login nodes.
Карта проверяется AST guard по фактическим существующим декораторам skip,
включая login-only `test_real_get_users_with_user_token_mode`, несмотря на имя.
Новые skips внутри configured группы по-прежнему являются ошибкой.

## 478.5: isolated tool acceptance, 18.11.2026

Куратор подтвердил nightly main `44274336409` (138/138) и main exact-tree
reuse `44273986008`. Повторять nightly и менять CI decision surface для этой
приёмки не требуется. Проверяем обычный isolated tool PR на ветке
`dev/roadmap-478-acceptance` от `dc06f7cabd3d993c7f9e3d72e227157d39a72a51`.

Полезное изменение ограничено описанием `whoami`: `limits.requests` и
`limits.window_seconds` показывают настроенный лимит запросов текущего
credential, а не остаток квоты. Ответ, поля, права, значения лимитов и другие
инструменты остаются прежними. Существующий owning test проверяет
экспортируемое описание после регистрации. Сначала он падает на старом тексте,
затем проходит после уточнения. Новые test nodes не добавляются.

Локальная приёмка: focused red/green, owning файлы, fast, inventory/count/
fingerprint/diff-check и живой вызов `whoami` на тестовом стенде с безопасным
кодом и телом ответа. Затем полный pre-freeze review актуального diff,
archive/structure, commit, committed-diff release review и push. Монолитный
default для этого isolated change не запускается по адресной матрице 478.5;
GitHub jobs, coverage и PR/main reuse принимает куратор. Scope не включает
auth-discovery B-3, scripts, workflow, impact map или inventory.

Оценка простоты: одно уточнение описания и один усиленный существующий test node.
Architecture Critique: not required — auth, storage, API response, production
behavior и ownership boundaries не меняются. Куратор создаёт PR и выполняет
merge, deploy и monitoring после локальной передачи evidence.

## 478.5 follow-up: запас fast(0), 18.11.2026

После merge isolated `whoami` PR #49 fast(0) прошёл все 452 теста, но main
`44311047772` дважды превысил неизменный wall guard 180 с: 210 и 222 с.
Тот же shard в PR `44309201311` занял 160 с. Непосредственная причина отказа
CI — превышение wall guard при успешных тестах. Подтверждённый фактор риска —
дисбаланс shard: алгоритм раскладывает файлы по **числу** nodes,
не по времени; fast(0) содержит `test_stage459_server_child_inventory.py`.
JUnit успешного PR даёт этому файлу 66.69 с из 119.15 с testcase time shard 0;
остальные shards имеют 0.78–26.02 с testcase time. Это измерение одного PR,
не прогноз каждого будущего запуска. Main JUnit с durations отсутствует, поэтому
источник разброса 160→222 с доказать нельзя.

### Архитектурное решение и декомпозиция

Вынести целый scanner-файл в отдельный fast shard 10, сохранив восемь обычных
shards и два существующих clean-process shards. После отдельного TLS failure
два дополнительных runners минимально изолируют оба файла от обычных shards.
После первого локального прогона оставшийся shard 0 занял 128 с wall (100.35 с
pytest): для запаса относительно наблюдаемого spread 62 с перенести два
проверенно дорогих файла `test_stage384_retuning.py` и
`test_stage111_blocker_cleanup.py` целиком в лёгкий shard 2. Они заняли
23.38 с testcase time локального shard 0; в PR JUnit — 14.58 с. Shard 2
до переноса имел 10.62 с testcase time в том же PR JUnit. Это фиксированный
адресный перенос по измерению, без нового scheduler.
Во втором локальном shard 0 после переноса 433 tests прошли и два TLS loopback
nodes упали на `ConnectionResetError`/`ResourceWarning` при закрытии socket;
оба node по отдельности и owning file (3 tests) прошли. Это указывает на
зависимость от длинного процесса/порядка, но не доказывает конкретный upstream
дефект. Чтобы сохранить строгий `-W error` и сами assertions, перенести весь
TLS loopback файл из shard 0 в собственный shard 11: Kimi pre-freeze review
справедливо указал, что scanner может сделать общий процесс длинным и одна
локальная зелёная попытка этого не опровергает. После этого проверить оба
затронутых shards адресно; красный повтор блокирует выпуск.
Вариант переноса файла в менее загруженный shard отвергнут: при наблюдаемом
разбросе 62 с его запас до guard нельзя уверенно обосновать. Вариант менять
timeout, повторять job или перераспределять по числу тестов не устраняет
измеренную проблему. Вариант нового duration scheduler требует новых входных
данных и логики, которых пока нет.

Инварианты: каждый fast node исполняется ровно один раз; inventory/fingerprint,
JUnit union, coverage aggregate, warning policy и 180 с guard остаются
fail-closed. Количество nodes и versioned inventory не меняются. Поскольку
изменяются CI script/workflow, main после merge выполняет полный контур.
При успешных tests и красном wall guard загрузить уже созданные JUnit,
fingerprint и coverage как диагностический artifact, не меняя failed status;
при failed tests artifact не публиковать. Aggregate отвергает лишние shard
directories, даже если ожидаемый union совпадает.
Rollback — revert этого CI-only изменения, если новая схема нарушит union или
coverage. При повторном wall failure revert сам по себе не восстанавливает
зелёный main: остановить приёмку и сделать адресный CI-only hotfix по durations
нового run, сохраняя guard. Ручной rerun старого main и ослабление лимита не
считаются fallback.

1. Guard и mutation red для отдельного scanner shard, точного union и CI
   matrix; owning suite, fast (≤150 строк).
2. Обновить partition, count, workflow; focused green, audit и deterministic
   checks (≤150 строк).
3. Полный diff review, default/PostgreSQL, archive, commit, release review,
   push; GitHub/deploy приёмка куратором (≤2 ч).

### Acceptance, simplicity и Architecture Critique

По PR JUnit после выделения scanner и переноса трёх файлов оценка прежнего
shard 0: 119.15−66.69−14.58−1.44 = 36.44 с testcase time. Новый максимум
shard 10 — 66.69 с testcase time, на 44.0% меньше
старого максимума 119.15 с. Его фактический PR wall
160 с не раскладывается точно по файлам: до GitHub run нельзя выдавать 36.44 с
за wall. Необходимое
подтверждение запаса — локальное исполнение новых shards и сохранённый guard;
новый GitHub PR должен показать максимум новых fast shards ≤110 с wall (запас
не менее 70 с до guard, больше наблюдаемого spread 62 с). Это эмпирическая
граница по доступным трём wall observations, не верхняя оценка будущего jitter.
Если PR не покажет этот запас, куратор не принимает
балансировку и нужен отдельный анализ durations нового run. Повтор того же
failed main run запрещён. Main после merge отдельно подтверждает полный
контур на новом decision surface. Ни один локальный замер не объявляется
гарантией времени GitHub runner.
Локально до выделения TLS в отдельный процесс affected shards 0/2/10 дали
wall 111/57/41 с; финальные measurements повторить для 10/11;
максимум 111 с оставляет 69 с до guard, на 7 с больше наблюдаемого PR→main
spread 62 с. Это сравнение фактических измерений, не гарантия будущего runner.

Simplicity: один фиксированный scanner-файл в shard 10, TLS файл в shard 11,
два целых файла в менее загруженный shard 2 и два новых индекса; без новых
абстракций, конфигурации или
второго алгоритма распределения. При добавлении
новых tests поддерживается существующая fail-closed проверка exact union.
Guard связывает число фактических shards, runner count и CI matrix, фиксирует
индексы двух существующих clean-process файлов и scanner, отвергает потерю
или дублирование node. Дополнительные runners — +2 к 10 параллельным fast jobs;
цену в runner-minutes измерить по новому GitHub PR, не выводить из testcase
time. В старой реализации `shard_fast_nodes(nodes, 8)` вызывается **до**
удаления dedicated файлов, поэтому остальные файлы shard 0 остаются на месте;
разности по файлам корректны лишь для testcase time старого PR.
Architecture Critique требуется: решение меняет CI performance/load и
decision surface. Проверить цену дополнительного runner, риск false confidence
от JUnit testcase durations, стабильность clean-process ownership и rollback
перед реализацией; затем PRD-review обоих сильных ревьюеров.
