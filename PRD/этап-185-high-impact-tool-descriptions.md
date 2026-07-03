# Этап 185. High-impact MCP tool description cleanup

## Контекст

Аудит 2026-07-03 live `mcp.list_tools` показал 119 MCP tools. Общая оценка
описаний — около `7/10`: RU/EN synonyms и специализированные descriptions
работают, но внешние LLM всё ещё могут выбирать опасные или похожие tools
неоптимально.

Production feedback `#20` уже закрыт: report linked to known issue `#23` со
статусом `fixed`.

## Проверенные факты

- FastMCP tool schema в текущем runtime доступна через `tool.parameters`, не
  через `inputSchema` на Python object. Первая критика про пустые schemas была
  artifact некорректной выгрузки.
- Live export содержит 119 tools; README table сейчас требует reconciliation
  или явного правила подсчёта.
- Нулевая schema ожидаемо только у `get_report_ai_prompt_helper`.
- Наиболее рискованные зоны:
  - destructive tools: `delete_client`, `delete_pet`, `delete_invoice`,
    `delete_invoice_document`;
  - high-blast-radius broadcast: `send_message_to_all`;
  - overlapping selection clusters;
  - Report AI/export sequence.

## Цель

Точечно улучшить LLM tool selection и safety для самых рискованных descriptions,
не превращая этап в массовую перепись всех 119 tools.

## Scope

In scope:
- High-impact safety wording for destructive/broadcast tools.
- Reciprocal disambiguation for top clusters:
  - `get_goods` vs `search_invoice_goods`;
  - `get_medical_cards` vs `get_medical_cards_by_date` /
    `get_medical_cards_by_client_id`;
  - `get_revenue_summary` vs `get_average_invoice`;
  - `get_clients` vs `get_debtors` / `get_inactive_clients` /
    `get_client_profile`;
  - Report export trio: `get_report_ai_job_export`, `start_report_export`,
    `get_report_export_file`.
- Report AI/export canonical order and preconditions in descriptions/helper.
- Focused create guidance only for `create_admission`, `create_medical_card`,
  `create_client`, and `create_pet`. Do not touch `update_*` descriptions in
  this stage.
- README tool count reconciliation or explicit counting rule.
- Regression tests for wording and live schema export via `tool.parameters`.

Out of scope:
- Mass rewrite of all 119 descriptions.
- New tools, new scopes, access changes, auth changes.
- Tool schema/parameter changes unless a concrete bug is found.
- Production behavior changes beyond deployed descriptions/docs.
- Full create/update guidance for every mutation tool.

## Архитектурное решение

### Проблема

LLM clients select tools mostly from names, descriptions and schemas. Current
descriptions are generally usable, but the risky cases do not stand out enough:
destructive/broadcast actions look too similar to safe reads, and overlapping
tools lack reciprocal selection guidance.

### Контекст и ограничения

- Description enrichment is centralized in `tool_descriptions.py`.
- `tools/list` schema/description regression tests already exist in
  `tests/test_tools_list_schema.py`.
- This stage changes public MCP descriptions and README docs, but not runtime
  Vetmanager API behavior.
- Descriptions must stay concise enough for LLM tool selection and avoid
  excessive boilerplate.
- Description text is public MCP contract surface. Tool names, parameters,
  required fields, scopes and existing non-target descriptions must remain
  stable except for explicitly listed target tools/clusters.

### Рассмотренные варианты

1. Rewrite all descriptions.
   - Plus: comprehensive cleanup.
   - Minus: high diff, review noise, high chance of introducing wording drift.
2. Change schemas/scopes to encode more guidance.
   - Plus: stronger structural guardrails.
   - Minus: out of scope; can break clients and requires broader contract review.
3. Target high-impact descriptions and tests.
   - Plus: addresses current risk with low blast radius.
   - Minus: leaves lower-value generic descriptions for later.

### Выбранное решение

Use option 3: update only the high-impact descriptions and documentation
contract. Add tests that pin the safety/disambiguation wording and confirm the
runtime schema export path uses `tool.parameters`.

### Инварианты

- No new tools.
- No scope/access changes.
- No Vetmanager API call behavior changes.
- Existing tool names and parameters remain stable.
- Tool names/count and parameters remain unchanged. Non-target descriptions are
  not intentionally edited; avoid golden snapshots for every non-target
  description because they would be brittle for future stages.
- Descriptions should guide LLM selection without requiring real API smoke.

### Rollback/fallback

Rollback is reverting description/docs/test changes. If a wording change proves
confusing, adjust `tool_descriptions.py` and tests without data migration.

Architecture Critique: required because MCP public contract and production
tool-selection behavior change, but scope is intentionally description-only.

## Acceptance Criteria

- Destructive/broadcast tools include explicit safety/blast-radius wording.
- Top overlapping clusters include reciprocal “use X instead” guidance.
- Report AI/export descriptions/helper include canonical order and state or
  precondition guidance.
- README uses one deterministic counting rule: live `mcp.list_tools` count.
  The README count must match that count or explicitly label any excluded
  internal/helper tools by name. `get_report_ai_prompt_helper` is counted in
  the live 119 unless the README explicitly excludes it by name.
- Tests cover:
  - high-impact safety wording;
  - reciprocal disambiguation;
  - Report AI/export state/order wording;
  - live schema export via `tool.parameters`.
  - README tool count reconciliation against live `mcp.list_tools`;
  - tool names/count and parameters unchanged.
- Targeted tests pass.
- Full suite and Docker suite pass.
- Deploy smoke verifies production `/mcp` is healthy and live `tools/list`
  exposes the intended natural-language safety/disambiguation wording on a
  known target tool, without requiring synthetic stage marker tokens and
  without calling real Vetmanager API.

## Review Gates

- Spark PRD review: read-only sandbox failed before review with bwrap/runtime
  error; per workflow repeated once with `gpt-5.3-codex-spark
  -s danger-full-access` and review-only prompt. Accepted findings:
  - optional create/update guidance was too vague and risked scope creep;
  - public contract compatibility needed an explicit invariant;
  - guard against collateral edits outside target descriptions;
  - README count/smoke criteria needed deterministic wording.
- Claude Opus Architecture/PRD review 1 accepted 3 findings:
  - use natural production wording instead of synthetic `HIGH-IMPACT` /
    `DESTRUCTIVE` marker tokens;
  - remove the contradiction between collateral guardrails and shared-generator
    edits;
  - make README count testing explicit and count `get_report_ai_prompt_helper`
    unless excluded by name.
- Claude Opus Architecture/PRD review 2 accepted 2 simplification findings:
  - avoid byte-for-byte golden snapshots for all non-target descriptions;
  - keep review gates out of product acceptance criteria.
