# Этап 225.3. Понятный отказ при дефекте диагнозов Vetmanager

## Цель

Когда Vetmanager возвращает подтверждённую ошибку typed `Diagnoses::$diagnoses`
при обновлении медкарты с диагнозом, вернуть модели ясный ToolError, что запись
не выполнена из-за дефекта upstream, без опасного обхода со стиранием диагноза.

## Архитектурное решение

Выбран узкий mapper в `update_medical_card`: он ловит `VetmanagerError` только
при HTTP 500 и точной стабильной части подтверждённой сигнатуры. Общий rewrite
всех 500 не выбран: клиент уже передаёт upstream message, а обобщение не может
правдиво утверждать причину или безопасность записи. Mapper явно говорит не
считать update состоявшимся и не повторять его с пустым `diagnos`. Если upstream
изменит сигнатуру, будет прежний прозрачный upstream error, а не ложная причина.
Rollback: удалить узкий except/mapper.

Architecture Critique: required (public MCP error contract and upstream boundary).

## Декомпозиция

1. Добавить узкий mapper и mock regression, ≤80 LOC.
2. Проверить, что обычные 500 не меняют смысл, ≤80 LOC.
3. Полный suite и аудит.

## Acceptance criteria

- Сигнатура diagnoses-500 возвращает понятный отказ без success payload.
- Сообщение не предлагает `diagnos: ""` и говорит, что запись не обновлена.
- Другие upstream-500 сохраняют исходный error behavior.
