# Deep Review: baseline post-stage-84
_Дата: 2026-04-17_
_Scope: full codebase_
_Reviewers: code, architecture, docs, security, performance-and-reliability, observability, tests, product_
_Aggregator: Opus 4.7_
_Codex arbitration: done (GPT-5.4)_

## Executive Summary

Codebase в целом здоровый (84 этапа дисциплинированной разработки, test coverage присутствует, observability база уже есть), но baseline-ревью выявил **два класса проблем, блокирующих спокойный merge**: (1) **скрытые функциональные баги в product-критичных tools** — `create_admission` шлёт поля старого контракта (`doctor_id`/`date` вместо `user_id`/`admission_date`) с дефолтным невалидным статусом, `get_medical_cards_by_client_id` продолжает использовать `client_id` после миграции FK на `owner_id` (stage 77.4), и три MCP-prompt'а ссылаются на несуществующие параметры; (2) **документационный drift** — README заявляет 101 tool в 12 группах (фактически 107/13), tech-reqs закрепили fastmcp >=2.0 против реального >=3.1, deploy-скрипты захардкодили старый хост. Системные темы: дублирование фильтра-билдеров в 15+ местах, две параллельные auth/rate-limit подсистемы, отсутствие per-tool latency metric и correlation-ID пропагации в VM API. Главные риски: (а) пользователи получают пустые результаты вместо admission'ов и медкарт, (б) при VM outage нет circuit breaker — воркеры зависают, (в) sentry sanitizer не редактирует `x-user-token`/`x-vm-api-key` и может утечь секреты. Performance-часть (отсутствие keep-alive в httpx, N+1 в medical_cards, sync redis в async handlers, PBKDF2 на event loop) — реальна и измерима, но не блокирующая для merge, если blockers из раздела Top-10 пофикшены.

## Verdict

**Do not merge** до устранения blocker'ов и top-4 high findings. Конкретно: (1) баг в `create_admission` payload + дефолтный `status='assigned'`, (2) `get_medical_cards_by_client_id` использует `client_id` вместо `owner_id`, (3) README/tech-reqs/deploy-скрипты drift, (4) оба observability-blocker'а (missing correlation-ID в VM headers + отсутствие per-tool latency metric). Остальные high — исправимы итерациями, но эти четыре бьют либо в продакшен-UX (пустые ответы на базовые сценарии), либо в операционную способность диагностировать инциденты, либо в доверие к документации для self-hosted адоптеров. После их фикса — merge допустим с явным tech-debt backlog по высоким performance/architecture пунктам.

## Top-10 critical findings (for Codex arbitration)

### 1. create_admission шлёт неправильный payload и невалидный default status
- severity: **high** (фактически blocker по product-impact), confidence: 0.95
- file: `tools/admission.py:298-326`
- problem: payload содержит `{doctor_id, date, pet_id}` вместо ожидаемых VM API полями `{user_id, admission_date, patient_id}`; `status` по умолчанию `'assigned'` — такого enum-значения в VM нет, запись оказывается в подвешенном состоянии и исчезает из всех активных фильтров schedule
- why_it_matters: ломает ключевой admin-сценарий "создай приём через MCP"; клиент получает 200 OK, но admission не виден в расписании
- suggested_fix: payload → `{user_id, admission_date, patient_id, client_id, status}`; дефолт status → `save` (реальный дефолт из ORM `Entity/Admission.php`). Внешние MCP-имена параметров оставить `doctor_id`/`date`/`pet_id` для LLM-эргономики — мапить на границе API
- confirmed_by: [product]
- **correction 2026-04-17**: изначальный suggested_fix пропустил `pet_id → patient_id` (подтверждено проверкой против `vetmanager-extjs/application/src/Entity/Admission.php:57-74` и `support-bot-base/.../Dostup_k_priemam.md`). Ревью без cross-check с authoritative источником — ненадёжно для API-контрактов. См. обновлённый чеклист в `artifacts/api-research-notes-ru.md`.

