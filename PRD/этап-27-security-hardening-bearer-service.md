# PRD: Этап 27. Security hardening Bearer-сервиса

## Цель

Усилить bearer-only сервис на уровне runtime-защиты, чтобы снизить риск abuse,
brute-force и бесконтрольной эксплуатации Bearer-токенов без изменения базового
продуктового контракта MCP.

## Контекст

- Этапы 20–26 уже перевели проект на bearer-only runtime и добавили:
  - аккаунты;
  - Vetmanager integration на уровне аккаунта;
  - хранение hash Bearer-токенов;
  - TTL / revoke;
  - usage accounting (`last_used_at`, `request_count`);
  - web-кабинет и два Vetmanager auth mode.
- В `Roadmap.md` следующий незавершённый этап после 26 — этап 27.
- По правилам workflow первым разрешённым пунктом реализации является `27.1`.

## Границы этапа 27

- `27.1` rate limiting по Bearer-токену.
- `27.2` более подробный audit trail по auth events.
- `27.3` cleanup/revocation policy для истёкших токенов.
- `27.4` security hardening web sessions и secret management.
- `27.5` синхронизация technical requirements и `AssumptionLog.md`.

## Граница текущей подзадачи 27.1

На этом шаге внедряется только базовый runtime rate limiting:

- ограничение применяется к bearer-аутентифицированным MCP-запросам;
- ключ лимита: `bearer_token_id`;
- реализация process-local in-memory, без новой схемы БД;
- окно лимита sliding-window;
- при превышении возвращается явная безопасная ошибка со статусом `429`;
- заблокированный запрос не должен обновлять usage accounting как успешный вызов.

## Почему без БД-распределённого limiter на этом шаге

- Roadmap требует начать с верхней подзадачи, а не с полной распределённой
  security-платформы.
- В текущем репозитории нет Redis/внешнего rate-limit backend.
- Для одного процесса MCP-сервера process-local limiter уже даёт реальную защиту
  от burst abuse и не требует миграций.
- Более строгая multi-instance координация может быть вынесена в будущий этап,
  если deployment-модель это потребует.

## Предлагаемый контракт 27.1

- Конфигурация через env:
  - `BEARER_RATE_LIMIT_REQUESTS` — максимум запросов в окне;
  - `BEARER_RATE_LIMIT_WINDOW_SECONDS` — длина окна.
- Дефолт:
  - `1000` запросов;
  - `60` секунд.
- Поведение:
  - каждый успешный проход auth context reservation занимает один слот окна;
  - если в пределах окна уже достигнут лимит, запрос получает `429`;
  - сообщение ошибки не раскрывает raw Bearer-токен;
  - текст ошибки может содержать `retry_after_seconds`.

## Точки интеграции

- `bearer_auth.py`
  - после успешного lookup и проверки статуса токена;
  - до `mark_used()` и до обновления `TokenUsageStat`.
- Новый модуль limiter
  - хранит process-local состояние;
  - имеет reset/helper для unit-тестов.
- `exceptions.py`
  - отдельный тип ошибки rate limiting со статусом `429`.

## Тестовая стратегия

- Unit/integration tests должны покрыть:
  - запросы в лимите проходят;
  - следующий запрос в том же окне блокируется;
  - лимит изолирован по разным Bearer-токенам;
  - после истечения окна токен снова допускается;
  - заблокированный запрос не увеличивает `request_count`.

## Декомпозиция

### 27.1.1 PRD и контракт
- Зафиксировать выбранную process-local sliding-window модель.
- Зафиксировать env-конфигурацию и дефолты.

### 27.1.2 Red tests
- Добавить тесты на limit exceed, window reset и token isolation.

### 27.1.3 Runtime implementation
- Добавить in-memory limiter с `asyncio.Lock`.
- Встроить limiter в `resolve_bearer_auth_context()`.
- Вернуть безопасную ошибку `429` без утечки секрета.

### 27.1.4 Verification
- Прогнать unit-тесты bearer/runtime/web слоёв, затронутых изменением.
- Обновить `Roadmap.md` и `AssumptionLog.md`.

## Критерии готовности для 27.1

- В репозитории есть отдельный PRD этапа 27.
- Bearer runtime ограничивает частоту запросов по `bearer_token_id`.
- Ошибка превышения лимита возвращается как `429`.
- Заблокированный запрос не увеличивает usage accounting.
- Тесты на rate limiting проходят.
