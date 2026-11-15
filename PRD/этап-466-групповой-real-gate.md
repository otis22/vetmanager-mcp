# Этап 466. Групповой real gate вместо монолитных повторов

## Цель

Получить полный real gate из независимых последовательных групп с проверяемым aggregate.

## Решение владельца и цель

После серии красных монолитных real-прогонов владелец остановил поезд и поставил этот этап перед 459. Нужно изменить устройство проверки, а не ослабить её: сохранить каждый real-сценарий и требование нуля пропусков, но выполнять их независимыми группами с единым fail-closed aggregate manifest. После failure исправляется и перезапускается только затронутная группа и её зависимости, а не весь набор на общем devtr6.

Выпуск по-прежнему запрещён до зелёного aggregate на неизменном runtime, default/PostgreSQL, committed-diff review и остальных релизных гейтов. Этап 466 создаёт механизм; завершение 459 происходит после него через этот механизм.

## Фактический baseline

Последний монолит на текущем WIP:

- default/mock: 4661 passed, 1 skipped, exit 0;
- PostgreSQL: 6 passed, 0 skipped, exit 0;
- real: 134 passed, 2 failed, 1 skipped-error, exit 1;
- cleanup: exit 0; JUnit и outcome обеих real groups сохранены.

Failure `test_real_validate_domain_api_key_connection` и `test_stage429_live_client_cards_page` связаны с ResourceWarning незакрытых transport/socket. `test_stage385_export_outcome_live` пропущен с безопасной причиной `Devtr6 export guard refused this safe test report`. Stage276 и stage389 прошли. Причина warnings и владелец ресурса не установлены; guard refusal не является pass.

Предыдущие focused-исправления уже находятся в WIP: строгий missing-client, AnyIO >=4.16, billing budget, stage396/431, loop/process cleanup, изолированный runner, уникальная метка Report AI seed, web timeout 60 с, real JUnit/outcome и exclusive 0600 `auth.env`. Их нельзя потерять при изменении runner.

## Почему меняем подход

Монолит смешивает независимые риски и внешнее состояние. Повтор всех сценариев после одного fix занимает 30–40 минут и создаёт дополнительные Report AI jobs/exports, изменяя условия следующих запусков. Focused pass сам по себе не доказывает полный gate, а серия монолитов увеличивает побочные записи и не локализует нестабильность.

Групповой подход ограничивает повтор только нужной областью и делает доказательство адресным. Он не превращает внешние сбои в успех и не позволяет накапливать зелёные результаты на разных runtime.

## Обязательные инварианты

1. **Полнота:** каждый collected real node присутствует ровно в одной группе. Нет неучтённых и дублированных nodes; их число и имена проверяются машиной, а не вручную по памяти.
2. **Ноль пропусков:** `skipped-not-configured=0`, `skipped-error=0`, JUnit skipped=0. Отдельный web happy-path входит в manifest как обязательный node.
3. **Ноль скрытых ошибок:** warnings-as-errors, отсутствие JUnit/outcome, missing case, failure/error и cleanup failure делают группу красной.
4. **Один runtime:** aggregate собирается только из evidence с одинаковым runtime fingerprint. Нельзя смешивать passes разных production-кодовых состояний.
5. **Консервативная invalidation:** изменение runtime инвалидирует все группы. Test-only изменение инвалидирует затронутую группу и все зафиксированные shared-helper зависимости; docs-only не инвалидирует проверки.
6. **Свежий baseline:** при внедрении 466 каждый node выполняется заново. Старые монолитные passes автоматически не импортируются и не смешиваются с новым manifest.
7. **Без случайных повторов:** failure останавливает release. Повторяется только затронутая группа после новой причинной фактуры; автоматических retry до зелёного нет.
8. **Безопасность:** секреты, адреса выгрузок, тела клинических ответов и ПДн не попадают в manifest, публичные PRD/Roadmap/AssumptionLog или stdout.
9. **Покрытие не удаляется:** перенос в отдельную группу не является удалением/отключением теста. Изменение состава проверок — только отдельным решением владельца и с сохранением риска.

