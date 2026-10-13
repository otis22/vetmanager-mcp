# Этап 385. Три MCP-воркера и общая наблюдаемость

## Цель и границы

Использовать три CPU из выделенных MCP 3 CPU/2G без потери MCP-сессий, прав,
дедупликации событий и суммарных метрик. 385.1 — только PRD; 385.2 — код,
сторожа и live devtr6; 385.3 — аудит, выпуск и наблюдение. Число воркеров 3
утверждено владельцем 13.10.2026. Публичные артефакты не содержат ключей,
токенов, данных клиники и приватных адресов.

## Проверенные факты

`server.py` создаёт `uvicorn.Config` без `workers`, `ws="websockets-sansio"`
и запускает `_DrainingUvicornServer.run()`; подкласс переопределяет
`handle_exit` и `shutdown`, закрывая GET SSE. Uvicorn 0.42.0 и uvloop в
production image проверены этапом 384. `mcp.http_app` создаёт локальный
FastMCP session manager. Его `_server_instances` читается для drain:
последующий запрос с `Mcp-Session-Id` на другом процессе не обязан найти
сессию. Текущий `ops/prometheus/prometheus.yml` scrapes `mcp:8000/metrics`
одним target; `/metrics` отдаёт process-local `service_metrics.py`.

В `storage.py` pool на процесс по умолчанию `10+20`; ×3 = 90 при PostgreSQL
`max_connections=50`, memory cap 1G. Цель — ≤40 соединений MCP суммарно,
оставив ≥10 для служебных клиентов: `DB_POOL_SIZE=8`, `DB_MAX_OVERFLOW=5`
на каждый процесс дают 39. Нулевой `pool_size` запрещён для этого режима.
Compose limits заданы на контейнер: три копии прежнего `3 CPU/2G` дали бы
9 CPU/6G. Каждому slot задать `1 CPU/640MiB`; проверить эффективные cgroup
значения и суммарный потолок ≤3 CPU/2GiB.
Этап 384.2c измерил peak RSS одного процесса около 143–150 MB;
`3×150343680+512MiB=987901952 B < 2GiB`. Это предварительный gate;
385.2 повторяет измерение под реальной конфигурацией и нагрузкой.
Production `prometheus_tsdb_head_series=289` по 384.3; 60+ имён метрик
не равны 60 series. Перед/после снять head_series, chunks и RSS Prometheus.

Process-local inventory (кодовая проверка; список расширить AST-аудитом в 385.2):

| Состояние | Сейчас | Требование для трёх процессов |
|---|---|---|
| `service_metrics.py`: counters, latency count/sum/max, gauges, snapshots | dict + Lock | Общий точный снимок, без client/account/token labels. Текущие имена/HELP/TYPE сохраняются. |
| `tools/report_ai.py`: queue, lifecycle, finalized, reject pending, export observations | `OrderedDict`, TTL/лимит | Общие атомарные переходы и дедуп в пределах текущего TTL; событие terminal/guidance учитывается один раз между воркерами. |
| FastMCP streamable HTTP sessions, GET SSE | память воркера | Все сообщения данной bearer-сессии попадают на один живой воркер; при restart документированный reconnect/reinitialize. |
| `activation_telemetry.py`: funnel/first-session cache, cleanup-due, `_ALERTED_THRESHOLDS` | память воркера, скан по `/metrics` | Единственный scan за интервал через Redis lease либо PG advisory lock; gauges публикуются общим snapshot. Alert dedup — общая атомарная запись, проверяется при смене scan owner. Первый сеанс как факт уже в PG (`FOR UPDATE`), не переносить. |
| `token_expiry_notice.py` | `ContextVar` в запросе; claim `TokenUsageStat.expiry_notice_at` в PG | Claim ≤1/24 ч на токен остаётся общим; `token_cleanup.py` scan вызывается при web-запросе, не периодический daemon. |
| `rate_limit_backend.py`, `web_security.py` | Redis backend с local handle, fallback in-memory | Production требует Redis fail-closed; лимит общий. Падение Redis не должно превратить три локальных лимитера в тройную квоту. |
| `host_resolver.py`, `vm_transport.breaker`, GET/request/clinic-timezone caches, shared HTTP clients | local TTL, breaker и coalescing | `request_cache.py` инвалидируется записью только в своём процессе: нужен общий барьер до upstream write. Остальные TTL/cache/клиенты могут остаться локальными при доказанной корректности; breaker — локальная защита, проверить суммарную нагрузку при half-open. |
| `vetmanager_connection_service.py` account locks/login preparation tasks | local locks/tasks | Сверить PG-ограничения и конкурентную запись из разных процессов; при отсутствии DB-гарантии добавить транзакционный lock, не полагаться на local lock. |
| `report_export.py` файлы и metadata | `/app/data` volume, HMAC от `WEB_SESSION_SECRET` | Все slot монтируют один volume с одинаковым signing secret; ссылка, выданная на одном slot, скачивается через каждый. Исходный CDN locator не возвращать. |

