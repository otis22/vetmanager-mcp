# Этап 320. Безопасная выгрузка Report AI

## Цель

Закрыть подтверждённые риски production-пути выгрузок Report AI без слишком
узкого предположения о CDN: безусловно проверять любой origin и закреплять
соединение за проверенным IP, опционально применять операторский allowlist,
убрать измеренные лишние полные копии 25-МБ экспорта и включить кэш таймзон
клиник в существующий bounded TTL lifecycle.

Findings F1, F22 и F24 из полного review этапа 319 считаются гипотезами до
проверки ниже, а не готовым описанием реализации.

## Источники и проверенные факты

### Locator и origin

Живой `start_report_export` на API-key стенде 16.09.2026, отчёт 84:

- `StartReport` → HTTP 200;
- `reportFile` → HTTP 401, HTTP 401, затем HTTP 200;
- и `csv_file`, и `csv_semicolon_file`: схема `https`, host
  `308427.selcdn.ru`, эффективный порт `443`, userinfo отсутствует, query
  отсутствует.

Значения locator, path и возможный query не печатались и в репозиторий не
переносятся. `PRD/этап-276-выгрузка-через-mcp.md` и запись этапа 276 в
`AssumptionLog.md` независимо подтверждают абсолютный HTTPS locator публичного
CDN, без query и авторизации. Постоянный журнал после этапа 278 намеренно
сохраняет только `target=report_export_storage`, код и длительность, поэтому
host из него восстановить нельзя. Локальная копия `known_issues` пуста; в
tracked seed/PRD/AssumptionLog других export-origin не найдено.

Read-only проверка конфигурационного контракта Ветменеджера уточнила, почему
одного стенда недостаточно:

- `vetmanager-extjs/_constants.php:18-27` берёт storage host из
  `FILE_STORAGE_HOST`; fallback зависит от datacenter;
- `.helm/values.yaml:220-223` содержит два cluster origin:
  `https://308427.selcdn.ru:443` и
  `https://vetmanager-public-user-files.s3.amazonaws.com:443`;
- `.docker/docker-alfavet.yml:106-110` задаёт on-prem origin
  `https://store.alfavet.by:443`;
- `.helm-premigrate/templates/migrate-job.yaml:75-78` выбирает storage host
  per cluster, а locator получает тот же origin. Полный список cluster/on-prem
  origin по этому контракту принципиально не восстанавливается из репозитория.

Следствие: **default allowlist отсутствует**. Пустой или незаданный
`REPORT_EXPORT_ALLOWED_ORIGINS` не блокирует origin, прошедший обязательный
SSRF минимум. Если оператор явно задал env, каждый элемент — exact HTTPS
origin; wildcard/suffix правил нет. Allowlist только ужесточает минимум и не
заменяет DNS/address validation или IP pinning.

Формат env: comma-separated origins. Canonical form — lowercase ASCII/IDNA
hostname без trailing dot и без явного default `:443`; поэтому
`https://host` и `https://host:443` эквивалентны. Path, query, fragment,
userinfo, wildcard, не-HTTPS и любой другой port делают конфигурацию
невалидной; непустой malformed env fail-fast при старте, а не превращает все
выгрузки в неожиданный runtime-отказ.

### Измерение памяти до изменений

Probe выполнен в штатном test-контейнере на валидном CSV размером ровно
`REPORT_EXPORT_MAX_BYTES = 26_214_400` байт, 25 650 строк:

- входной `bytes`: 26 214 433 байта с overhead;
- результат `str`: 52 480 166 байт — BOM переводит compact ASCII representation
  в двухбайтовую Unicode representation;
- после `build_export_csv`: RSS +115 604 KiB, traced current 52 484 678,
  peak 142 394 064 байта;
- после `store_export`: stored CSV 26 240 056 байт; прежний peak не вырос, но
  `csv_text.encode()` временно материализует ещё одно полное тело;
