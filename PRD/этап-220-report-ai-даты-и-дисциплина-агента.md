# Этап 220. Report AI: даты в обезличивании и дисциплина агента

## Контекст

Живая проверка шести Report AI отчётов показала два MCP-наблюдаемых дефекта.
В свободном текстовом поле централизованный обезличиватель заменил даты
`2024-01-01`, `2026-12-31` и фрагмент `2024-10-23 17:50:51` на
`[redacted-phone]`. Одновременно static helper не объясняет агенту, как
работать с нулевым результатом, неоднозначностью без пользователя,
многочастными запросами и обычным временем ожидания очереди.

## Проверенные факты

- `depersonalization.sanitize_text()` применяется только к allowlisted
  free-text keys и сейчас использует один общий phone regex.
- Structured phone fields остаются отдельной key-based маской; их контракт не
  меняется.
- `get_report_ai_prompt_helper` и MCP prompt используют один static artifact
  `artifacts/report-ai-prompt-helper-short-mcp-2026-06-15.md` через
  `prompts.get_report_ai_prompt_helper_text()`.
- `REPORT_AI_LONG_QUEUED_THRESHOLD_SECONDS = 30` — локальная диагностика
  наблюдаемого queued state, а не SLA upstream.
- Наблюдения пользователя на одном контуре: одиночный job обычно доходил до
  `ready_to_save` примерно за 1–3 минуты; параллельно созданные jobs шли
  заметно дольше. Это не гарантия API.

## Scope

- Защитить date/time до free-text phone redaction: ISO `YYYY-MM-DD`, ISO
  `YYYY-MM-DD[T ]HH:MM:SS` с timezone и `DD.MM.YYYY` остаются неизменяемыми
  фрагментами; к остальному тексту применяется прежняя phone mask. Это
  сохраняет даты и не блокирует телефон сразу после даты.
- Сохранить redaction настоящего телефона, в том числе когда он находится в
  той же строке, что дата.
- Дополнить короткий русский helper наблюдаемыми правилами: пустой результат,
  проверка записей за период, разумный default без пользователя, один вопрос —
  один узкий последовательный job и нормальный порядок ожидания.
- Добавить focused regression tests.
- В review-evidence runner отвергать `--evidence-dir` внутри repository working
  tree до чтения review object и создания evidence.

## Out of scope

- Изменение Vetmanager backend, SQL, очереди или API contract.
- Новые MCP tools, автоматический retry/create/save/polling или изменение
  `REPORT_AI_LONG_QUEUED_THRESHOLD_SECONDS`.
- Изменение structured field redaction либо ослабление privacy boundary.
- Утверждения о гарантированном времени выполнения Report AI.

## Архитектурное решение

### Проблема

Телефонная маска допускает цепочки цифр, разделённые дефисами, и поэтому
совпадает с ISO-датой. У агента есть безопасный helper, но без нескольких
правил он может ошибочно пересоздавать job при отсутствии данных либо
перегружать очередь.

### Контекст и ограничения

- Existing sanitizer заменяет только явные PII patterns в free text; false
  negative для настоящего телефона недопустим как побочный эффект.
- Дата и время — business data, которые должны сохраняться в обезличенном
  ответе.
- Helper — статическая инструкция перед каждым отчётом; текст должен быть
  кратким, по-русски и не называть observed timings гарантией.
- Знания о внутренней реализации backend в repository не добавляются; только
  MCP-наблюдаемое поведение.

### Рассмотренные варианты

1. Отключить phone redaction в free text.
   - Плюс: убирает ложное совпадение.
   - Минус: открывает PII, неприемлемо.
2. Добавить исключения для известных дат перед текущей широкой маской.
   - Плюс: небольшая правка.
   - Минус: исключения хрупки и могут оставить другие date-like совпадения.
3. Сначала выделять известные business date/time tokens, затем применять
   прежнюю phone mask к оставшимся сегментам.
   - Плюс: устраняет причину, сохраняя privacy contract.
   - Минус: date-token corpus должен покрывать ISO `T`/timezone и локальную
     дату, чтобы не расширять privacy exception неявно.

### Выбранное решение

Выбрать вариант 3 и добавить регрессии на оба наблюдённых формата даты,
ISO `T`/timezone, локальную дату и телефон непосредственно после каждой из
них. Runner должен отклонять evidence path внутри repo. Обновить один shared
helper artifact, чтобы tool и prompt не расходились.

### Инварианты

- Настоящий телефон в free text по-прежнему заменяется на `[redacted-phone]`.
- ISO/local date-time и соседний business text не изменяются.
- Телефон redacted независимо от соседней даты, пробела или дефиса.
- Structured phone fields по-прежнему redacted по ключу.
- Tool helper и MCP prompt возвращают идентичный текст.
- 30 секунд — сигнал локальной диагностики, а не признак поломки и не
  обещание SLA.

### Rollback / fallback

Перед применением новой маски прогнать existing и new focused corpus: каждая
строка, которую старый pattern маскировал, а новый нет, должна быть явной
ISO date/date-time или date-range negative case; все сохранённые phone forms
должны иметь отдельный test. Если новый corpus обнаружит нераспознанный
реальный phone format, расширить только явный phone alternative с новым
negative date test. Если observed очередь изменится, обновить helper wording
отдельно по новым наблюдениям, не меняя runtime behavior.

Architecture Critique: not required. Задача не меняет public/API/MCP contract,
auth, storage, production behavior или ownership boundary: это локальная
privacy-regex regression и static advisory text.

## Декомпозиция

1. 220.1: создать PRD, review gates и tests на date/time/phone/helper. ≤2h.
2. 220.2: сузить free-text phone pattern до passing focused corpus. ≤150 LOC.
3. 220.3: обновить shared helper и assertions. ≤150 LOC.
4. 220.4: targeted/full checks, audit и review; без push. ≤2h.

## Acceptance criteria

1. `2024-01-01` и `2026-12-31` сохраняются в free-text report description.
2. `2024-10-23 17:50:51` и строка `дата: 2024-10-23 17:50:51` сохраняются.
3. Настоящий телефон рядом с датой в одной строке и непосредственно после
   date/time через пробел либо дефис redacted; focused corpus также сохраняет
   маскирование прежних форматов с `+`, скобками, пробелами, дефисами (включая
   `8-999-123-45-67`) и compact digits. ISO date, ISO `T`/timezone date-time,
   local `DD.MM.YYYY` date и date range не маскируются.
4. Helper советует: zero rows — результат; перед повтором проверить прямым
   read tool наличие записей за период; без пользователя выбрать и явно
   записать разумное default; разбивать многочастный запрос; создавать jobs
   последовательно; 1–3 минуты — наблюдаемый порядок до `ready_to_save`, а 30
   секунд диагностики сами по себе не означают failure.
5. Tool и MCP prompt helper остаются идентичными.
6. Focused и полный Docker suite проходят; ShellCheck не требуется, если
   `scripts/*.sh` не изменяются.
7. `run_claude_review.sh` возвращает отказ до вызова `git`/reviewer, если
   evidence directory разрешается внутри repo; regression test это доказывает.
