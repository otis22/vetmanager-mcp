# PRD: Этап 25. Usage accounting и admin analytics

## Цель

Добавить эксплуатационный слой вокруг Bearer-токенов: фиксировать фактическое
использование токенов в runtime и показывать эти данные в web-кабинете без
раскрытия секретов.

## Проблема

- Web-кабинет уже умеет выпускать и показывать токены, но usage-поля пока в
  основном статичны.
- В storage уже есть `last_used_at`, `token_usage_stats` и `token_usage_logs`,
  но runtime пока не обновляет их при реальных bearer-authenticated запросах.
- Без usage accounting кабинет показывает форму токена, но не даёт оператору
  наблюдаемости по тому, когда токен использовался и сколько запросов он сделал.

## Границы этапа

- `25.1` ограничен обновлением `last_used_at` для Bearer-токена в runtime.
- `25.2` добавляет счётчик запросов.
- `25.3` добавляет lifecycle audit для create/revoke событий.
- `25.4` использует уже собранные usage-данные в кабинете.
- `25.5` добавляет отдельные security-oriented тесты на usage accounting.

## Декомпозиция

### 25.1 last_used_at
- Обновлять `ServiceBearerToken.last_used_at` на успешном bearer lookup.
- Не обновлять timestamp для invalid/revoked/expired token paths.

### 25.2 request_count
- Завести и/или обновлять `TokenUsageStat.request_count`.

### 25.3 audit log
- Фиксировать безопасные lifecycle events без raw token.

### 25.4 web display
- Показать usage metadata в кабинете как уже живые данные, а не placeholders.

### 25.5 tests
- Добавить tests для last_used/request_count/audit без утечек raw secrets.

## Критерии готовности для 25.1

- В runtime успешный bearer-authenticated запрос обновляет `last_used_at`.
- Timestamp сохраняется в БД и доступен для web-кабинета.
- Ошибочные auth paths не создают ложных отметок использования.
