# Этап 211. Контракт и диагностика очереди Report AI

## Цель

После воспроизводимого `queued` состояния и export `403` синхронизировать
MCP-подсказки с фактическим контрактом Report AI и получить от Vetmanager
проверяемый upstream contract для queue/export. Пользователь и агент должны
понимать, когда результат можно ожидать, когда требуются права на сохранение и
когда retry безопасен — без ложного обещания same-turn результата.

## Наблюдения и доказательства

Ниже приведены incident evidence и результаты probes. Они достаточны для
диагностики и эскалации, но не являются обещанием внутреннего поведения
Vetmanager API для MCP-пользователя. Детали worker/cleanup и 403 taxonomy можно
публиковать в описаниях инструментов только после подтверждения upstream.

- Production feedback `#15`, `#19`, `#21`, `#37` образуют queue/preview
  cluster; `#9` — historical inventory queued case. `#16` и high-severity
  `#17` фиксируют read-only gap после `ready_to_save`; `#11` — large-result
  limitation.
- Real probe на test contour 2026-08-04: job `#116` осталась `queued` более
  2,5 минут с неизменным `updated_at`, без `error_code`, `report_id` и
  retry metadata. `/data` для неё вернул HTTP 409 `INVALID_TRANSITION`.
- Повторный read-only probe job `#116` после cleanup window: job стала
  `failed` с `PREVIEW_FAILED` и safe message, что она зависла в
  `needs_confirmation` дольше 600 секунд. Source history подтверждает
  intentional TTL abandoned interactive jobs, но API не публикует его как
  public contract (`expires_at`, отдельный code или retry metadata отсутствуют).
- Saved fixtures вернули rows и CSV pointer. Первый `StartReport` успешно
  стартовал, повторный вызов вернул HTTP 403 long-running limit.
- Наблюдение в доступном upstream source: task проходит `queued → recognizing
  → building_preview → ready_to_save`; cleanup настроен на stale job после 600
  секунд с интервалом запуска 300 секунд. Это не public API SLA и не должно
  попадать в MCP guidance без подтверждения Vetmanager.
- Подтверждено source + real probes: `/data` разрешён для `saved` и
  `existing_report_matched`; inline cap — 10000 строк; AI reports создаются с
  `allow_rest_api=1`.
- Подтверждено source history + real probe: `findStaleInProgress()` намеренно
  включает interactive statuses `needs_confirmation` и `ready_to_save` в
  cleanup selection, чтобы abandoned job не блокировали dedupe бессрочно;
  каждые 300 секунд записи старше 600 секунд переходят в
  `failed/PREVIEW_FAILED`. При штатной периодичности cleanup фактическое окно
  истечения составляет примерно 600–900 секунд: запись становится stale после
  600 секунд и ждёт ближайший запуск task до 300 секунд. Это current upstream
  policy, но не опубликованный public API contract/SLA: MCP не должен обещать
  пользователю это время confirm/save, пока Vetmanager не подтвердит TTL и не
  добавит metadata.
- Подтверждено source: оба export 403 guards tenant-global, а не scoped to
  `report_id`: non-terminal REST export возрастом до 30 минут выдаёт
  `Report creating in progress`; любой REST export возрастом до 10 минут —
  `You can not run a report more than 10 minutes`. API не возвращает stable
  code, `retry_after` или already-created `report_file_id`.
- User-directed fallback, source-backed: после любого из этих двух
  распознанных 403 MCP рекомендует ждать 30 минут и выполнить одну новую
  `StartReport` попытку. Это не automatic retry, не `retry_after` от API и не
  гарантия успеха: параллельные или немедленные повторы запрещены.
- Full API handoff отправлен в Bitrix24 чат `Roadmap API`, message `#434805`.
  Вопросы queue worker, `tasks_serialized` и global Report Constructor state
  находятся у Vetmanager; MCP не имеет к ним доступа.

## Проверенные API-факты

- `artifacts/vetmanager_openapi_v6.json` публикует
  `GET /rest/api/report/StartReport` и `GET /rest/api/report/reportFile`, но
  не описывает их report-specific параметры, состояния и 403 taxonomy.