- `web_routes_export.read_bytes()` добавил `bytes` размером 26 240 089 байт,
  traced current вырос с 52 485 794 до 78 728 777 байт.

F22 подтверждён: в production path одновременно живут raw body и полный
Unicode result; внутри разбора дополнительно живут полный decoded input,
`list(rows)` и output buffer, а storage/serve создают полные байтовые копии.
Потоковая обработка нужна не из предположения, а в трёх измеренных местах:
download accumulation, row materialization/output construction и public serve.

### Кэш таймзон

`_REPORT_AI_CLINIC_TIMEZONES` — process-global `OrderedDict`, но значение
содержит только строку timezone. В отличие от четырёх соседних observation
map, он не хранит `last_seen`, не ограничен
`REPORT_AI_QUEUE_OBSERVATION_MAX_ENTRIES` и не обрабатывается
`_cleanup_report_ai_queue_observations()`. F24 подтверждён по коду.

## Scope и декомпозиция

### 320.1 SSRF и DNS rebinding — отдельный коммит (≤150 LOC production)

1. До HTTP разобрать locator через `urlsplit` и отказать, если:
   - схема не `https`;
   - есть username/password;
   - эффективный порт не `443`;
   - hostname отсутствует или DNS не вернул A/AAAA.
   Если `REPORT_EXPORT_ALLOWED_ORIGINS` непуст, дополнительно отказать, когда
   canonical origin отсутствует в этом exact allowlist. При пустом/незаданном
   env эта дополнительная проверка выключена.
2. Резолвить все A/AAAA через `getaddrinfo` вне event loop. Отклонять весь
   locator, если хотя бы один адрес не удовлетворяет `ipaddress.is_global`;
   этим безусловно закрываются loopback/private/link-local/multicast/
   unspecified, а также shared/reserved non-global диапазоны, для IPv4 и IPv6.
   DNS phase ограничена отдельным `asyncio.wait_for` и использует собственный
   маленький `ThreadPoolExecutor`, поэтому зависший resolver не занимает общий
   executor CSV/disk/tool I/O; исчерпание этого пула даёт bounded safe error.
   Все адреса сохраняются в стабильном IPv4-first, затем IPv6 порядке. Backend
   делит один общий connect deadline на попытки и не умножает timeout на число
   адресов, поэтому недоступный адрес не ломает dual-stack CDN и latency
   остаётся внутри прежнего export connect timeout.
3. Передать проверенный набор IP в отдельный `httpcore.AsyncNetworkBackend`
   под маленьким `httpx.AsyncBaseTransport`. `httpcore` становится прямой
   совместимо ограниченной зависимостью (`>=1.0.9,<2`) и в `pyproject.toml`,
   и в production `Dockerfile`, а не неявной/private деталью
   `AsyncHTTPTransport._pool`. URL остаётся с исходным hostname,
   поэтому HTTP Host и TLS SNI/certificate validation остаются библиотечными;
   TCP backend получает только уже проверенный IP и не делает второй DNS
   lookup. Transport переводит все `httpcore` transport exceptions в
   соответствующие `httpx` exceptions, чтобы существующий safe-error path не
   менялся. На каждый новый client backend отмечает фактический `connect_tcp`;
   transport не возвращает response, если backend не был использован.
   Redirects остаются выключенными, proxy/env — выключенными.
   Resolver и transport factory имеют внутренний injectable seam: production
   defaults всегда выполняют validation+pinning, тесты явно подставляют fake
   backend; default mock suite guard запрещает реальный `getaddrinfo`/TCP.
4. Ошибка включённого allowlist называет canonical origin только в ожидаемом
   tool response, но никогда locator/path/query. Persistent log, metric и
   Sentry получают только reason code без origin. Отказ обязательного минимума
   даёт понятную общую ошибку без какого-либо адреса. Host observability не
   добавляется: она не нужна для исправления и расширила бы privacy-контракт
   этапов 276/278.
