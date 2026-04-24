# Этап 142. Packaging and LLM-client UX cleanup

## Контекст

Источник: `artifacts/review/2026-04-24-full-stage-136.md`, findings F23/F24.

Цель этапа: закрыть packaging metadata drift и сделать scope-denial ошибки полезными для LLM/user workflows без изменения token scope enforcement.

## Проверенные факты

- `pyproject.toml` сейчас declares wheel build через Hatch, но `[tool.hatch.build.targets.wheel] packages = ["tools"]`; runtime imports many top-level modules/packages (`server.py`, `auth/`, `resources/`, `vm_transport/`, `storage.py`, `tool_access_registry.py` и т.д.).
- `pyproject.toml` допускает `fastmcp>=2.0.0`, а Docker production/test images ставят `fastmcp>=3.1.0,<4`.
- Runtime production path в Docker не устанавливает wheel, а копирует source tree и запускает `python server.py`.
- Wheel не используется production Docker image, но `pyproject.toml` уже публикует installable project metadata; поэтому `pip install .`/локальный wheel build являются supported development/packaging contract and must not install an incomplete runtime.
- Scope enforcement выполняется в `tools/__init__.py::_ensure_tool_scopes_allowed()`: denied calls сейчас возвращают generic `Tool is not permitted for this token.`
- `tool_access_registry.py` содержит `TOKEN_PRESET_SCOPES`, `MARKETED_PRESET_TOOLS`, `TOKEN_PRESET_LABELS` и `infer_token_preset()`, поэтому можно строить deterministic hints без дублирования отдельной матрицы.
- Prompts сейчас статичны и не знают runtime bearer scopes; фильтровать prompt discovery per token без отдельного request-aware prompt wrapper будет шире текущего scope.

## Scope

### In scope

1. Исправить wheel build metadata так, чтобы wheel installation содержал runtime modules/packages needed by `server.py` and registered tools, либо явно проверить build failure если stance изменится.
2. Выровнять `fastmcp` bounds in `pyproject.toml` with Docker: `>=3.1.0,<4`.
3. Добавить tests, которые строят wheel или проверяют build target metadata и ловят incomplete `tools`-only package drift.
4. Улучшить scope-denial `ToolError`: required scopes, missing scopes, current inferred preset when exact match, allowed advertised presets for the tool.
5. Добавить lightweight prompt prefix guidance: если tool denied by token scopes, пользователю нужно выбрать токен/preset с нужными scopes; не обещать, что prompts скрываются.
6. Обновить README/tech notes if packaging or UX contract changes user-facing behavior.

### Out of scope

- Dynamic prompt filtering by bearer token scopes.
- Changing scope model, presets or enforcement semantics.
- Publishing package to PyPI or adding release automation.
- Repackaging the whole project into a new `vetmanager_mcp/` package namespace.

## Acceptance Criteria

- `pyproject.toml` and Docker use aligned FastMCP lower/upper bounds: `fastmcp>=3.1.0,<4`.
- Packaging test proves the configured wheel includes all top-level runtime source modules/packages needed for source-layout execution, excluding explicit non-runtime trees (`tests/`, `PRD/`, `artifacts/`, local logs/cache/build outputs). Examples that must be covered by this property: `server.py`, `auth/bearer.py`, `storage.py`, `tool_access_registry.py`, `vm_transport/breaker.py`.
- Scope denial still happens before tool body execution.
- Denial message includes:
  - denied tool name;
  - required scopes;
  - missing scopes;
  - current inferred preset label or `custom scopes`;
  - allowed advertised preset labels for that tool when known.
- Denial message does not leak bearer token value, token hash, Vetmanager credentials, account email, domain, or API key.
- Existing full-access and correctly scoped tokens continue to execute allowed tools.
- Prompt text includes one static scope-denial guidance string from a single constant in `prompts.py`; no new prompt helper module, no conditional prompt formatting, and no claim that prompts are dynamically filtered.
- Targeted tests and full Docker test profile pass.

## Decomposition

1. Tests for FastMCP bound alignment and wheel/runtime inclusion. ≤ 2h / ≤ 150 LOC.
2. Implement packaging metadata fix. ≤ 2h / ≤ 150 LOC.
3. Tests for scope-denial details and no body execution. ≤ 2h / ≤ 150 LOC.
4. Implement denial message helpers using `tool_access_registry.py`. ≤ 2h / ≤ 150 LOC.
5. Tests/docs for prompt guidance. ≤ 2h / ≤ 150 LOC/docs.
6. Full checks, audit, external diff review, commit/push, self-attestation. Workflow step.

## Simplicity Notes

- Simpler variant considered: remove the wheel target and declare source/Docker-only. Rejected because the project already exposes installable metadata via `pyproject.toml`; leaving `pip install .` incomplete is worse than completing the existing flat-layout wheel selection.
- Prefer completing the existing Hatch wheel target over switching the repository to a new package namespace.
- Use existing registry constants to compute allowed presets; do not maintain a second mapping.
- Improve denial messages first. Dynamic tool/prompt discovery filtering is higher risk because it depends on request-aware FastMCP internals and can be handled in a later stage if needed.
- Prompt guidance is a single static string appended by the existing prompt prefix function; no new prompt wrapper/helper module.
