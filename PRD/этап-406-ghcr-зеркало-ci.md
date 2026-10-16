# Этап 406. Устранение ECR 429 в CI

## Цель и факты

Шесть падений Tests 16.10.2026 вызваны общим лимитом ECR на скачивание `public.ecr.aws/docker/library/python:3.12-slim`. `test.yml` трижды строит одинаковый test-образ. Ручной `test-real.yml` строит production-образ. Dockerfile задаёт ECR как базу по умолчанию, а production deploy строит образ на сервере через Compose. `Deploy Prod` получает `workflow_run` только после завершения Tests на main, затем проверяет изменения от последнего удачного деплоя через `deploy_scope_check.sh`; документация там уже исключена. GitHub branch protection через API отсутствует; отдельного обязательного check на docs-коммит сейчас нет. Общий PRD и технические требования изучены; контракт Vetmanager API не затрагивается.

## Требования и приёмка

- Опубликовать побайтовое зеркало официального `python:3.12-slim` из ECR в `ghcr.io/otis22/python:3.12-slim`; записать digest источника и опубликованного manifest. Проверить доступность пакета анонимным pull после удаления Docker-учётных данных из временного контекста.
- Dockerfile по умолчанию и CI-сборки используют публичный GHCR. Локальный Compose и production deploy используют ту же базу без GHCR login. Ручной Real API workflow также использует GHCR.
- В Tests для push и pull_request на main добавить `paths-ignore` для `**.md`, `PRD/**`, `docs/**`. Проверить фактом: до изменения push docs-only запускает Tests; после изменения — docs-only push не создаёт Tests run. Для docs-only push отсутствие `workflow_run` ожидаемо: Deploy Prod не запускается, что соответствует нынешнему `deploy` skipped; следующий code push вычисляет разницу от последнего успешного deploy и захватывает кодовые изменения.
- Test-образ собирается один раз на Tests run; три job используют его как готовый артефакт. Изоляция между job сохраняется, registry write permissions для тестового workflow не требуется. PostgreSQL service image из ECR — отдельный источник риска, не относящийся к Python base; оценить его по фактическим логам и зафиксировать предел решения.
- Сторож CI-конфигурации: на старом workflow красный; на новом зелёный. Проверяет три consumer job, один build job, GHCR base и docs-filter. Дополнительно проверить `Deploy Prod` связь и scope.
- После committed diff review — аудит, один полный mock+real suite по финальному SHA, push main, зелёный Tests и Deploy Prod. В логах Tests/Deploy подтвердить `ghcr.io/otis22/python`.

## Архитектурное решение

**Проблема.** Внешний ECR 429 блокирует тесты и production build; три одинаковые сборки утраивают шанс отказа. Документальные коммиты зря расходуют quota.

**Варианты.** Buildx cache оставляет три запуска build и сложнее доказывает одну сборку; SHA-tagged GHCR test image добавляет registry write permissions и публикацию каждого тестового образа. Выбран один build job с `docker save` и `actions/upload-artifact`, а три job делают download + `docker load`: образ передаётся только в пределах run без внешнего registry. Для base используется публичное GHCR-зеркало. Существующий `retry_ecr_build.sh` остаётся в репозитории как страховка для исторических вызовов/отката, но не применяется к GHCR: его классификатор строго привязан к ECR и иначе не повторит сборку.

**Инварианты.** Все три test job запускают один и тот же test image из текущего commit; test failure остаётся красным. Pull request не получает права записи пакета. Ручной real contour остаётся ручным. Deploy Prod запускается на успешный code Tests и не деплоит документацию. Изменение Dockerfile применяется также на production сервере; анонимный GHCR pull обязателен до выпуска. Откат — вернуть предыдущий Dockerfile/workflow отдельным коммитом; зеркало можно оставить.

**Architecture Critique.** Требуется, потому что меняется CI orchestration, production base и поведение цепочки релиза. Сильный PRD review проверяет архитектуру, scope, альтернативы, безопасность, совместимость, тесты и rollback.

## Декомпозиция

1. Проверить исходный CI и trigger, создать PRD и пройти Spark + Astra/Sol review — до 2 ч.
2. Опубликовать зеркало, проверить digest и анонимный доступ — до 2 ч.
3. Написать красный сторож workflow и реализовать GHCR base, docs filter, одну сборку — до 150 строк кода.
4. Аудит, committed diff review, один полный suite, выпуск и живое наблюдение CI — до 2 ч.

## Обновление зеркала

Раз в 1–2 месяца выполнить `docker pull public.ecr.aws/docker/library/python:3.12-slim`, затем `docker tag public.ecr.aws/docker/library/python:3.12-slim ghcr.io/otis22/python:3.12-slim`, затем `docker push ghcr.io/otis22/python:3.12-slim`. Перед push необходим `gh auth token | docker login ghcr.io -u otis22 --password-stdin`. Сверить digest и проверить публичный pull; обновление mutable tag требует отдельного CI прогона.

## Оценка простоты

Один build job, штатный artifact для передачи образа и узкий сторож YAML; новых runtime-зависимостей нет.