- `POST /rest/api/report-ai-job`, `GET /{id}`, `GET /{id}/data`, confirm/save
  — custom Report AI contract, подтверждённый source + real probes.
- `intent_text` ограничен 20000 символами; `limited=true` означает, что total
  превышает inline cap 10000. Эти значения заменили historical 1000 limits.
- `save_report_ai_job_as_report` — единственный write tool и требует
  `report_ai.write`; Analytics preset содержит этот narrow scope.

## Scope

### In scope

1. Зафиксировать upstream response по worker queue, stale cleanup и export 403
   taxonomy в PRD/AssumptionLog без PII, credentials, raw SQL или export URLs.
2. Сверить все Report AI tool descriptions, helper и README с подтверждённым
   контрактом: async queue, bounded polling, readable states, `20000` /
   `10000`, `limited=true`, explicit save и safe export retry.
   Source + real-probe подтверждённая редакция может быть выпущена независимо
   от нового upstream endpoint: statuses `queued` / `recognizing` /
   `building_preview` вместо ложного `processing`; interactive
   `needs_confirmation` / `ready_to_save` нужно обрабатывать без отложенного
   обещания срока, потому что API не отдаёт expiry metadata; export 403 —
   tenant-global temporary guard без `retry_after`, поэтому повторный
   `StartReport` не запускается автоматически; по прямому решению пользователя
   для двух known 403 разрешена одна новая попытка после 30 минут.
3. Внести только MCP-изменения, которые не зависят от непроверенных обещаний
   upstream, и покрыть их targeted unit/mock + opt-in real tests.
4. После upstream исправления или контракта повторить test-contour probes,
   проверить production feedback/known issue и выполнить deploy/smoke только
   для фактически внесённых MCP-изменений.

### Вне scope

- Исправление Vetmanager worker, `tasks_serialized`, cleanup или Report
  Constructor из этого репозитория.
- Изменение состояния production feedback/known issues до подтверждения
  причины и воспроизводимой проверки.
- Автосохранение `ready_to_save` report из read-looking MCP tool.
- Повторный `StartReport` как способ polling, скрытый retry либо немедленный/
  параллельный retry.
- Вывод raw SQL, PII, API keys, tenant identifiers или export locators в logs,
  metrics, PRD или ToolError.

## Архитектурное решение

### Проблема

MCP может наблюдать symptom (`queued`, 409, 403), но не может достоверно
диагностировать internal worker или global Report Constructor blocker. Неверная
подсказка приводит либо к бесконечному polling, либо к duplicate export, либо к
ложному утверждению, что API permanently unsupported.

### Варианты

1. Сразу менять MCP и считать любую долгую очередь transient.
   - Минус: скроет stuck worker и может закрепить неверный retry.
2. Не менять MCP до ответа Vetmanager.
   - Плюс: не искажает ownership; минус: известные описательные уточнения ждут
     дольше.
3. Разделить работу: сейчас зафиксировать evidence и поправить только
   подтверждённые descriptions; после ответа добавить точные codes/retry.
   - Плюс: точность без предположений; минус: две итерации.

### Выбранное решение

Выбран вариант 3. MCP сохраняет current state-machine guardrails и добавляет
только factual guidance. Queue diagnostics, retry policy и export error mapping
расширяются лишь после ответа Vetmanager, который назовёт stable API fields или
подтвердит отсутствие таких полей.

Уточнение scope `211.3`: можно выпустить wording, который описывает уже
проверенные текущие API responses и отсутствие metadata, но нельзя называть
внутренние `600`/`300` секунд public SLA, добавлять client-side retry automation
или менять wire payload. Это минимальный вариант, который уменьшает ложные
ожидания без предположения о будущем upstream contract.

Уточнение user-directed fallback: source guards имеют максимальное окно 30
минут от создания REST export. Поэтому для двух exact 403 текстов допустима одна
новая попытка после 30 минут. Это manual/deferred action следующего agent turn,
а не фоновая задача MCP и не API SLA.