## Архитектурное решение

**Проблема и ограничения.** Несколько Uvicorn worker процессов на одном порту
распределяют запросы без знания FastMCP session manager. Даже идеальная общая
метрика не исправит 404/400 последующего MCP запроса на другом воркере.
Внешний nginx уже установлен `scripts/init_server.sh`; Compose и deploy script
сейчас управляют одним `mcp`, nginx направляет на loopback 8000. Redis уже
есть для rate limiting, без persistence и с cap 512M; PostgreSQL 1G/50 conn.
Публичный MCP контракт, авторизация и `/metrics` должны сохраняться.

**Варианты.** `uvicorn --workers 3` или gunicorn с `uvicorn.workers` проще
по Compose, но обходят кастомный `_DrainingUvicornServer`/не дают липкости
FastMCP session; принятие потребовало бы отдельного shared session store,
которого код не имеет. Prometheus multiprocess mode потребовал бы заменить
ручной `service_metrics.py` на client registry и управлять lifecycle файлов
между рестартами; при этом Report AI и сессии остаются нерешёнными. PostgreSQL
для каждого counter вызывает запись на критическом пути и конкурирует с
50 соединениями. Выбраны три однопроцессных Compose replica/slot за host nginx
и Redis для общей метрики и ограниченных Report AI observations. Это больше
настроек nginx, но сохраняет `Server.run()`, uvloop и custom drain.

**Маршрутизация.** Три фиксированных backend slot на loopback портах; nginx
использует consistent hash от `Authorization` для `/mcp` (и legacy SSE route,
если включён), без записи заголовка в access/error log. Один bearer попадает
в один slot; `Mcp-Session-Id` не раскрывается proxy и не используется как
первичный hash, так как initialize его ещё не знает. Проверить, что каждый
MCP запрос, включая GET SSE, действительно несёт одинаковый bearer header;
если клиент его не посылает, выпуск блокируется до решения владельца о
совместимом session affinity. OAuth access token меняется при refresh примерно
раз в час. Новый token иногда попадает в тот же slot: тогда существующая
session может продолжиться по текущему FastMCP контракту. Если hash уводит
его на другой slot, FastMCP возвращает ошибку неизвестной session;
клиент повторяет initialize и открывает GET SSE с новым bearer. Не обещать
универсальный отказ старой session без отдельной token-binding проверки.
Проверить реальные клиентские циклы для **обоих** исходов hash: initialize →
refresh → continuation на том же slot либо отказ на другом → reinitialize →
tools/call и GET SSE. Если клиент не восстанавливается, выпуск блокируется до
выбора маршрутизации по стабильному session ID. Web/OAuth и health routes могут балансироваться без
липкости: web cookie подписаны, данные в PG; `/report-export` дополнительно
требует общего volume и signing secret. Keepalive/IP affinity недостаточны.

Для последующих совместимых выпусков перевести slot в quiescing: под
одним lock атомарно закрыть приём **всех новых write-запросов** (включая
tools, выглядящие читающими, но запускающие работу) и увеличить счётчик
уже принятых write. Все write после fence получают явный 503 **до**
upstream действия, в том числе из существующей session. После fence
дождаться нуля ранее принятых in-flight writes; одновременно новые
initialize тоже запрещены. Сторож ставит write из старой session ровно
между fence и проверкой нуля — upstream не вызывается.
После ограниченного grace закрыть SSE с явным reconnect сигналом, убрать
slot из nginx upstream, проверить синтаксис nginx-конфигурации, reload и только затем SIGTERM.
Этот fence защищает только отключаемый slot: другие два продолжают работать,
а их записи синхронизируются отдельным общим PG cache-барьером. Для первого
перехода с версии 384 действует fleet-wide maintenance ниже; эти два режима
не смешиваются.
После readiness новой версии вернуть slot и reload. Consistent hash при
изменении состава может перемаршрутизировать другие активные сессии;
проверить это на трёх удерживаемых GET SSE с interleaved tools/call и
считать reconnect обязательным. Завершённый ответ не дублировать; при
обрыве после write с неизвестным исходом сверять предметную запись по
read-only ID до повтора, без автоматического retry. Непрерывность SSE при
rollout не обещается; если клиент не умеет корректно восстановиться,
выпуск блокируется. Каждый slot сохраняет `_DrainingUvicornServer` и
получает собственный SIGTERM с `streamable_http_drain_finished`.

