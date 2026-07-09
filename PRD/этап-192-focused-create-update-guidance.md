# Stage 192. Focused create/update guidance

## Контекст

Stage 185.5 was stopped to avoid scope creep. The remaining useful part is a
small text-only improvement for a few high-risk create/update tools so LLMs do
lookup steps before writing.

## Цель

Improve create/update tool descriptions for selected tools without changing
schemas, scopes, runtime write behavior or Vetmanager API assumptions.

## Архитектурное решение

Проблема: LLM may attempt write calls with human names instead of resolved IDs
or without confirming exact target.

Ограничения:
- descriptions are centrally enriched in `tool_descriptions.py`;
- Vetmanager API behavior must not be invented;
- write logic and schemas should remain stable.

Варианты:
- rewrite all write descriptions: too broad;
- targeted guidance for 4-5 tools: low risk and testable.

Выбор: update only descriptions for `create_admission`,
`create_medical_card`, `create_client`, `create_pet`, optionally
`update_admission`, with lookup-chain/confirmation wording.

Инварианты:
- no schema or access registry changes;
- no runtime write path changes;
- tools/list remains valid.

Rollback: revert text changes and tests.

Architecture Critique: not required; text-only MCP description guidance does not
change auth, storage, public API, performance or cross-module runtime behavior.

## Scope

1. Identify current descriptions and exact enrichment path.
2. Add concise guidance fragments.
3. Add regression tests for fragments and schema stability.

## Out of scope

- Mass description rewrite.
- Required-field claims not verified by existing code/OpenAPI.
- Runtime validation changes.

## Acceptance Criteria

1. Target tool descriptions mention resolving IDs before create/update where
   applicable.
2. Descriptions remain concise and do not contradict schemas.
3. Tests pin key fragments and tools/list schema shape.

## Tests

- Description registry tests.
- Existing tools schema tests.

## Rollout

Deploy normally. Smoke verifies `/mcp`/tools-list reaches production.
