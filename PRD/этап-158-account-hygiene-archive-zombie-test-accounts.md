# Этап 158. Account hygiene — archive zombie test accounts

**Дата:** 2026-05-03
**Статус:** done

## Цель

Убрать zombie/test accounts из продуктовых метрик без hard delete и без потери audit trail. Zombie account — это старый аккаунт без признаков реального использования и без активного Vetmanager-подключения. После архивации такие аккаунты не должны попадать в `total`, `dead`, `dead_list`, `no_tokens`, `no_active_connection` и top-N product metrics по умолчанию, но должны оставаться восстановимыми.

## Контекст

Production snapshot 2026-05-02 показал несколько dead accounts, которые выглядят как тестовые/заброшенные и искажают adoption/product metrics. В артефакты проекта нельзя записывать email или другие персональные данные; Stage 158 фиксирует только агрегаты, masked output и non-secret DB ids при необходимости.

## Проверенные факты

- `Account` сейчас имеет поля `id`, `email`, `password_hash`, `status`, `created_at`, `updated_at`.
- `ACCOUNT_STATUSES = ("active",)`, а CHECK constraint `ck_accounts_status` сейчас допускает только `status IN ('active')`.
- У аккаунтов есть FK-зависимости: `vetmanager_connections`, `service_bearer_tokens`, `agent_feedback_reports`, `known_issue_match_events`. Hard delete не нужен и опасен для audit trail.
- `scripts/product_metrics_report.py` считает:
  - total/new через `_count_accounts`;
  - live через `TokenUsageStat.last_used_at`;
  - dead через `Account.created_at < now-30d` и max `TokenUsageStat.last_used_at`;
  - no tokens/no active connection через joins от `Account`;
  - top accounts по `TokenUsageStat.request_count`;
  - dead list выводит masked email через `_mask_email`.
- Product metrics script уже read-only и предназначен для prod запуска через `docker compose exec -T mcp python scripts/product_metrics_report.py`.
- Миграции используют Alembic, для SQLite-совместимых ALTER применяется `op.batch_alter_table`.
- Canonical auth/request audit event names live in `auth_audit.py` and include `token_` prefix:
  `token_auth_succeeded`, `token_auth_rate_limited`,
  `token_auth_failed_revoked`, `token_auth_failed_expired`,
  `token_auth_failed_disabled`, `token_auth_failed_ip_denied`,
  `token_auth_failed_no_scopes`, `token_auth_failed_no_connection`.

## Scope

1. Добавить soft-archive поле в `accounts`:
   - `archived_at: datetime | None`;
   - `archived_reason: str | None` не добавлять в Stage 158, чтобы не хранить потенциально чувствительные операторские комментарии;
   - `status` не расширять, чтобы не менять auth semantics и существующий CHECK constraint.
2. Добавить CLI:
   - `scripts/archive_zombie_accounts.py --dry-run`;
   - `scripts/archive_zombie_accounts.py --apply`;
   - `scripts/archive_zombie_accounts.py restore --account-id <id> --dry-run|--apply`;
   - machine-readable line output без email: `status=ok matched=N archived=N unchanged=N skipped=N candidate_ids=1,2,3 archived_ids=4,5`;
   - ids считаются non-PII для операторского восстановления; raw email/domain/token/hash не выводить.
3. Criteria для archive:
   - `Account.archived_at IS NULL`;
   - `Account.created_at < now - 30 days`;
   - нет активного Vetmanager connection (`VetmanagerConnection.status == "active"`);
   - нет request history за всё время:
     - нет `TokenUsageStat` с `request_count > 0` или `last_used_at IS NOT NULL`;
     - нет `TokenUsageLog` auth/request events по токенам аккаунта;
     - lifecycle token events (`token_created`, `token_revoked`, `token_expired`) не считаются request history, иначе любой аккаунт с выпущенным токеном никогда не станет candidate;
   - нет engagement history в `agent_feedback_reports` и `known_issue_match_events` по `account_id`;
   - не архивировать аккаунты с любым request history, включая failed-only auth history и старые successful requests;
   - не архивировать аккаунты с feedback-only / known-issue-match-only history;
   - не архивировать аккаунты, созданные недавно;
   - не архивировать уже archived accounts.
4. Restore:
   - `restore --account-id` снимает `archived_at`;
   - не меняет токены, connections, audit logs, feedback rows;
   - работает idempotent: active account remains unchanged;
   - output uses the same no-email/no-domain/no-token rule as archive;
   - restore output/exit contract:
     - restored archived account: `status=ok restored=1 already_active=0 not_found=0 account_id=<id>`, exit 0;
     - dry-run for archived account: `status=ok restored=0 would_restore=1 already_active=0 not_found=0 account_id=<id>`, exit 0;
     - already active/non-archived account: `status=ok restored=0 already_active=1 not_found=0 account_id=<id>`, exit 0;
     - unknown account id: `status=not_found restored=0 already_active=0 not_found=1 account_id=<id>`, exit 1.
5. Product metrics:
   - по умолчанию исключить archived accounts из `total`, `new_*`, `live_7d`, `dead_30d`, `dead_list`, `no_tokens`, `no_active_connection`, top-N;
   - token inventory and event counters (`tokens.*`, `requests.total_*`, `failures.by_event_*`) intentionally remain global operational signal, because Stage 158 does not revoke archived tokens or change auth behavior;
   - добавить `archived` count отдельной строкой;
   - JSON output включает `accounts.archived`;
   - email в reports остаётся masked.