### 2. get_medical_cards_by_client_id фильтрует по client_id вместо owner_id
- severity: **high** (blocker по product-impact), confidence: 0.98
- file: `tools/medical_card.py:58-134`
- problem: после stage 77.4 FK медкарты на питомца/клиента мигрировал на `owner_id`; tool продолжает слать `client_id` — API возвращает пусто; дополнительно tool использует N+1 по питомцам вместо IN-фильтра (как уже сделано в stage 82/83)
- why_it_matters: "клиент без медкарт" для реальных клиентов с питомцами — один из самых частых сценариев; после stage 82/83 IN-паттерн уже отработан, несогласованность
- suggested_fix: заменить фильтр на `owner_id` + применить IN-батчинг по patient_id (как в get_inactive_pets)
- confirmed_by: [product, performance-and-reliability]

### 3. README и tech-reqs расходятся с кодовой реальностью
- severity: **blocker** (docs), confidence: 0.97
- file: `README.md:473-488, 482, 497-499, 539-543; artifacts/technical-requirements-vetmanager-mcp-ru.md:34`
- problem: README — "101 инструмент в 12 группах" (факт: 107/13, нет Schedule row); Finance упоминает `create_payment` при явном запрете Payment CREATE в таблице CRUD-ограничений; tech-reqs закрепили `fastmcp >=2.0.0` против Dockerfile `>=3.1.0,<4` (несовместимые мажоры — ровно тот провал, что разобран в CLAUDE.md §9.1); AssumptionLog фиксирует "75 MCP tools + 20 prompts"; таблица артефактов неполная
- why_it_matters: первая точка контакта для self-hosted операторов и LLM-клиентов; рассогласование подрывает доверие и провоцирует регресс по зависимостям
- suggested_fix: синхронизировать README (Schedule row + счётчик + убрать create_payment либо добавить в CRUD-таблицу), tech-reqs на `fastmcp>=3.1.0,<4`, пометить устаревшие разделы AssumptionLog
- confirmed_by: [docs]

### 4. VM API calls без X-Correlation-ID — цепочка рвётся на границе
- severity: **blocker** (observability), confidence: 0.97
- file: `vetmanager_client.py:175-228`
- problem: `_headers()` не пробрасывает `correlation_id` из `request_context` в исходящие VM-запросы; любой инцидент "долго тормозил VM API" невозможно связать с конкретным tool call
- why_it_matters: при прод-инцидентах команда не сможет трассировать цепочку incoming MCP call → VM upstream
- suggested_fix: получить correlation_id из ContextVar и добавить в `X-Correlation-ID` заголовок; для fallback при отсутствии контекста — сгенерировать UUID4 и залогировать
- confirmed_by: [observability]

### 5. 80+ MCP tools без latency/outcome метрики
- severity: **blocker** (observability), confidence: 0.98
- file: `tools/crud_helpers.py` (место для декоратора)
- problem: нет per-tool latency histogram и outcome counter — невозможно построить SLO по tool'ам, невидимы regression'ы после релизов
- why_it_matters: без этой метрики SRE-capabilities проекта остаются на нуле; "медленный MCP" не отделить от "медленный VM API"
- suggested_fix: декоратор `@instrument_tool(name)` в crud_helpers: `tool_latency_seconds{tool_name,outcome}` histogram + counter; применить через CRUD-фабрики и вручную на custom tools
- confirmed_by: [observability]

### 6. Нет upstream latency metric + timeout/network без лога
- severity: **high**, confidence: 0.97
- file: `vetmanager_client.py` (lines 175-228 для метрики, 219-227 для лога)
- problem: нет counter/histogram по VM API upstream (target, status, duration); timeouts и network errors поднимают исключение без structured-лога с domain/url/method
- why_it_matters: невозможность ответить на "VM API тормозит или наш код?"; timeout'ы видны только по косвенным признакам
- suggested_fix: `record_upstream_request(target='vetmanager', status, duration_ms)` + `RUNTIME_LOGGER.warning` с `domain/url/method/elapsed` в catch-блоках
- confirmed_by: [observability, performance-and-reliability]

### 7. Sentry sanitizer не редактирует VM/user-token заголовки
- severity: **high** (security), confidence: 0.95
- file: `error_tracking.py:14-43`
- problem: allowlist покрывает стандартные `Authorization`/`Cookie`, но пропускает `x-user-token`, `x-vm-api-key`, `x-vm-domain`, `x-app-name` — при любом exception с request context эти значения уходят в Sentry
- why_it_matters: прямая утечка долгоживущих креденшлов 3rd-party SaaS
- suggested_fix: перейти с allowlist на pattern-based детекцию (имена содержат `token|key|secret|api|auth|domain|cookie`) или расширить deny-list; добавить regression test
- confirmed_by: [security]

