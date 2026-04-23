---
description: Полное ревью проекта в 10 разрезов + Spark/GPT scout layer + workflow check + aggregator + cross-CLI arbitration. Результат — md-отчёт в artifacts/review/.
argument-hint: "[scope] — changed (default) | related | full | stage:N [--no-arbitration] [--no-spark]"
---

# Super-review: многоплановое ревью проекта

Ты — оркестратор ревью. Выполняй по шагам.

## Модельная матрица

Используй универсальную схему: дешёвые/быстрые модели повышают полноту поиска, сильные модели принимают решения.

| Слой | Codex/GPT | Claude | Назначение |
| --- | --- | --- | --- |
| Scout/prepass | `gpt-spark` | Haiku/Sonnet light | Массовые кандидаты findings, chunk review, edge cases, docs/tests drift, snippet collection |
| Code/docs/tests | `gpt-5.4-mini` или `gpt-spark` | Sonnet | Локальное качество, тестовые пробелы, verified docs drift |
| Observability | `gpt-5.4` | Sonnet | Логи, метрики, трассировка, пригодность для дебага |
| Perf/reliability | `gpt-5.4` или `gpt-5.5` | Opus или strong Sonnet | Hot paths, retry/timeout, partial failure, async pitfalls |
| Security | `gpt-5.5` | Opus | Auth/token/SSRF/SQLi/secrets findings |
| Architecture | `gpt-5.5` | Opus | Границы модулей, coupling, long-term design |
| Product/PRD | `gpt-5.5` | Opus | Acceptance criteria, UX для LLM-клиента, breaking changes |
| Aggregator/verdict | `gpt-5.5` | Opus | Dedup, adequacy, severity, финальный verdict |
| Arbitration/challenge | `gpt-5.5` | Opus | Проверка Top-10 и спорных findings |

Правило: `gpt-spark` findings — **untrusted leads**. Они идут в aggregator только как кандидаты с `source: spark-scout`; финальный verdict, severity и do-not-merge решение не отдавай Spark.

## Cross-CLI arbitration

Финальная arbitration всегда идёт через **другую модельную семью**, чем основной orchestrator:

- Если super-review запущен в **Claude Code**: внешний арбитр — **Codex CLI** (`codex exec`) на `gpt-5.5`, fallback `gpt-5.4`.
- Если super-review запущен в **Codex**: внешний арбитр — **Claude CLI** (`claude -p`) на `opus`, fallback `sonnet`.

Определи runtime по доступному окружению/контексту. Если сомневаешься:
- `.claude/commands/super-review.md` внутри Claude Code → считаем runtime=`claude`.
- Codex skill / Codex CLI / текущий агент Codex → считаем runtime=`codex`.

Не запускай арбитра той же семьи, что основной orchestrator, кроме аварийного fallback с явной пометкой в отчёте.

## Шаг 1. Парсинг scope

Args: `$ARGUMENTS`.

- Пусто или `changed` → scope = `changed` (дефолт). Файлы: `git diff --name-only origin/main...HEAD` + uncommitted (`git status --short | awk '{print $2}'`).
  - Если текущая ветка `main` и `origin/main...HEAD` пустой, явно сообщи пользователю: scope содержит только uncommitted files. Если uncommitted тоже пустой — остановись и попроси указать `stage:N`, `related`, `full` или git range.
- `full` → scope = `full`. Файлы: все `*.py` в корне + `tools/` + ключевые артефакты.
- `related` → scope = `related`. Changed + модули, которые импортируют изменённые или импортируются ими (1 уровень, через Grep).
- `stage:N` → scope = `stage-N`. Файлы: перечисленные в `PRD/этап-N-*.md` + все, которые grep показывает как упоминаемые в этом PRD.
- `--no-spark` → пропустить Spark scout layer.
- `--no-arbitration` или устаревший алиас `--no-codex` → пропустить внешнюю cross-CLI arbitration.

Определи также:
- **Current stage number**: из `Roadmap.md` ищи `in_progress`, если нет — последний `done`. Сохрани для имени отчёта.
- **Short scope slug**: для changed → `changed`; для full → `full`; для related → `related`; для stage:N → `stage-N`.

