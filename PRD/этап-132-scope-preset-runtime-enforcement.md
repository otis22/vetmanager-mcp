# Этап 132. Scope/preset runtime enforcement hardening

## Цель

Закрыть scope/preset findings после super-review stage 130: tool access registry должен стать runtime preflight до выполнения tool, а preset matrix должна совпадать с продуктовым контрактом.

## Контекст

Источник задачи: `artifacts/review/2026-04-23-full-stage-130.md`.

Основные findings:
- H4: `required_scope_for_request()` не мапит `/rest/api/ClientPhone` на `clients.read`, что оставляет phone index probing без client scope.
- H5: `frontdesk` preset обещает operational slots workflow, но `get_doctor_free_slots` требует `analytics.read`, которого в preset нет.
- M1: `TOOL_REQUIRED_SCOPES` проверяется тестами, но не применяется как preflight в runtime; aggregate tools могут частично выполниться до позднего scope failure.
- M7: preset tests inclusion-only; не хватает exact bundle, negative preset/ip mask cases и marketed preset × tool matrix.

Проверенные факты из кода:
- `tool_access_registry.py` содержит `TOOL_REQUIRED_SCOPES` для всех зарегистрированных tools и `TOKEN_PRESET_SCOPES` для 6 user-facing preset'ов.
- `tools/__init__.py` уже resolve'ит runtime credentials до выполнения tool в depersonalization wrapper; это естественная точка для tool-level preflight.
- `token_scopes.py` содержит path-level `required_scope_for_request()` как defense-in-depth внутри `VetmanagerClient`.
- `PRD/этап-130-token-presets-and-depersonalized-bearer-tokens.md` фиксирует expectation: `frontdesk` имеет operational доступ к записи/слотам, `doctor` read-only к расписанию врача/пациента.
- Текущий `analytics.read` blast radius в `TOOL_REQUIRED_SCOPES`: `get_doctor_free_slots`, `get_message_reports`, `get_timesheet_by_id`, `get_timesheets`. Stage 132 принимает этот blast radius для `frontdesk` как read-only operational visibility; более узкий `schedule.read` scope не вводится, чтобы не расширять RBAC модель в hotfix stage.

## Scope

- Добавить `ClientPhone`/`clientphone` в path-level scope mapping как `clients.read`.
- Внедрить tool-level preflight по `TOOL_REQUIRED_SCOPES[tool_name]` в wrapper регистрации tools до выполнения tool body.
- Имя tool для preflight определяется при регистрации как `kwargs.get("name") or func.__name__`; если имени нет в `TOOL_REQUIRED_SCOPES`, wrapper fail-closed с generic `ToolError`.
- Если `credentials.scopes` отсутствует или пустой, preflight fail-closed. Legacy bearer tokens с пустым `scopes_json` уже нормализуются в full-access до `RuntimeCredentials`, поэтому отдельной non-bearer ветки нет.
- Сохранить path-level `_require_scope` в `VetmanagerClient` как defense-in-depth.
- Для aggregate tools закрыть partial execution: если не хватает любого required scope, tool body и upstream calls не выполняются.
- Синхронизировать `frontdesk` preset с `get_doctor_free_slots` через добавление `analytics.read`.
- Backfill existing stage-130 `frontdesk` tokens: так как scopes snapshot'ятся в `scopes_json`, нужно обновить только токены с exact legacy frontdesk bundle, добавив `analytics.read`; остальные custom/legacy/full-access bundle не менять.
- Усилить tests: exact preset bundles, marketed preset × tool matrix, negative preset aliases/whitespace, malformed ip mask.
- Создать explicit source constant `MARKETED_PRESET_TOOLS` в `tool_access_registry.py` как источник истины для preset × advertised tools matrix; tests импортируют её, а не держат отдельную mirror-fixture.
- Обновить `AssumptionLog.md` и stage 130/132 PRD source-of-truth notes.

## Вне scope

- Переработка всей RBAC модели на per-field/per-clinic ACL.
- Изменение legacy tokens: старые токены продолжают читать сохранённый `scopes_json`.
- Observability metrics additions из stage 134/135, кроме уже существующих test expectations.
- Пересмотр user-facing preset list или добавление `custom`.

## Acceptance Criteria

