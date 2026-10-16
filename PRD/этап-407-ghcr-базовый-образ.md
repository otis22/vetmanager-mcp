# Этап 407. GHCR-зеркало базового образа

## Цель и проверенные факты

Этап 406 дважды получил ECR 429 при разрешении metadata базового Python даже при тёплом GHA cache. Владелец опубликовал публичный `ghcr.io/otis22/python:3.12-slim`; анонимный `docker buildx imagetools inspect` 17.10.2026 вернул digest `sha256:139b146ecf6cadf1960a88887c83846bd030bf1bc0a478fae48215c49917c075`. Это single-platform manifest, локальный Docker — x86_64; архитектуру Docker daemon на production host требуется проверить перед сборкой в Deploy Prod. PostgreSQL service в Tests также ссылается на ECR. Production Compose и локальный Compose собирают тот же Dockerfile. Deploy Prod не содержит собственного Docker build, а запускает удалённый staged deployment. Общий PRD и технические требования изучены; контракт Vetmanager API не меняется.

## Требования и приёмка

- Dockerfile использует публичный GHCR Python с закреплённым digest; обе CI-сборки и production deploy наследуют этот источник без override. GitHub workflow не содержит активного `public.ecr.aws`; PostgreSQL service использует тот же Docker Hub образ, что и Compose.
- Красный сторож до исправления проверяет Dockerfile, `test.yml`, `test-real.yml`, `deploy-prod.yml`, `docker-compose.yml` и production build в `scripts/stage385_deploy.py`: разрешённый FROM, отсутствие активного ECR и переопределений BASE_IMAGE. Старый сторож этапа 406, требующий ECR FROM, также сначала показывается красным, затем обновляется; поведенческие тесты fallback retry сохраняются.
- Локальная сборка CI test target без `docker login` успешна. После push в логах Tests виден `load metadata for ghcr.io/otis22/python`, а не ECR; Tests и Deploy Prod зелёные; кодовый push запускает Tests независимо от docs-only фильтра.
- `scripts/retry_ecr_build.sh` остаётся для ручной ECR-сборки при откате. Workflow его не вызывает. Если он потребуется штатному CI, это сигнал оставшейся ECR-зависимости.
- Раз в 1–2 месяца оператор обновляет зеркало: `gh auth token | docker login ghcr.io -u otis22 --password-stdin`, затем `docker pull`, `docker tag`, `docker push` (точные команды в README). После push сверяет анонимный pull и новый digest, обновляет Dockerfile отдельным коммитом с тестами и CI. Одноплатформенный mirror покрывает проверенный локальный amd64 контур. Deploy Prod до staged cutover проверяет `docker info --format` на production host и останавливается при несовместимой архитектуре; успешный лог проверки служит подтверждением. При arm64 выпуск остановить и подготовить multi-platform зеркало с новым digest.
- Перед push: PRD и committed diff gate Spark → Astra и Sol, аудит, один полный mock+real suite по финальному кодовому SHA. После push: проверить Tests и Deploy Prod.

## Архитектурное решение

**Проблема.** BuildKit обращается к ECR за manifest даже при cache hit, а общий лимит ECR уже блокировал CI.

**Контекст и варианты.** GHA cache и retry не устраняют metadata-зависимость. Переопределение `BASE_IMAGE` только в workflow оставило бы локальную и production сборки на ECR. Выбран default Dockerfile с GHCR digest; все сборки используют один immutable источник. PostgreSQL service переводится на Docker Hub, как существующий Compose. Приватный GHCR потребовал бы login для CI, deploy и локальной разработки, поэтому пакет публичный.

**Инварианты.** Runtime/test dependency setup и цели Dockerfile не меняются. Нет registry credentials в репозитории и CI. Все активные CI образы обходят ECR. Digest pin защищает от смены mutable tag. Текущий digest — только amd64; совместимость production проверяется в Deploy Prod до сборки и cutover.

**Rollback/fallback.** При ошибке production-сборки staged deploy оставляет работающий образ без cutover. При деградации GHCR сначала повторить сборку после восстановления реестра или опубликовать новое зеркало и закрепить его digest. Возврат к ECR отдельным коммитом требует вернуть вместе с Dockerfile/CI service и соответствующий GHCR-сторож; при ECR 429 прежняя CI схема может снова блокировать выпуск. `retry_ecr_build.sh` пригоден только для ручного ECR build, не для текущего build-push-action. Нельзя незаметно переключаться на mutable upstream.

**Architecture Critique.** Требуется: меняется источник production base и цепочка выпуска. Совмещается с PRD review, охватывающим scope, варианты, security, совместимость, rollback и тесты.

## Декомпозиция

1. Проверить контуры, digest, написать PRD; Spark → Astra/Sol PRD/Architecture review — до 2 ч.
2. Показать красный сторож, обновить Dockerfile, service image, README и старый сторож; локальная сборка и фокусные тесты — до 150 строк кода.
3. Аудит, Spark → Astra/Sol committed diff review, закрыть замечания — до 2 ч.
4. Один полный mock+real suite на финальном кодовом SHA, push, живые Tests/Deploy Prod, AssumptionLog и Roadmap — до 2 ч.

## Оценка простоты

Одна смена базового FROM и источника PostgreSQL service, без новых credentials, скриптов или механизмов retry.
