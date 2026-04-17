# Этап 88. Observability core — correlation_id + per-tool + upstream metrics

## Контекст

Baseline super-review 2026-04-17 отметил 2 observability-blocker'а (B2, B3) и 1 high (F6):
- B2: VM API calls без `X-Correlation-ID` — incoming MCP request и upstream VM call нельзя связать в логах
- B3: 80+ MCP tools без per-tool latency/outcome метрики — невозможно отделить «медленный MCP» от «медленный VM API»
- F6: нет upstream latency histogram; timeouts и network errors поднимают исключение без structured-лога с domain/url/method/elapsed

## Цель

Закрыть эти три пробела минимальным хирургическим вмешательством в существующие модули `service_metrics.py`, `vetmanager_client.py`, `tools/crud_helpers.py` без рефакторинга.

## Scope

**В scope (88.1-88.4):**
- `service_metrics.py`: 2 новых record-функции (upstream_request с latency, tool_call)
- `vetmanager_client.py`: correlation_id в outgoing headers; upstream latency recording; structured warning log на timeout/network
- `tools/crud_helpers.py`: instrumentация crud_list/get_by_id/create/update/delete — latency + outcome
- Tests

**Вне scope (88.5-88.8) — отдельный этап:**
- auth_audit расширение (ip/ua в лог stream)
- auth_successes_total counter
- /logout /register business metrics
- process_start_time gauge

## Подзадачи

### 88.1 service_metrics.py: новые функции

Добавить:
- `record_upstream_request(*, target: str, status: str, duration_seconds: float)` — labels (target, status), counter + latency histogram
- `record_tool_call(*, endpoint: str, method: str, outcome: str, duration_seconds: float)` — labels (endpoint, method, outcome), counter + latency histogram
- Внутренние `_UPSTREAM_REQUESTS_TOTAL`, `_UPSTREAM_LATENCY`, `_TOOL_CALLS_TOTAL`, `_TOOL_CALL_LATENCY` defaultdict'ы
- `reset_service_metrics` очищает и их
- `snapshot_service_metrics` экспортирует
- `render_prometheus_metrics` выводит в prom-формате с TYPE/HELP

LOC: ≤80.

### 88.2 correlation_id в VM API headers (B2)

`vetmanager_client.py::_headers()` — добавить `X-Correlation-ID` из `get_current_request_context()["correlation_id"]`. Если контекст пуст (non-HTTP транспорт) — сгенерировать UUID4 и положить в headers.

LOC: ≤15.

### 88.3 Upstream latency + structured log на fail (F6)

`vetmanager_client.py::_request()`:
- Обернуть httpx-вызов в `time.monotonic()` start/elapsed
- Success: `record_upstream_request(target="vetmanager_api", status=f"http_{response.status_code}", duration_seconds=elapsed)`
- Timeout/network: после `record_upstream_failure` — `RUNTIME_LOGGER.warning` с `event_name`, `domain`, `method`, `url_path` (не полный URL — в нём могут быть фильтры), `elapsed_ms`, `attempt`
- Dup: можно унифицировать в вспомогательную ф-цию внутри модуля, но не расширять scope

LOC: ≤40.

### 88.4 Per-tool metric в crud_helpers (B3)

`tools/crud_helpers.py`:
- Внутренняя ф-ция `_instrumented_call(endpoint: str, method: str, coro)` — оборачивает coroutine вызов, замеряет `time.monotonic()` start/elapsed, записывает `record_tool_call` с outcome="success"/"error" (по исключению)
- crud_list/crud_get_by_id/crud_create/crud_update/crud_delete — через `_instrumented_call`
- paginate_all — не инструментируем (это композитный утилит, состоит из множества crud_list'ов; метрика per-call уже достаточна)

LOC: ≤40.

### 88.5 Тесты

- `test_upstream_request_metric_records_status_and_duration` (mock success, assert counter + latency sum)
- `test_upstream_request_metric_records_error_status` (mock 500)
- `test_tool_call_metric_records_outcome_success` (через crud_list)
- `test_tool_call_metric_records_outcome_error` (через crud_list с 500)
- `test_vm_api_receives_correlation_id_header` (mock VM, assert X-Correlation-ID в outgoing headers)
- `test_timeout_logs_structured_warning` (mock timeout, capture logs, assert event_name и domain поля)
- `test_prometheus_output_includes_new_metrics` (render_prometheus_metrics содержит новые типы)

LOC: ≤140.

### 88.6 Run tests + Codex review + commit + push

Обычный workflow.

## Acceptance

- Новые тесты проходят
- Полный test suite зелёный (577 → 584+)
- `X-Correlation-ID` в outgoing VM headers (проверено mock'ом)
- `vetmanager_upstream_request_latency_seconds` и `vetmanager_tool_call_latency_seconds` в /metrics
- Timeout/network error порождает `event_name=vm_upstream_timeout`/`vm_upstream_network_error` warning лог
- Codex review — 0 адекватных critical'ов
