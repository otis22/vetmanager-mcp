# Stage workflow template

Копируемый чек-лист для нового этапа. Источник правил и бюджетов: `AGENTS.md` и `.cursor/rules/agent-workflow.mdc`. Если они изменились, сначала сверить этот шаблон с ними.

## 1. Задача и PRD

- [ ] Проверить `git branch --show-current`: работать в назначенной `dev/roadmap-<этапы>`.
- [ ] Выбрать верхнюю доступную `todo` в `Roadmap.md`, перевести этап и выбранную подзадачу в `in_progress`.
- [ ] Создать/прочитать PRD в `PRD/`, сверить с источником задачи и релевантными `artifacts/`. Указать цель, scope, проверенные факты, архитектурное решение, декомпозицию ≤2 ч или ≤150 строк, acceptance и rollback.
- [ ] Для VM API проверить реальные имена полей и enum в `artifacts/api-research-notes-ru.md`, OpenAPI или entity reference; найти sibling-вызовы и контракты `create`/`update`/`delete`.
- [ ] Если меняются auth, storage, public/API/MCP contract, production behavior, performance или граница модулей, провести Architecture Critique до реализации; он делит бюджет PRD-гейта. Иначе записать причину N/A.

## 2. PRD-гейт

- [ ] Spark-review (`gpt-6-luna`) по узкому prompt: объект PRD, severity, формат ответа и запрет правок. Требовать `files_read`; пустой verdict без прочитанных файлов не засчитывать. Spark — candidate-only, принять лишь важные проверенные находки.
- [ ] Запустить сильную пару параллельно: Astra (`gpt-6-astra`) и Kimi K3. Исполнитель этапа — `gpt-6-sol`. Требуется Codex CLI ≥ 0.155.
- [ ] Для Astra использовать `codex exec` с `-s danger-full-access`, `--output-schema`, `-o`, review-only prompt и валидатор `scripts/validate_review_result.py --plain` по result JSON. Сохранять prompt, result, stderr и metadata с временем, моделью, объектом, exit codes и SHA для diff.
- [ ] Для Kimi использовать `scripts/run_kimi_review.py` с `--file` для PRD, `--attempt N/3` и evidence вне checkout; default runner — Kimi K3. Runner проверяет один непустой assistant JSON без tool calls через `scripts/validate_review_result.py --plain`; `outcome=valid_verdict` подтверждается metadata. В `AssumptionLog.md` указать stream/metadata, `cli_exit`, `outcome`, `validator_exit`, `model`, `len(result)`.
- [ ] Свести findings Astra и Kimi в `AssumptionLog.md`: общие/раздельные, принятое/отклонённое с причиной. После существенных правок повторить review в рамках бюджета.
- [ ] Завершить PRD-review: устранить адекватные находки, при существенных изменениях повторить сильную пару в пределах бюджета. Оценить простоту PRD до реализации; если оценка изменила решение, снова пройти PRD-review. Причину N/A для тривиального исправления записать явно.

## 3. Реализация и проверки

- [ ] Написать guard/test и показать красным, чем сломана защищаемая гарантия; затем внести минимальное исправление и показать зелёным.
- [ ] Для API-правок сверить каждое payload-поле и literal enum с источником истины; покрыть sibling `update`/`delete`, если исправлен `create`, и проверить unhappy/boundary cases.
- [ ] Если изменён MCP-инструмент, вызвать его на выбранном заранее стенде и записать HTTP-код и тело в `AssumptionLog.md`. `TEST_DOMAIN`/`TEST_API_KEY` и bearer-контур различны.
- [ ] При изменении Dockerfile или зависимостей сначала пересобрать test image; запускать mock и, при наличии тестового контура, real suite командами из раздела «Тесты и проверки» в `AGENTS.md`, чтобы исключить устаревший образ. Явное исключение владельца для документного этапа зафиксировать отдельно.
- [ ] Выполнить focused + fast для default/runtime входов, затем полное pre-review рабочего diff Spark → Astra + Kimi K3. Правки накопить пакетом и повторить инвалидированные focused + fast один раз. После заморозки кода запустить полный default при изменении его входов и применимые long gates; полный real suite по финальному SHA до push обязателен для обычного этапа релизного поезда. Явное исключение владельца для документного этапа зафиксировать в `AssumptionLog.md`. При изменении `scripts/*.sh` обязательны ShellCheck и Bash syntax по командам из `AGENTS.md`.
- [ ] Повторять только инвалидированные контуры: runtime/shared fixtures/dependencies — focused + fast, полный default и связанные PostgreSQL/real; default-only test — focused + fast/default; PostgreSQL-only test — focused + PostgreSQL; real-only test — только real (focused + затронутая группа и финальный aggregate); docs-only — suites не повторяет. Контурный fingerprint `scripts/offline_gate_manifest.py` обязателен и остаётся fail-closed; mismatch не игнорировать.
- [ ] Перед commit выполнить каждую новую исполнимую команду из процессной документации точно в записанном виде и зафиксировать её реальный exit code.
- [ ] Аудировать diff, legacy-предписания, дублирование и секреты. После рефакторинга повторить предусмотренные проверки.

