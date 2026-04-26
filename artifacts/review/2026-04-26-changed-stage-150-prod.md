# Super Review — changed-stage-150-prod — 2026-04-26

## Scope

- Commits reviewed:
  - `def9427` — Stage 150: add agent feedback PII guardrails
  - `1a1e547` — Fix prod deploy feedback pepper secret
- Focus: production deploy correctness, secret handling, feedback PII guardrails, migration safety, docs drift.

## Runtime Notes

- Spark read-only pass hit the known Codex `bwrap` sandbox/runtime failure before useful local review output.
- Retried the same `gpt-5.3-codex-spark` model with `danger-full-access` and explicit review-only/no-write prompt.
- `gpt-5.5` and `gpt-5.4` read-only validation passes also hit sandbox/runtime startup failure; both were retried with the same model and review-only/no-write prompt.
- Claude Opus arbitration ran with `--tools ""`; all context was provided inline.
- No files were edited by reviewer subprocesses.

## Findings

```yaml
- severity: high
  reviewer: claude-opus-arbitrated
  category: security
  file: scripts/deploy_server.sh
  lines: "26,40-46"
  problem: >
    FEEDBACK_FINGERPRINT_PEPPER is passed as an SSH/remote bash positional
    argument and then interpolated into a sed replacement.
  why_it_matters: >
    The pepper is the HMAC key that makes feedback fingerprints non-reversible.
    Passing it via argv can expose it through process listings, audit/process
    accounting, or diagnostics on the runner/remote host during deploy. The sed
    replacement is also not metachar-safe: values containing characters such as
    &, |, backslash, slash, or newline can corrupt the .env update and either
    break startup or silently write the wrong value.
  suggested_fix: >
    Stop passing the pepper as a positional argument to bash -s. Transfer it over
    a non-argv channel such as stdin or a temporary 0600 file on the remote host,
    read it once, and remove the temp file after updating .env. Replace sed
    substitution with a quoting-safe writer, for example a small Python env-file
    updater that reads the pepper from stdin/file rather than argv.
  confidence: 0.86

- severity: medium
  reviewer: claude-opus-arbitrated
  category: docs
  file: README.md
  lines: "371-377"
  problem: >
    The Deploy Prod section lists required GitHub Secrets but omits
    FEEDBACK_FINGERPRINT_PEPPER, while the workflow now validates it and the
    PostgreSQL runtime requires it.
  why_it_matters: >
    Operators following the documented required secret list will configure an
    incomplete production deploy and hit a hard failure at the workflow
    validation step or runtime startup.
  suggested_fix: >
    Add FEEDBACK_FINGERPRINT_PEPPER to the required GitHub Secrets list and mark
    it mandatory for production/PostgreSQL feedback fingerprints. Cross-reference
    the Agent feedback section that explains the HMAC fingerprint requirement.
  confidence: 0.99

- severity: medium
  reviewer: claude-opus-arbitrated
  category: deploy
  file: scripts/sync_and_deploy_server.sh
  lines: "29-31"
  problem: >
    The documented private-repo rsync deploy path calls deploy_server.sh without
    forwarding FEEDBACK_FINGERPRINT_PEPPER.
  why_it_matters: >
    The GitHub Actions deploy path was updated, but the rsync deploy path can
    still leave remote .env missing or stale on fresh hosts or pepper rotation.
    With PostgreSQL this can fail startup; with an old value it can keep
    fingerprint matching on the wrong HMAC key.
  suggested_fix: >
    Forward FEEDBACK_FINGERPRINT_PEPPER from sync_and_deploy_server.sh using the
    same safer transport chosen for deploy_server.sh, and document/export it in
    the private-repo rsync deploy instructions.
  confidence: 0.97
```

## Arbitration Summary

Claude Opus confirmed all three findings.

- F1 kept as high: the current deploy pattern reused a low-sensitivity
  positional-argument approach for a production HMAC key.
- F2 kept as medium: documentation and workflow validation are misaligned.
- F3 kept as medium: the alternate deploy entry point was not updated for the new
  production feedback fingerprint requirement.

## Merge Verdict

Do not treat the deploy hardening as complete until F1 is fixed. F2 and F3 should
be fixed in the same stage because they are low-risk documentation/wrapper
alignment changes around the same secret contract.
