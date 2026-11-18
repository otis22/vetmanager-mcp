---
name: super-review
description: Review vetmanager-mcp changes with Spark candidate passes, Astra and Kimi K3 verdicts, evidence, adequacy checks, and a Markdown report.
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

For a full super-review report, cover these briefs with bounded passes or explicit sections in the strong prompts: `code` (semantic and local defects), `architecture` (boundaries), `simplicity` (unneeded complexity), `docs` (verified drift), `security` (access and secrets), `performance-and-reliability` (timeouts and load), `observability` (safe logs and diagnostics), `tests` (missing failure paths), `test-contours` (impact map, fail-closed selection, node loss/skip, invalidation and PR/main/nightly boundaries), `product` (PRD and user-visible behavior), and `codex-blindspot` (edge cases). Assign current models by the contract below; do not infer model names from a historical role matrix. When CI or test contours are in scope, omission of `test-contours` is failed role coverage, not an empty verdict.

Aggregate candidates across roles: deduplicate, verify line references, reject speculative, low-impact, duplicate and pre-existing findings; drop non-meta findings with confidence below 0.4. Preserve all critical/high. If more than 120 remain, retain the highest severity × confidence medium/low up to 120. Record inadequacy reasons in the report or inadequate-findings memory. The strong Astra and Kimi verdicts arbitrate disputed material findings; neither a role pass nor Spark alone approves release.

## Model and runtime contract

- Stage executor: `gpt-6-sol`. Spark scout: `gpt-6-luna`, candidate-only. Strong reviewers: `gpt-6-astra` and Kimi K3, launched in parallel after Spark. Codex CLI ≥ 0.155.
- Spark uses `codex exec` with `-s danger-full-access`; its narrow review-only prompt names the object (PRD, uncommitted or committed diff), severity, JSON format, and prohibits file edits and write commands. Require `files_read`; `[]` without actual file reads is invalid. Validate important findings independently. Maximum 3 pre-gate Spark runs; if spent, record rationale before repeating the strong pair without a fourth pre-gate Spark run.
- Astra uses `codex exec` with `-s danger-full-access`, `--output-schema` and `-o` to preserve plain JSON. Validate it with `scripts/validate_review_result.py --plain`. Preserve prompt, result, stderr and metadata: model, object, reviewed SHA for diff, CLI version, start/end, process exit and validator exit.
- Kimi K3 uses `scripts/run_kimi_review.py`: `--file` for PRD/Architecture Critique, `--working-diff` before freeze, `--range` for committed diff, `--attempt N/3`; evidence stays outside the checkout. The runner accepts exactly one nonempty assistant JSON without tool calls and validates it with `scripts/validate_review_result.py --plain`. Record metadata/stream path, `cli_exit`, `outcome`, `validator_exit`, `model`, `len(result)` in `AssumptionLog.md`.
- Review prompts prohibit editing and commands. Kimi runs with `kimi -m kimi-code/k3 -p ... --output-format stream-json`, isolated `KIMI_CODE_HOME`, and an agent profile with `tools: []` and `subagents: []`. Text-only `-p` cannot satisfy the visual gate. Only explicit provider/model failure permits a documented model fallback for a scout; the strong gate still requires Astra and Kimi.

## Budgets and failures

- Astra and Kimi each have 2 valid verdict slots per gate and 3 independent infrastructure attempts. A schema-valid `findings` array, including `[]`, spends a valid slot. Empty, malformed, auth/provider/model or runtime failure is infrastructure failure: record `N/3`, do not count it as a verdict or spend a valid slot. Changing prompt/schema does not reset the count. After 3 failures for either reviewer, the gate is `blocked` and push is forbidden.
- Architecture Critique shares the PRD budget. Visual review has its own budget; Astra receives screenshots with `-i`, Kimi through a verified image-capable transport, and a Kimi `[]` needs confirmed pixels and matching image paths, sizes and SHA-256 in metadata. Screenshots must be scrubbed of PII, tokens, session identifiers and clinic data before transmission; record the check in metadata. Both strong verdicts are required for every applicable gate.
- Merge Astra and Kimi findings in `AssumptionLog.md`: separate and common findings, accepted/rejected with rationale, evidence paths and time. After valid budgets are spent, any further code fix gets a separate Spark scout and tests before push.
- Full working-diff review happens before long gates. After code freeze, committed-diff review passes **только блокеры релиза**: critical/high and any finding that breaks acceptance, new behavior correctness, security/privacy, access/fail-closed rules or a required regression guard. non-blocking findings go to Roadmap without changing the current branch. A blocker repeats focused/owning/fast and only invalidated full contours.

## Workflow

1. Read Roadmap, PRD, canonical rules and relevant source files. Choose scope and capture changed/related file list.
   For VM API findings, use verified inline API facts and source documents; do not substitute model memory for the contract.
2. Run Spark, check `files_read`, reject speculative or low-impact candidates. Run Astra and Kimi in parallel; await and validate both.
3. Dedupe findings, verify line references and severity against evidence. Do not turn infrastructure failure into `[]` or substitute a lower model for a required strong verdict.
4. Write the requested report and inadequate-findings memory. If this is a PRD, working-diff or committed diff gate, record verdicts and evidence in `AssumptionLog.md`; for committed diff, separate release blockers from Roadmap-only non-blocking findings.
5. Before returning, check that no reviewer process from this run remains. Review only: do not auto-fix findings, commit reports or push unless the user explicitly requests those actions. If a later implementation task uses this review, its release train remains the assigned `dev/roadmap-<этапы>` branch; the supervisor merges after green branch CI and full mock+real suite on the final SHA.

## Commands for runtime inspection

```bash
codex --version
scripts/run_kimi_review.py --help
scripts/validate_review_result.py --help
git branch --show-current
```