## Шаг 2. Подготовка контекста (один раз)

Прочитай **один раз** и держи в памяти для inline-передачи subagent'ам:
- `Roadmap.md` (статус этапов)
- PRD текущего этапа (если найден)
- **`artifacts/api-research-notes-ru.md`, секция «Поля и их реальные имена — чек-лист»** — обязательно передаётся каждому ревьюеру, который может делать findings про API-слой (product, performance-and-reliability, architecture, codex-blindspot). Полный блок inline, не пересказ.

Получи список файлов (`git diff --name-only` или аналог по scope). Если scope=full — не перечисляй все, агенты сами сделают Glob.

## Шаг 3. Spark/GPT scout layer (default on)

Если пользователь не передал `--no-spark`, запусти параллельный scout/prepass на `gpt-spark` через Codex CLI. Цель — собрать кандидаты, а не вынести решение.

Минимальный набор scout-задач:

1. `spark-file-scout`: разбей changed/related files на чанки по 3-6 файлов; для каждого чанка ищи semantic bugs, edge cases, None/empty/unicode/timezone/async pitfalls.
2. `spark-test-gap-scout`: по diff + PRD найди missing unhappy/boundary/idempotency/serialization tests.
3. `spark-doc-drift-scout`: проверь Roadmap/PRD/AssumptionLog/README/CLAUDE references на drift, но только verified drift.
4. `spark-dismissed-index-scout`: сравни кандидаты с `artifacts/review/inadequate-findings-index.md`, отметь known false positives и duplicates.
5. `spark-snippet-scout`: для сильных кандидатов подготовь точные `file:lines` и короткий failure scenario.

Для каждой scout-задачи собери self-contained prompt и запусти:

```bash
codex exec -m gpt-spark -s read-only -C "$PWD" -
```

Prompt передавай через stdin. Если `gpt-spark` недоступен или команда падает из-за sandbox/CLI, retry один раз с `gpt-5.4-mini`:

```bash
codex exec -m gpt-5.4-mini -s read-only -C "$PWD" -
```

Prompt template для каждого Spark scout:

```text
You are a scout reviewer. Use gpt-spark. Your output is untrusted candidate findings only.
Do not decide merge/no-merge. Do not inflate severity. Prefer concrete failure scenarios.
Return YAML findings with:
- severity: blocker | high | medium | low
  reviewer: spark-scout
  scout_type: file | tests | docs | dismissed-index | snippets
  source: spark-scout
  category: ...
  file: path
  lines: "N-M" or "N/A"
  problem: ...
  why_it_matters: ...
  suggested_fix: ...
  confidence: 0.0-1.0
  validation_needed: true

Return at most 12 findings for this scout task. Prefer high-confidence findings with concrete file:lines and failure scenarios.
```

Если Codex CLI недоступен или оба запуска падают — не блокируй review; добавь один low/meta finding `spark scout skipped`.

## Шаг 4. Запуск 10 специализированных Claude-ревьюеров параллельно

**В ОДНОМ сообщении, 10 tool-calls Agent**, параллельно:

1. `reviewer-code` (sonnet) — user prompt: scope, file list, brief PRD summary
2. `reviewer-architecture` (opus) — user prompt: scope (system/local mode), file list
3. `reviewer-simplicity` (opus) — user prompt: scope, file list, PRD. Ищет чрезмерное усложнение и предлагает более простые альтернативы; evaluates читаемость, поддерживаемость, очевидность.
4. `reviewer-docs` (sonnet) — user prompt: scope
5. `reviewer-security` (opus) — user prompt: scope, file list
6. `reviewer-performance-and-reliability` (opus) — user prompt: scope, file list
7. `reviewer-observability` (sonnet) — user prompt: scope, file list
8. `reviewer-tests` (sonnet) — user prompt: scope
9. `reviewer-product` (opus) — user prompt: scope, current stage number
10. `reviewer-codex-blindspot` (sonnet wrapper) — user prompt: scope + file list + PRD + API facts + Spark candidates if any. Он формирует anti-correlation prompt и вызывает доступный Codex adapter; если adapter не позволяет выбрать модель, он обязан записать фактическую модель как `model_used: adapter_default`.