### 8. httpx.AsyncClient создаётся на каждый запрос + нет retry/backoff/circuit breaker
- severity: **high** (performance), confidence: 0.95
- file: `vetmanager_client.py:27-29, 175-228`
- problem: три связанных дефекта в одном месте: (а) `async with httpx.AsyncClient()` на КАЖДЫЙ `_request` → fresh TLS handshake, нет keep-alive; (б) `MAX_RETRIES=1` и ретрай только на timeout/network, нет backoff на 429/5xx и нет honor Retry-After; (в) нет circuit breaker → при VM outage worker'ы зависают 30s/request
- why_it_matters: 100-400ms overhead на каждый tool call (ровно когда MCP-клиенты дергают серию вызовов); при VM инциденте — коллапс пула
- suggested_fix: process-wide singleton `httpx.AsyncClient` с `Limits(max_keepalive=50)`, exponential backoff + Retry-After, pybreaker keyed on `(domain)`
- confirmed_by: [performance-and-reliability]

### 9. prompts.py ссылается на несуществующие параметры после миграций
- severity: **high** (product), confidence: 0.95
- file: `prompts.py:81-89, 132-144` + соседние prompt'ы
- problem: `book-appointment` вызывает `get_pets(client_id=...)` — параметр мигрировал на `owner_id` (stage 77.4); `unconfirmed_appointments` берёт одну дату вместо диапазона и не упоминает `status=not_confirmed`; `unpaid_invoices` делает client-side фильтр вместо `payment_status` (есть с stage 78.6); `client_no_visit` дублирует функциональность `get_inactive_clients` (stage 77)
- why_it_matters: prompt'ы — главный UX контракт для LLM-клиентов; сейчас они обещают сценарии, которые ломаются на первом же вызове
- suggested_fix: audit всех prompt'ов на соответствие текущим tool-сигнатурам, переписать `book-appointment` на `owner_id`, `unconfirmed_appointments` на диапазон+status, `unpaid_invoices` на payment_status
- confirmed_by: [product]

### 10. Две параллельные rate-limit и auth подсистемы с разными SLA
- severity: **high** (architecture + security), confidence: 0.88
- file: `bearer_rate_limiter.py:42-97` + `rate_limit_backend.py` + `auth`-кластер из 7 модулей
- problem: bearer-путь использует только in-memory limiter (bypass через multi-worker deployment); web-путь — через Redis backend; auth раздроблен между `bearer_auth`/`runtime_auth`/`request_auth`/`request_credentials` (dead)/`vetmanager_auth`/`vetmanager_connection_service`/`web_auth` — из них `request_credentials.py` — полностью мёртв после stage 22.4
- why_it_matters: (security) rate-limit bypass реален при горизонтальном масштабировании; (architecture) 7 модулей тормозят любое изменение auth-контракта и провоцируют рассинхрон
- suggested_fix: удалить `bearer_rate_limiter`, ввести `namespace='bearer_token'` в общем `rate_limit_backend` с pluggable Redis/InMemory; свернуть auth в `auth/` package (bearer.py, vetmanager.py, context.py) и удалить `request_credentials.py`
- confirmed_by: [architecture, security, performance-and-reliability]

## Blockers

### B1. README/tech-reqs/AssumptionLog drift
См. Top-10 #3. confirmed_by: [docs]

### B2. Missing X-Correlation-ID propagation к VM API
См. Top-10 #4. confirmed_by: [observability]

### B3. 80+ MCP tools без latency/outcome метрики
См. Top-10 #5. confirmed_by: [observability]

### B4. Deploy-скрипты захардкодили старый хост 342915.simplecloud.ru
- severity: blocker (docs), confidence: 0.95
- file: `scripts/*.sh`, `.github/workflows/deploy-prod.yml`
- problem: prod крутится на `vetmanager-mcp.vromanichev.ru`, дефолт во всех скриптах — старый SimpleCloud IP
- why_it_matters: любой `deploy.sh` без явного override задеплоит в dev-host; вероятность ошибки высокая
- suggested_fix: заменить дефолты или сделать параметр обязательным; landing_page.py/web_html.py тоже захардкодили домен — вынести в `SITE_BASE_URL` env
- confirmed_by: [docs]