## Предлагаемые группы

Окончательный inventory строится по фактическому collect-only. Кандидаты по общему ресурсу и побочным эффектам, а не просто по алфавиту файлов:

- `real-read`: read-only API, connection validation и projections; сюда попадают текущие ResourceWarning cases, если их фактический путь read-only.
- `real-auth-web`: web account/token flow и browser scenarios, включая отдельную прежнюю group 2.
- `real-write`: write/update с гарантированным restore и отрицательными write-контрактами; выполняется последовательно.
- `real-report-ai`: создание/ожидание/dedup/rating Report AI с уникальными метками. Длинные stage420 и stage422 выделяются в самостоятельные группы либо заведомо ограниченные подгруппы.
- `real-export`: stage276 и stage385 export строго последовательно на одном внешнем guard. Нельзя запускать эти сценарии параллельно между группами.
- `real-workers`: локальные workers, Redis/PostgreSQL recovery, SSE и process lifecycle в отдельных disposable Compose projects.

Допустимо более мелкое разбиение, если оно сохраняет единый manifest и не создаёт параллельного доступа к общему guard. Нельзя объединять export с другими долгими write-сценариями только ради сокращения числа групп.

## Архитектура runner и evidence

Предпочтительно расширить существующий изолированный runner, а не создавать параллельную несовместимую систему:

1. Машинный manifest содержит версию схемы, полный список node IDs, назначение группы, shared-helper зависимости и требуемые обязательные nodes (включая stage276/stage389).
2. Для каждой группы создаётся новый Compose project и отдельный evidence-каталог вне репозитория. Общий upstream доступ остаётся последовательным.
3. Сохраняются JUnit и существующий outcome JSON плагина; `tests.real_suite_outcomes` и его классификация `skipped-error` не ослабляются.
4. Результат группы включает node IDs, runtime/test fingerprints, exit codes, counts, evidence paths и cleanup status. Права generated auth/evidence остаются fail-closed 0600.
5. Aggregate проверяет полноту inventory, свежесть, один runtime, все обязательные nodes и ноль skips/failures. Недостающая или устаревшая группа — не green.
6. Точные CLI команды фиксируются исполнителем после inventory и проходят проверку в документированном виде. Должны быть отдельные операции `list/validate manifest`, `run one group`, `aggregate`; монолитный режим больше не используется для диагностического повтора.

Runtime fingerprint должен покрывать production Python-код, зависимости и production Docker/config, влияющие на поведение. Допустимо переиспользовать packaging allowlist с явным сторожем на новые неучтённые runtime-файлы. Test fingerprint включает файлы группы и shared helpers. Простой HEAD SHA без учёта незакоммиченного WIP недостаточен.

## Что делать с текущими красными случаями

- ResourceWarning cases попадают в соответствующие read/worker группы и сохраняют warnings-as-errors. Их исправление принадлежит 459 и требует ownership evidence; suppression, `gc.collect()` и глобальное увеличение grace запрещены.
- Export guard refusal остаётся красным outcome. В export-группе фиксируется безопасная причина отказа и занятость guard. Нельзя удалять guard, превращать skip в pass или автоматически создавать серию exports. Ожидание допускается только для того же file ID в отдельном обоснованном bounded окне.
- Report AI сохраняет уникальную метку seed и строгие dedup assertions. Повторный intent обязан находить match/confirmation, а не просто создавать новую job.

## Декомпозиция

1. **466.1 Inventory + PRD/Architecture Critique:** collect-only карта всех nodes, группы, зависимости, fingerprints, manifest schema, точные команды, security/privacy, rollback. Пройти Spark → Astra + Opus по действующему бюджету и simplicity review.
2. **466.2 Реализация runner:** test-first красные guards на потерю/дублирование node, missing XML/outcome, skip/failure, смешение runtime, устаревший shard, неполный aggregate и cleanup failure; затем реализация и focused green.
3. **466.3 Первый baseline:** выполнить каждую группу на текущем runtime, проверить агрегирование и fail-closed поведение. Красные продуктовые/тестовые случаи передать в 459 с evidence; не объявлять их исправленными инфраструктурой.

