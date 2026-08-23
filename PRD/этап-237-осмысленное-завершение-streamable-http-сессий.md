# Этап 237. Осмысленное завершение streamable-HTTP сессий

## Цель

Устранить PYTHON-6 (`ASGI callable returned without completing response`) при
штатной остановке контейнера, не меняя публичный MCP transport, путь или
контракт уже подключённых Claude и ChatGPT.

## Проверенные факты и scope

- После выкатки `693f8c4` 23.08.2026 в 01:16 МСК счётчик PYTHON-1 не вырос:
  cleanup asyncpg на живом event loop из этапа 230 работает.
- В ту же остановку PYTHON-6 вырос с 1 до 2. Его прислал останавливаемый
  контейнер с кодом этапа 230, поэтому это не регресс release-тегов этапа 236.
- Runtime использует FastMCP 3.2.0 и `mcp` 1.29.0 (проверено командой Docker
  против lockfile). Его stateful
  `StreamableHTTPSessionManager` хранит сессии в `_server_instances`; у сессии
  открыт GET SSE stream. Менеджер завершает все эти сессии только в собственном
  lifespan shutdown, который Uvicorn начинает после завершения или отмены
  активных ASGI tasks.
- В текущем порядке Uvicorn сначала прекращает listener и ждёт active tasks до
  `timeout_graceful_shutdown=20`; бесконечный session GET не является обычным
  tool call и естественно не завершится. После timeout Uvicorn отменяет task,
  отчего ASGI response остаётся незавершённым. Это объясняет PYTHON-6.
- Обычный POST tool call имеет ограниченный существующий budget upstream read
  20 секунд и может завершиться в drain. Долгоживущая GET-сессия требует
  явного закрытия её stream, после чего EventSourceResponse закончит HTTP
  response штатно.
- Изменение затрагивает production behavior и внешний transport, поэтому до
  реализации нужен Architecture Critique.

## Декомпозиция

1. **237.1 — regression harness (≤150 LOC).** Построить local ASGI-проверку
   настоящего streamable-HTTP session manager: обычный завершённый response
   остаётся завершённым, а удерживаемый SSE GET существует до drain и получает
   корректный `http.response.body` с `more_body=false` после него.
2. **237.2 — session drain (≤150 LOC).** При SIGTERM до передачи управления
   Uvicorn на живом event loop закрыть только standalone GET SSE stream у snapshot
   stateful transports, не завершая transport и не трогая in-flight POST tool
   calls. Записать безопасный structured outcome. Новые соединения
   по-прежнему перестаёт принимать Uvicorn; transport/path/auth не меняются.
3. **237.3 — handoff.** Документировать в AssumptionLog ожидаемую живую
   проверку супервизора: после deploy PYTHON-6 не увеличивается, а закрытие
   старой удерживаемой сессии выглядит для клиента как нормальное завершение
   SSE, а не обрыв ASGI response. Пункт не закрывается этим PR.

## Архитектурное решение

### Проблема

Uvicorn корректно ждёт обычные конечные запросы, но stateful streamable-HTTP
GET намеренно долгоживущий. Ждать его до общего timeout означает отменить ASGI
task до отправки финального body event.

### Контекст и ограничения

FastMCP 3.2.0 не предоставляет public API для обхода всех manager sessions,
поэтому snapshot реестра `_server_instances` изолирован в одном helper. Зато
у `mcp` 1.29.0 transport есть public синхронный
`close_standalone_sse_stream()`: он закрывает только GET SSE connection,
оставляя сам transport и его POST request streams живыми. Это предотвращает
обрыв активного tool call той же MCP-сессии. Helper валидирует наличие нужных
атрибутов/метода, тест проверяет identity извлечённого manager; при несовместимой
библиотеке он пишет безопасный error и оставляет старое поведение, а
`STREAMABLE_HTTP_DRAIN_ENABLED=false` — аварийный обратимый kill switch. В
логах запрещены session IDs, авторизационные данные и данные запросов.

### Рассмотренные варианты

1. Увеличить `timeout_graceful_shutdown`. Не работает: удерживаемый GET не
   имеет естественного конца, только растягивает deploy.
