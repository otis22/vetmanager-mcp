# PRD: Этап 23. Vetmanager auth mode #1 `domain + rest_api_key`

## Цель

Оформить первый поддерживаемый способ подключения аккаунта к Vetmanager как
явный auth-mode слой, а не как неструктурированный словарь credentials.

## Проблема

- В bearer runtime уже хранится `vetmanager_connection`, но его credentials пока
  читаются как generic payload без отдельного контракта по mode.
- Следующий этап продукта должен поддерживать несколько способов авторизации в
  Vetmanager, поэтому current `domain/api_key` path нужно вынести в отдельный
  abstraction layer заранее.

## Границы этапа

- `23.1` реализует только mode `domain + rest_api_key`.
- Проверка реального подключения при сохранении connection остаётся задачей `23.2`.
- Полный прогон всех MCP tools/prompts поверх bearer runtime остаётся задачей `23.4`.

## Решение

1. Добавить отдельный модуль Vetmanager auth modes.
2. Зафиксировать mode identifier для первого режима:
   `domain_api_key`.
3. Реализовать resolver, который:
   - принимает `VetmanagerConnection`;
   - расшифровывает payload;
   - валидирует обязательные поля `domain` и `api_key`;
   - возвращает нормализованный credentials contract для runtime клиента.

## Критерии готовности для 23.1

- В проекте есть явный abstraction layer для Vetmanager auth modes.
- Mode `domain + rest_api_key` реализован как отдельный поддерживаемый режим.
- Runtime bearer lookup получает Vetmanager credentials через этот слой, а не
  напрямую из generic dict.