Каждая подзадача ограничена ≤2 человеко-часами или ≤150 строками реализации там, где это достижимо без искусственного дробления контракта. Изменения runtime в 466 не предполагаются; если они нужны, остановиться и отнести их к 459 с отдельным обоснованием.

## Приёмка этапа 466

- Inventory машинно доказывает покрытие всех real nodes ровно один раз и присутствие обязательной web group.
- Красные mock-сторожа подтверждают fail-closed поведение на каждом нарушении инвариантов; зелёные fixtures показывают валидный aggregate.
- Каждая группа имеет внешние JUnit/outcome, counts, exit и cleanup evidence. Ни один skip не принимается за успех.
- Runner корректно останавливает release при красном или неполном baseline; первый baseline собран без монолитного повтора.
- Roadmap/AssumptionLog содержат точные команды, результаты и переход к 459. Красные реальные сценарии остаются явными блокерами 459, а не скрываются за инфраструктурным `done`.

## Переход к 459 и выпуск

После 466 исправляются конкретные красные группы 459. Затем aggregate обязан показать каждый real node зелёным на одном runtime, при нуле пропусков и успешном cleanup. Дополнительно заново проходят default/PostgreSQL по правилам invalidation. Только после этого разрешены commit → committed-diff Spark → Astra + Opus → push рабочей ветки → merge/deploy куратором → production smoke → 60 минут мониторинга → обновление обоих дашбордов.

Любое runtime-изменение после зелёных групп требует нового полного aggregate по группам, но не монолитного случайного повтора. Этап 465 позже отдельно пересматривает назначение и состав тестов; 466 не удаляет и не переносит проверки в необязательные.

## Rollback

До commit — точечное редактирование новых runner/manifest файлов с сохранением прежнего WIP. После commit — обычный revert соответствующего веточного commit до merge. Старый монолитный runner остаётся доступным только как аварийная диагностическая команда, а не способ обойти новый release gate. Production в 466 не меняется.

## Inventory 466.1 (collect-only, 15.11.2026)

Команда: `docker compose --profile test run --rm test python -m pytest --collect-only -q -m 'real_api or real_browser' tests/`. Выражение маркера прочитано из `test_contours.OPT_IN_REAL_TEST_CONTOUR`; `run_opt_in_real_test_suite.py` разделяет web happy-path отдельной командой. Собрано 137 nodes, 4668 deselected; сценарии не исполнялись. Полный node inventory сохранён для формирования машинного manifest.

План групп: `read` (проекции и без записи), `auth-web` (bearer/OAuth, браузер и отдельный web happy-path), `write-restore` (медкарта и иные обратимые записи), `report-ai` (короткие jobs), `report-ai-420` и `report-ai-422` (длинные сценарии), `export` (stage276 затем stage385 на одном guard), `workers` (slots, recovery, Redis/PG, SSE, процессы). Группы выполняются последовательно; один общий upstream guard никогда не вызывается конкурентно. Неоднозначные сценарии классифицируются по фактическому вызову перед фиксацией manifest.

Схема manifest v1: `schema_version`, `marker_expression`, `nodes` (словарь nodeid → group), `groups` (имя → упорядоченные nodeids), `shared_helpers` (пути файлов → зависимые группы), `required_nodes` (web happy-path, stage276, stage385, stage389). `validate` сверяет manifest с новым collect-only и требует точного равенства множеств и уникальности.

