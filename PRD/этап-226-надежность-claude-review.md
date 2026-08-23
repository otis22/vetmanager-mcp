# Этап 226. Надёжность внешнего Claude review

## Цель

Сделать один запуск Claude structured-review конечным и диагностируемым: он
либо сохраняет валидный verdict, либо в ограниченный срок возвращает ошибку с
причиной, evidence и exit code. Зависший CLI не должен удерживать review gate
бесконечно.

## Проверенные факты

- `run_claude_review.sh` запускает Claude через GNU `timeout`, но без
  `--kill-after`: процесс, игнорирующий TERM, может пережить deadline.
- Evidence от 2026-08-22 18:48:18Z зафиксировал пустой envelope, `cli_exit=143`
  и длительность 41.6 s. Это внешний SIGTERM, а не verdict Claude; runner
  сохранил факт, но не классифицировал причину.
- Валидатор уже отвергает пустой `.result`, однако вызывается лишь после
  `cli_exit=0`; поэтому причина non-zero outcome остаётся только косвенной.

## Scope

1. Ограничить CLI deadline и добавить короткий kill grace, чтобы timeout
   гарантированно завершал процесс и его group.
2. Записать в metadata однозначный termination/diagnostic status для timeout,
   signal и invalid/empty verdict; вывести его в stderr без содержимого review
   или секретов.
3. Добавить регрессии с fake Claude, который игнорирует TERM, и с пустым
   structured result.
4. Проверить runner фактическим committed-diff review после commit.

## Out of scope

- Изменение модели, содержания review, API/MCP-контрактов и формата успешного
  verdict.
- Автоматическое повторение review: попытки учитываются workflow и должны
  оставаться явными.

## Архитектурное решение

Architecture Critique: not required — изменение ограничено локальным shell
runner и evidence workflow, не меняет storage, публичный API, production
поведение или межмодульное ownership.

Проблема: один `timeout` с TERM не гарантирует завершение непослушного CLI, а
raw exit code не объясняет пустой evidence. Альтернативы: (a) оставить
существующий timeout, (b) полагаться на внешний timeout оркестратора, (c)
использовать GNU timeout с kill grace и классифицировать outcome. Выбрано (c):
`timeout --kill-after` сохраняет текущую CLI-команду и обеспечивает жёсткий
верхний предел; metadata фиксирует наблюдаемый outcome, не пытаясь угадать
вердикт.

Инварианты: evidence остаётся вне working tree, сохраняются raw stdout/stderr
даже при timeout, успешный valid verdict и schema не меняются, секреты не
печатаются. Rollback: удалить только новую классификацию/kill grace, сохранив
captured evidence; при недоступности GNU timeout runner честно завершается с
диагностикой вместо запуска без deadline.

## Декомпозиция

1. Добавить bounded termination и outcome metadata (≤150 строк).
2. Написать fake-CLI regression tests (≤150 строк).
3. Прогнать shell checks, полный test contour, аудит и committed-diff review.

## Acceptance criteria

- CLI, игнорирующий TERM, завершается после configured timeout плюс grace, а
  runner сохраняет evidence и non-zero result.
- Пустой/invalid verdict получает явную диагностическую классификацию.
- Успешный structured verdict по-прежнему печатается validator'ом.
- Команда `scripts/run_claude_review.sh --range HEAD^..HEAD --attempt 1/3`
  способна завершиться валидным verdict или bounded diagnostic outcome.