**GET cache.** `request_cache.py` хранит значения локально; общие версии
cache tags и write-барьеры хранить в PostgreSQL, а не в volatile Redis.
Новая таблица содержит только HMAC tag, generation и `active_writes`;
HMAC key выводится с отдельным purpose label из стабильного server secret,
общего для трёх slot. Ротация key требует инвалидировать local cache;
никаких URL, API keys или payload клиники. До любого upstream
POST/PUT/DELETE короткая PG-транзакция увеличивает `active_writes`;
без её commit **не выполнять write**. После ответа upstream другая
PG-транзакция увеличивает generation и уменьшает `active_writes`.
Если она не удалась, durable барьер остаётся, cache hits по tag
обходятся до безопасного расследования. Concurrent writes используют
счётчик, не boolean. GET сверяет generation и нулевой барьер в PG перед
выдачей local entry и перед кешированием upstream ответа; если версия
изменилась, ответ не кешировать. При недоступной PG cache обходится,
новые entries не создаются. При PG restart запись барьера сохраняется.
Граница консистентности: GET, **начатый после** завершённого write,
не отдаёт прежнюю cache entry; GET, уже начатый до write, может получить
предшествующее значение и считается упорядоченным до write. Stale entry
после такой гонки всё равно не сохраняется под новым generation. Сторож
ставит паузу после проверки GET, завершает write на другом slot и
проверяет эту границу и следующий GET.
Барьер умершего writer не снимать автоматически по TTL; ручное снятие
после сверки исхода upstream. Сторож: write на slot A, read на B с
другим bearer той же клиники; PG outage до write и после успешного
upstream write, рестарт PG до истечения cache TTL. Дополнительные
короткие PG запросы входят в pool ≤40 и p95 gate.

**Метрики.** Сохранить публичный текстовый `/metrics` и один scrape target
`mcp:8000/metrics`; на любом slot он строится из Redis snapshot. Все
монотонные `*_total`, latency `*_count/_sum/_max` и bounded labels переходят
в Redis с атомарным обновлением; `max` — атомарный compare/update. Gauges
активации и account-age публикуются как один versioned snapshot сканера,
не суммируются между воркерами. Параметры metric HELP/TYPE и cardinality
сверить по всем `render_prometheus_metrics()`/`snapshot_metrics()` сериям,
включая внутренние gauges, и для каждой составить машинно проверяемую карту
`имя → counter/aggregate/gauge → Redis key/TTL/owner`.

| Семейства текущего экспорта | Куда и как |
|---|---|
| `vetmanager_{http_requests,auth_failures,upstream_failures,upstream_requests,tool_calls,prompt_requests,known_issue_lookups,business_events}_total` | Redis atomic counters с прежними ограниченными labels |
| `vetmanager_{token_expiry_notice_issued,token_expiry_notice_skipped,token_preset_issued,placeholder_argument_rejections,rate_limit_backend_degraded,sanitizer_failures,rest_unmapped_read}_total` | Redis atomic counters |
| `vetmanager_{sentry_delivery_lost,sentry_delivery_accepted,report_export_download,report_export_serve}_total` | Redis atomic counters |
| `vetmanager_report_ai_{long_queued_polls,stage_stall_polls,jobs,save_attempts,job_transitions,job_terminal_outcomes,empty_preview_guidance_issued,empty_preview_guidance_jobs,empty_preview_guidance_outcomes,exports,outcomes_by_code}_total` | Redis atomic counters; outcome переход связан одной транзакцией с observation |
| `vetmanager_{http_request_latency,upstream_request_latency,tool_call_latency}_seconds`, `vetmanager_report_ai_{job_stage_duration,job_duration,export_duration}_seconds` | Redis atomic count/sum/max; max как compare/update, не сумма максимумов |
| `vetmanager_{activation_funnel_accounts,activation_event_accounts,first_session_*}` | Versioned Redis snapshot единственного scan owner; остальные воркеры только читают |
| `vetmanager_cache_{hits,misses,invalidations,evictions}_total`, `vetmanager_cache_entries` | События cache → Redis counters; entries — сумма трёх slot gauges с TTL/lease, без slot label наружу |
| `vetmanager_account_last_request_age_hours{account_id}` | Удалить ряд с account ID; scan публикует два gauge: `vetmanager_account_last_request_age_avg_hours` и `vetmanager_account_last_request_age_p95_hours`. Обновить Grafana выражения и сторожа; сверить смысл среднего/p95 по тем же аккаунтам. |