Runtime fingerprint: SHA-256 отсортированных путей и байтов production `*.py`, `pyproject.toml`, lock/dependency файлов, `Dockerfile`, production compose/config; для WIP берутся байты рабочего дерева. Test fingerprint каждой группы: SHA-256 её node IDs, файлов тестов и shared helpers (`conftest.py`, `real_suite_outcomes.py`, `live_test_lifecycle.py`, runner и warning policy). Изменение runtime инвалидирует все shards, test-only — затронутые группы и зависимости, docs-only — ни одной. Неизвестный влияющий файл требует обновления allowlist и отказа validate. HEAD SHA сохраняется для аудита, но не заменяет fingerprints.

CLI: `run_isolated_test_suite.py --suite real --group NAME --evidence-dir DIR` исполняет одну группу; `--list-groups` показывает manifest; `--validate-manifest` делает collect-only сверку; `--aggregate EVIDENCE_ROOT` проверяет полное покрытие. Каждый shard записывает SHA-256 полного валидированного manifest, свой test fingerprint и точные node IDs; создаёт новый disposable Compose project и внешние JUnit/outcome/cleanup evidence. Aggregate заново вычисляет hash manifest и test fingerprint и требует их совпадения, а также точного равенства manifest nodes, collected/executed nodes и JUnit testcase IDs; счётчики без node-level сверки не принимаются. Никакие прежние монолитные результаты не импортируются.

## Архитектурное решение

Расширяем существующий isolated runner и outcomes plugin: это сохраняет warnings-as-errors и текущую классификацию skip. Отдельный несовместимый runner отвергнут из-за риска рассинхрона auth/cleanup. Объединение всех групп в один проект отвергнуто из-за общего состояния и невозможности адресного повторения. Секреты и клинические тела не входят в manifest/evidence summary; generated auth остаётся 0600. Совместимость: старый monolithic CLI остаётся диагностическим, но не принимается aggregate. Rollback: удалить точечные изменения runner/manifest до commit с сохранением WIP 459; после commit — revert веточного изменения.

Подзадачи реализации: (1) manifest + collect validation, (2) fingerprints + invalidation, (3) group execution/cleanup, (4) aggregate/JUnit/outcome guards, (5) focused mock tests; каждую ограничить двумя часами или 150 строками там, где применимо.

### Уточнение после Architecture Critique

До запуска группы runner обязательно собирает test image из текущих build inputs, сохраняет image ID и `pip freeze` hash фактически запущенного контейнера. Код тестов и production находится в image (`COPY . .`), поэтому runtime fingerprint и test fingerprint вычисляются из рабочего дерева непосредственно перед build и после группы; любое изменение между ними красит shard. Aggregate пересчитывает runtime fingerprint относительно текущего checkout, сравнивает его с каждым shard и сохраняет image ID каждого shard как provenance, но сравнивает runtime и dependency hash: общий image ID неприменим, поскольку test image содержит тесты и документацию. Если build с теми же inputs дал иной image ID или состав зависимостей, прежние shards инвалидируются. Параллельный build/запуск групп запрещён.

Каждая попытка группы регистрируется в append-only index evidence-root *до* старта. Последняя попытка по группе единственная допустимая; предыдущий зелёный shard не может перекрыть новый красный или незавершённый. Index создаётся с `O_EXCL`/lock и закрытыми правами; aggregate отклоняет отсутствующий, повреждённый или неоднозначный index. Неуспешный cleanup остаётся красным. Нельзя выбирать зелёную попытку вручную.

Collect-only для `validate` выполняется тем же isolated Compose и auth/env-профилем, что и групповой запуск, по фактическому marker expression из `test_contours.py`. Отдельный web happy-path собирается той же отдельной командой, что в прежнем runner; exact node ID должен входить в manifest один раз. При каждом shard runner записывает список реально собранных и исполненных node IDs; aggregate сравнивает его с manifest и JUnit. Условные marker/parametrize изменения делают manifest невалидным.

