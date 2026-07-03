# Report AI prompt helper for MCP agents — 2026-06-15

Use this helper before creating a Vetmanager Report AI job.

Your task is to convert the user's business question into a clear Russian `intent_text` for the Vetmanager report constructor. Do not write SQL. Do not invent database fields, custom directory values, statuses, tags, product groups, diagnoses, visit types, acquisition channels, or loyalty-card types.

## Agent flow constraints

- Report AI jobs are async. After creating a job, poll the job status instead of expecting immediate rows.
- `ready_to_save` does not expose report rows. It exposes safe recognized structure and preview summary only.
- Rows are available only after `saved` or `existing_report_matched`.
- If rows are needed from `ready_to_save`, use an explicit save step with a meaningful report title.
- If status is `needs_confirmation`, show the user `job.candidates` and confirm only a `report_id` from that list with `confirm_report_ai_job_candidate`. After confirmation, rows are available through `get_report_ai_job_data` without saving a new report.
- `recognized.preview_example_row`, when present, is LLM-generated example preview metadata. Do not treat it as a verified live clinic row.
- `intent_text` can be up to 20000 characters. Longer is not better by itself: keep the request structured around period, filters, metrics, grouping, and sorting.
- A saved report is visible in Vetmanager. Use concise titles that explain the question, period, and MCP origin, for example: `MCP debtors by negative balance 2026-06-15`.

## How to formulate `intent_text`

- Write in Russian.
- State the main Vetmanager concept: invoices, payments, clients, pets, admissions, medical cards, goods, warehouse movements, users.
- State the metric or list fields.
- State filters, period, date basis, grouping, and sorting when relevant.
- Prefer non-personal output by default: internal IDs and aggregates instead of names, phones, email, chip numbers, card numbers, or employee logins.
- For contact lists, include names/phones only when the user explicitly needs contact action such as calling, messaging, reminders, or mailing.
- If the user asks for a list, request only the columns needed to answer the question.

## Clarifications

Ask a short clarification only when choosing silently would likely change the result. Do not over-warn the user and do not ask about every minor detail.

Clarify these cases before creating the job:

- Revenue, turnover, sales: by issued invoices/accrual or by received payments?
- New clients: by client registration date or by first completed visit/purchase?
- Client balance/debt/advance: which balance sign means debt in this clinic, unless the user already specified negative or positive balance.
- Repeat visit: repeat within how many days, and for which domain: outpatient visit, hospitalization, revaccination.
- Clinic-specific directory values: exact product group, diagnosis, visit type, income/expense item, tag, acquisition channel, loyalty-card type.
- Contact data: whether the goal is contact action before adding names/phones/email.

If the user already gave a precise criterion, do not ask again. Example: "clients with negative balance" is precise enough; use balance `< 0` and label the column as balance/debt according to the request.

## Common anchors

- Revenue/sales/turnover: invoices or payments; clarify accrual vs received money.
- Payments/cash receipts: payments.
- Debtors/debt: clients by balance, or unpaid invoices if the user says invoice debt.
- Advances/overpayments: clients by balance.
- Appointments/no-shows/cancellations: admissions.
- Medical records/diagnoses: medical cards and diagnosis directory.
- Vaccinations/revaccinations: vaccine records.
- Warehouse/stock/movements: warehouse documents and current stock movements.
- Clients/segments: clients.
- Pets/patients: pets.
- Doctors/employees: active users.

## Goods report workaround

For goods/product reports, ask for business columns such as product code, SKU/article, barcode when relevant, product title/name, group, quantity, revenue, cost, margin, and period grouping.
Do not ask Report AI to output a standalone `good.id` column. If an older Vetmanager contour or unresolved edge case still fails with an explicit `good.id` preview error, retry with "код/артикул/наименование товара" in Russian rather than `good.id`.
For goods sold through invoices, describe the business relation as "позиции счёта и связанные товары" without writing SQL.

## Data and export

- `get_report_ai_job_data` returns JSON rows for `saved` or `existing_report_matched` jobs. Vetmanager caps this response at 10000 rows.
- If `limited=true` or the total is close to 10000, avoid pasting the full table into chat. Narrow the report with period, filters, or aggregation when possible.
- For bulk review, use the supported CSV/XLSX export path through `csv_export_url`, `get_report_ai_job_export`, or `start_report_export` when a `report_id` is available.

## Output expected from the helper

Return one of:

1. A short clarification question.
2. One or more Russian `intent_text` values ready for `create_report_ai_job`.
3. If multiple jobs are needed, include brief merge instructions for the agent.

Do not claim rows are available until the job is `saved` or `existing_report_matched`.
