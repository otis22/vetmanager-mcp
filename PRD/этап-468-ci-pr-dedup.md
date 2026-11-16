# Этап 468. Убрать дублирующийся CI на dev-ветках

## Цель

Убрать два набора Tests и Docs Check для одной SHA `dev/**`, когда ветка
обновляется вместе с открытым pull request. Сократить ожидание и расход CI
без ослабления проверки main после merge.

## Контекст и контракт

Сейчас `test.yml` и `docs.yml` слушают и push `dev/**`, и pull_request в main.
`Tests` содержит fast, default и PostgreSQL jobs; `Docs Check` валидирует
Roadmap. `deploy-prod.yml` пропускает только успешный Tests для main от push
или workflow_dispatch. `shellcheck.yml` и `test-real.yml` не входят в изменение.
Главный PRD и технические требования не задают триггеры CI; контракт здесь
определён действующими workflow и решением владельца 16.11.2026.

## Архитектурное решение

- Проблема: два события GitHub Actions запускают один и тот же workflow для
  одной PR SHA.
- Варианты: условное отключение jobs на dev-push сложнее и всё равно создаёт
  workflow run; отмена через concurrency может прервать полезную PR-проверку.
- Решение: в `test.yml` и `docs.yml` оставить `push.branches: [main]` и
  существующие `pull_request.branches: [main]`. Ручной Tests сохранить.
- Инварианты: main push запускает Tests и Docs Check по прежним path filters;
  dev PR запускает их по тем же path filters; прямой hotfix в main проверяется;
  deploy gate, ShellCheck и opt-in real не меняются.
- Ограничение: dev-ветка без PR больше не получает Tests/Docs; это сознательное
  решение владельца, заменяющее dev-push контракт этапа 414. Проверяются PR
  только с base `main`; промежуточные PR в другую dev-ветку не получают эти
  два workflow. PR проверяет GitHub merge ref, а не непосредственно head SHA.
  Исполнитель передаёт ветку после push; куратор открывает PR и проверяет
  статусы до merge. Правило выпуска в workflow и шаблоне обновляется.
- Откат: вернуть `dev/**` в оба push triggers, если процесс PR изменится.

Architecture Critique: required — изменение CI влияет на обязательные
проверки перед выпуском, хотя runtime и API не затрагиваются.

## Подзадачи

1. (≤2 ч, ≤150 строк) Обновить сторож прежнего dev-push контракта на матрицу
   событий; показать focused red до YAML-правки.
2. (≤2 ч, ≤150 строк) Изменить два YAML trigger, актуализировать документацию.
3. (≤2 ч) Focused green, owning/fast, YAML и event-matrix проверка; аудит,
   pre-review, применимые gates, commit, committed-diff review и branch push.

## Критерии приёмки

- Для `dev/**` Tests/Docs доступны через PR в main и не запускаются от push.
- Для main push Tests/Docs остаются; Tests workflow_dispatch остаётся.
- Path filters, Jobs, Deploy Prod, ShellCheck, real и защита main не меняются.
- Причинный red/green, проверки и оба сильных verdict зафиксированы.
- До push статическая матрица триггеров доказывает отсутствие dev-push runs и
  сохранение main-push runs. После открытия PR куратор сверяет реальные Tests
  и Docs Check на head SHA: один pull_request run каждого применимого workflow,
  ноль push runs. После merge куратор сверяет Tests main push и штатный Deploy
  Prod. Эти внешние наблюдения не выдаются за выполненные до создания PR.
