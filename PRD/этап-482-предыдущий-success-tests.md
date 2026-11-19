# Этап 482 — предыдущий успешный Tests run для docs-only main

## Цель

Убрать лишний полный продуктовый контур после docs-only merge на main, когда
непосредственный предыдущий commit уже имеет достоверный успешный Tests run.
При отсутствии такого доказательства или ошибке GitHub API выполнять полный
контур.

## Факты и границы

- На публичном GitHub REST API для предыдущего SHA `06c9c550d1f6bac1b6c6073f96a6e1911d4b9632`
  endpoint `actions/workflows/test.yml/runs` с `event=push`, `head_sha` и
  `status=success` возвращает `total_count=0`; без `status` — один run
  `44472826301` со `status=completed`, `conclusion=success`, `event=push`,
  `head_branch=main`, нужными SHA и workflow path. Такой же ноль дают
  `status=completed` и `status=failure`. Запросы повторены 20.11.2026.
- Документация [GitHub REST API](https://docs.github.com/en/rest/actions/workflow-runs)
  описывает `status` как фильтр по status или conclusion. Наблюдаемый ответ
  противоречит этому контракту именно для указанного run. Внутренняя причина
  расхождения в GitHub недоступна через публичный API; предположение о ней не
  является основанием для skip.
- Контракт Vetmanager API, runtime, деперсонализация и UI не затрагиваются.
  Из `artifacts/prd-vetmanager-mcp-ru.md` и
  `artifacts/technical-requirements-vetmanager-mcp-ru.md` применимы только
  общие требования к надёжности и проверяемости; CI-схема задана PRD 478A.

## Решение

Запрашивать runs по точному `head_sha` и `event=push` без серверного `status`.
На клиенте принимать лишь run с точным SHA, `event=push`, `head_branch=main`,
`status=completed`, `conclusion=success` и ожидаемым workflow path. Неверная
структура ответа, отсутствующий success и ошибка API оставляют
`run_product=true`. Ограничение 100 результатов и точный SHA сохраняются.

## Подзадачи

1. Зафиксировать пары ответов публичного API и красные focused guards для
   существующего success, отсутствия success, неверных полей и ошибки API
   (до 150 строк).
2. Исправить `scripts/ci_scope.py`, довести каждый red node до зелёного,
   пройти owning suite и fast (до 150 строк).
3. Аудит, full pre-review рабочего diff, применимые локальные gates,
   отдельный PR и проверка workflow на нём; commit и release-review
   (до 2 часов на шаг).

## Приёмка

- Guard проверяет фактически отправленный query: точные `event=push` и
  `head_sha`, `per_page=100`, без параметра `status`. Для исторического run
  `44472826301` селектор принимает успех из такого ответа; docs-only main
  возвращает `run_product=false`.
- Отдельные негативные примеры для `status` не `completed`, `conclusion` не
  `success`, чужого SHA, `head_branch`, `event` и workflow path, а также
  невалидного ответа и ошибки API дают полный продуктовый контур.
- На реальном PR `Tests` и `Docs Check` завершаются, а CI-only изменение
  decision script запускает требуемые product jobs. После merge куратор
  проверит docs-only main по результатам отдельного PR.

## Проверки и откат

Focused red/green, owning suite, fast, инвентаризация и структура Roadmap,
полный default и PostgreSQL после заморозки (Python-скрипт входит в общий
fingerprint), сильное PRD/pre-freeze/committed review. ShellCheck, browser,
real API и live MCP tool не применяются, поскольку их код/контракты не
меняются. Откат — вернуть
`status=success`: это создаст лишний полный контур, но сохранит fail-closed.

## Оценка простоты

Один существующий запрос и один предикат в одном файле. Новых классов,
конфигурации и веток workflow нет. Более сложный fallback с повторным
запросом не нужен: ответ без `status` уже позволяет локально проверить поля.
