# PRD Этап 16: tools/list по спецификации MCP

## Цель
Гарантировать, что `tools/list` возвращает для всех зарегистрированных
инструментов полноценный MCP-совместимый контракт без хардкода на стороне
клиента: `name`, осмысленное `description` и непустой `inputSchema`.

## Проблема
- `FastMCP` уже публикует `inputSchema`, но качество `description` зависит от
  docstrings инструментов.
- После перехода на headers-only в экспортируемых описаниях остались legacy
  строки про `domain` и `api_key`, которых больше нет в runtime-контракте.
- Отдельной регрессионной проверки на полноту `description` + `inputSchema`
  пока нет.

## Границы задачи
- Обновить docstrings `tools/*.py` настолько, чтобы `tools/list` отдавал
  актуальные описания.
- Добавить тест на экспорт `tools/list`.
- Обновить README, Roadmap и AssumptionLog.
- Не менять transport, бизнес-логику инструментов и OpenAPI-контракт.

## Декомпозиция

### 16.1 Проверка текущего tools/list
- Убедиться, что все tools публикуют `name`, `description`, `inputSchema`.
- Проверить отсутствие пустых схем и пустых описаний.

### 16.2 Очистка description
- Убрать из docstrings `tools/*.py` устаревшие `domain` / `api_key` аргументы.
- Сохранить полезное описание бизнес-параметров и поведения.

### 16.3 Тесты
- Добавить проверку, что `tools/list` возвращает:
  - непустой `description`;
  - непустой `inputSchema`;
  - отсутствие legacy credential hints в `description`.

### 16.4 Документация
- Зафиксировать в README, что `tools/list` можно использовать как источник
  описаний и схем параметров.
- Обновить AssumptionLog и статус этапа в Roadmap.

## Критерии готовности
- Все tools в `tools/list` имеют непустой `description`.
- Все tools в `tools/list` имеют непустой `inputSchema`.
- В `description` нет legacy указаний про runtime credentials.
- Есть тест, защищающий контракт от регрессии.