Для test fingerprint учитываются все загруженные `tests/*` модули, `conftest.py`, shared helpers и файлы runner; неизвестный импорт/fixture закрывает gate до обновления dependency map. Первый baseline 466.3 запускает каждую группу в свежем проекте и проверяет отсутствие межгрупповых seed/session зависимостей. Проверка порядка делается адресно при подозрении на зависимость, без автоматического повторного Report AI/export. `created_at` shard и максимально допустимое окно aggregate фиксируются в manifest (24 часа); если доступна безопасная версия upstream, она сохраняется как неприватный идентификатор и должна совпадать. При недоступной версии 24-часовое окно не доказывает идентичность стенда, поэтому внезапный upstream drift требует пересъёмки затронутых групп, а не принятия старого evidence.


### Исправления после второго сильного вердикта и решение куратора

Второй раунд Astra и Opus обнаружил, что общий test image включает тесты и документы. Поэтому равенство image ID между группами **не является** условием aggregate: оно ломает адресную invalidation. Фактический image ID хранится как provenance; совместимость определяется текущим runtime fingerprint, dependency hash и индивидуальным test fingerprint. При пересборке новой группы runner дополнительно сверяет production-файлы внутри контейнера с runtime fingerprint рабочего дерева; старые группы принимаются лишь при совпадении runtime/dependency fingerprint с текущими, а не по image ID. Docs-only изменение не меняет эти fingerprints. При отличии разрешённых зависимостей все группы инвалидируются.

Для каждой группы создаётся неприватная HMAC-метка тестового контура и auth-профиля: ключ HMAC создаётся 0600 для evidence-root, вход включает нормализованный test domain и идентификаторы разрешённых auth-режимов/профилей без записи исходных токенов. Aggregate сравнивает метки групп и заново вычисленную метку текущей конфигурации; без ключа и совпадения — отказ. Межгрупповое состояние: красный cleanup либо незавершённый restore пишущей группы блокирует запуск следующих групп и инвалидирует более поздние shards до ручного подтверждённого восстановления. JUnit, логи и outcome хранятся только во внешнем 0600 evidence; в публичные артефакты попадают лишь counts, node IDs и обезличенные классы ошибок, без assertion bodies/system-out/system-err.

Отдельный web happy-path имеет один node ID `tests/test_e2e_real.py::test_real_web_account_can_issue_bearer_and_call_tool` среди 137 collected. Общий collect использует `-k 'not test_real_web_account_can_issue_bearer_and_call_tool'`; отдельный collect выбирает ровно этот node ID. Union равен 137, intersection пустой.

Второй валидный раунд сильного PRD-ревью исчерпал бюджет 2/2 у обоих рецензентов. Куратор разрешил продолжить без третьего сильного запуска после отдельного post-budget Spark scout и собственной сверки. Scout прочитал исправленный PRD и оба вторых verdict, `files_read=5`, `findings=[]`, `high_closed=true`; evidence: `/home/otis/.local/share/vetmanager-mcp-review-evidence/stage466/post-budget-prd.result`. Собственная сверка: общий image ID отменён, runtime/dependency fingerprints сравниваются с текущим состоянием, контур/auth идентифицируются HMAC, попытки append-only и последняя перекрывает старую. Подтверждённых critical/high не осталось; PRD принят для 466.2.


## Реализация 466.1–466.2 в этом ходе

Manifest v1: `scripts/real_group_manifest.json`; 137 nodes ровно один раз. Точный состав — массивы `groups` в manifest, проверенные collect-only в изолированном Compose project. Размеры: `read` 76, `auth-web` 20, `write-restore` 6, `report-ai` 15, `report-ai-420` 2, `report-ai-422` 1, `export` 3, `workers` 14. Export-группа содержит stage276, stage385 export outcome и stage385 metrics последовательно; stage389 и web happy-path обязательны.

