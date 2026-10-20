# Этап 426 — исполнимая workflow-документация

Дата: 21.10.2026. Источник: `artifacts/review/2026-10-20-full-stage-420.md`, R7 и подтверждённые README cleanups.

## Цель

Копируемые инструкции должны соответствовать `AGENTS.md` и `.cursor/rules/agent-workflow.mdc`: исполнитель `gpt-6-sol`, Spark `gpt-6-luna` только как candidate, сильный гейт — Astra `gpt-6-astra` и Claude Opus параллельно. Текущий шаблон требует один retired Codex review и push в main; skill содержит retired модели и read-only sandbox. Релизный поезд работает в `dev/roadmap-426-429`, merge в main делает супервизор после зелёного CI ветки. README ошибочно обещает sort/filter всем list `get_*` и пропускает `find_pets_by_alias`.

## Проверенные факты

Канон — текущие `AGENTS.md` и `.cursor/rules/agent-workflow.mdc`, включая отдельный визуальный гейт, деление PRD-бюджета с Architecture Critique, три Spark-запуска на гейт, два валидных слота и три infrastructure attempts на сильного ревьюера. `scripts/run_claude_review.sh` принимает `--file`/`--range` и `--attempt N/3`; `scripts/validate_review_result.py --plain` валидирует Astra. Opus runner валидирует envelope. Evidence пишется вне checkout, findings — в `AssumptionLog.md`.

## Scope и правки по файлам

1. `docs/stage-workflow-template.md`: заменить single-review шаги на PRD и committed diff Spark → Astra+Opus, Architecture Critique и визуальный гейт, бюджеты и правило infrastructure failure; указать точные исполнимые команды, branch push, CI и передать merge супервизору.
2. `.codex/skills/super-review/SKILL.md`: убрать retired model/sandbox/fallback инструкции и привести runtime section к текущим `AGENTS.md` и `.cursor/rules/agent-workflow.mdc`, не менять исторические отчёты.
3. `README.md`: ограничить формулировку sort/filter реальным набором list инструментов; добавить `find_pets_by_alias` в Pet inventory и скорректировать итог.
4. `tests/test_stage426_workflow_docs.py`: текстовый guard на двух активных документах. Красный: исходные `/codex rescue`, `git push origin main` и `gpt-5.6-*` вызывают отказ в любом контексте. Зелёный: обязательные названия Astra+Opus, runner, validator, dev-ветка. Доказательство: исходный текст красный, новый зелёный; повторная вставка запрещённой команды в активный документ снова красная.
5. `Roadmap.md`, `AssumptionLog.md`: статусы и evidence; self-attestation показывается пользователю после push. Лог работы отдельно в `LiveHelperAgent/logs/mcp`.

Вне scope: бизнес-код, этапы 428/429, merge в main, deploy, production checks.

## Декомпозиция

- 426.1 (≤2 ч, документация без бизнес-кода): PRD и гейт; обновить шаблон, skill и README. Каждый файл правится отдельно с аудитом размера; вместе это один небольшой документный этап. Acceptance: оба документа описывают действующий контракт, README сверена с сигнатурами зарегистрированных tools; `find_pets_by_alias` есть в inventory, итог пересчитан.
- 426.2 (≤2 ч): guard с показанным красным на исходных файлах; точное выполнение новых команд; focused tests, аудит, archive/structure, AssumptionLog, commit, committed diff gate, push и Tests CI. Выпуск = зелёный CI ветки.

## Архитектурное решение

Проблема — две копируемые точки входа описывают несовместимый процесс. Выбран прямой текстовый контракт с указателями на канонические правила и небольшим guard без нового review framework. Альтернатива: удалить документы и ссылаться только на `AGENTS.md`; это лишает пользователей шаблона и skill. Инварианты: сильный гейт требует два валидных verdict; infrastructure failure не считается verdict и не тратит валидный слот; после третьей infrastructure attempt сторона blocked и push запрещён; push только в dev-ветку. Guard проверяет действующие предписания, не исторические упоминания. Rollback: вернуть документные правки и guard вместе, затем заново проверить действующий контракт.

Architecture Critique: not required — меняются только инструкции и README, без auth/storage/API/production behavior.

Оценка простоты: один параметризованный guard без нового фреймворка; документы сохраняются как копируемые точки входа, детали evidence отсылаются к канону. Дальнейшее дробление этапа не уменьшает риск.

## Acceptance

- Красный guard на старом тексте, зелёный после правок; `python3 scripts/archive_roadmap.py`, затем `python3 scripts/check_roadmap_structure.py`, оба exit 0.
- README: сверить исключения sort/filter с сигнатурами tools, добавить `find_pets_by_alias`, пересчитать итог по inventory.
- Все новые shell-команды в исполнимых документах запущены в точной записи и exit codes внесены в AssumptionLog.
- PRD и committed diff гейты: Spark candidate pass, валидные Astra и Opus verdict, findings разобраны.
- Аудит diff, commit и push только в `dev/roadmap-426-429`; зелёный Tests CI ветки — выпуск 426.2. Полный suite не требуется по указанию владельца для документного diff.
- AssumptionLog явно отмечает отсутствие изменений смысла выданных credentials (§6.0) и N/A для живой проверки инструментов (§6.1).
