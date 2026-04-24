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

- `gpt-5.3-codex-spark`: scout/prepass only. Treat output as untrusted leads.
- `gpt-5.4-mini` or `gpt-5.3-codex-spark`: code/docs/tests candidate mining.
- `gpt-5.4`: observability and normal validation.
- `gpt-5.5`: security, architecture, product, hard disputes, and GPT-side aggregation if needed.

Claude side:

- `opus`: external arbitration from Codex runtime; security/architecture/product/aggregator quality bar.
- `sonnet`: fallback external arbitration and routine code/docs/tests checks.

Never let Spark decide final severity or merge verdict.

## Runtime Defaults And Fallbacks

Use these defaults when shelling out from Codex:

- Per reviewer/scout command timeout: **1200 seconds**.
- External arbitration timeout: **900 seconds**.
- First attempt sandbox: `-s read-only`.
- Classify failures before retrying:
  - **Sandbox/runtime failure**: process fails before meaningful file reads due to local execution errors such as `bwrap: loopback: Failed RTM_NEWADDR`, sandbox initialization, PTY/session startup, local timeout wrapper issues, or shell/env problems. Retry the **same model** once with the adjusted runtime settings described below. Do not switch models for these failures.
  - **Model failure**: stderr/stdout clearly indicates the requested model is unavailable, unknown, unsupported, denied for the account, capacity-limited, quota-limited, or otherwise rejected by the model provider. Only this class may use the documented fallback model.
  - **Review-output failure**: command ran and read files but returned empty output, malformed YAML, non-findings prose, or a meta runtime error. Do not switch models automatically unless the output itself identifies a model/provider failure; mark the role `skipped_or_failed` or rerun the same model once if the failure is obviously transient.
- If Codex CLI fails before reading files with sandbox/runtime errors such as `bwrap: loopback: Failed RTM_NEWADDR`, retry that exact pass once with `-s danger-full-access` and a prompt that explicitly says: `Review only. Do not edit files. Do not run write commands.`
- If and only if a model failure is identified, retry once with the documented fallback model and record the fallback in the report header/limitations.
- If a role returns empty output, non-YAML output, or only a meta runtime error, do not silently treat it as "no findings"; mark that role as `skipped_or_failed` in the report header and continue with available roles.
- Before finalizing, check that no `codex exec` / `claude -p` processes from this run are still alive.

## Known Runtime Issues Memory

These are known review-runner issues, not project findings. Do not include them in the main findings list, do not send them to arbitration as product defects, and append them to dismissed memory only if they are newly observed in a materially different form:

- `bwrap: loopback: Failed RTM_NEWADDR` on Codex read-only sandbox startup.
  - Classification: sandbox/runtime failure.
  - Action: retry the same model once with `-s danger-full-access` plus the mandatory review-only/no-write prompt.
  - Not allowed: fallback to another model solely because of this error.
- Spark or reviewer output that repeats the prompt, dumps long command logs, or returns non-YAML after reading files.
  - Classification: review-output failure.
  - Action: salvage concrete YAML-like findings only if independently validated; otherwise mark the role/pass `skipped_or_failed` or `partial_output`.
  - Not allowed: treat this as "no findings" or as a project defect.
- Old PRDs and historical Roadmap sections that describe retired runtime contracts.
  - Classification: historical artifact unless the current README, technical requirements, active PRD, or workflow references them as current truth.
  - Action: do not report historical drift unless it actively misleads current work.

## Codex Workflow

1. Parse scope and stage from user args. Read `Roadmap.md`, current PRD, and the API facts block from `artifacts/api-research-notes-ru.md`.
2. Build changed/related/full file list.
3. Unless `--no-spark`, run Spark scout passes in parallel where available. In Codex runtime, use subagents if available; otherwise run bounded local passes yourself. If shelling out is appropriate, use:

```bash
timeout 1200 codex exec -m gpt-5.3-codex-spark -s read-only -C "$PWD" -
```

Fallback once:

```bash
timeout 1200 codex exec -m gpt-5.4-mini -s read-only -C "$PWD" -
```

Use this fallback command only when the first command failed because the **model** was unavailable/unsupported/denied/quota-limited. Do not use it for sandbox/runtime failures or malformed review output.

If the failure is the known read-only sandbox startup error (`bwrap: loopback: Failed RTM_NEWADDR`), retry the same model with:

```bash
timeout 1200 codex exec -m gpt-5.3-codex-spark -s danger-full-access -C "$PWD" -
```

The prompt for any `danger-full-access` retry must include: `Review only. Do not edit files. Do not run write commands.`

Scout tasks:

   - file chunks: semantic bugs, edge cases, `None`, empty values, unicode, timezone, async pitfalls
   - tests: missing unhappy/boundary/idempotency/serialization coverage
   - docs: verified drift only
   - inadequate index: known false positives and duplicates
   - snippets: `file:lines` and failure scenarios for strong candidates
4. Run one bounded Codex pass per reviewer role. Use the role briefs below and keep all outputs in the YAML schema. Use `timeout 1200` for each role. Start with `-s read-only`; on the known `bwrap` startup failure retry once with the same model and `-s danger-full-access` plus the review-only/no-write prompt sentence. Use a fallback model only for explicit model/provider failures. If you cannot run a role separately, say so in the report header; do not pretend parity with the Claude command.
5. Aggregate findings: dedupe, validate Spark leads, dismiss low-confidence/speculative/pre-existing/duplicate findings, sort by severity x confidence.
6. Unless `--no-arbitration`, perform cross-CLI arbitration with Claude CLI because the orchestrator is Codex:

```bash
timeout 900 claude -p --model opus --permission-mode default --tools "" --input-format text
```

Pass the arbitration prompt via stdin. If `opus` fails because the model/provider rejects the model, quota, account access, or capacity, retry once:

```bash
timeout 900 claude -p --model sonnet --permission-mode default --tools "" --input-format text
```

If `opus` fails due to local CLI/runtime/shell problems, retry `opus` once after fixing the runtime issue instead of switching models.

`--tools ""` is required: the arbiter must not read the filesystem. Provide all snippets inline.

7. Merge Claude verdicts into the report and finalize `merge` / `do not merge`.
8. Write the report and append dismissed findings to the inadequate index.
9. Run `ps -eo pid,ppid,stat,cmd | rg 'codex exec|claude -p' || true`; stop or wait for processes that belong to this review before returning.

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
- Use the exact model name `gpt-5.3-codex-spark`; do not use older short aliases for Spark.
- Record runtime limitations explicitly: model fallback, sandbox fallback, timeout, partial role output, skipped arbitration. Keep these in the report header/limitations, not in the confirmed findings list.
- For VM API fields, trust inline API facts and authoritative repo sources, not model memory.