Имена в таблице сверяются с фактическими `# TYPE` и snapshot перед 385.2:
ни одно семейство не остаётся process-local. Новых client/account/token labels
не добавлять, прежний account ID gauge заменить указанным агрегатом.
Redis отказ: `/metrics` возвращает 503 (не старый или неполный local snapshot),
recording не меняет успешный ответ инструмента **после выполненного upstream
действия**, особенно write; отдельный сторож роняет Redis именно после
upstream success. Rate limiting на новых запросах остаётся fail-closed.
Поскольку Redis без persistence, restart сбрасывает counters. Prometheus
видит reset, поэтому сравнение N вызовов допускается только без restart;
в 385.2 измерить дополнительную память Redis, `head_series` (baseline 289)
и проверить, что series не умножаются втрое. Если подход потребует PID/worker
labels или неконтролируемого роста series, PRD пересмотреть до production.

**Report AI.** Текущие `OrderedDict` observation records перенести в Redis
под ключами с HMAC/необратимым идентификатором tenant/job (без raw IDs и
текста); purpose-separated HMAC key выводится из того же стабильного secret
на каждом slot. Сохранить окно 3600 с и контроль числа записей; transitions и
увеличение связанного counter выполняются одной атомарной операцией/Lua.
Active observations не auto-expire: expiry index позволяет одному воркеру
атомарно финализировать просроченную/вытесненную запись **до** удаления,
включая `abandoned_wait`, stage duration и guidance outcome. Финализированные
tombstone имеют TTL для дедупа; cleanup запускается даже без нового poll
этого job (например, при `/metrics` или отдельном bounded tick). Проверить
конкурентный cleanup на трёх процессах и переход через 3600 с. Избыточные
локальные lock оставлять только для локальных клиентов. Redis
недоступен — не заявлять terminal/guidance outcome и не блокировать
upstream job; отметить degraded метрику/лог без ПД. Дедуп после потери Redis
не гарантируется, как и после нынешнего restart process. Уточнить все пять
семейств observation из таблицы, не переносить только lifecycle/finalized.

**Инварианты.** N успешных tool calls на трёх PID увеличивают общий counter
ровно на N; один и тот же `/metrics` с любого slot возвращает ту же сумму.
Один logical job не даёт три terminal/guidance outcomes. Notice остаётся
≤1/24 ч на токен, first-session claim не повторяется. Суммарный pool ≤40,
health/readiness работают через публичный адрес и напрямую для каждого slot.
Никаких raw credentials/PII в metrics, Redis keys, nginx logs и evidence.

**Первый выпуск с версии 384.** Это совместимость **не** rolling update:
текущий старый процесс не пишет общие Redis метрики и не читает PG
cache-барьер. Смешанное обслуживание старых и новых процессов запрещено.
До rsync новой версии оставить live checkout неподвижным; CI/deploy script
выкладывает новую версию в отдельный release directory и собирает image
там, сохраняя фактическое Compose project name, volumes, секреты вне bundle.
После backup включить nginx maintenance/503 для новых запросов, дождаться
завершения in-flight writes, штатным SIGTERM/drain остановить старый MCP,
затем поднять **сразу три** новых slot без `.:/app` и переключить nginx
после проверки синтаксиса nginx-конфигурации и трёх readiness. Во время cutover будет короткий простой;
zero downtime для первой миграции не обещается. Старый и новый код никогда
не обслуживают запросы одновременно. Если нельзя подтвердить завершение
старых write, выпуск остановить; после обрыва сверить их исход read-only.
Дальнейшее поочерёдное обновление допускается только при совместимом
контракте Redis/PG и пройденном write-admission fence.

