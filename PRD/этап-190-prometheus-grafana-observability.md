# Stage 190. Prometheus and Grafana production observability

## Контекст

`/metrics` уже отдаёт Prometheus-compatible counters, но это process-local
snapshot. Без Prometheus/Grafana owner видит только ad-hoc product metrics и не
может смотреть историю top tools, error rate, upstream failures, activation.

## Цель

Добавить production Prometheus/Grafana contour with persistent storage,
local-only access by default, and pre-provisioned dashboard. Персональные данные
не должны попадать в metrics labels/dashboard.

## Архитектурное решение

Проблема: process-local metrics reset on restart; ad-hoc script cannot show
time-series.

Ограничения:
- `/metrics` is already restricted by nginx to localhost externally;
- `/metrics` may also be app-protected by `METRICS_AUTH_TOKEN`; Prometheus must
  use a bearer-token file when that env is set and must not log the token;
- docker-compose production profile is the deployment unit;
- user requires Grafana either through nginx basic auth or equivalent safe
  access. For v1, bind Grafana/Prometheus to `127.0.0.1` and document SSH tunnel
  or nginx basic auth as the only public exposure path;
- Grafana must not use default credentials. Admin user/password come from env
  (`GRAFANA_ADMIN_USER`, `GRAFANA_ADMIN_PASSWORD`), sign-up and anonymous access
  are disabled. Production deploy fails fast if the password is empty/default.
  Secret delivery follows the existing `.env`/deploy-secret contract: no repo
  commit, no echo, restrictive server permissions, and static tests for the
  guard;
- no PII labels: existing metrics use endpoint/method/outcome/status/event, not
  raw account emails or clinic payload.

Варианты:
- hosted Prometheus/Grafana: less repo work, more external dependency;
- add compose services: reproducible and owner-controlled;
- expose Grafana publicly now: convenient but risky without basic auth secrets.

Выбор: add compose services with localhost-only ports and provisioning. No
public Grafana by default. If nginx exposure is needed, docs require basic auth.

Инварианты:
- application image and `/metrics` contract do not change for existing clients;
- Prometheus scrapes `mcp:8000/metrics` inside Docker network;
- Grafana does not expose secret env values or raw clinic data;
- Prometheus retention is capped by time/size to avoid unbounded disk growth;
- both observability containers have explicit CPU/memory limits;
- named Docker volumes are preferred for Prometheus/Grafana data so first
  deploy does not depend on host-path ownership; runtime checks still verify
  containers are running;
- deploy remains rollbackable by stopping observability services.

Rollback: remove/disable services or run `docker compose --profile production
stop prometheus grafana`; app service remains independent.

Architecture Critique: required because this changes production infrastructure
and observability access.

## Scope

1. Compose services `prometheus` and `grafana` under production profile.
2. Persistent volumes.
3. Prometheus config scraping `mcp:8000/metrics`.
4. Grafana datasource and dashboard provisioning.
5. README and smoke/deploy docs updates.
6. Fold product-metrics command top-5 tool-call addition into this stage.
7. Deploy script starts Prometheus/Grafana after the application is healthy.
   Observability runtime checks run after app smoke as warnings/non-fatal gates
   so a Grafana/Prometheus issue does not roll back an otherwise healthy app.

## Out of scope

- Alertmanager.
- Public Grafana without auth.
- Adding PII labels or per-account dashboard panels.

## Acceptance Criteria

1. `docker compose --profile production config` validates.
2. Prometheus config file is present and scrapes `mcp:8000/metrics`.
3. Grafana provisioning includes Prometheus datasource and dashboard panels for:
   top tool calls, call rate, error rate, upstream statuses, business events,
   activation telemetry.
4. Ports are bound to `127.0.0.1`, not `0.0.0.0`.
5. README explains access via SSH tunnel or nginx basic auth only.
6. Product metrics command includes top-5 tool-call counters and process-local
   period.
7. Grafana admin password is required and cannot be `admin`; anonymous access
   and sign-up are disabled. `deploy_server.sh` rejects empty/default Grafana
   password values before starting Grafana.
8. Prometheus has explicit TSDB retention time/size, and Prometheus plus Grafana
   both have container resource limits.
9. Static tests verify dashboard/Prometheus queries use only approved low-cardinality
   labels and contain no account/email/clinic/customer labels.
10. Deploy/smoke checks verify Prometheus target `mcp:8000/metrics` is up and
    Grafana provisioning exposes the Prometheus datasource/dashboard; these
    checks report warnings, not app-deploy failures.
11. Prometheus scrape config includes bearer-token-file support for
    `METRICS_AUTH_TOKEN` and tests verify the config does not inline secrets.
12. Docker volumes for observability data are named volumes, and deploy checks
    report container start/permission failures distinctly.

## Tests

- Static tests for compose service definitions, localhost-only bindings and
  provisioning files.
- Static tests for Grafana security env, Prometheus retention/resource limits,
  and allowed label schema in dashboard/prometheus expressions.
- Smoke/deploy-script tests for observability startup and runtime checks.
- Static tests for Prometheus bearer-token-file config when metrics auth is
  enabled and for deploy guards rejecting default Grafana credentials.
- Existing Prometheus metrics tests remain green.

## Rollout

Deploy normally. Deploy script must first keep the existing hard gates for
PostgreSQL, migrations, MCP health, pepper, and app smoke. Then it starts
`prometheus` and `grafana`, verifies containers are running, Prometheus target
`mcp:8000/metrics` is up, Grafana datasource/dashboard provisioning is present,
and Grafana login page is reachable via localhost/SSH tunnel only. Failures in
these observability-only checks are logged as warnings for operator follow-up,
not as app-deploy rollback triggers.