## High

| # | file:lines | problem | category | reviewers | conf |
|---|-----------|---------|----------|-----------|------|
| H1 | tools/admission.py:298-326 | create_admission payload+status (Top-10 #1) | product | product | 0.95 |
| H2 | tools/medical_card.py:58-134 | client_id вместо owner_id + N+1 (Top-10 #2) | product/perf | product, perf | 0.98 |
| H3 | vetmanager_client.py:175-228 | нет singleton httpx/retry/breaker (Top-10 #8) | perf | perf | 0.95 |
| H4 | vetmanager_client.py + observability | upstream metric + лог ошибок (Top-10 #6) | observability | obs, perf | 0.97 |
| H5 | error_tracking.py:14-43 | sanitizer пропускает VM tokens (Top-10 #7) | security | security | 0.95 |
| H6 | prompts.py:81-144 | prompt'ы ссылаются на legacy параметры (Top-10 #9) | product | product | 0.95 |
| H7 | bearer_rate_limiter+auth кластер | 2 подсистемы, dead module (Top-10 #10) | arch/sec | arch, sec, perf | 0.88 |
| H8 | web_routes_account.py:41-155 | account_integration_submit и _reauth_submit 90% дубль | code | code | 0.97 |
| H9 | tools/admission.py:198-211,281-296 | crud_list unwrap скопирован в upcoming_visits/daily_schedule | code | code | 0.95 |
| H10 | tools/pet.py:293-362 | get_inactive_pets тройной nested break + UPPER_CASE mutable; worst case 6000 sequential requests | code/perf | code, perf | 0.90 |
| H11 | multiple tools/* | json.dumps фильтров скопирован 15+ раз, нет FilterBuilder | architecture | arch | 0.90 |
| H12 | tools/medical_card.py:58-134 | N+1 по pet'ам (отдельно от #H2 — подтверждено perf-reviewer) | perf | perf | 0.95 |
| H13 | web_security.py + rate_limit_backend.py | sync redis в async handlers → блокирует loop | perf | perf | 0.90 |
| H14 | web_auth.py | PBKDF2 390k iterations inline в async хендлере | perf | perf | 0.95 |
| H15 | request_context.py | silent fallback к {} — non-HTTP транспорты теряют ID | observability | obs | 0.90 |
| H16 | tools/crud_helpers.py | exceptions наружу без tool_name+account_id в контексте | observability | obs | 0.92 |
| H17 | web_routes_auth.py | /register без business metric, rate_limit события не логируются | observability | obs | 0.93 |
| H18 | tests/test_client_multitenancy.py + runtime_factories.py | asserts на private _auth_source/_domain/_api_key; фабрика ставит 8+ приватных полей | tests | tests | 0.88 |
| H19 | tests/test_e2e_mock_entities.py | нет unhappy path (billing 500/404, VM timeout, malformed JSON, 429); error tests минуют mcp.call_tool | tests | tests | 0.88 |
| H20 | tool_descriptions.py:1-724 | god-module: synonyms+metadata+post-registration мутации | architecture | arch | 0.75 |
| H21 | tools/* (layer violation) | нет service/repository слоя — tool'ы миксуют JSON+pagination+business | architecture | arch | 0.85 |
| H22 | prompts.py (unconfirmed_appointments) | принимает одну дату вместо диапазона, нет status filter | product | product | 0.90 |

## Medium

Компактный список (file:lines — problem (category, reviewer, conf)):

- `tools/client.py:370-421` — inline импорты + прямой vc.get() минуя crud_helpers (complexity, code, 0.88)
- `tools/pet.py:186-248` — тот же антипаттерн в get_pet_profile (complexity, code, 0.88)
- `tools/_inactive_helpers.py:196-210,234-247` — распаковка pid из invoice/medcard дублируется (dup, code, 0.85)
- `vetmanager_client.py:190-228` — _request смешивает cache/rate-pace/retry (complexity, code, 0.80)
- `validators.py:56-70` — _add_months через hardcode 31 для декабря вместо calendar.monthrange (readability, code, 0.85)
- `tools/medical_card.py:36-48` — ручной json.dumps вместо filters= в build_list_query_params (readability, code, 0.82)
- `tools/admission.py:82-84` — inline импорт datetime (naming, code, 0.92)
- `tools/client.py:31-37` — мёртвая else-ветка в _search_client_phones (readability, code, 0.78)
- `vetmanager_connection_service.py:139-146` — тернарный f-string для error message (readability, code, 0.82)
- `bearer_auth.py:74-244` — resolve_bearer_auth_context делает 7+ разнородных вещей (coupling, arch, 0.70)
- `multiple: vm_connection_service/host_resolver/vm_client` — 3 места строят httpx+error mapping; allowlist только в host_resolver (dup, arch, 0.85)
- `multiple: rate_limit_backend/request_cache/bearer_rate_limiter` — нет общего kv_backend.py Protocol (extension, arch, 0.70)
- `landing_page.py:1-751` + `web_html.py:662` — HTML-string god modules, inline styles → CSP unsafe-inline (arch, 0.65)
- `web.py:1-407` — orchestrator + shared helpers + dashboard rendering; 6-10 callables пробрасываются в register_* (coupling, arch, 0.75)
- `AssumptionLog.md` — нет записей для этапов 76, 82, 83, 84 (missing, docs, 0.80)
- `README.md:466-469` — описание cache key без account_id (stage 54.2.3) (drift, docs, 0.87)
- `artifacts/technical-requirements-vetmanager-mcp-ru.md` — roadmap 20-49 vs актуальный 20-84 (outdated, docs, 0.92)
- `README.md:66-67` — fast contour без --profile test (drift, docs, 0.82)
- `CLAUDE.md` §5.4 vs commit f507fc1 — 2 итерации vs 3 (contradiction, docs, 0.85)
- `landing_page.py:22-23,671; web_html.py:447` — hardcoded vetmanager-mcp.vromanichev.ru в canonical/og (outdated, docs, 0.93)
- `bearer_rate_limiter.py:42-97` — in-memory bypass через multi-worker (sec, 0.85)
- `web_auth.py:132-183` — stateless HMAC session, logout не инвалидирует до 24h (sec, 0.70)
- `web_security.py:107-138` — WEB_TRUSTED_PROXY_IPS exact IPs, не CIDR (sec, 0.60)
- `vetmanager_client.py` — одиночный 30s timeout без connect/read/write split (perf, 0.85)
- `host_resolver.py/vetmanager_client.py` — billing resolve per-instance, не process-wide (perf, 0.95)
- `alembic + storage_models.py` — token_usage_logs без индекса (bearer_token_id, event_at) (perf, 0.85)
- `rate_limit_backend.py` — sync client.ping() в factory init (perf, 0.75)
- `request_cache.py` — copy.deepcopy на каждом get/set (perf, 0.75)
- `tools/client.py + tools/pet.py` — asyncio.gather без return_exceptions (perf, 0.85)
- `tools/pet.py:272-362` — get_inactive_pets 6000 sequential (перекликается с H10, perf, 0.80)
- `bearer_auth.py:222-233` — usage_stats lookup-then-insert race (perf, 0.80)
- `web.py` — readyz только storage, dashboard делает VM API sync в HTML render (perf, 0.65)
- `vetmanager_client.py:141-158` — _pace_requests serialize asyncio.gather (perf, 0.85)
- `tools/crud_helpers.py` — paginate_all без default max_rows (perf, 0.80)
- `vetmanager_connection_service.py` — timeouts не логируются и не попадают в upstream_failures_total (obs, 0.88)
- `auth_audit.py` — ip_address/user_agent только в DB, не в log stream (obs, 0.97)
- `host_resolver.py` — billing_host_resolved на DEBUG (obs, 0.85)
- `bearer_auth.py` — нет auth_success counter (obs, 0.91)
- `web_routes_auth.py` — /logout без любого лога/аудита (obs, 0.89)
- `service_metrics.py` — нет process_start_time, alert'ы ложно срабатывают на restart (obs, 0.88)
- `tests/test_e2e_mock_entities.py` — fake fixtures с одним полем (tests, 0.80)
- `tests/test_get_doctor_free_slots.py` — нет zero-length timesheet, 31-day boundary (tests, 0.85)
- `tests/test_inactive_pets.py` — нет last_visit_date=None, limit boundary (tests, 0.88)
- `tests/test_inactive_clients.py` — months_min>months_max, limit=0 (tests, 0.80)
- `tests/test_ergonomic_filters.py` — phone edge cases (tests, 0.75)
- `tests/` — нет concurrency tests (tests, 0.80)
- `tests/` — нет billing API non-200 tests (tests, 0.85)
- `tests/test_inactive_pets.py` — content[0].text vs structured_content смешано (tests, 0.70)
- `tests/test_inactive_clients.py` + `test_inactive_pets.py` — substring-match фильтра (fragile, tests, 0.90)
- `prompts.py` — unpaid_invoices client-side фильтр, client_no_visit дублирует get_inactive_clients (product, 0.90)
- `prompts.py` — search_good передаёт name= (legacy title), low_stock N+1 без warning (product, 0.85)
- `tools/finance+warehouse+clinical` — inconsistent extra{camelCase} vs filter[property] (product, 0.80)
- `tools/operations.py` — get_timesheets.user_id → extra{userId}, поле doctor_id (product, 0.90)
- `tools/finance.py` — new_clients без date_from filter (product, 0.80)
- `tools/client.py` — inconsistent envelope формы ответа (product, 0.75)
- `tools/invoice.py` — date_from/date_to без normalization midnight/EOD (product, 0.70)
- `landing_page.py` — overpromise товаров/выручки без tool-поддержки (product, 0.70)

## Low

- `tools/crud_helpers.py:82-83` — paginate_all не поддерживает sort (code, 0.75)
- `tools/schedule.py:22-29` — константы что, не почему (code, 0.70)
- `tools/_inactive_helpers.py:112-127` — тривиальные date helpers рядом (code, 0.72)
- `vetmanager_client.py:103-106` — _api_key_fingerprint мёртвый guard (code, 0.70)
- `tools/pet.py:283-284` — UPPER_CASE локальные переменные (code, 0.80)
- `tools/admission.py:369-372` — shadow builtin `type` (code, 0.85)
- `request_credentials.py` — dead X-VM-* legacy module (arch, 0.95)
- `storage_models.py` — модели импортируют bearer_token_manager+secret_manager (arch, 0.65)
- `multiple env-helpers` — 3-4 разных парсера (arch, 0.60)
- `vetmanager_auth.py` — if/elif вместо strategy pattern (arch, 0.70)
- `observability_logging.py` и соседи — 4 модуля, границы нечёткие, 33-line shim (arch, 0.55)
- `AssumptionLog.md:10-14,161-178` — X-VM-* legacy разделы не помечены (docs, 0.90)
- `README.md:539-543` — таблица артефактов без 6 файлов (docs, 0.88)
- `README.md` — WEB_SESSION_MAX_AGE_SECONDS не задокументирован (docs, 0.85)
- `bearer_token_manager.py` — SHA-256 без pepper (sec, 0.50)
- `storage_models.py` — Fernet без binding к account_id (sec, 0.60)
- `web_routes_auth.py` — нет global-rate limit на /register (sec, 0.50)
- `web_auth.py` — нет max length на password (DoS PBKDF2) (sec, 0.60)
- `web_routes_system.py` — /metrics public без auth (sec, 0.55)
- `vetmanager_client.py` — AuthError message содержит masked api_key (sec, 0.60)
- `tools/user.py` — get_users с name filter 2 sequential (perf, 0.90)
- `storage_models.py` — service_bearer_tokens без composite index (perf, 0.55)
- `storage.py` — reset_storage_state swallows exceptions (perf, 0.55)
- `tools/schedule.py` — no reuse slots для overlap windows (perf, 0.40)
- `vetmanager_connection_service.py` — validate_*_connection без split timeout (perf, 0.60)
- `rate_limit_backend.py` — reset_all через scan_iter + delete O(N) (perf, 0.40)
- `server.py` — startup failure через logging.critical, ломает json (obs, 0.82)
- `web_routes_account.py` — token create/revoke без business metric (obs, 0.80)
- `tests/test_parse_date_param.py` — None, +0m, datetime строки (tests, 0.65)
- `tests/test_slots_helpers.py` — parse_admission_length malformed (tests, 0.70)
- `tests/` — нет tests на ClientPhone 500/network (tests, 0.70)
- `tests/test_client_multitenancy.py` — cache test не проверяет identity (tests, 0.55)
- `tests/test_error_tracking.py` — asserts на private Sentry internals (tests, 0.75)
- `tests/test_convenience_tools.py` — bare Exception, нет negative days (tests, 0.65)
- `tools/finance.py` — get_payments без date_from/date_to (product, 0.70)
- `tools/invoice.py` — get_invoices.client_id через extra{} top-level (product, 0.65)
- `Roadmap.md` — нет формального deprecation flow (product, 0.70)
- `PRD/этап-80-doctor-free-slots.md` — "единое имя doctor_id" vs get_timesheets.user_id (product, 0.80)
- `tools/operations.py` — get_anonymous_clients не в PRD (product, 0.50)

## Dismissed

- **SSRF cert pinning + public-IP validation** (`host_resolver.py`, sec, 0.55) — defense-in-depth поверх уже работающего allowlist; hypothetical DNS takeover billing API. Overkill для текущей модели угроз.
- **CSRF token rotation** (sec, 0.30) — spec не требует rotation per-POST; token одноразовый в рамках сессии — это стандартный pattern. False-positive.
- **Timing attack found vs not-found token** (bearer_auth, sec, 0.30) — rate-limiter на level выше делает timing-атаку нереалистичной; measurable только при отключенном лимите.
- **Explicit verify=True + cert pinning** (vetmanager_connection_service, sec, 0.30) — httpx verify=True по умолчанию; cert pinning — лишний operational toll при rotation VM API.
- **web.py info_disclosure str(exc) с Postgres creds** (sec, 0.40) — SQLAlchemy exceptions не содержат passwords в message; speculative.
- **/account/integration upstream error messages** (sec, 0.40) — показывает полезный feedback пользователю; деперсонализация снизит UX без реальной выгоды.
- **Low-confidence performance nits** (reset_all O(N), slots reuse, 0.40) — спекулятивная оптимизация, не подтверждена profile.
- **scope_creep get_anonymous_clients** (product, 0.50) — tool существует и используется; отсутствие в PRD не равно scope creep.
- **fragile test_error_tracking private Sentry asserts** (tests, 0.75 — но по факту это тест именно контракта sanitizer'а) — переклассифицирован как приемлемая связность, пока Sentry внутренний класс не поменяется.

## Systemic themes

1. **Drift API-контракта после миграций (stage 77.4 owner_id, stage 78.6 payment_status, stage 82/83 IN-батчинг)**. `get_medical_cards_by_client_id`, `create_admission`, `book-appointment` prompt, `unpaid_invoices` prompt, PRD этап 80 vs get_timesheets — все указывают на одну проблему: миграции field names/enum'ов не сопровождаются full-sweep по call sites. Нужен regression-checklist при миграциях + линт-правило «grep старого имени поля во всём tools/ и prompts/ на CI».

2. **Фрагментация инфраструктурных подсистем**. Auth (7 модулей, 1 dead), rate-limit (2 параллельных), http.AsyncClient (3 места строят), кэш (per-instance vs process), env-парсеры (3-4 реализации). Паттерн: решения добавлялись инкрементально без consolidation; пора сделать шаг назад и собрать `auth/`, `infra/http.py`, `infra/kv_backend.py`, `config.py`.

3. **Observability слепые зоны**. Correlation-ID не проходит в upstream, per-tool метрики отсутствуют, upstream latency не измеряется, exceptions без tool_name/account_id, /logout и /register без бизнес-событий. Все пять finding'ов — один gap: системное решение по instrumentation (декоратор + helper для upstream + расширение audit stream) закроет 5 пунктов одним этапом.

4. **Дублирование из-за отсутствия shared utilities**. json.dumps фильтров 15+, crud_list unwrap 2 раза, invoice/medcard pid unpacking, account_integration форма 2 раза, httpx client 3 раза. Системный fix: `FilterBuilder`, `_unwrap_crud_list`, `_handle_integration_form` helpers, `vetmanager_http.request`. Каждый отдельный дубль маленький, но совокупно это 200+ строк копипасты и 4-5 мест для забытого fix.

---

## Codex arbitration (GPT-5.4)

Codex подтвердил 9/10 findings. Три корректировки severity (см. ниже).

| # | Verdict | Severity | Codex's fix (summary) |
|---|---------|----------|------------------------|
| F1 | **confirm** | keep (high) | Payload → `user_id`/`admission_date`, default status `not_confirmed` или `save`. MCP-параметр `doctor_id` оставить, транслировать на границе API. |
| F2 | **confirm** | keep (high) | Переключить фильтр pets на `owner_id`, потом одним запросом `patient_id IN [...]`. Осторожно с pagination — батчинг меняет семантику limit/offset. |
| F3 | **confirm** | **lower → high** (был blocker) | Разделить на два work item'а: runtime-критичное (deploy domain + dependency version) первым, описательное (tool counts, stale audit) — hygiene debt. |
| F4 | **confirm** | keep (blocker) | Добавить correlation-merge в `_request` без изменения auth-header construction. Если context нет — header просто не отдавать. |
| F5 | **confirm** | **lower → high** (был blocker) | Инструментировать CRUD helper path один раз, labels по tool_name + outcome class, тот же registry что HTTP-метрики. "Blocker" агрессивно, если политика организации не требует per-tool метрик до релиза. |
| F6 | **confirm** | keep (high) | Duration histogram на success И failure; структурные warning logs на terminal timeout/network с `method/url/domain/elapsed`. Retry metrics отдельно от terminal outcome. |
| F7 | **confirm** | keep (high) | Перейти на deny-by-pattern санитайзер для заголовков + чистить request body, query params, cookies, extra context. Сохранить безобидные поля типа correlation_id. |
| F8 | **confirm** | keep (high) | Поэтапно: сначала shared `httpx.AsyncClient` с pooling; потом retry policy для 429/5xx с bounded backoff; circuit breaker — если load test покажет failure amplification. Не как один большой рефакторинг. |
| F9 | **confirm** | keep (high) | Prompts → `owner_id` terminology, align create_admission с исправленным tool contract, "next 2 days" — range + `not_confirmed` filter. «В MCP-продукте stale prompts — часть functional surface.» |
| F10 | **needs_more_context** | **lower → medium** (был high) | Rate-limit split плausibly real, но нужна информация о deployment topology (действительно ли bearer traffic multi-worker / multi-pod в prod?). Auth consolidation — разумный cleanup, но нужно отделить от rate-limit вопроса. Architecture debt, ещё не подтверждённый defect из предоставленного. |

### Codex: systemic observations

> "These findings point to a codebase with decent feature velocity but weak **contract-discipline at integration boundaries**. The highest-risk pattern is drift after migrations: API field names, ownership links, prompts, docs, and observability all appear to lag behind architectural changes. There is also a recurring theme of local correctness without enough operational hardening, especially around tracing, metrics, and upstream failure behavior. Next steps should be: lock down API-boundary adapters and prompt contracts with regression tests, centralize observability at helper/client choke points, and run a focused **'post-migration consistency sweep'** across docs, prompts, and auth/rate-limit layers."

### Итоговые корректировки к verdict

Blockers после арбитража: **B2, B3, B4** (было B1-B4).  
B1 (docs drift) разделён: часть про deploy-домен и fastmcp версию → B4 уже покрывает → остаётся blocker; описательная часть (tool counts, audit entry) → high tier.

**Final verdict: Do not merge** до устранения:
- F1 (create_admission bug)
- F2 (medical_cards owner_id)
- F4 (correlation_id propagation) — blocker observability
- Deploy-scripts hardcode (B4) — blocker docs
- F7 (Sentry sanitizer) — high security, но легко фиксится и блокирует утечку креденшлов → рекомендую включить в merge gate

Остальные — допустимый tech debt в backlog, решать отдельными этапами:
- F3 (tool counts/AssumptionLog/README descriptive drift) — high, docs sweep
- F5 (per-tool metric) — high, один этап observability
- F6, F8 (perf/observability VM client) — один этап "VM client overhaul"
- F9 (prompt audit) — один этап
- F10 (rate-limit + auth consolidation) — medium после подтверждения deployment topology