**Откат.** Конфигом вернуть один Compose slot/старый nginx upstream, сохранив
PG/Redis schema без обратных миграций. Redis keys
общих метрик имеют namespace/version без автоматического TTL для counters,
observations — ограниченное окно/TTL после финализации; один воркер читает
их так же, как три. При откате к прежнему image без Redis metrics counters
начнут новый epoch — мониторинг помечает reset; данные PG не преобразуются.
Production slot исполняет код **из image**, без нынешнего `.:/app` bind mount;
общий volume монтируется только на `/app/data`, логи отдельно. Это позволяет
старым slot оставаться на старом image при rolling update. Перед выпуском
проверить entrypoint, миграции и report export без bind mount. Для **первого**
отката сохранить pre-385 image ID, старый source bundle и отдельный immutable
rollback Compose manifest: один slot запускается на сохранённом старом image
**без source bind mount**; вернуть старый nginx upstream. Старый Compose с
`.:/app` непосредственно не применять к обновлённому checkout. Сохранить
также nginx config и секреты на прежнем месте; не копировать их в repo.
Откат испытать после **реальной правки кода** в изолированном контуре:
запустить именно pre-385 image с rollback manifest, проверить версию модуля
внутри контейнера, health/ready, tools/list, `/metrics`, export download и
GET SSE reconnect. Кодовая/данная миграция PG только additive; старый image
её игнорирует, обратная миграция не нужна. Если это не подтверждено до
production выпуска, выпуск блокируется.

## Декомпозиция 385.2 и живые критерии

Каждая подзадача ≤2 ч или ≤150 строк кода; если больше — делить до работы.
Сторож считается принятым только после показанного красного прогона с
описанием конкретной поломки. Изменённый инструмент вызвать вживую на devtr6
и приложить HTTP код и очищенное тело; запись live проверки — в AssumptionLog.
Не смешивать bearer стенд и `TEST_DOMAIN`/`TEST_API_KEY` из `.env`.