- Токен без `clients.read` не может выполнить phone search через `ClientPhone` path.
- Tool wrapper проверяет `TOOL_REQUIRED_SCOPES` после credentials resolve и до tool execution; при нехватке scope поднимается generic `ToolError`, tool body не вызывается.
- Tool wrapper fail-closed, если registered tool отсутствует в `TOOL_REQUIRED_SCOPES` или если `credentials.scopes` пустой/отсутствует.
- Scope-denial `ToolError` использует generic message `Tool is not permitted for this token.` без имени missing scope; scope-denial logging/metrics остаётся stage 134.
- Scope-denial `ToolError` не содержит missing-scope/tool-name деталей ни в message, ни в structured payload/data.
- Aggregate tools `get_client_profile`, `get_pet_profile`, `get_inactive_pets`, `get_doctor_free_slots` не делают partial upstream calls при missing scopes; тесты явно проверяют, что tool body/upstream mocks не вызваны.
- `frontdesk` exact scope bundle содержит `analytics.read` и проходит marketed tools matrix для slots/schedule/client/pet/admission workflows.
- `frontdesk` blast radius от `analytics.read` явно принят: доступ к `get_doctor_free_slots`, `get_timesheets`, `get_timesheet_by_id`, `get_message_reports`.
- Existing tokens with exact stage-130 frontdesk scope snapshot receive `analytics.read` via migration/backfill; non-exact legacy/custom snapshots are unchanged.
- `full_access` preset проходит matrix для каждого tool из `TOOL_REQUIRED_SCOPES`.
- Preset tests проверяют exact bundles для всех preset'ов, а не только inclusion.
- Negative tests покрывают unknown/whitespace preset и malformed `ip_mask`.
- `clinical_staff` принимается только как legacy web-form value и нормализуется в `doctor`; direct service/registry preset `clinical_staff` rejected как unknown.
- `clinical_staff` normalization lives only in `web_routes_account.py` form handling before calling `issue_service_bearer_token`; `tool_access_registry.normalize_token_preset("clinical_staff")` remains rejected.
- Legacy tokens без `scopes_json` остаются full-access через существующий `deserialize_token_scopes(None)` contract; это фиксируется в AssumptionLog как compatibility choice.
- Regression test confirms `deserialize_token_scopes(None)` still yields full access.
- Полный suite `docker compose --profile test run --rm test` зелёный.

## Оценка PRD на простоту

Триггер: добавляется runtime preflight на уровне wrapper.

Более простой вариант оставить только path-level `_require_scope` не закрывает M1: aggregate tools могут успеть выполнить часть upstream calls до позднего failure. Передача required scopes вручную в каждый tool создаёт дублирование и риск рассинхрона с `TOOL_REQUIRED_SCOPES`.

Выбранный вариант минимален: wrapper уже получает `RuntimeCredentials` до tool body, поэтому может проверить `credentials.scopes` against central registry. Preflight runs after credentials resolve and before any depersonalization/sanitizer decision that depends on tool result. Tool name доступен на этапе wrapping, а path-level enforcement остаётся второй линией защиты.

## Декомпозиция

- 132.1 Research artifacts/code и подтвердить matrix/preset gaps. — done in PRD
- 132.2 Добавить tests для `ClientPhone` scope mapping и tool-level preflight fail-before-body, включая unknown tool mapping и empty scopes fail-closed.
- 132.3 Добавить tests для aggregate no-partial-execution при missing scopes с assert zero body/upstream calls.
- 132.4 Добавить exact preset bundles и source-level `MARKETED_PRESET_TOOLS` matrix tests, включая full-access every-tool coverage и explicit `analytics.read` blast-radius assertions.
- 132.5 Добавить tests для stage-130 frontdesk scope snapshot backfill и legacy `deserialize_token_scopes(None)` full-access compatibility.
- 132.6 Добавить negative tests для preset/ip-mask boundaries и `clinical_staff` web-form alias normalization.
- 132.7 Реализовать `ClientPhone` mapping, preflight helper, `frontdesk` `analytics.read`, backfill/migration и минимальные code fixes под Red tests.
- 132.8 Обновить `AssumptionLog.md`/PRD notes, прогнать tests/audit/external review/commit/push.
