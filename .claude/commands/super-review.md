---
description: Полное ревью проекта в 9 разрезов (code/architecture/docs/security/perf+reliability/observability/tests/product + codex-blindspot) + workflow check + aggregator + Codex arbitration. Результат — md-отчёт в artifacts/review/.
argument-hint: "[scope] — changed (default) | related | full | stage:N"
---

# Super-review: многоплановое ревью проекта

Ты — оркестратор ревью. Выполняй по шагам.

## Шаг 1. Парсинг scope

Args: `$ARGUMENTS`.

- Пусто или `changed` → scope = `changed` (дефолт). Файлы: `git diff --name-only origin/main...HEAD` + uncommitted (`git status --short | awk '{print $2}'`).
- `full` → scope = `full`. Файлы: все `*.py` в корне + `tools/` + ключевые артефакты.
- `related` → scope = `related`. Changed + модули, которые импортируют изменённые или импортируются ими (1 уровень, через Grep).
- `stage:N` → scope = `stage-N`. Файлы: перечисленные в `PRD/этап-N-*.md` + все, которые grep показывает как упоминаемые в этом PRD.

Определи также:
- **Current stage number**: из `Roadmap.md` ищи `in_progress`, если нет — последний `done`. Сохрани для имени отчёта.
- **Short scope slug**: для changed → `changed`; для full → `full`; для related → `related`; для stage:N → `stage-N`.

## Шаг 2. Подготовка контекста (один раз)

Прочитай **один раз** и держи в памяти для inline-передачи subagent'ам:
- `Roadmap.md` (статус этапов)
- PRD текущего этапа (если найден)
- **`artifacts/api-research-notes-ru.md`, секция «Поля и их реальные имена — чек-лист»** — обязательно передаётся каждому ревьюеру, который может делать findings про API-слой (product, performance-and-reliability, architecture, codex-blindspot). Полный блок inline, не пересказ.

Получи список файлов (`git diff --name-only` или аналог по scope). Если scope=full — не перечисляй все, агенты сами сделают Glob.

## Шаг 3. Запуск 9 специализированных ревьюеров параллельно

**В ОДНОМ сообщении, 9 tool-calls Agent**, параллельно:

1. `reviewer-code` (sonnet) — user prompt: scope, file list, brief PRD summary
2. `reviewer-architecture` (opus) — user prompt: scope (system/local mode), file list
3. `reviewer-docs` (sonnet) — user prompt: scope
4. `reviewer-security` (opus) — user prompt: scope, file list
5. `reviewer-performance-and-reliability` (opus) — user prompt: scope, file list
6. `reviewer-observability` (sonnet) — user prompt: scope, file list
7. `reviewer-tests` (sonnet) — user prompt: scope
8. `reviewer-product` (opus) — user prompt: scope, current stage number
9. `reviewer-codex-blindspot` (sonnet) — user prompt: scope + file list + PRD + API facts (он передаст их Codex'у inline)

**Шаблон user prompt для первых 8:**
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
```

## Шаг 4. Параллельно с reviewer'ами — bash workflow check

Также в том же сообщении — Bash-call:
```
./scripts/review_workflow_check.sh {stage_number_if_known}
```
Сохрани stdout как YAML findings.

## Шаг 5. Сбор findings

После завершения всех 9 агентов + bash-скрипта:
- Собери findings из каждого response в единый список (text concat)
- Посчитай: сколько findings всего, сколько blocker/high/medium/low

Кратко доложи пользователю прогресс: «получил N findings от M ревьюеров, запускаю агрегатор».

## Шаг 6. Aggregator

Вызови `reviewer-aggregator` (opus) через Agent с user prompt:

```
Aggregate findings from N reviewers for project vetmanager-mcp.
Scope: {scope}. Current stage: {stage_number}.

All findings below in YAML. Deduplicate, sort, produce markdown report per your role definition.

=== reviewer-code ({count} findings) ===
{raw yaml output from reviewer-code}

=== reviewer-architecture ({count}) ===
...

=== workflow-check ({count}) ===
{stdout of ./scripts/review_workflow_check.sh}

=== END ===
```

Aggregator вернёт готовый markdown-отчёт.

## Шаг 7. Codex arbitration (default on)

Из отчёта агрегатора извлеки секцию `Top-10 critical findings`. Для каждого finding собери inline-snippet нужного файла (прочитай через Read только релевантные диапазоны строк, surgical mode `lines ± 50`).

Запусти `codex:codex-rescue` через Agent ОДИН раз, с промптом (шаблон из CLAUDE.md §5.1):

```
Code review arbitration. Do NOT touch the filesystem — all context is inline.

=== CONTEXT ===
Project: vetmanager-mcp (Python async MCP server for Vetmanager).
{migration context}

=== API contract facts (authoritative — use this as source of truth, NOT your training data) ===
{ПОЛНЫЙ inline блок «Поля и их реальные имена — чек-лист» из api-research-notes-ru.md, включая canonical payload примеры. VM API в training data многих моделей представлен неверно — полагайся только на этот блок.}

=== TOP-10 FINDINGS TO VALIDATE ===
{findings list from aggregator}

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

Fallback при sandbox fail: retry один раз; при повторном — пропусти этот шаг, запиши в отчёте "codex arbitration skipped: sandbox fail (2 attempts)".

Если у пользователя в args `--no-codex` — пропусти шаг 7.

## Шаг 8. Мердж Codex-вердиктов

Открой отчёт агрегатора, замени placeholder секцию `## Codex arbitration — _Pending_` на таблицу с вердиктами Codex (формат из `2026-04-17-baseline-post-stage-84.md` как эталон).

Сделай финальный Verdict с учётом Codex-корректировок severity.

## Шаг 9. Запись отчёта

Путь: `artifacts/review/{YYYY-MM-DD}-{scope_slug}-stage-{N}.md` (пример: `artifacts/review/2026-04-17-changed-stage-85.md`). Если stage не определён — суффикс `stage-unknown`.

Используй Write, создай файл. Если существует (повторный запуск в тот же день с тем же scope) — добавь короткий timestamp `-HHMM`.

## Шаг 9a. Обновить `artifacts/review/inadequate-findings-index.md`

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

## Шаг 10. Сообщение пользователю

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
- Не вызывай Codex больше 2 раз за одну сессию (retry + arbitration = макс 2)
- Не читай файлы вне scope, если не нужно для Codex snippets