### Инварианты

- Rows остаются доступными только для `saved` / `existing_report_matched`, пока
  upstream не введёт другой явно подтверждённый contract.
- `save_report_ai_job_as_report` остаётся явным write action.
- `StartReport` выполняется один раз на export attempt; polling идёт только по
  полученному `report_file_id`.
- После двух known 403 новая export attempt допускается не ранее чем через 30
  минут; она одна, не параллельна первой и не запускается автоматически.
- Tool descriptions не называют `queued` успешным результатом и не обещают
  время готовности, которого upstream не отдаёт.
- Изменения не ослабляют scope checks и не раскрывают sensitive data.

### Rollback / fallback

Если Vetmanager не добавит stable diagnostics, MCP использует bounded polling
и честное указание, что причина недоступна клиенту. Если upstream contract
изменится, MCP сохраняет raw safe status/HTTP classification и обновляет только
проверенные descriptions/tests. При ambiguous 403 MCP не создаёт duplicate
export и предлагает retry позже.

Architecture Critique: пройден для безопасного scope `211.3`. Он подтвердил,
что runtime не использует устаревший `processing`, а `StartReport` уже вызывается
с `retry=False`; изменения ограничены wording и safe error mapping. Новый review
обязателен перед любым расширением API contract после `211.2`.

## Декомпозиция

1. `211.1` PRD/research/handoff: собрать и отправить evidence, создать PRD и
   зафиксировать исходные API факты/ownership boundary. ≤2 ч.
2. `211.2` Upstream contract decision: получить ответ Vetmanager, подтвердить
   каждый новый API claim на test contour и зафиксировать ownership. ≤2 ч.
3. `211.3` Contract descriptions/mapping: обновить tool descriptions, helper,
   README и safe mapping только по подтверждённым facts; добавить regressions.
   Допустимы source + real-probe facts из уточнения scope; новые API fields,
   TTL/SLA claims и retry automation требуют завершённой `211.2`. ≤150 LOC.
4. `211.4` Real verification/closure: targeted + full Docker tests, opt-in real
   probes, audit, reviews, deploy/smoke и closure feedback. ≤2 ч.

## Acceptance criteria

1. Vetmanager подтверждает intended TTL/policy для `needs_confirmation` /
   `ready_to_save` и результат повторной real probe; ответ также привязан к
   incident evidence либо явно фиксирует отсутствие machine-readable
   queue/export diagnostics.
2. Все user-facing Report AI descriptions используют `20000` для intent и
   `10000` для inline rows; не содержат historical `1000` claims.
3. Descriptions разделяют `queued`, `ready_to_save`, `saved` и
   `existing_report_matched`; не обещают rows или same-turn result раньше
   допустимого статуса.
4. Export description объясняет polling по `report_file_id`; two known 403
   разрешают одну новую attempt через 30 минут, а ambiguous 403 остаётся
   bounded/temporary guidance без этого срока.
5. Tests проверяют утверждённый wire contract, error classification и отсутствие
   скрытого `/save` или sensitive data в logs.
6. Real probe подтверждает каждый новый upstream claim до его публикации в MCP.

## Текущее состояние

Безопасные части `211.3` и `211.5` завершены по source + real-probe фактам.
Для двух exact export 403 опубликована только user-directed рекомендация:
выждать 30 минут и выполнить одну новую попытку `StartReport`. MCP не запускает
её автоматически, немедленно или параллельно; это не `retry_after` и не SLA.

`211.2` переведена в внешний API backlog: без ответа Vetmanager нельзя
публиковать TTL/SLA, новые API fields, queue diagnostics или автоматический
retry. Завершение Stage 211 не означает, что upstream contract получен или что
эти ограничения устранены.

Partial release выполнен для SHA `e004860`: GitHub Tests `30914997709` и Deploy
Prod `30915283135` завершились successfully, production `/healthz` и `/readyz`
вернули `ok`. Следующий release SHA для `211.5` дополнит эту запись после CI и
production smoke.