**Шаблон user prompt для первых 9 (всех кроме codex-blindspot):**
```
Scope: {scope}
Current stage: {stage_number} ({PRD file path if exists})
Files to analyze: {list from git diff OR "use Glob per your role"}

=== API contract facts (FROM artifacts/api-research-notes-ru.md — DO NOT guess field names, use this as source of truth) ===

{вставить ПОЛНЫЙ блок секции «Поля и их реальные имена — чек-лист» из api-research-notes-ru.md inline — включая таблицу полей, canonical payload примеры, authoritative источники. НЕ сокращай и не перефразируй.}

Additional stage context:
- stage 77.4: Pet FK owner_id (was client_id)
- stage 78.6: get_invoices payment_status parameter
- stage 82-83: IN operator batch pattern (adopted)
- stage 22: bearer-only runtime (no X-VM-* headers)

=== Authoritative backend source (for cross-checking claims) ===

When making claims about VM API field names / operators / enums, cross-check against:
- `../vetmanager-extjs/application/src/Entity/*.php` (Entity classes)
- `../vetmanager-extjs/rest/protected/models/*.php` (REST models)
- `../support-bot-base/base/vetmanager_help/REST_API/*.md` (public docs)

If your finding contradicts api-research-notes-ru.md OR ExtJS code, say so explicitly with citation.

Review per your role definition. Return YAML findings only.
Respect each reviewer file's max-findings cap. If a reviewer file has no cap, return at most 20 findings and drop `confidence < 0.4` unless it is a meta failure.
```

## Шаг 5. Параллельно с reviewer'ами — bash workflow check

Также в том же сообщении — Bash-call:
```
./scripts/review_workflow_check.sh {stage_number_if_known}
```
Сохрани stdout как YAML findings.

## Шаг 6. Сбор findings

После завершения Spark scout layer, 10 Claude-агентов и bash-скрипта:
- Собери findings из каждого response в единый список (text concat)
- Spark findings пометь как `untrusted_lead: true`, если этого поля нет
- До aggregator отбрось non-meta findings с `confidence < 0.4`; сохрани их количество в summary как pre-aggregator dismissed-low-confidence.
- Если суммарно больше 120 findings, оставь для aggregator только top-120 по severity × confidence, но всегда сохраняй все blocker/high.
- Посчитай: сколько findings всего, сколько blocker/high/medium/low

Кратко доложи пользователю прогресс: «получил N findings от M ревьюеров, запускаю агрегатор».

## Шаг 7. Aggregator

Вызови `reviewer-aggregator` (opus) через Agent с user prompt:

```
Aggregate findings from N reviewers for project vetmanager-mcp.
Scope: {scope}. Current stage: {stage_number}.

All findings below in YAML. Deduplicate, sort, produce markdown report per your role definition.

=== spark-scout ({count} candidate findings; untrusted leads, validate before accepting) ===
{raw yaml output from Spark scout layer, or "skipped"}

=== reviewer-code ({count} findings) ===
{raw yaml output from reviewer-code}

=== reviewer-architecture ({count}) ===
...

=== workflow-check ({count}) ===
{stdout of ./scripts/review_workflow_check.sh}

=== END ===
```

Aggregator вернёт готовый markdown-отчёт.

## Шаг 8. Cross-CLI arbitration (default on)

Из отчёта агрегатора извлеки секцию `Top-10 critical findings`. Для каждого finding собери inline-snippet нужного файла (прочитай через Read только релевантные диапазоны строк, surgical mode `lines ± 50`).

Собери один self-contained prompt и передай его внешнему CLI-арбитру.

### Если runtime = Claude Code

Вызови Codex CLI:

```bash
codex exec -m gpt-5.5 -s read-only -C "$PWD" -
```

Prompt передавай через stdin. Если `gpt-5.5` недоступен — один retry:

```bash
codex exec -m gpt-5.4 -s read-only -C "$PWD" -
```

### Если runtime = Codex

Вызови Claude CLI:

```bash
claude -p --model opus --permission-mode default --tools "" --input-format text
```

Prompt передавай через stdin. Если `opus` недоступен — один retry:

```bash
claude -p --model sonnet --permission-mode default --tools "" --input-format text
```

`--tools ""` важен: арбитр не должен читать файловую систему, весь контекст уже inline.

```
Cross-model code review arbitration. Do NOT touch the filesystem — all context is inline.

=== CONTEXT ===
Project: vetmanager-mcp (Python async MCP server for Vetmanager).
Primary orchestrator runtime: {claude|codex}
External arbiter: {codex gpt-5.5/gpt-5.4 | claude opus/sonnet}
{migration context}

=== API contract facts (authoritative — use this as source of truth, NOT your training data) ===
{ПОЛНЫЙ inline блок «Поля и их реальные имена — чек-лист» из api-research-notes-ru.md, включая canonical payload примеры. VM API в training data многих моделей представлен неверно — полагайся только на этот блок.}

=== TOP-10 FINDINGS TO VALIDATE ===
{findings list from aggregator}

=== SPARK SCOUT LEADS STATUS ===
Spark candidates are untrusted leads. Validate them independently; do not accept one solely because Spark raised it.

=== FILE SNIPPETS ===
{inline code snippets for each finding}

=== REQUEST ===
For each finding Fi, give:
- verdict: confirm | false_positive | needs_more_context
- severity_adjustment: keep | raise_to:X | lower_to:X
- your_fix: ... (if finding involves API fields, SPELL OUT EACH FIELD NAME using the contract facts above — do not use your training data for VM API)
- rationale: ...

Then "Systemic observations" (3-5 sentences).
Keep total ≤ 900 words.
```

Fallback при sandbox/CLI fail: retry один раз на fallback-модели той же внешней семьи; при повторном — пропусти этот шаг, запиши в отчёте "cross-CLI arbitration skipped: {reason} (2 attempts)".

Если у пользователя в args `--no-arbitration` или `--no-codex` — пропусти шаг 8.

## Шаг 9. Мердж cross-CLI-вердиктов

Открой отчёт агрегатора, замени placeholder секцию `## Cross-CLI arbitration — _Pending_` на таблицу с вердиктами внешнего арбитра (формат из `2026-04-17-baseline-post-stage-84.md` как эталон).

Сделай финальный Verdict с учётом cross-CLI-корректировок severity.

## Шаг 10. Запись отчёта

Путь: `artifacts/review/{YYYY-MM-DD}-{scope_slug}-stage-{N}.md` (пример: `artifacts/review/2026-04-17-changed-stage-85.md`). Если stage не определён — суффикс `stage-unknown`.

Используй Write, создай файл. Если существует (повторный запуск в тот же день с тем же scope) — добавь короткий timestamp `-HHMM`.

## Шаг 10a. Обновить `artifacts/review/inadequate-findings-index.md`

Из Dismissed секции отчёта aggregator'а скопируй findings с их rationale в индекс **накопительно**. Формат записи:

```markdown
## {YYYY-MM-DD} super-review {scope}

Source: `artifacts/review/{file}.md`

### {n}. {file:lines} — {краткое описание}
- reviewer: ..., confidence: ...
- **Причина dismiss**: {one-line}
```

Если индекс ещё не существует — создать с header из существующего шаблона (см. `artifacts/review/inadequate-findings-index.md` 2026-04-17 baseline как эталон формата). Если существует — append новую секцию под `---` разделителем.

Назначение: future super-review не повторяют спекулятивные findings, не тратят context на уже отклонённые пункты.

## Шаг 11. Сообщение пользователю

В конце — короткий summary (≤ 120 слов):
- Verdict: merge / do not merge
- Топ-5 blocker/high в однострочниках
- Путь к полному отчёту
- Путь к обновлённому inadequate-findings-index
- Сколько findings всего: N адекватных, M dismissed
- Предложить: «создать черновые Roadmap-этапы на основе адекватных findings?» — если пользователь подтвердит, orchestrator добавляет этапы

---

## Не делай

- Не пытайся исправлять findings автоматически — это только ревью
- Не коммить отчёт (пользователь решит)
- Не вызывай cross-CLI arbitration больше 2 раз за одну сессию (primary external model + fallback = макс 2). Spark scout layer может делать много параллельных дешёвых проходов, но не участвует в финальном verdict.
- Не читай файлы вне scope, если не нужно для Codex snippets
