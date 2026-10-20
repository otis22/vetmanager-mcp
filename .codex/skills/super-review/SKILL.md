---
name: super-review
description: Review vetmanager-mcp changes with Spark candidate passes, Astra and Claude Opus verdicts, evidence, adequacy checks, and a Markdown report.
---

# Super Review

Use this skill when the user asks for super-review, deep review, Spark scout review, or cross-model arbitration in this repository. `AGENTS.md` and `.cursor/rules/agent-workflow.mdc` are the current source of truth for review gates, budgets, CI and the release train.

## Scope and output

- Scopes: `changed` (default), `related`, `full`, `stage:N`.
- Exploratory report flags `--no-spark` and `--no-arbitration` may be used only when the user explicitly requests a reduced report. They never satisfy a mandatory PRD, visual or committed diff gate; a gate always requires Spark or its documented exhausted-budget rationale and both strong verdicts.
- Report: `artifacts/review/{YYYY-MM-DD}-{scope_slug}-stage-{N}.md`, unless the user requests a different destination.
- Candidate findings: YAML with `severity`, `reviewer`, `category`, `file`, `lines`, `problem`, `why_it_matters`, `suggested_fix`, `confidence`. Record dismissed recurring findings in `artifacts/review/inadequate-findings-index.md` when writing a super-review report.
- If this skill is used as a workflow gate, its final gate verdict is the schema-valid `findings` JSON from both strong reviewers. A Markdown report or YAML candidate list alone is not a gate verdict.

## Multi-role report coverage

For a full super-review report, cover these briefs with bounded passes or explicit sections in the strong prompts: `code` (semantic and local defects), `architecture` (boundaries), `simplicity` (unneeded complexity), `docs` (verified drift), `security` (access and secrets), `performance-and-reliability` (timeouts and load), `observability` (safe logs and diagnostics), `tests` (missing failure paths), `product` (PRD and user-visible behavior), and `codex-blindspot` (edge cases). Assign current models by the contract below; do not infer model names from a historical role matrix.

Aggregate candidates across roles: deduplicate, verify line references, reject speculative, low-impact, duplicate and pre-existing findings; drop non-meta findings with confidence below 0.4. Preserve all critical/high. If more than 120 remain, retain the highest severity × confidence medium/low up to 120. Record inadequacy reasons in the report or inadequate-findings memory. The strong Astra and Opus verdicts arbitrate disputed material findings; neither a role pass nor Spark alone approves release.

## Model and runtime contract

- Stage executor: `gpt-6-sol`. Spark scout: `gpt-6-luna`, candidate-only. Strong reviewers: `gpt-6-astra` and Claude Opus, launched in parallel after Spark. Codex CLI ≥ 0.155.
- Spark uses `codex exec` with `-s danger-full-access`; its narrow review-only prompt names the object (PRD, uncommitted or committed diff), severity, JSON format, and prohibits file edits and write commands. Require `files_read`; `[]` without actual file reads is invalid. Validate important findings independently. Maximum 3 pre-gate Spark runs; if spent, record rationale before repeating the strong pair without a fourth pre-gate Spark run.
- Astra uses `codex exec` with `-s danger-full-access`, `--output-schema` and `-o` to preserve plain JSON. Validate it with `scripts/validate_review_result.py --plain`. Preserve prompt, result, stderr and metadata: model, object, reviewed SHA for diff, CLI version, start/end, process exit and validator exit.
- Claude Opus uses `scripts/run_claude_review.sh`: `--file` for PRD/Architecture Critique, `--range` for diff, `--attempt N/3`; evidence stays outside the checkout. The runner validates its JSON envelope with `scripts/validate_review_result.py`. A valid result has `is_error=false` and nonempty schema-valid `.result`; `stop_reason` does not determine validity. Record envelope path, `subtype`, `stop_reason`, `output_tokens`, `thinking_tokens`, `len(result)` in `AssumptionLog.md`.
- Review prompts prohibit editing and commands. Opus prompt deadline is 600 seconds with 1200-second shell timeout; disable tools/MCP for inline review. Only explicit provider/model failure permits a documented model fallback for a scout; the strong gate still requires Astra and Opus.

## Budgets and failures

- Astra and Opus each have 2 valid verdict slots per gate and 3 independent infrastructure attempts. A schema-valid `findings` array, including `[]`, spends a valid slot. Empty, malformed, auth/provider/model or runtime failure is infrastructure failure: record `N/3`, do not count it as a verdict or spend a valid slot. Changing prompt/schema does not reset the count. After 3 failures for either reviewer, the gate is `blocked` and push is forbidden.
- Architecture Critique shares the PRD budget. Visual review has its own budget; Astra receives screenshots with `-i`, Opus with `--image`, and an Opus `[]` needs matching image paths, sizes and SHA-256 in metadata. Both strong verdicts are required for every applicable gate.
- Merge Astra and Opus findings in `AssumptionLog.md`: separate and common findings, accepted/rejected with rationale, evidence paths and time. Unresolved critical/high block release. After valid budgets are spent, any further code fix gets a separate Spark scout and tests before push.

## Workflow

1. Read Roadmap, PRD, canonical rules and relevant source files. Choose scope and capture changed/related file list.
2. Run Spark, check `files_read`, reject speculative or low-impact candidates. Run Astra and Opus in parallel; await and validate both.
3. Dedupe findings, verify line references and severity against evidence. Do not turn infrastructure failure into `[]` or substitute a lower model for a required strong verdict.
4. Write the requested report and inadequate-findings memory. If this is a PRD or committed diff gate, record verdicts and evidence in `AssumptionLog.md`.
5. For code release, commit and push only in the assigned `dev/roadmap-<этапы>` branch after checks. The supervisor merges to main after green branch CI and full mock+real suite on its final SHA.

## Commands for runtime inspection

```bash
codex --version
scripts/run_claude_review.sh --help
scripts/validate_review_result.py --help
git branch --show-current
```