Реализованные команды: `python3 scripts/run_isolated_test_suite.py --list-groups`; `python3 scripts/run_isolated_test_suite.py --validate-manifest --evidence-dir /home/otis/.local/share/vetmanager-mcp-review-evidence/stage466/validate-manifest-3`; `python3 scripts/run_isolated_test_suite.py --group read --evidence-dir /home/otis/.local/share/vetmanager-mcp-review-evidence/stage466/baseline`; `python3 scripts/run_isolated_test_suite.py --aggregate --evidence-dir /home/otis/.local/share/vetmanager-mcp-review-evidence/stage466/baseline`. Последние две команды здесь **не запускались**: baseline 466.3 относится к следующему ходу. Group mode создаёт отдельный project, пересобирает test image, пишет внешние JUnit/outcome/shard и append-only index; aggregate принимает только последние попытки, текущие fingerprints/контур и ноль ошибок/skip.

Уточнение реализации: provenance image ID фиксируется отдельно, зависимость от shared test helpers и импортов `tests.*` входит в test fingerprint; контур вычисляется HMAC по заданным env-файлам и разрешённым переменным окружения. HMAC-ключ и evidence-root закрыты правами 0600/0700. Внешние raw JUnit/логи не копируются в публичные артефакты.


## Первый baseline 466.3 — остановлен после read

Команда: `python3 scripts/run_isolated_test_suite.py --group read --evidence-dir /home/otis/.local/share/vetmanager-mcp-review-evidence/stage466/baseline`, exit 1. Disposable Compose project: build/startup/create-stage385/create-stage400/create-stage408/collect/auth выполнены с exit 0; `read` outcome 76 collected, 75 passed, 1 failed, 0 skipped-not-configured, 0 skipped-error; JUnit 76 cases; cleanup exit 0. Красный node: `test_real_get_hospitalizations`, безопасный класс причины — `ResourceWarning`/`PytestUnraisableExceptionWarning` в `ExceptionGroup`. Raw JUnit, outcome, summary и логи сохранены только во внешнем закрытом evidence `stage466/baseline/read-ad29860e2efe/`.

После теста runner упал на неверном предположении об имени test image (`{project}-test` вместо `services.test.image` из Compose), поэтому shard не был записан. Это инфраструктурный дефект, baseline остановлен; `auth-web`, `write-restore`, `workers`, `report-ai`, `report-ai-420`, `report-ai-422`, `export` не запускались. Исправление test-first: новый guard `test_image_id_comes_from_compose_service_image` сначала red exit 1 (`ImportError`), затем `resolve_test_image_id` читает фактический image из Compose config и инспектирует его; первый focused 49 passed с повтором точного node, итоговый focused без дубля 48 passed, Ruff exit 0. Исходный `read` не повторялся: правка shared runner изменила test fingerprint и предыдущие passes не подходят для aggregate.

Команда `python3 scripts/run_isolated_test_suite.py --aggregate --evidence-dir /home/otis/.local/share/vetmanager-mcp-review-evidence/stage466/baseline`: exit 1. Её отдельный collect-only и cleanup exit 0; aggregate отказал на отсутствующем `read/shard.json`, старые монолитные результаты не импортировал. Инфраструктурный 466.3 остаётся `in_progress`; зелёный групповой baseline не заявлен. В том ходе baseline был остановлен; позднее куратор разрешил новую read-попытку после исправления runner. Продуктовый ResourceWarning остаётся наблюдением для 459, не исправленным в 466.3.


## Продолжение первого baseline 466.3 — aggregate blocked

После причинного исправления image resolution куратор разрешил новую попытку `read` с тем же evidence root. Каждая следующая группа выполнена ровно один раз, последовательно. Последние попытки (passed/failed/skipped-not-configured/skipped-error; CLI exit; cleanup exit):

