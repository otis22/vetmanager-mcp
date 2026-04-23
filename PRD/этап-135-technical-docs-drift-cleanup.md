# Этап 135. Technical docs drift cleanup after stage 130

## Контекст

После stages 130-134 runtime-контракт bearer tokens изменился: новые токены выпускаются через preset'ы, scope enforcement стал runtime preflight, depersonalized token fail-closed, а observability получила дополнительные метрики и audit/correlation события. Технические артефакты частично описывают более старое состояние: future scopes, default full-access для новых токенов и неполный набор stage 130+ изменений.

## Цель

Синхронизировать технические документы с фактическим stage 130+ контрактом без изменения runtime-кода.

## Scope

1. Обновить `artifacts/technical-requirements-vetmanager-mcp-ru.md`:
   - current state должен охватывать stages 20-134;
   - dependency строка `fastmcp` должна явно развести project metadata (`pyproject.toml`: `fastmcp>=2.0.0`) и Docker runtime pin (`Dockerfile`: `fastmcp>=3.1.0,<4`), если оба источника остаются актуальными;
   - section token scopes должна описывать текущий preset-based issuance, runtime enforcement и legacy compatibility вместо future-only модели;
   - scope matrix должна быть сверена с `tool_access_registry.py` и `token_scopes.py`, включая preset -> scopes, tool -> scopes, REST path defense-in-depth mappings, `ClientPhone -> clients.read`, `messages/reports -> analytics.read`, send-message tools -> `messaging.write`, `messaging.read` как legacy supported scope вне active preset'ов.
2. Синхронизировать PRD/Roadmap формулировки depersonalization free-text policy:
   - address redaction только structural по ключам;
   - broad address heuristics не входят в clinical free-text scrubber.
3. Проверить и при необходимости обновить README, SECURITY и operations/readiness docs на user-visible изменения stages 131-134:
   - README: `/account` issuance flow с шестью preset'ами, depersonalized checkbox/fail-closed contract, новые `vetmanager_token_preset_issued_total` и `vetmanager_sanitizer_failures_total`, `/metrics` unauthorized security signal.
   - SECURITY: privacy/auth boundary для depersonalized bearer token, fail-closed sanitizer path, hash-only/service-token boundary.
   - operations readiness: metrics/audit/correlation additions stage 134 без дублирования полного observability runbook.
4. Зафиксировать результат в `AssumptionLog.md`: before -> after drift items, решение по dual FastMCP dependency docs, scope matrix rationale, подтверждение docs-only/no runtime changes.
5. Прогнать docs/workflow проверки, достаточные для docs-only stage.
6. Перед каждым current-state утверждением свериться с source of truth:
   - `tool_access_registry.py`: preset matrix, `TOOL_REQUIRED_SCOPES`, marketed preset tools.
   - `token_scopes.py`: REST path defense-in-depth, включая `ClientPhone`.
   - `tools/__init__.py` и `depersonalization.py`: depersonalized fail-closed wrapper/sanitizer behavior.
   - `pyproject.toml` и `Dockerfile`: dependency metadata/runtime pins.
7. Точечно закрыть legacy workflow gaps, поднятые `scripts/review_workflow_check.sh 135`, если они не меняют runtime-контракт и относятся только к управленческим артефактам.

## Не делать

- Не менять runtime-код, storage migrations или preset matrix.
- Не вводить новый scope (`schedule.read`, `messages.read.v2` и т.п.).
- Не менять sanitizer heuristics.
- Не переписывать старые исторические записи AssumptionLog, кроме новой записи stage 135.
- Не дублировать observability runbook в high-level docs; давать краткий summary и ссылку.
- Не переписывать исторические PRD закрытых этапов шире точечной корректировки stale wording, явно указанной в Roadmap 135.1 или 135.3, либо workflow-gap fix из Scope 7.
- Если код противоречит PRD/Roadmap, source of truth — код. Docs переписываются под код; если это выявляет runtime bug, docs update останавливается и finding эскалируется отдельно.

## Декомпозиция

- 135.1 PRD + review gates: ≤ 2 ч.
- 135.2 Technical requirements current-state update: ≤ 2 ч.
- 135.3 Scope/preset/depersonalization wording sync in PRD/Roadmap: ≤ 2 ч.
- 135.4 README/SECURITY/operations docs check and targeted updates: ≤ 2 ч.
- 135.5 AssumptionLog + workflow checks + final audit: ≤ 2 ч.

## Верификация

- `scripts/review_workflow_check.sh 135`
- `rg` checks for stale docs wording:
  - `runtime enforcement scopes пока не включён`
  - `новые токены получают default full-access`
  - `rg -i "address pattern|address heuristic|sanitize address|адресн(ый|ые).*маркер|простые адресные маркеры" artifacts/ PRD/ Roadmap.md`
  - ожидаемый результат: нет утверждений, что depersonalized free-text scrubber использует broad address heuristics; допускаются упоминания structural address keys и исторический контекст, если рядом указано, что v1 не делает broad free-text address scrub.
- Full test suite is not required for docs-only edits unless workflow/scripts or executable snippets are changed.

## Acceptance Criteria

1. Technical requirements no longer claim scope enforcement is future-only or that new tokens default to full-access.
2. Scope docs match `tool_access_registry.py` and `token_scopes.py`: active preset scopes, `TOOL_REQUIRED_SCOPES`, marketed preset coverage, `ClientPhone -> clients.read`, `analytics.read` for reports/schedule analytics, `messaging.write` for send tools, `messaging.read` legacy-only.
3. Depersonalization docs consistently say address redaction is structural-only in v1, not broad free-text address heuristic.
4. README mentions preset issuance and depersonalized token behavior; SECURITY mentions fail-closed depersonalized privacy boundary; operations/readiness mentions new metrics/audit/correlation signals or links to the observability runbook.
5. Roadmap and AssumptionLog reflect stage 135 completion, review budgets, docs-only/no runtime changes, and workflow check passes.

## Проверенные факты после создания PRD

- `pyproject.toml` содержит `fastmcp>=2.0.0`, а Dockerfile runtime install использует `fastmcp>=3.1.0,<4`; docs должны описывать это различие вместо одного "единственного" pin.
- `tool_access_registry.py` содержит active preset matrix без `messaging.read`; `get_message_reports` требует `analytics.read`, send-message tools требуют `messaging.write`.
- `token_scopes.py` и stage 132 должны быть проверены для REST path defense-in-depth mappings до финального docs update.
- `artifacts/review/2026-04-23-full-stage-130.md` M8 является прямым источником stage 135.
- `artifacts/observability-runbook-vetmanager-mcp-ru.md` уже содержит stage 134 observability additions; stage 135 должен не дублировать runbook, а синхронизировать high-level docs.
