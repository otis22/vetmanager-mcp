# Этап 218. Evidence каждой попытки внешнего ревью

## Цель

Сделать каждый запуск Claude structured-review диагностируемым независимо от
результата: сохранить raw-конверт и контекст вызова вне рабочей копии, чтобы
следующий infrastructure failure можно было проверить по фактам.

## Проверенные факты

- Исторические записи о «без output» не содержат raw JSON-конверт и не могут
  быть достоверно переклассифицированы.
- На измеренной лестнице до 127 793 байт structured result доставлялся, но
  thinking занимал до 13 410 из 13 932 output tokens (96%).
- `Think briefly, then return JSON matching the schema immediately` уменьшал
  thinking в малом контуре и остаётся частью эталонного prompt.

## Scope

1. Добавить runner одной попытки Claude review с обязательными range и меткой
   `N/3`.
2. Сохранять вне рабочей копии raw stdout-конверт без преобразования, stderr,
   prompt, schema и metadata: stdin bytes/lines, range, CLI version, start,
   duration, exit и ключевые поля envelope.
3. Обновить workflow: каждая попытка ссылается в AssumptionLog на evidence и
   перечисляет `subtype`, `stop_reason`, `output_tokens`, `thinking_tokens`,
   `len(result)`.
4. Покрыть успешный и неуспешный CLI outcome regression-тестами.

## Out of scope

- Изменение глубины review, дробление больших diff или изменение MCP/API
  контрактов.
- Задняя переклассификация старых запусков без сохранённого конверта.

## Архитектурное решение

Architecture Critique: not required — runner ограничен локальным workflow и
файловым evidence вне working copy; он не меняет MCP/API-контракты, storage или
production behavior. Один shell-runner выбран вместо нового сервиса: raw stdout
записывается отдельным файлом без JSON-пересборки, а metadata хранит извлечённые
поля и ссылки на неизменяемые evidence-файлы. При ошибке runner сохраняет
доступный stdout/stderr и возвращает исходный exit CLI; fallback — ручной разбор
сохранённого package без попытки угадать verdict.

## Acceptance criteria

- Для exit 0 и non-zero создаётся evidence package с marker `attempt-N-of-3`.
- Raw stdout сохраняется байт-в-байт, включая пустой stdout.
- Metadata содержит все перечисленные параметры вызова и извлечённые поля
  envelope, если JSON разобран.
- Документированный baseline prompt сохраняет ограничение thinking.
