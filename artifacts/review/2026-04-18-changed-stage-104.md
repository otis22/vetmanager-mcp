# Super-review: vetmanager-mcp stage 103a/103c/103d (auth / vm_transport / resources splits)
_Дата: 2026-04-18_
_Scope: changed (47 files, last 10 commits c87bfa8..15dcd0a)_
_Reviewers: code, architecture, docs, security, performance-and-reliability, observability, tests, product, codex-blindspot, workflow-check (10)_
_Aggregator: Opus 4.7_
_Codex arbitration: GPT-5.4 — confirmed 10/10 top findings; promoted F4 to blocker_

## Verdict

**Do not merge** — Codex arbitration promoted F4 (breaker amplification + retry bypasses breaker re-check) из high к blocker. Два блокера:

- **B1 (orig blocker)**: Roadmap.md:1469/1492 называет 103.3/103.4 deferred, тогда как 103a (commit 7185ac5), 103c (dffe240), 103d (ce3dd67) shipped. Тривиальный fix документации, 5 минут.
- **B2 (promoted from high)**: vm_transport/breaker.py + vetmanager_client.py:344-414 — retry loop инкрементирует breaker failure per-attempt (не per-call) и не re-check'ит breaker между retry; один падающий GET с max_retries=3 даёт 4 breaker failures; на dead upstream worst-case 80s. Breaker защитный механизм работает как amplifier.

Остальные 8 high findings (CancelledError wedge, pool race, layering violation, zero-filter privacy, admission code quality × 2, AssumptionLog section missing, tech-requirements drift) — merge-with-followup качество; требуют отдельных hotfix-стадий 105.x.

Total: 130 raw findings → 22 high (promoted +1 blocker) + 48 medium + 55 low + adequacy-filtered.

## Blockers

### B1. Roadmap.md статус 103.3/103.4 deferred vs shipped
- **file**: Roadmap.md:1469, 1492
- **severity**: blocker, confidence 0.97 (docs) — Codex: confirm, keep
- **problem**: блок "stage 103 status" утверждает, что 103.3/103.4 отложены, но коммит `dffe240` (103c) и `ce3dd67` (103d) уже в main; 1469 и 1492 противоречивы.
- **fix**: обновить 1469/1492 в соответствии с git history; добавить `## Этап 103a / 103c / 103d` заголовки.

### B2. Breaker failure amplification + retry bypasses breaker re-check (promoted)
- **file**: vetmanager_client.py:344-414, vm_transport/breaker.py
- **severity**: blocker (Codex raised from high 0.75)
- **problem**: retry loop инкрементирует `_breaker_record_failure` per-attempt (stage 99.1 intentional), но также не re-check'ит `_check_breaker_allows` перед каждым retry; один failing GET с MAX_RETRIES_READ=3 даёт 4 breaker failure, опуская circuit после 1 "logical" запроса вместо 4 (при threshold=5). Worst-case read timeout 20s × 4 = 80s на dead upstream.
- **fix**: одно "внешнее" MCP-обращение = одно breaker observation, не retry; re-check `_check_breaker_allows` перед каждым retry; при OPEN breaker — сразу raise `VetmanagerUpstreamUnavailable` без дальнейших retry. Либо вернуть MAX_RETRIES_READ=1 как временное смягчение.
- **Codex**: *"inflated breaker counts and continued calls after the circuit should stop them. On a dead upstream this produces both incorrect breaker state and excessive latency."*

## Top-10 findings (Codex arbitration validated)

