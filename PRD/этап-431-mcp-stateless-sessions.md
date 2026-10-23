# Этап 431 — устойчивость MCP при смене воркера

Дата: 23.10.2026. Источник: Roadmap 431, feedback #139.

## Цель

После смены MCP-воркера или его перезапуска read tool отвечает HTTP 200 со старым `Mcp-Session-Id` и без него, без повторной инициализации клиента. Scheduled-клиент сохраняет доступ к каталогу инструментов.

## Проблема и факты

Scheduled Claude Cowork теряет каталог инструментов после ночного деплоя или перехода на другой из трёх воркеров. По наблюдению супервизора в прод-журнале есть 404 на POST /mcp со старым Mcp-Session-Id; снимок логов в рабочем окружении отсутствует. В `mcp.server.streamable_http_manager` SDK stateful transport хранится в `_server_instances` процесса, а неизвестный ID отклоняется. `FastMCP.http_app` установленной 3.4.7 принимает `stateless_http`; в SDK stateless создаёт transport на каждый POST без session ID. Авторизация FastMCP выполняется на каждом HTTP-запросе. Кода sampling, elicitation, roots, progress/log notifications и event store в приложении нет. `first_session` хранится в БД по account_id, а не по transport ID. Rate limiter привязан к bearer/account, а `RequestContextHeaderMiddleware` к отдельному HTTP-запросу. Smoke инициализирует MCP, отправляет `notifications/initialized` и вызывает инструмент; заголовок сессии ставит только при наличии.

Связанные артефакты: `artifacts/prd-vetmanager-mcp-ru.md` (контракт read/write tools), `artifacts/technical-requirements-vetmanager-mcp-ru.md` (streamable HTTP и auth). Контракт Vetmanager REST не меняется.

## Декомпозиция

1. 431.1. Проверить runtime/SDK, воспроизвести stale-session 404 в тесте, подтвердить совместимость auth, smoke, middleware (≤ 2 ч).
2. 431.2. Включить stateless на производственном streamable HTTP пути, адаптировать drain и проверки, живой вызов, выпуск (≤ 150 строк кода).

## Архитектурное решение

Выбор: `stateless_http=True` на streamable HTTP в `_run_http_server`. Варианты: Redis session/event store требует общей модели transport и поддержки SDK; event store сам по себе хранит события, но не активный session transport. Sticky nginx сохраняет affinity между воркерами, но после деплоя старый процесс и ID пропадают, а расписанный клиент может не переинициализироваться. Stateless убирает ID и маршрутизационную зависимость без новой инфраструктуры.

Инварианты: bearer проверяется на каждом POST; отказ без ключа и лимиты остаются; OAuth, /healthz, /metrics доступны; `notifications/initialized` и smoke работают; read tool доступен после смены процесса без ручной повторной инициализации. Stateful SSE drain в stateless не имеет удерживаемых GET потоков; write fence и graceful shutdown остаются. Возможные потери: server→client запросы, GET SSE и event resumability; сейчас они не используются. Установленный SDK 3.4.7 игнорирует старый заголовок в stateless: локальный protocol probe и regression guard подтверждают HTTP 200. Если новая версия SDK изменит поведение, обновление блокируется красным сторожем до совместимого исправления или отката. Rollback: вернуть stateful, сохранив прежний код release; тогда stale ID опять требует новой инициализации. Пост-релизно супервизор сверяет feedback #139 и session-404/retry через 7 дней.

## Приёмка

- Красный сторож воспроизводит stale ID после пересоздания app, затем зелёный для старого ID и без ID, с реальным MCP initialize/tools/list.
- Нет обхода bearer и вызовов без прав; smoke совместим с ответами stateless.
- Живой стенд: initialize → read tool → новый HTTP transport/воркер → тот же read tool; коды и тела сохранены без клинических данных и секретов.
- Фокусные и полные mock+real проверки, code review gate, CI ветки зелёные.

## Совместимость деплоя и тестов

Spark PRD review: accepted medium finding о неописанном SIGUSR2/drain контракте. Rolling deploy `scripts/quiesce_mcp_slot.py` ждёт `streamable_http_drain_finished`. В stateless нет held GET SSE: при SIGUSR2 после write fence логировать тот же event с `session_count=0`; отсутствие manager не ошибка. Shutdown продолжает ждать in-flight writes. Старый live guard этапа 384 на held GET SSE заменить проверкой 405 для GET /mcp, SIGUSR2 и нулевого drain marker; внутренний stateful drain unit оставить для обратимости. Старые real tests с обязательным session ID адаптировать к отсутствию заголовка и новым ожиданиям. Smoke проверяет notification status 202.

