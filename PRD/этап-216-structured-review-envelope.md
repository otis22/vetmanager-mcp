# Этап 216. Корректная оценка structured output внешнего ревью

## Цель

Исправить workflow strong-review для Claude Code: не считать штатный
`stop_reason=tool_use` инфраструктурным сбоем, когда `--json-schema` доставляет
structured verdict в JSON-конверте.

## Проверенные факты

- Claude CLI возвращает JSON-конверт; успех определяется `is_error=false` и
  непустым `.result`, который содержит JSON verdict.
- При `--json-schema` `stop_reason=tool_use` является штатным способом доставки
  structured output и не характеризует успех или сбой.
- Базовый `claude -p "Reply with OK"` из Codex runtime работает; известный
  сбой был пустым `.result` после израсходования output budget на thinking, а
  не пустым stdout или недоступной авторизацией.

## Scope

1. Обновить `.cursor/rules/agent-workflow.mdc`, `AGENTS.md` и `CLAUDE.md`:
   success/failure классифицируется по JSON-конверту и `.result`, без проверки
   `stop_reason`.
2. Добавить в пример `jq -e`, который извлекает `.result`, парсит verdict и
   проверяет required findings schema.
3. Добавить в эталонный prompt фразу: `Think briefly, then return JSON
   matching the schema immediately`.
4. Сохранить существующий бюджет: инфраструктурный сбой не расходует slot,
   максимум три подряд на один strong gate.

## Out of scope

- Повторный запуск исторических review или задняя переклассификация без
  сохранённых JSON-конвертов.
- Изменение code/product behavior и push.

## Простота решения

Architecture Critique: not required — меняются только проверяемые workflow
инструкции и shell-пример. Один `jq -e` pipeline делает критерий наблюдаемым и
не требует нового runner/script.

## Acceptance criteria

- `tool_use` и `stop_reason` не являются failure criteria.
- Валидный envelope с непустым schema-valid `.result` засчитывается; пустой или
  invalid `.result` — infrastructure failure.
- Пример извлекает verdict, а не принимает raw stdout за вывод ревьюера.
- Промпт ограничивает размышление перед structured result.
