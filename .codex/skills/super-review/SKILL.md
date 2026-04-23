---
name: super-review
description: Run the vetmanager-mcp multi-role super-review from Codex with Spark scout passes, GPT validation, Claude CLI cross-arbitration, YAML findings, inadequate-findings memory, and markdown report output.
---

# Super Review

Use this skill when the user asks for `super-review`, deep review, multi-agent review, review arbitration, Spark scout review, or cross-model review in this repository.

## Contract

Use the same review protocol as `.claude/commands/super-review.md`, but adapt runtime-specific steps to Codex tools:

- scopes: `changed` default, `related`, `full`, `stage:N`
- flags: `--no-spark`, `--no-arbitration`
- output report: `artifacts/review/{YYYY-MM-DD}-{scope_slug}-stage-{N}.md`
- dismissed memory: append to `artifacts/review/inadequate-findings-index.md`
- findings schema: YAML items with `severity`, `reviewer`, `category`, `file`, `lines`, `problem`, `why_it_matters`, `suggested_fix`, `confidence`

If the Claude command and this skill differ, prefer it only for shared review policy: scopes, model matrix, finding schema, report format, adequacy rules, and cross-CLI arbitration contract. Do not copy Claude-only mechanics such as `.claude/agents/*`, `Agent` tool-calls, or Claude command syntax into Codex execution.

## Model Routing

Spark/GPT side:

- `gpt-spark`: scout/prepass only. Treat output as untrusted leads.
- `gpt-5.4-mini` or `gpt-spark`: code/docs/tests candidate mining.
- `gpt-5.4`: observability and normal validation.
- `gpt-5.5`: security, architecture, product, hard disputes, and GPT-side aggregation if needed.

Claude side:

- `opus`: external arbitration from Codex runtime; security/architecture/product/aggregator quality bar.
- `sonnet`: fallback external arbitration and routine code/docs/tests checks.

Never let Spark decide final severity or merge verdict.

## Codex Workflow

1. Parse scope and stage from user args. Read `Roadmap.md`, current PRD, and the API facts block from `artifacts/api-research-notes-ru.md`.
2. Build changed/related/full file list.
3. Unless `--no-spark`, run Spark scout passes in parallel where available. In Codex runtime, use subagents if available; otherwise run bounded local passes yourself. If shelling out is appropriate, use:

```bash
codex exec -m gpt-spark -s read-only -C "$PWD" -
```

Fallback once:

```bash
codex exec -m gpt-5.4-mini -s read-only -C "$PWD" -
```

Scout tasks:

   - file chunks: semantic bugs, edge cases, `None`, empty values, unicode, timezone, async pitfalls
   - tests: missing unhappy/boundary/idempotency/serialization coverage
   - docs: verified drift only
   - inadequate index: known false positives and duplicates
   - snippets: `file:lines` and failure scenarios for strong candidates
4. Run one bounded Codex pass per reviewer role. Use the role briefs below and keep all outputs in the YAML schema. If you cannot run a role separately, say so in the report header; do not pretend parity with the Claude command.
5. Aggregate findings: dedupe, validate Spark leads, dismiss low-confidence/speculative/pre-existing/duplicate findings, sort by severity x confidence.
6. Unless `--no-arbitration`, perform cross-CLI arbitration with Claude CLI because the orchestrator is Codex:

```bash
claude -p --model opus --permission-mode default --tools "" --input-format text
```

Pass the arbitration prompt via stdin. If `opus` fails once, retry once:

```bash
claude -p --model sonnet --permission-mode default --tools "" --input-format text
```

`--tools ""` is required: the arbiter must not read the filesystem. Provide all snippets inline.

7. Merge Claude verdicts into the report and finalize `merge` / `do not merge`.
8. Write the report and append dismissed findings to the inadequate index.

## Codex Reviewer Roles

Run these roles as separate passes where practical; each pass returns YAML findings only.

- `code` (`gpt-5.4-mini` or current Codex model): local readability, dead code, naming, local duplication, complexity. Max 20 findings.
- `architecture` (`gpt-5.5` preferred): module boundaries, layering, coupling, cross-module duplication, fit to technical requirements. Max 20 findings.
- `simplicity` (`gpt-5.5` preferred): over-engineering, unnecessary indirection, premature flexibility, simpler concrete alternatives. Max 20 findings.
- `docs` (`gpt-5.4-mini` or current Codex model): verified drift across README/Roadmap/PRD/AssumptionLog/CLAUDE/AGENTS and code. Max 20 findings.
- `security` (`gpt-5.5` preferred): tokens, auth, SSRF, SQLi, CSRF, secrets, info disclosure. Max 20 findings.
- `performance-and-reliability` (`gpt-5.5` or `gpt-5.4`): N+1, timeouts, retry/backoff, async blocking, partial failure, cleanup. Max 20 findings.
- `observability` (`gpt-5.4`): logs, metrics, correlation IDs, incident debuggability, safe logging. Max 20 findings.
- `tests` (`gpt-5.4-mini` or current Codex model): behavior coverage, unhappy paths, boundaries, fixture realism, fragile mocks. Max 20 findings.
- `product` (`gpt-5.5` preferred): PRD acceptance, LLM-client UX, breaking changes, missing implementation. Max 20 findings.
- `codex-blindspot` (`gpt-5.5` or current Codex model): semantic bugs and edge cases that ordinary role reviews may miss. Max 15 findings.

Before aggregation, drop non-meta findings with `confidence < 0.4`. If more than 120 findings remain, keep all blocker/high and the highest severity x confidence medium/low findings up to 120 total.

## Arbitration Prompt

Use this self-contained prompt for the Claude CLI pass:

```text
Cross-model code review arbitration. Do NOT touch the filesystem; all context is inline.

=== CONTEXT ===
Project: vetmanager-mcp (Python async MCP server for Vetmanager).
Primary orchestrator runtime: codex
External arbiter: claude opus/sonnet

=== API CONTRACT FACTS ===
{full API facts block from artifacts/api-research-notes-ru.md}

=== TOP FINDINGS TO VALIDATE ===
{top-10 findings from aggregator}

=== SPARK SCOUT STATUS ===
Spark candidates are untrusted leads. Validate independently; do not accept solely because Spark raised it.

=== FILE SNIPPETS ===
{inline snippets, lines +-50 around each finding}

=== REQUEST ===
For each finding Fi:
- verdict: confirm | false_positive | needs_more_context
- severity_adjustment: keep | raise_to:X | lower_to:X
- fix: concrete correction
- rationale: concise reasoning

Then add systemic observations in 3-5 sentences.
Keep total <= 900 words.
```

## Guardrails

- Review only; do not auto-fix findings.
- Do not commit reports unless explicitly asked.
- External arbitration max two calls: primary external model plus fallback.
- Spark calls can be numerous, but Spark output remains candidate-only.
- For VM API fields, trust inline API facts and authoritative repo sources, not model memory.