| # | Severity | Confidence | File:lines | Problem | Codex verdict | Fix summary |
|---|----------|-----------|------------|---------|---------------|-------------|
| F1 | **blocker** | 0.97 | Roadmap.md:1469,1492 | 103.3/103.4 deferred markers, но shipped | confirm, keep | Update status + add 103a/c/d headers |
| F2 | high | 0.85 | vetmanager_client.py:261-400 | CancelledError wedges HALF_OPEN probe_in_flight | confirm, keep | try/finally around retry loop, clear probe_in_flight on exit |
| F3 | high | 0.85 | vm_transport/pool.py:49-69 | Race concurrent first-init → orphan AsyncClient | confirm, keep | Use existing `_shared_http_client_lock` with double-check + close loser |
| F4 | **blocker** | 0.75 | vetmanager_client.py:344-414 | Breaker amplification 4x + no re-check between retries | **confirm, raise_to:blocker** | One logical call = one breaker failure; re-check breaker per retry; abort on OPEN |
| F5 | high | 0.85 | resources/*.py | Layering violation: imports from tools/ | confirm, keep | Move `gather_sections` + `ACTIVE_ADMISSION_STATUSES` to lower-level module |
| F6 | high | 0.78 | filters.py:188-196 | Zero-filter drops client_id=0 etc — privacy risk | confirm, keep | Remove zero-filter; only skip None/"" |
| F7 | medium | 0.95 | tools/admission.py:299 | `type` builtin shadow | confirm, **lower_to:medium** | Rename to `admission_type` |
| F8 | medium | 0.95 | tools/admission.py:169-183,236-251 | 24-line duplicated unwrap block | confirm, **lower_to:medium** | Extract `_normalize_admission_list_response(resp)` |
| F9 | high | 0.95 | AssumptionLog.md | No dedicated `## Этап 103a/c/d` sections | confirm, keep | Add 3 sections; CI script needs exact headings |
| F10 | high | 0.97 | technical-requirements-ru.md:116-128,219-244 | Structure section outdated; bearer_auth shown as monolith | confirm, keep | Rewrite structure + module descriptions |

Codex raised F4 to blocker; lowered F7/F8 to medium (code quality, not correctness).

## High (remaining after arbitration)

- **H11** auth/rate_limit.py:64-94 — check_or_raise: no log inside limiter (obs, 0.85). Silent 429s outside bearer-specific caller.
- **H12** web_routes_account.py:157-234 — token issuance/revoke: no structured log (obs, 0.90). Audit trail relies on DB only.
- **H13** web_routes_auth.py:51-128 — account register: no log/metric (obs, 0.88). Can't alert on spike.
- **H14** tools/admission.py:79,146,212 — inline datetime imports (code, 0.95). Repeated 3×.
- **H15** tools/medical_card.py:35,77 — inline filters imports (code, 0.92).
- **H16** tests/runtime_factories.py:70-79 — private attr assignment fragile; any rename breaks majority of integration tests (tests, 0.90).
- **H17** tests/test_stage102:50-60 — manual asyncio.sleep patch instead of monkeypatch (tests, 0.85). Race risk.
- **H18** tests/test_stage91:292-308 — breaker state private field access (tests, 0.88).
- **H19** tests/test_stage87:32-34 — PROMPTS_SRC dead module-level read — FileNotFoundError при переименовании prompts.py (tests, 0.95).
- **H20** Roadmap.md:902 — obsolete prod URL 342915.simplecloud.ru (docs, 0.95). Заменён на vetmanager-mcp.vromanichev.ru в этапе 89.2.
- **H21** vetmanager_client.py:81-96 — _shared_http_client dead sentinel + stale state helper (code/arch/perf, 0.90). Helper возвращает `{exists: False, closed: True}` даже когда есть N активных per-loop clients.

## Medium (grouped by theme)

**Inline imports (code maintainability):** tools/_aggregation.py:63-67 + :102 (0.88); tools/client.py:363-364 (0.80); tools/medical_card.py:136 nested ternary (0.90).

**Breaker/BC fragility:** auth/rate_limit.py sys.modules shim patch fragile (codex 0.65); dual sync mechanism + runtime lookup (arch 0.65); DomainBreaker.lock bound to creating loop — cross-loop RuntimeError risk (perf 0.60); `_shared_http_clients` dict not WeakKeyDictionary → loop id reuse (perf 0.70).

**Observability gaps for new paths:** aggregator_partial log missing correlation_id (obs 0.80); section_errors.message может включать masked API key fragment (obs 0.70); graceful shutdown unstructured log (obs 0.82); no tool_name label → endpoint collision (obs 0.78); retry attempts silent at info (obs 0.75); web_login_succeeded no correlation (obs 0.72); host_resolver.py no latency metric for billing_api (obs 0.88).

**Resources gateway architectural issues:** shared VetmanagerClient across 4 sections, pace_lock serializes (perf/product 0.75-0.80); Vaccinations limit=100 silent truncation affects last_vaccination_date (perf 0.70); last/next_vaccination_date derivation wrong for multi-vaccine schedules (codex 0.70); no vc-injection for testing (arch 0.55); json.dumps Filter pattern duplicated 5+ times (code/arch 0.75-0.78).

**Legacy code в vetmanager_client.py:** 30+ BC re-exports bloat (arch 0.75) / double API surface (product 0.70); god-function _request 174 LOC (arch 0.70); TTL bypasses ttl_for_entity (arch/perf 0.65-0.70); WHAT-not-WHY comment (code 0.75); 3-copy _env_int/_env_float (arch 0.80).

**Docs drift:** AssumptionLog duplicate 103.1 entry (docs 0.88); AssumptionLog "Не сделано" block not marked obsolete (docs 0.92); Roadmap 1469/1492 contradictory 103.3 status (docs 0.96) — related to B1; Roadmap no ## Этап 103a/c/d headers (docs 0.90); tech-requirements 130-142 bearer_auth.py monolithic (docs 0.93); tech-requirements 187-193 build_list_query_params location outdated (docs 0.92).

**Security (non-critical):** auth/bearer.py:162-166 disabled-token branch skips rate-limit + audit log — DoS amplification (sec 0.70).

**Test brittleness:** test_request_auth.py patches shim not canonical (tests 0.80); test_stage91 _shared_http_clients re-export (tests 0.75); test_bearer_rate_limit no observed-through-auth.bearer test (tests 0.70); test_stage91 _parse_retry_after missing boundaries (tests 0.85); test_stage88 no vm_upstream_network_error parallel test (tests 0.90); conftest.py no assert dict identity after re-export (tests 0.88); test_stage91:341-355 asserts magic numbers (tests 0.72); test_client_multitenancy test_wait_50ms flaky (tests 0.92).

**Product/scope:** Roadmap deleted 37 backlog items → tech-debt visibility loss (product 0.85); Roadmap 93/94 "done (focused subset)" masks stop'нутые подзадачи (product 0.80); no post-prod observation plan (product 0.70); 103a/c/d single-session violates ≤150 LOC rule (product 0.65).

## Low (55 compact items)

Full low list — see raw findings per reviewer. Key clusters: REQUEST_TIMEOUT dead constant; duplicated Stage-83 comments; storage_models user_agent unbounded; read timeout × retries = 95s worst case; auth_successed INFO signal/noise; HALF_OPEN→CLOSED recovery no log; integration errors no log; test_stage87 tuple structure assumption; test_stage93 IN [42]/[None] boundaries; test_stage102 upstream_unavailable error_type; PRD aspirational MFA/SSO; landing "Руководитель" persona; vm_transport/retry dead `if parsed_dt is None`; vm_transport/breaker asyncio.Lock at module import; email.utils.parsedate_to_datetime slow.

## Dismissed

### Speculative (confidence < 0.4)
- auth/bearer.py token lookup not constant-time (sec, 0.30) — theoretical timing oracle, no exploit path
- auth/bearer.py rate-limit retry_after timing oracle (sec, 0.35) — speculative
- auth/rate_limit.py reset public no env-guard (sec, 0.45) — scope creep без production misuse
- email.utils.parsedate_to_datetime slow (perf nit, 0.30) — micro-opt nit

### Pre-existing / out of scope
- 22 × workflow-check PRDs lacking `## Цель` section (stages 5, 65, 66, 89, 94, 95, 99, etc.) — все retroactive для already-production stages; housekeeping, не relevant to 103a/c/d diff

### Borderline (tracked, not blocking)
- resources no vc-injection for testing (arch, 0.55) — low ROI without concrete test pain
- 103a/c/d single-session violates ≤150 LOC workflow rule (product, 0.65) — post-hoc policy; code shipped
- Roadmap deleted 37 backlog items (product, 0.85) — conscious cleanup commit 15dcd0a
- Roadmap 93/94 masked as "done (focused subset)" (product, 0.80) — orchestrator decision

## Systemic observations (Codex)

> *"The dominant pattern is split-related drift: code moved successfully, but the supporting architecture contracts (Roadmap, AssumptionLog, technical requirements, layering boundaries) were not updated to the same standard. The most serious runtime risk is in transport resilience, where cancellation, breaker accounting, and retry semantics are not aligned; that is more important than the documentation defects. A second pattern is unsafe "helpful" abstraction behavior, such as silently dropping zero-valued filters, which converts caller mistakes into broad queries instead of explicit failures. I would prioritize F4, F2, F3, then the workflow/documentation fixes (F1, F9, F10), and leave F7/F8 as cleanup unless they are touched by adjacent work."*

## Adequacy scorecard per reviewer

| Reviewer | Total | Adequate | Dismissed | Borderline | Adequacy rate |
|----------|-------|----------|-----------|------------|---------------|
| code | 15 | 15 | 0 | 0 | 100% |
| architecture | 12 | 11 | 0 | 1 | 92% |
| docs | 13 | 13 | 0 | 0 | 100% |
| security | 9 | 5 | 3 | 0 | 56% |
| performance-and-reliability | 15 | 13 | 2 | 0 | 87% |
| observability | 13 | 13 | 0 | 0 | 100% |
| tests | 15 | 15 | 0 | 0 | 100% |
| product | 10 | 6 | 0 | 3 | 60% + 30% borderline |
| codex-blindspot | 6 | 6 | 0 | 0 | 100% |
| workflow-check | 22 | 0 | 22 (pre-existing) | 0 | 0% — all about legacy PRDs |

## Suggested Roadmap-delta

**Stage 105 (blocker resolution, must ship before next release):**
- 105.1: fix B1 (Roadmap doc sync) + B2 (breaker amplification + retry re-check). Testable via new unit test `test_breaker_one_failure_per_logical_call`.

**Stage 106 (high-severity reliability hardening):**
- 106.1: F2 CancelledError try/finally wrapping
- 106.2: F3 pool race — use existing lock
- 106.3: F5 layering violation — extract shared helpers
- 106.4: F6 zero-filter removal + test for client_id=0
- 106.5: F9 AssumptionLog section headers
- 106.6: F10 tech-requirements rewrite

**Stage 107 (observability gaps):**
- 107.1-3: H11/H12/H13 auth-path metrics + logs
- 107.4: aggregator_partial correlation_id + sanitization
- 107.5: tool_name metric label

**Stage 108 (code quality):**
- tools/admission.py cleanup (F7/F8/H14 + duplicate Stage-83 comments)
- Inline imports sweep
- vetmanager_client.py dead sentinel removal

**Stage 109 (test brittleness):**
- runtime_factories + private attr coupling
- monkeypatch migration in test_stage102
- boundary + unhappy-path coverage

---

## Inadequate findings index update

See `artifacts/review/inadequate-findings-index.md` for cumulative tracking. Block for this review:

```markdown
## 2026-04-18 — stage 103a/103c/103d review

Source: artifacts/review/2026-04-18-changed-stage-104.md

### Speculative (confidence < 0.4 or no concrete exploit path)
- auth/bearer.py token lookup not constant-time (security, conf 0.30)
- auth/bearer.py rate-limit retry_after timing oracle (security, 0.35)
- auth/rate_limit.py reset public no env-guard (security, 0.45)
- email.utils.parsedate_to_datetime slow (perf nit, 0.30)

### Pre-existing / out of scope
- 22 × workflow-check PRDs lacking `## Цель` (retroactive, stages 5/65/66/89/94/95/99)
- retry parse_retry_after email date slow (perf, 0.30)

### Borderline (orchestrator decision)
- resources no vc-injection (architecture, 0.55)
- 103a/c/d single-session violates ≤150 LOC rule (product, 0.65)
- Roadmap deleted 37 backlog items (product, 0.85)
- Roadmap 93/94 "done (focused subset)" convention (product, 0.80)
```