6. Tests:
   - migration round-trip добавляет nullable fields and preserves existing rows;
   - archive criteria: old/no-connection/no-usage архивируется;
   - no archive when active connection exists;
   - no archive when any request history exists, including failed-only auth `TokenUsageLog` history;
   - no archive when feedback-only or match-event-only history exists;
   - no archive for young account;
   - dry-run does not mutate;
   - apply idempotent;
   - restore clears `archived_at`;
   - restore success/already-active/unknown-id output contains no raw email/PII;
   - product metrics excludes archived and reports `archived` count;
   - CLI/help/static privacy test: no raw email in archive script output.

## Out of Scope

- Hard delete accounts.
- Deleting/revoking tokens as part of archive.
- Web UI for archived accounts.
- Auth behavior changes for archived accounts. Stage 158 is metrics hygiene only; auth denial for archived accounts would be a separate security/lifecycle stage.
- Storing free-form archive reasons.
- Writing production personal data into repo artifacts.
- Durable account lifecycle audit (who archived/restored and why). Stage 158 preserves existing auth/feedback audit trail and stores current archive state in `accounts.archived_at`; it does not add an append-only account lifecycle table. That trade-off keeps the stage small and avoids storing operator free-form comments that may contain PII.

## Дизайн

### Migration

Add migration `20260503_000014_account_archival.py`:

- `upgrade`: use `op.batch_alter_table("accounts")` to add nullable `archived_at` and create `ix_accounts_archived_at`;
- `downgrade`: use `op.batch_alter_table("accounts")` to drop `ix_accounts_archived_at`, then drop `archived_at`.

`Account` model adds:

```python
__table_args__ = (
    CheckConstraint(...),
    Index("ix_accounts_archived_at", "archived_at"),
)
archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

No status CHECK changes.

### Archive Criteria Query

Use aggregate query grouped by account id:

- outer join `VetmanagerConnection` filtered to active connection count;
- outer join `ServiceBearerToken`, `TokenUsageStat`, `TokenUsageLog`, `AgentFeedbackReport`, `KnownIssueMatchEvent`;
- detect request/engagement history with `EXISTS` subqueries or aggregates over usage stats, auth/request logs, feedback reports and match events;
- `--apply` must re-evaluate the full archive predicate at write time, not update a stale dry-run candidate list. Preferred shape: one `UPDATE accounts SET archived_at = now WHERE id IN (<initial candidate ids>) AND archived_at IS NULL AND <full criteria> RETURNING id` or equivalent transactionally-safe query. `archived_ids` must come from the guarded write result, not from a post-update `archived_at IS NOT NULL` scan. `candidate_ids` are the initial scan result; new candidates that appear after the scan wait for the next run.
- candidates where:
  - `archived_at IS NULL`;
  - `created_at < cutoff`;
  - `active_connection_count == 0`;
  - no `TokenUsageStat` row with `request_count > 0` or `last_used_at IS NOT NULL`;
  - no `TokenUsageLog` row with event type in request-history events:
    `token_auth_succeeded`, `token_auth_rate_limited`,
    `token_auth_failed_revoked`, `token_auth_failed_expired`,
    `token_auth_failed_disabled`, `token_auth_failed_ip_denied`,
    `token_auth_failed_no_scopes`, `token_auth_failed_no_connection`;
  - no `AgentFeedbackReport.account_id == account.id`;
  - no `KnownIssueMatchEvent.account_id == account.id`.

Return only DB ids and counts. Do not print emails.

### Product Metrics Filter

Add shared helper/predicate in `scripts/product_metrics_report.py`:

- `_active_account_clause() -> Account.archived_at.is_(None)`;
- apply it to every account-derived query;
- archived count uses `Account.archived_at.isnot(None)`.

Top accounts joins must filter `Account.archived_at.is_(None)` before grouping. Token counters and request/failure event counters stay global because archived tokens are still authenticatable in Stage 158; hiding their auth events would weaken incident-triage signal. A future lifecycle/security stage may revoke or deny archived accounts, but this stage does not.

## Acceptance Criteria

1. `alembic upgrade head` creates nullable `accounts.archived_at`.
2. `archive_zombie_accounts.py --dry-run` reports candidate counts and does not mutate DB.
3. `archive_zombie_accounts.py --apply` archives only old accounts with no active connection and no request/engagement history, and re-evaluates the full predicate at write time.
4. Restore command clears `archived_at` for a specific account id and is idempotent.
5. Product metrics excludes archived accounts from account/adoption counters and top-N, includes `archived`, and deliberately keeps token/request/failure operational counters global.
6. CLI output and repo artifacts do not contain raw production email/PII.
7. Full Docker suite passes.

## Декомпозиция

- 158.3 Migration + model field (≤150 LOC).
- 158.4 Archive/restore CLI + tests for criteria/idempotency/privacy (≤150 LOC script plus focused tests).
- 158.5 Product metrics filters for account/adoption counters + top-N, archived count + tests (≤150 LOC).
- 158.6 Full checks and review gates.
