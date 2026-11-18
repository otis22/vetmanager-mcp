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
aggregate. Недостаток любого секрета — явный failed preflight, а не skip.

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