| Группа | Evidence directory | Counts | CLI | Cleanup |
|---|---|---|---:|---:|
| read | `read-c6fe77c46198` | 76/0/0/0 | 0 | 0 |
| auth-web | `auth-web-1b6004dbb34f` | 20/0/0/0 | 0 | 0 |
| write-restore | `write-restore-f2ff96ec08bb` | 6/0/0/0 | 0 | 0 |
| workers | `workers-ae7b943c3482` | 14/0/0/0 | 0 | 0 |
| report-ai | `report-ai-6cc7f22673d4` | 15/0/0/0 | 0 | 0 |
| report-ai-420 | `report-ai-420-dfd4a737788e` | 2/0/0/0 | 0 | 0 |
| report-ai-422 | `report-ai-422-37006ed12272` | 1/0/0/0 | 0 | 0 |
| export | `export-7da5ae32f57e` | 1/1/0/1 | 1 | 0 |

Все директории находятся под `/home/otis/.local/share/vetmanager-mcp-review-evidence/stage466/baseline/`, содержат JUnit, outcome, summary, cleanup и shard последней попытки. Последние результаты суммарно 135 passed, 1 failed, 1 skipped-error из 137. Красные nodes: `tests/test_stage276_live_export_download.py::test_real_export_is_downloaded_cleaned_and_served_by_us` — failure в export guard/download пути; `tests/test_stage385_export_outcome_live.py::test_export_poll_success_is_one_outcome_across_slots` — skipped-error, guard refused. Тела ошибок и адреса выгрузок остаются только во внешнем evidence. Export не повторялся.

`python3 scripts/run_isolated_test_suite.py --aggregate --evidence-dir /home/otis/.local/share/vetmanager-mcp-review-evidence/stage466/baseline`: exit 1. Собственный collect-only и cleanup exit 0, затем aggregator попытался прочитать отсутствующий `shard.json` **исторической первой** `read` попытки `read-ad29860e2efe`, хотя последняя `read-c6fe77c46198` имеет валидный shard. Это инфраструктурный дефект выбора попытки: red aggregate не доказывает проверку полного набора последних shards. По указанию куратора при новом infrastructure failure baseline остановлен без исправления и retry в этом ходе. 466.3 остаётся in_progress; 459 и release не объявлены зелёными.


## Узкая правка aggregate: последние попытки и fingerprint

Запрос куратора: исправить чтение append-only index без повторного real. Новый `load_latest_attempts` валидирует все записи index, выбирает последнюю запись каждого group и читает **только её** shard. Историческая прерванная read остаётся в журнале и не блокирует последнюю валидную read; отсутствующая/невалидная/красная последняя попытка блокирует aggregate. Старый зелёный shard не подменяет последний красный export.

Test-first: новый guard до реализации дал red exit 2 (`ImportError: load_latest_attempts`). После реализации намеренная мутация «старейшая запись выигрывает» дала red exit 1; мутация «принимать красный shard» дала red exit 1. Исходный код восстановлен. Focused `tests/test_stage466_group_gate.py tests/test_stage459_isolated_environment.py tests/test_stage438_real_outcomes.py`: exit 0, **53 passed**. Ruff, синтаксис Python, структура Roadmap и `git diff --check`: exit 0. Evidence `/home/otis/.local/share/vetmanager-mcp-review-evidence/stage466/red-latest-attempt.txt`, `red-aggregate-oldest-wins.txt`, `red-aggregate-red-accepted.txt`, `focused-latest-attempt-final.txt`, `ruff-latest-attempt.txt`.

После этого выполнен только `python3 scripts/run_isolated_test_suite.py --aggregate --evidence-dir /home/otis/.local/share/vetmanager-mcp-review-evidence/stage466/baseline`: exit 1; отдельный collect-only и cleanup exit 0. Aggregate теперь проходит историческую incomplete read, но отклоняет последний read на `stale test_fingerprint`. Сверка всех восьми последних shards: runtime и manifest fingerprints совпадают; **test fingerprint не совпадает у всех восьми**, потому что изменённые `scripts/real_group_gate.py` и `scripts/run_isolated_test_suite.py` включены в shared helpers. Это консервативная invalidation по действующему контракту. Красный export (1 failed stage276, 1 skipped-error stage385) остаётся в evidence, но aggregate до его node-level проверки не дошёл. Фактический verdict отличается от ожидаемого продуктового красного; 466/466.3 остаются `in_progress`, 459 — `supervisor_pending`, release заблокирован. Real-группы, export и Report AI не повторялись.