5. Красные guards: HTTP, userinfo, нестандартный порт, loopback, private IPv4,
   private IPv6, link-local, shared/reserved non-global, mixed safe+unsafe DNS,
   DNS rebinding/pinned TCP, чужой origin, redirects. Transport-level test с fake network stream обязан
   доказать connect к проверенному IP, исходные Host/TLS `server_hostname` и
   отсутствие второго `getaddrinfo`; одного `MockTransport`/respx недостаточно.
   Отдельные guards покрывают DNS timeout, IPv6→IPv4 fallback, каждый класс
   transport error → прежний sanitized export error, runtime backend assertion,
   а также отсутствие locator/origin в logs/metrics/Sentry для каждого refusal
   reason. Dependency change требует явного
   `docker compose --profile test build test` до полного suite.
   Existing `error_tracking._sanitize_event` уже рекурсивно удаляет URL из
   frame locals; новый event-level guard дополнительно строит transport
   exception с `.request`, breadcrumbs и frame `locator/payload`, затем
   проверяет весь captured event: locator/path/query и allowlist origin
   отсутствуют.

### 320.2 Измеренное memory amplification (≤150 LOC production)

1. Download пишет decompressed chunks непосредственно в один `BytesIO` с тем
   же 25-МБ hard limit; список chunks и финальный `b"".join` исчезают. Raw
   export остаётся только в памяти запроса и никогда не записывается на диск.
2. CSV reader идёт строка за строкой из `TextIOWrapper(BytesIO)`. Очищенная
   строка сразу пишется в private temporary CSV рядом с будущим final path;
   полный decoded input, `list(rows)`, `StringIO` output и `csv_text.encode()`
   исчезают. UTF-8-sig → cp1251 fallback делает seek того же in-memory buffer,
   а не вторую raw-копию. При позднем `UnicodeDecodeError` temporary output
   удаляется/пересоздаётся, raw buffer возвращается на позицию 0 и весь parse
   начинается заново с `newline=""`; частичный UTF-8 output не смешивается с
   cp1251; `TextIOWrapper.detach()` сохраняет underlying `BytesIO` между
   попытками. Деперсонализация `sanitize_report_cell(column, value)` не хранит
   cross-row state, поэтому обработка остаётся построчной.
3. Metadata и готовый CSV публикуются только после полного успешного parse,
   flush/fsync/chmod; ошибка удаляет temporary и companion. Незавершённый файл
   не разрешается публичным route. Hidden temp names имеют узнаваемый suffix;
   `sweep_expired` удаляет stale temp вместе с обычной трёхдневной уборкой,
   чтобы crash/kill не копил orphan files.
4. Public route до создания ответа открывает готовый CSV; failure даёт прежний
   404. Затем bounded `StreamingResponse` читает уже открытый descriptor
   chunks через async file wrapper/to-thread и закрывает его в `finally`:
   event loop не блокируется, concurrent unlink не ломает чтение и
   private filesystem path не попадает в ошибку. Прежние Content-Type,
   Content-Disposition, Cache-Control и security headers сохраняются;
   ETag/Last-Modified/Range не добавляются.
5. Повторить тот же 25-МБ probe и записать числа до/после. Guards проверяют
   bounded chunks, row-wise cleaning, поздний cp1251 fallback, cleanup при
   parse/write failure и streaming serve без `Path.read_bytes`. Табличные
   fixtures обязаны дать byte-identical output старого и нового пути: BOM,
   header, quoting, formula escaping, CRLF и depersonalization.

### 320.3 Кэш таймзон в общей уборке (≤50 LOC production)

1. Значение cache становится `(timezone_name, fetched_at_monotonic)`. TTL
   абсолютный: hit не обновляет `fetched_at`, иначе активная клиника никогда не
   увидит изменение timezone; для size-LRU hit только двигает запись в конец.
   Read path сам проверяет TTL до использования и перечитывает timezone после
   expiry независимо от того, вызывалась ли общая уборка. `fetched_at` и
   `now`, переданный в cleanup, берутся только из того же `_monotonic_seconds`;
   wall clock здесь не участвует.
