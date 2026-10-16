# Этап 406. Снижение ECR 429 в CI: план Б

## Цель и проверенные факты

16.10.2026 шесть CI-сборок упали на общем лимите передачи данных ECR при получении `public.ecr.aws/docker/library/python:3.12-slim`. `Tests` строил один test-образ в трёх job. Dockerfile по умолчанию использует ECR; production Compose строит образ на сервере. `Deploy Prod` слушает `workflow_run` Tests и исключает документацию через `deploy_scope_check.sh`. Токен машины не имеет `read:packages` и `write:packages`; по корректировке владельца GHCR-зеркало отложено. Общий PRD и технические требования прочитаны; Vetmanager API не меняется.

## Требования и приёмка

- `Tests` на push/PR в `main` игнорирует `**.md`, `PRD/**`, `docs/**`. Ручной `workflow_dispatch` сохраняет запуск при ограничении GitHub path filter (первые 300 файлов). До правки docs-only push запускал Tests; после правки показать docs-only SHA без Tests run через `gh run list`. Отдельный Docs Check проверяет структуру Roadmap.
- Одна job `build-image` строит test-образ, сохраняет его artifact на сутки; `fast`, `default`, `postgres-activation-telemetry` загружают один и тот же образ. Перед upload проверяются размер архива (≤4 GiB) и свободное место (≥8 GiB). Снять фактические времена передачи в CI.
- Сборка `build-image` и ручного `Real API Tests` использует Buildx `type=gha` `cache-from/cache-to`. У ручного workflow дополнительно читается cache test-образа для общих базовых слоёв. Даже тёплый cache не исключает ECR manifest/metadata resolve по mutable `FROM`; отсутствие blob-трафика снижает вероятность Data limit 429, но не доказывает независимость от ECR. На cache miss риск ещё выше. `retry_ecr_build.sh` оставить в репозитории как ручную страховку/для отката; текущий action его не вызывает. Сборка production на сервере не получает GHA cache и остаётся за пределами решения. Обновить устаревший сторож этапа 402, требующий вызова retry из каждой job, сохранив поведенческие тесты самого скрипта.
- Сторож YAML сначала красный на старом workflow, затем зелёный: фильтр, одна сборка и три consumer job, GHA cache в обеих CI-сборках, неизменный ECR base. Проверить Deploy Prod связь и trusted upstream event, чтобы PR из fork не открыл production secrets.
- После review и аудита выполнить ровно один полный mock и real suite по финальному кодовому SHA, push в main, проверить Tests и Deploy Prod. В логе CI зафиксировать `cache-from/cache-to type=gha`, источник base и исход job. Cache hit допустим только после появления предыдущей записи; первый miss может ещё получить 429.

## Архитектурное решение

**Проблема.** Три независимые сборки утраивали запросы к базовому образу и могли каждая попасть на ECR 429. Docs-only коммит расходовал ту же квоту.

**Контекст и варианты.** GHCR-зеркало убрало бы зависимость от ECR, но без package scopes его нельзя безопасно опубликовать и проверить публичность. Три параллельных `buildx build` с общим cache по читаемости и расходу хуже одной сборки. SHA-образ в registry требует write permission на каждом PR. Выбран один Buildx job с GHA cache и artifact внутри run. Artifact передаёт уже готовый образ, GHA cache сохраняет базовые слои между run. `docker/build-push-action` использует runtime cache credentials без собственных токенов в workflow.

**Инварианты.** Три тестовые job выполняют один образ текущего SHA; ошибку теста нельзя скрыть cache hit. PR не получает registry write. Real API workflow остаётся ручным. Deploy Prod получает только успешные Tests от доверенных push/dispatch на main; docs-only push не даёт `workflow_run`, а следующий кодовый push сравнивается с последним успешным deploy. Dockerfile и локальные сборки остаются на прежней базе. PostgreSQL service image из ECR — отдельный риск.

**Rollback/fallback.** Если artifact или GHA cache не работает, вернуть workflow отдельным коммитом и использовать старую тройную сборку с `retry_ecr_build.sh`; production образ не затрагивается. Cache miss может всё ещё упасть на ECR 429; тогда адресный rerun после восстановления лимита. Следующий этап GHCR устраняет этот остаточный риск.

**Architecture Critique.** Требуется: меняется orchestration CI и цепочка выпуска. PRD review покрывает архитектуру, альтернативы, безопасность, rollback, приёмку и тесты.

## Декомпозиция

1. Сверить старый CI и trigger, PRD, Spark → Astra/Sol PRD review — до 2 ч.
2. Показать красный сторож и реализовать docs-filter, один build job, GHA cache — до 150 строк кода.
3. Провести аудит и Spark → Astra/Sol committed diff review — до 2 ч.
4. Один полный mock+real suite, push, проверить docs-only отсутствие run, Tests и Deploy Prod — до 2 ч.

## Отложенное GHCR-зеркало

После выдачи владельцем токена с `write:packages,read:packages` либо `gh auth refresh -s write:packages,read:packages` выполнить обновление раз в 1–2 месяца: `docker pull public.ecr.aws/docker/library/python:3.12-slim`, `docker tag public.ecr.aws/docker/library/python:3.12-slim ghcr.io/otis22/python:3.12-slim`, `docker push ghcr.io/otis22/python:3.12-slim`. До push: `gh auth token | docker login ghcr.io -u otis22 --password-stdin`. Обычный `docker push` с текущей машины публикует лишь её платформу; для сохранения multi-platform index отдельно выполнить `docker buildx imagetools create -t ghcr.io/otis22/python:3.12-slim public.ecr.aws/docker/library/python:3.12-slim`. Сверить платформы/digest и анонимный pull amd64/arm64, сделать пакет public, затем отдельным этапом закрепить index digest в Dockerfile и прогнать CI/Deploy. До этой проверки CI и Dockerfile на GHCR не переключать.

## Оценка простоты

Один build job, штатные artifact и Buildx cache; новых runtime-зависимостей и registry permissions нет.