## 4. Статусы, commit и committed diff-гейт

- [ ] Добавить раздел `## Этап N. <title>` в `AssumptionLog.md`, в том числе red/green, команды и exit codes, решения, review evidence, влияние на права доступа/credentials и необходимость живого вызова.
- [ ] Сохранить статус `in_progress` до зелёного применимого PR CI; выполнить `python3 scripts/archive_roadmap.py`, затем `python3 scripts/check_roadmap_structure.py`, оба с exit 0.
- [ ] Закрывая finding из `artifacts/review/`, оставить resolution note в исходном отчёте; сделать commit с префиксом `Stage N:` в рабочей dev-ветке после аудита.
- [ ] Spark-review committed diff → Astra + Kimi K3 параллельно. Kimi получает `--range`, Astra — committed diff и reviewed SHA. Оба валидных verdict обязательны до push; пропускать **только блокеры релиза**. non-blocking findings — в Roadmap без правок текущей ветки; блокер повторяет focused/owning/fast и только инвалидированные полные контуры.
- [ ] Для каждого гейта максимум 3 предгейтовых Spark-прохода. У Astra и Kimi независимо по 2 валидных verdict и по 3 infrastructure attempts. Пустой или невалидный ответ, auth/provider/model failure не расходует валидный слот; каждую попытку записать как `N/3`. После третьего infrastructure failure любой стороны гейт `blocked`, push запрещён. Смена prompt/schema счётчик не сбрасывает.

## 5. Релизный поезд

- [ ] Push только в назначенную `dev/roadmap-<этапы>`; передать ветку куратору для PR в main. Tests и Docs Check запускаются на PR, не на dev-push. До merge куратор проверяет зелёные применимые PR checks. Для docs-only PR Tests исключён path filter; ручной Tests на dev-ветке запускать только если это требуется отдельным решением.
- [ ] После зелёного PR CI перевести завершённые подзадачи и этап в `done`, записать CI-ссылку в `AssumptionLog.md`, проверить структуру Roadmap и отправить status commit в ту же dev-ветку. Запустить `scripts/check_stage_completion.sh` с номером этапа и оценить его findings, включая старые baseline findings.
- [ ] Выпуск подзадачи в рабочей ветке = зелёный применимый PR CI. После зелёного CI и полного mock+real suite по финальному SHA ветки супервизор делает merge в main. Деплой и production-проверки относятся к работе после merge.
- [ ] Показать self-attestation пользователю после push; не заменять его строкой в commit message.

## Дополнительный визуальный гейт

Если меняется UI, следовать матрице состояний и снимков из `AGENTS.md`: Astra получает PNG через `-i`, Kimi получает PNG только через подтверждённый image-capable transport; текстовый `-p` не засчитывается. Для Kimi `[]` требуется metadata с подтверждённой передачей пикселей, путями, размерами и SHA-256; иначе гейт blocked. До передачи PNG удалить PII, токены, идентификаторы сессий и данные клиник и отметить очистку в metadata. У визуального гейта отдельный бюджет, оба валидных verdict обязательны.

## Команды самопроверки инструкций

```bash
codex --version
scripts/run_kimi_review.py --help
scripts/validate_review_result.py --help
git branch --show-current
```