2. Использовать существующие
   `REPORT_AI_QUEUE_OBSERVATION_TTL_SECONDS` и
   `REPORT_AI_QUEUE_OBSERVATION_MAX_ENTRIES`, не вводить новый cache/helper.
3. `_cleanup_report_ai_queue_observations(now)` удаляет expired timezone rows и
   oldest rows сверх лимита рядом с остальными observation maps.
4. Красные guards: hit до TTL без HTTP, ещё один hit внутри окна не продлевает
   absolute TTL, expiry перечитывает изменившуюся timezone даже без отдельного
   cleanup call, size eviction, обычный cleanup очищает cache.

## Архитектурное решение

### Проблема и ограничения

Locator контролирует чужой сервер, но экспорт содержит данные клиники. Нельзя
доверять DNS между validation и connect, отдавать locator в ошибку/лог или
сохранять raw export на диск. Storage origin задаётся per cluster/on-prem и
полный список не известен этому сервису, поэтому default allowlist сломал бы
production. Public CSV уже хранится на private disk после очистки; этот факт
позволяет стримить sanitized output и готовый файл, не меняя public MCP contract.

### Рассмотренные варианты

- Обязательный встроенный allowlist известных host: отвергнут — три известных
  origin не образуют полный per-cluster/on-prem список и сломают production.
- Только allowlist hostname: не закрывает private DNS и rebinding.
- Проверить DNS, затем обычный `httpx.get(hostname)`: второй DNS lookup оставляет
  rebinding окно.
- Подменить URL на IP и поставить `Host`: TCP pinned, но стандартная TLS
  проверка получает IP вместо hostname/SNI и ломает сертификат.
- Public network-backend seam `httpcore.AsyncConnectionPool` под небольшим
  `httpx.AsyncBaseTransport`: TCP получает IP,
  тогда как URL, Host, TLS SNI и cert validation сохраняют hostname. Это
  минимальный вариант, который закрывает TOCTOU. `httpcore` объявляется прямой
  совместимо ограниченной зависимостью, чтобы обновление transport engine не
  вернуло обычный DNS молча.
- Raw tempfile на диске: проще для csv reader, но нарушает инвариант этапа 276
  «неочищенный export на диск не попадает».
- Async CSV parser: добавляет новую зависимость/свой parser. `BytesIO` bounded
  25 МБ + sync row streaming в worker thread проще и сохраняет csv semantics.

Выбраны pinned network backend и bounded in-memory raw + row-streaming sanitized
disk output. Security helper отделяется от большого `tools/report_ai.py`, хотя
call-site один: отдельная граница нужна для прямых guards DNS/transport и не
является общей speculative abstraction.

### Инварианты

- Ни locator, ни path/query не появляются в tool response, error, metric,
  persistent log, Sentry context или tracked artifact.
- Всегда только HTTPS/443, no userinfo; все DNS answers имеют
  `ipaddress.is_global=true`; connect использует только проверенный IP. Exact origin проверяется
  дополнительно только при явно непустом `REPORT_EXPORT_ALLOWED_ORIGINS`.
- Redirects/proxy env выключены; API key/authorization CDN не получает.
- Raw bytes bounded 25 МБ, живут только в request memory; на disk попадает
  только полностью очищенный CSV.
- Depersonalization и CSV formula protection применяются к каждой строке до
  публикации; cp1251 fallback сохраняется.
- Public URL/response schema, three-day TTL и access liveness не меняются.

### Rollback/fallback