2. Перевести transport в stateless/JSON или изменить клиентский контракт.
   Нарушает подключённые интеграции и выходит за scope.
3. Завершать менеджер в lifespan. Слишком поздно: до lifespan Uvicorn уже
   ждёт тот же бесконечный ASGI task.
4. На входе в drain вызвать штатный `close_standalone_sse_stream()` для
   удерживаемых GET. Он завершает именно response, но не прерывает POST.
5. Отдельный `loop.add_signal_handler`. Он конкурирует с Uvicorn за владельца
   сигнала и усложняет порядок shutdown; уже существующий тонкий Uvicorn
   subclass остаётся единственной точкой signal ownership.

### Выбранное решение

Выбран вариант 4. Server строит HTTP app один раз, извлекает live session
manager из созданного streamable route и передаёт его тонкому Uvicorn subclass.
`handle_exit` только выставляет draining и вызывает исходный Uvicorn handler.
Переопределённый async `shutdown()` на живом loop вызывает helper для snapshot
stateful transports, даёт пробуждённым EventSourceResponse один scheduling
turn, и лишь затем вызывает `super().shutdown()`, закрывающий listener и
ожидающий уже конечный ASGI task. Нельзя завершать transport или удалять
session: это оборвало бы активный POST tool call. Повторный SIGTERM оставляет
обычный Uvicorn force-exit semantics вне гарантий этого graceful-stage.

### Инварианты

- `streamable-http`, `/mcp`, OAuth и существующие headers не меняются.
- Обычный и in-flight POST MCP response не закрывается принудительно.
- Удерживаемый session stream завершает ASGI response до общего Uvicorn
  timeout. Завершение GET — ожидаемое контролируемое отключение: после
  restart MCP-клиент устанавливает новую сессию; server-initiated messages на
  старом GET не обещаны во время deploy.
- Shutdown helper запускается только из `Uvicorn.shutdown()` на живом loop и
  не вмешивается в cleanup
  ресурсов этапа 230.
- Ошибка или SDK drift одной сессии не блокируют остальные и не раскрывают IDs.

### Rollback/fallback

Один revert возвращает прежний порядок Uvicorn. Для следующей выкатки оператор
может задать `STREAMABLE_HTTP_DRAIN_ENABLED=false` (по умолчанию `true`), что
отключает только новый helper, не меняя transport или startup. Если FastMCP/MCP меняет нужные
атрибуты/метод, helper оставляет прежний lifecycle и пишет безопасное
наблюдаемое событие; адаптация требует отдельного PRD, а не тихого обращения
к другой private структуре.

## Acceptance criteria

- Local regression показывает различие между конечным обычным response и
  удерживаемым stateful SSE GET; второй после drain посылает final ASGI body,
  не остаётся pending и не выдаёт `ASGI callable returned without completing
  response`.
- При SIGTERM Uvicorn вызывает helper до своего `super().shutdown()`; все
  удерживаемые GET SSE streams закрываются idempotently и без session IDs в
  логах, существующий in-flight POST не закрывается и получает время прежнего
  20-second drain. Regression проверяет порядок override перед parent
  `Uvicorn.shutdown()` и завершение реального SDK memory stream.
- Test доказывает identity извлечённого manager, normal no-op при отсутствии
  GET stream, public method на реальном установленном SDK и безопасный kill
  switch/SDK-compatibility fallback; stateless manager даёт корректный no-op.
- Полный Docker test contour проходит; новый runtime module (если появится)
  добавлен в wheel allowlist.
- PR открыт сразу после первого push. Для 237.3 супервизор сверяет baseline
  счётчика PYTHON-6 перед deploy и после окна обычной клиентской активности;
  рост, либо повторный незавершённый ASGI response — trigger kill switch/revert.
  230.4 не закрывается до этого evidence.

## Не входит в этап

- Ручной доступ к production server, deploy или изменение Sentry.
- Изменение MCP transport/auth/client configuration.
- Закрытие Roadmap 237.3 либо 230.4 без live evidence супервизора.