## Финальный baseline после invalidation shared runner

Куратор разрешил по одной новой попытке каждой группы в прежнем evidence root после честного `stale test_fingerprint`; код runner/manifest/тестов во время цикла не менялся, прежние passes не импортировались. Порядок read → auth-web → write-restore → workers → report-ai → report-ai-420 → report-ai-422 → export соблюдён; параллельных групп и retry нет. Последние попытки (passed/failed/skipped-not-configured/skipped-error, CLI exit, cleanup exit):

| Группа | Evidence directory | Counts | CLI | Cleanup |
|---|---|---|---:|---:|
| read | `read-166159df2b55` | 75/1/0/0 | 1 | 0 |
| auth-web | `auth-web-f90193ba0d95` | 19/1/0/0 | 1 | 0 |
| write-restore | `write-restore-d4d4941c39a4` | 6/0/0/0 | 0 | 0 |
| workers | `workers-0d15d32ebb0b` | 14/0/0/0 | 0 | 0 |
| report-ai | `report-ai-bd69d3d1df18` | 15/0/0/0 | 0 | 0 |
| report-ai-420 | `report-ai-420-0a41617acb69` | 2/0/0/0 | 0 | 0 |
| report-ai-422 | `report-ai-422-edf801b22565` | 1/0/0/0 | 0 | 0 |
| export | `export-aa536ecedc42` | 2/0/0/1 | 1 | 0 |

Все директории находятся под `/home/otis/.local/share/vetmanager-mcp-review-evidence/stage466/baseline/`; JUnit, outcome, summary, shard и cleanup имеются у каждой. Последние outcomes суммарно 134 passed, 2 failed, 1 skipped-error из 137; skipped-not-configured=0. Красные nodes: `tests/test_stage412_live.py::test_stage412_live_stock_batch_and_missing_clinic` — ResourceWarning/PytestUnraisableExceptionWarning; `tests/test_e2e_real.py::test_real_validate_user_token_connection_from_login_password_or_env_token` — ResourceWarning/PytestUnraisableExceptionWarning; `tests/test_stage385_export_outcome_live.py::test_export_poll_success_is_one_outcome_across_slots` — skipped-error, guard refused. Stage276 download в этой попытке прошёл, прежний failure не переносится в текущий результат. Секреты/тела ответов не перенесены в репозиторий.

Точный aggregate `python3 scripts/run_isolated_test_suite.py --aggregate --evidence-dir /home/otis/.local/share/vetmanager-mcp-review-evidence/stage466/baseline`: exit 1; его отдельный collect-only и cleanup exit 0 (`aggregate-collect-4aef82dd11a3`). Он загрузил последние восемь shards, затем отказал на красном `read` (`test or cleanup failed`). Read-only адресная сверка всех групп подтвердила: manifest/runtime/test fingerprints совпадают, dependency fingerprint один, пять shards валидны зелёными и три красны только по test outcome. Это не ожидаемый вариант «только export»; согласно условию куратора 466/466.3 остаются `in_progress`, 459 `supervisor_pending`, release заблокирован. Новых infrastructure/cleanup/restore failures не было. Счётчик непреднамеренных красных групп 7/10 (три новых: read, auth-web, export). Код и runner в этом ходе не менялись.


## Решение куратора о приёмке инфраструктуры

Куратор принял 466/466.3 как `done`: все последние восемь shards загружены, manifest/runtime/test fingerprints и dependency совпадают, cleanup 0 для каждой группы, aggregate отказал на фактически красном read outcome. Предыдущее условие «красный только export» признано избыточным и не блокирует инфраструктурный этап. Последний baseline: 134 passed, 2 failed, 1 skipped-error из 137; красные read, auth-web и export переданы в 459. Release остаётся заблокированным до зелёного aggregate и остальных гейтов.