| Подзадача | Красный сторож | Live devtr6 |
|---|---|---|
| 385.2a1 (≤2 ч): Compose slots, immutable images, limits | Вернуть `.:/app` или `3 CPU/2G` на slot: конфиг-сторож красный. | 3 PID, три `/readyz` 200, один shared `/app/data`; проверить cgroup CPU/memory каждого и код image через один slot. |
| 385.2a2 (≤2 ч): nginx affinity и OAuth refresh | Убрать consistent hash: initialize → tools/call → GET SSE ломается на другом PID, сторож красный. | Один bearer сохраняет slot; разные bearer распределяются. После refresh проверить оба случая: hash сохранил slot — session продолжается; hash сменил slot — ошибка прежней session, клиент повторяет initialize и безопасный tools/call с GET SSE. Коды/очищенные тела. |
| 385.2a3 (≤2 ч): atomic write fence и drain | Убрать admission fence: write из старой session проходит после нуля in-flight — красный. | 3 удерживаемых SSE, interleaved tools/call, SIGTERM каждого slot и `streamable_http_drain_finished`; write после fence — 503 до upstream, обрыв после write — read-only сверка. |
| 385.2a4 (≤2 ч): первая миграция и immutable rollback | Разрешить mixed old/new traffic или вернуть source bind в rollback manifest: красный сторож. | В изолированном контуре pre-385 image и изменённый новый код: staged rsync, maintenance/drain, три новых slot, затем старый image без bind; версия модуля/health/metrics/exports/SSE подтверждены. |
| 385.2b (≤2 ч): pool budget и startup validation | Вернуть 10+20 или задать нулевой pool: расчёт `3×(pool+overflow)≤40` красный. | На трёх slot под нагрузкой PG `pg_stat_activity` ≤40 MCP соединений, `SHOW max_connections=50`, readiness 200; оценить timeout при насыщении. |
| 385.2c1 (≤2 ч): Redis metric core, HTTP/tool/auth counters | Вернуть process-local запись: вызовы с трёх slot дают сумму меньше N, сторож красный. | N безопасных `tools/call get_clients(limit=1)` на трёх slot; `vetmanager_tool_calls_total{tool="client.list",endpoint="/rest/api/client#list",method="GET",outcome="success"}` увеличивается ровно на N и одинаков на каждом `/metrics`; 200/очищенные тела. При cache hit вызов всё равно инструментирован. |
| 385.2c2a (≤2 ч): token/guard/rate-limit counters | Отключить запись token notice или guard: inventory и сумма красные. | Безопасные bearer вызовы на разных slot; общий token/guard counter, код и очищенное тело. |
| 385.2c2b (≤2 ч): report export/Report AI counters | Отключить запись одного outcome: inventory и сумма красные. | Безопасный тестовый job/export на разных slot; общий bounded outcome, код и очищенное тело. |
| 385.2c2c (≤2 ч): sentry/known-issue/business counters и полнота каталога | Оставить одну серию локальной: inventory test красный. | Сверить доступные безопасные события и один target Prometheus, имена/TYPE и отсутствие PID labels; недостижимые вручную семейства проверить mock интеграцией. |
| 385.2c3 (≤2 ч): latency count/sum/max и cache counters | Убрать atomic max или локализовать cache counter: тест красный. | Три slot дают одинаковый summary, max равен максимуму наблюдений; `/metrics` 503 при Redis outage, затем 200. |
| 385.2d1 (≤2 ч): activation scan lease, gauges/age aggregates | Раздвоить scan или оставить account_id label: сторож красный. | Один scan за интервал, одинаковые gauges на slot, новый avg/p95 в Grafana, head_series без 3× роста. |
| 385.2d2 (≤2 ч): activation alert dedup и owner handoff | Убрать общий claim `_ALERTED_THRESHOLDS`: двойное предупреждение красное. | При смене scan owner одна alert запись на account/threshold; после восстановления трафика повторное событие допустимо. |
| 385.2e1a (≤2 ч): Report AI queue/reject observations | Два slot, один job: снять атомарную запись — красный двойной исход. | Безопасный тестовый job через два slot, коды/очищенные тела и общие значения метрики. |
| 385.2e1b (≤2 ч): Report AI export observations | Два slot, один export: снять дедуп — красный двойной исход. | Безопасный тестовый export через два slot, очищенные ответы и один outcome. |
| 385.2e2 (≤2 ч): lifecycle/finalized, guidance atomic dedup | Один job на двух slot с повторным terminal/guidance: без atomic transition красный +2. | Тестовый job даёт +1 в общей метрике; raw ID отсутствует в Redis keys. |
| 385.2e3 (≤2 ч): Report AI expiry/eviction finalization | Auto-expire без финализации: `abandoned_wait`/duration не появится — красный. | Через >3600 с без poll cleanup даёт один outcome; два slot одновременно не удваивают его. |
| 385.2f1a (≤2 ч): notice/first-session claims | Снять PG claim: конкурентный тест выдаёт два notice/event — красный. | Две параллельные безопасные операции на разных slot, один notice claim и first-session event в PG. |
| 385.2f1b (≤2 ч): connection locks/rate limiter и прочие local caches | Убрать PG защиту account save или Redis limiter: конкурентный тест красный. | Два slot изменяют тестовое соединение без потери данных; rate limit общий и fail-closed, коды/очищенные тела. |
| 385.2f2a (≤2 ч): PG migration и write barrier | Удалить предварительный барьер: запись выполняется при отказе PG — красный. | Безопасная тестовая запись при доступной PG даёт ожидаемый код/очищенное тело; при отказе PG upstream write не вызван. |
| 385.2f2b (≤2 ч): cache read/version и failure recovery | Удалить финальный generation/check: запись на A, чтение на B дают старое — красный. | Изменить тестовую сущность через A и прочитать через B; потерять PG после успешного upstream ответа, перезапустить до TTL; коды/очищенные тела без stale. |
| 385.2f3 (≤2 ч): report export shared storage | Убрать общий volume или поменять signing secret в одном slot: download красный 404. | Получить безопасную тестовую ссылку на A и скачать через каждый slot; коды и очищенные признаки файла, без содержимого отчёта. |
| 385.2g (≤2 ч): ресурсный и полный integration gate | Снизить MCP cap/увеличить pool/сломать memory formula — красный. | Повторить 200 `tools/call get_clients(limit=1)` на трёх slot, снять peak RSS каждого, cgroup peak/OOM, Redis memory, PG sessions, `prometheus_tsdb_head_series/chunks`, p95 и HTTP коды/очищенные тела. При >70% 2G или OOM — stop до пересмотра. |

385.3: аудит, strong committed diff review, полный mock+real suite один раз
по финальному SHA, CI, sanctioned deploy и проверка утилизации CPU/latency
до/после. Проверить nginx config не только шаблоном, но текущим production
файлом; deployment script обязан иметь полный rollback bundle. PRD-review
385.1 совмещает Architecture Critique: reviewers проверяют affinity,
атомарность, cardinality, pool, живые критерии и откат.
