# PRD: Этап 42.1. Browser test stack в стандартном pytest

## Контекст

Этап 42 переводит browser happy-path проверки из разовых ручных/opt-in сценариев
в обязательную часть обычного test suite. Первая подзадача должна подготовить
только инфраструктурный слой, на который затем опрутся live harness, upstream
mocks и сами browser happy-path tests.

В текущем репозитории:
- основной test suite запускается через `pytest` внутри Docker profile `test`;
- browser-level тесты как часть обычного suite ещё не подключены;
- в проекте нет зафиксированного browser stack, pytest browser fixtures и
  docker-окружения для такого запуска.

## Цель 42.1

Сделать так, чтобы стандартный запуск тестов проекта уже содержал готовый
browser test stack:
- зависимости для browser tests входят в проект и test container;
- `docker compose --profile test run --rm test` устанавливает и видит этот stack;
- обычный `pytest` знает о browser marker/fixtures и может запускать browser
  tests без отдельного ручного bootstrap вне проекта.

Сами browser happy-path тесты и live HTTP harness в эту задачу не входят.

## Границы задачи

### Входит

- Добавление Python-зависимостей для browser tests.
- Подготовка Docker image/test command под browser runtime.
- Настройка `pytest` для browser-маркера и минимального smoke coverage.
- Добавление минимального regression test, который подтверждает наличие browser
  stack в дефолтном suite.

### Не входит

- Реальный browser happy-path по страницам `/register`, `/login`, `/account`.
- Live HTTP harness для реального браузера.
- Upstream mocks Vetmanager для browser path.
- Cleanup test accounts и browser tests на реальных внешних данных.

## Решения для реализации

### Browser stack

- Использовать Playwright как browser runtime.
- Использовать `pytest-playwright` для интеграции с обычным `pytest`.
- Дефолтный browser для проекта на этом этапе: Chromium.

### Docker-only workflow

- Browser stack должен подниматься внутри существующего Docker test workflow.
- Не должно появиться требований запускать отдельный локальный bootstrap на
  хосте как обязательное условие для обычного test suite.

### Smoke-проверка

- Нужен минимальный тест, который падает, если browser plugin/fixtures не
  подключены в стандартном `pytest`.
- Проверка должна быть детерминированной и не зависеть от внешнего Vetmanager.

## Декомпозиция

### 42.1.1 PRD и workplan
- Создать PRD для задачи 42.1.
- Пометить `42.1` как `in_progress` в `Roadmap.md`.

### 42.1.2 Red test
- Добавить минимальный тест на наличие browser stack в обычном `pytest`.
- Зафиксировать ожидаемый marker/fixture/runtime contract.

### 42.1.3 Infra
- Добавить зависимости Playwright/pytest-playwright в проект и Docker image.
- Подготовить установку browser binaries/system deps в test/runtime образе.
- При необходимости обновить `pytest.ini`.

### 42.1.4 Validation
- Прогнать целевой тест.
- Прогнать полный test suite через docker profile `test`.
- После завершения обновить `Roadmap.md` и `AssumptionLog.md`.

## Критерии готовности

- В репозитории есть PRD задачи 42.1.
- Обычный `pytest` знает browser marker и browser fixtures.
- `docker compose --profile test run --rm test` включает browser stack без
  дополнительного ручного bootstrap на хосте.
- Есть regression test на наличие browser stack.
- Результат зафиксирован в `Roadmap.md` и `AssumptionLog.md`.