Если оператор включил allowlist и upstream меняет CDN, оператор сначала
подтверждает новую форму живым probe и добавляет exact origin в
`REPORT_EXPORT_ALLOWED_ORIGINS`; обязательные scheme/port/DNS/IP guards нельзя
отключить даже при пустом allowlist. Если pinned backend несовместим с новой httpx/httpcore,
только export-вызов fail-closed с безопасной ошибкой, остальные инструменты
продолжают работать; version constraints, transport-level guard и runtime
backend-used assertion не позволяют молча вернуться к обычному DNS. Исправление обязано сохранить equivalent IP pinning,
возврат к обычному DNS не является rollback. Streaming storage можно откатить
к bounded in-memory реализации отдельно от 320.1, сохранив SSRF boundary.

## Acceptance

1. Все guards 320.1 показаны красными целевой поломкой и затем зелёными;
   transport-level guard доказывает pinned IP + original Host/SNI без второго
   DNS lookup, timeout/fallback/error mapping и runtime backend assertion.
2. При пустом/незаданном `REPORT_EXPORT_ALLOWED_ORIGINS` allowlist ничего не
   блокирует; при непустом env работает exact-origin фильтр. Env доезжает в
   production container и документирован без locator; malformed непустой env
   fail-fast, canonical `https://h` совпадает с `https://h:443`.
3. Повторный 25-МБ probe показывает отсутствие полных decoded/rows/output/
   serve copies в production path и содержит численное сравнение peak/current.
4. Деперсонализация, byte-equivalence, late encoding fallback, atomic
   publication, streaming response/header contract, size/content-type,
   no-redirect и no-credential contracts зелёные.
5. Timezone cache истекает, ограничен и очищается штатной функцией; изменение
   timezone после TTL видно без restart.
6. Изменённый export tool вызван вживую на API-key стенде с записью HTTP/tool
   outcome без locator. После Deploy Prod используется public MCP export smoke,
   если deploy располагает write-capable credential; иначе повторяется стенд.
7. 320.1 закоммичен отдельно; затем 320.2/320.3 проходят полный Core Loop,
   committed-diff reviews, push, зелёный GitHub Tests и Deploy Prod.

## Out of scope

- Default, wildcard/suffix allowlist и автоматическое обучение origin по ответу
  upstream.
- Следование redirects или proxy environment.
- Изменение 25-МБ product limit, CSV output contract, public-link lifetime или
  access-capability model.
- Хранение raw export на disk, XLSX support, concurrent export semaphore.
- Новый общий cache framework: timezone cache уже живёт рядом с observation
  lifecycle и переиспользует его TTL/limit/cleanup.

## Оценка простоты

Проверены triggers §4.1. Новый generic cache, async CSV framework, resolver
service и configurable-everything отвергнуты. Нетривиальные элементы остаются
только там, где их требуют конкретные security/privacy invariants: pinned TCP
backend и atomic row-streamed publication. Allowlist — одна опциональная env,
без неё обязательный SSRF minimum продолжает работать; изменение cache policy
— существующих двух constants; public contract не получает второго API surface.

## Результат PRD-review

- Spark pass 1: приняты direct `httpcore` constraint и transport-level proof;
  rollback без существующего kill switch переписан на честный fail-closed.
- После исправления allowlist владельцем Spark pass 2: приняты
  `ipaddress.is_global` и явные dependency changes в обоих manifests.
- Strong Architecture/PRD review 1/2: приняты absolute timezone TTL,
  transport exception mapping, DNS timeout/address fallback, Sentry/log sinks,
  byte-equivalence и late cp1251 restart, безопасный streaming serve, runtime
  backend assertion и обязательный image rebuild.
- Strong Architecture/PRD review 2/2: приняты strict origin canonicalization,
  total connect deadline, injectable test seam, stale-temp sweep, async file
  reads/detach, monotonic clock и dedicated bounded DNS executor. Existing
  Sentry scrubber закрепляется whole-event guard’ом. Замечание «не показывать
  origin вызывающему» отклонено: владелец явно требует понятную allowlist
  ошибку с canonical origin; origin допустим в tool response, но locator,
  path/query и origin в log/Sentry запрещены. Бюджет PRD исчерпан 2/2;
  повторный strong review после этих конкретизирующих, не меняющих решение
  правок не запускается.