## Architecture Critique verdict, 23.10.2026

Spark: medium drain contract accepted; see section above. Astra: `[]`. Opus: four findings; accepted mixed-fleet rollout/rollback, deterministic live check, lifespan verification. Mixed stateful/stateless fleet fails when init occurs on stateless and next POST lands on stateful (400 Missing session ID), so first rollout requires fleet maintenance/all slots switched together, not rolling `stage385_deploy.py`; supervisor handles production deployment after merge. Rollback likewise uses fleet maintenance and warns that stateless clients must initialize anew. No production config changed here. GET concern checked against installed FastMCP 3.4.7 source: route methods are `POST, DELETE` when stateless, so GET is 405; guard verifies it. FastMCP app lifespan wraps `_lifespan_manager()` once per app process; stateless manager starts low-level MCP server per POST, not application lifespan; test guards process lifespan. Per-request transport cost to be checked with timing in focused smoke; no shared session state is held. Live check runs an isolated local HTTP server with devtr6 bearer, kills and restarts the same port between requests, then sends both old ID and no ID; guarantees a new process.

Legacy real guards that explicitly exercise stateful session recovery, held SSE, and their surrounding feature flows start `_run_http_server(stateless_http=False)` so their historical transport contracts remain testable. Stage 431's dedicated guard and live smoke run the production default (`True`) and cover stale ID, missing ID, notifications and a read tool after process restart. This avoids silently making historical guards assert obsolete production behavior while retaining rollback coverage.

## Первый выпуск и rollback (действие супервизора после merge)

Spark #2 medium accepted: transition sequence was underspecified. Supervisor enters fleet maintenance at proxy (stop routing `/mcp`, while `/healthz` can remain available), drains writes on every slot and waits for zero in-flight writes, stops all three old MCP workers, starts all three from the new image, verifies each local upstream has `/readyz=200`, no `Mcp-Session-Id` on initialize, and POST tools/list 200 both with stale ID and without ID; only then resumes `/mcp` traffic. If any slot fails, keep MCP routing stopped, replace all slots with the old image, verify stateful initialize and session-ID behavior, then resume traffic. Do not mix versions during either transition. This is a supervisor rollout instruction, not an agent action; no production proxy or config edits in this stage.


## Проверка замечаний второго PRD-гейта

Astra #2: `[]`. Opus #2: требование `## Цель` принято и добавлено. High о якобы rolling deploy отклонён по коду: `.github/workflows/deploy-prod.yml` запускает `scripts.stage385_deploy`; в `stage385_deploy.py` сначала `_write_site(maintenance)`, затем `_stop_old` всех слотов, затем `_compose ... --force-recreate` всех трёх и `_ready` для каждого, и только после этого `_write_site(active)` (строки 388–402). Rollback в том же `except` оставляет maintenance до восстановления прежних слотов (строки 419–431). Поэтому именно автоматический выпуск уже реализует требуемую защиту; prose супервизора уточняет проверку session режима. Medium об env-флаге отклонён: новый переключатель и изменение production compose добавят два независимых источника режима при уже атомарном full-fleet cutover. Medium о производительности принят как измерение: локальный ASGI benchmark 100 последовательных tools/list на FastMCP 3.4.7 дал stateful p50/p95 0.85/1.48 мс, stateless 1.17/1.96 мс; приёмка — p95 stateless не более stateful + 10 мс на том же контуре, повторить при апгрейде SDK. Это microbenchmark без сети/БД; live read tool и полный suite страхуют функциональность. Medium про long-running read POST отклонён как прежнее ограничение Uvicorn `timeout_graceful_shutdown=20`: оно не меняется этим этапом, write fence не обещает завершить любой read. В пределах 20 секунд Uvicorn дожидается активного POST; запросы дольше лимита могут прерываться и в прежнем режиме. Наблюдение за такими отказами — отдельная задача при фактическом сигнале.

Post-budget Spark scout found a valid release gap: `stage385_deploy.py` opened nginx after `/readyz` only. Implemented `_stateless_protocol_ready` before `_write_site(active)`: each local slot must answer initialize HTTP 200 both without session ID and with a stale ID, with protocolVersion 2025-03-26 and no new `mcp-session-id` header. Failure keeps maintenance and follows existing full-fleet rollback. The public bearer smoke remains after activation as a second check. No nginx or production configuration was edited. Live devtr6 process test invokes the same preflight against both fresh processes.
