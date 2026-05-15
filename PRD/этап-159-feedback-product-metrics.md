# Этап 159. Feedback metrics in product report

## Цель

Добавить feedback-аналитику в существующий ad-hoc product metrics report, чтобы оператор одним запуском видел не только accounts/tokens/requests/failures, но и состояние feedback loop:

- сколько feedback reports создано за 24h / 7d / 30d;
- сколько reports остаются `new`;
- распределение по `source`, `status`, `severity`, `category`;
- сколько reports помечено `possible_pii`;
- top related tools по reports;
- known-issue match events за 7d / 30d с разбивкой по `source`;
- top known issues по match events.

## Контекст

Существующий `scripts/product_metrics_report.py` читает Accounts / Tokens / Requests / Failures, но не читает `AgentFeedbackReport` и `KnownIssueMatchEvent`.

Feedback pipeline уже реализован:

- `report_problem` → `agent_feedback_service.create_feedback_report` → `agent_feedback_reports`;
- known issue matches пишутся в `known_issue_match_events`;
- auto feedback reports могут быть подавлены dedup/cap, поэтому match events являются более точным signal для частоты срабатывания known issue.

## Scope

1. Расширить `collect_metrics()` feedback-блоком.
2. Добавить read-only SQL helpers:
   - counts by window;
   - breakdown by report fields;
   - top related tools;
   - match event counts and top known issues.
3. Расширить Markdown и JSON output.
4. Обновить README section `Product metrics`.
5. Добавить focused tests.
6. Запустить checks, review gates, commit/push/deploy.

## Out of Scope

- Новые таблицы или миграции.
- Prometheus metrics для feedback reports.
- Raw feedback text в отчёте.
- Email/account identity в feedback-разделе.
- Автоматический triage/promote known issues.

## Privacy

Feedback-раздел не должен выводить `summary`, `details`, `error_excerpt`, `params_shape_json`, `suggested_fix`, `reproduce`, raw email, bearer token, Vetmanager payload или clinic data.

Разрешены только агрегаты, DB ids known issues и `KnownIssue.title` после повторной sanitization через feedback sanitizer. `distinct_accounts` и `distinct_tokens` — только integer counts через `COUNT(DISTINCT ...)`, никогда не списки id.

## JSON Shape

Feedback добавляется отдельным top-level блоком:

```json
{
  "feedback": {
    "reports": {
      "total_24h": 0,
      "total_7d": 0,
      "total_30d": 0,
      "new_open_30d": 0,
      "possible_pii_30d": 0,
      "by_source_30d": {"model": 0, "auto": 0, "user_complaint": 0},
      "by_status_30d": {"new": 0, "grouped": 0, "triaged": 0, "linked": 0, "ignored": 0},
      "by_severity_30d": {"low": 0, "medium": 0, "high": 0},
      "by_category_30d": {"bug": 0, "missing_tool": 0, "bad_description": 0, "contract": 0, "perf": 0, "docs": 0, "other": 0},
      "top_tools_30d": [{"tool": "get_clients", "reports": 0}]
    },
    "match_events": {
      "total_7d": 0,
      "total_30d": 0,
      "by_source_7d": {"injection": 0, "report": 0, "auto": 0},
      "by_source_30d": {"injection": 0, "report": 0, "auto": 0},
      "top_known_issues_30d": [
        {
          "known_issue_id": 1,
          "title": "sanitized title",
          "events": 0,
          "distinct_accounts": 0,
          "distinct_tokens": 0
        }
      ]
    }
  }
}
```

Top-level `window_days: 30` remains for the existing product report contract. Feedback multi-window values are nested explicitly.

## Acceptance Criteria

1. `collect_metrics()` возвращает top-level key `feedback`.
2. JSON output содержит `feedback` без raw feedback text.
3. Markdown output содержит `## Feedback`.
4. Feedback counts считают только `AgentFeedbackReport.created_at` по окнам 24h / 7d / 30d.
5. `new_open_30d` считает reports со `status='new'` и `created_at >= now - 30d`.
6. `possible_pii_30d` считает reports с `possible_pii=true` и `created_at >= now - 30d`.
7. `reports.by_source_30d` uses only report sources `{model, auto, user_complaint}`; `match_events.by_source_{7d,30d}` uses only match-event sources `{injection, report, auto}`.
8. `by_status_30d`, `by_severity_30d`, `by_category_30d` присутствуют в JSON output и Markdown, always include all known enum labels with default `0`.
9. `top_tools_30d` считает только reports с `created_at >= now - 30d`, группируется по `related_tool`, NULL отображается как `unknown`, ограничен `top_n`, default 10, order by reports desc.
10. Match event counters читают `KnownIssueMatchEvent.created_at`, имеют окна `7d` и `30d`, и группируются по `source`.
11. `top_known_issues_30d` считается по `KnownIssueMatchEvent.created_at >= now - 30d`, ограничен `top_n`, default 10, order by events desc, и содержит только `known_issue_id`, sanitized `title`, `events`, `distinct_accounts`, `distinct_tokens`.
12. `distinct_accounts` и `distinct_tokens` — integers, не arrays и не raw id lists.
13. `distinct_accounts` и `distinct_tokens` inside `top_known_issues_30d` use `COUNT(DISTINCT ...)` over the same `created_at >= now - 30d` rows as `events`.
14. `KnownIssue.title` output is sanitized with `sanitize_text(title, limit=240)`; if sanitizer returns empty, output `"unknown"`. If sanitizer returns `[REDACTED]`, keep `[REDACTED]` rather than dropping the row.
15. Tests покрывают collect, Markdown, JSON и privacy whitelist output. Whitelist test запускается отдельно для `format_markdown()` и `format_json()`: разрешены только агрегаты, `known_issue_id`, sanitized `title`, `events`, `distinct_accounts`, `distinct_tokens`, `related_tool`/`tool`, counter keys и перечисленные enum labels; запрещены `summary`, `details`, `error_excerpt`, `params_shape_json`, `suggested_fix`, `reproduce`, raw email, bearer token, raw `account_id`, raw `bearer_token_id`, Vetmanager payload и clinic data.

## Проверки

- Targeted red/green: `docker compose --profile test run --rm test sh -c "python -m pytest tests/test_stage159_feedback_product_metrics.py tests/test_stage110_product_metrics.py -q"`
- Full: `docker compose --profile test run --rm test`
- Audit: `git diff --check`
