# Report AI prompt helper for MCP agents — 2026-10-15

Use this helper before creating a Vetmanager Report AI job.

Your task is to convert the user's business question into a clear Russian `intent_text` for the Vetmanager report constructor. Do not write SQL. Do not invent database fields, custom directory values, statuses, tags, product groups, diagnoses, visit types, acquisition channels, or loyalty-card types.

## Короткий маршрут

1. Уточните вопрос только там, где выбор меняет результат. До вызова составьте
   русский `intent_text`: предмет отчёта, метрика или список, период и основание
   даты, фильтры, группировка и сортировка. Не пишите SQL и не выдумывайте поля.
2. Вызовите `create_report_ai_job(intent_text=..., wait_seconds=30)` один раз.
   Сохраните `job_id`; при ожидании вызовите `get_report_ai_job(job_id=job_id, wait_seconds=30)`
   для того же job. Не создавайте дубль из-за долгого ожидания.
3. При `needs_confirmation` проверьте кандидата и подтвердите подходящий либо
   один раз отклоните неподходящий. При `ready_to_save` сохраните отчёт под
   осмысленным названием; при `existing_report_matched` не сохраняйте повторно.
   Превью помогает принять решение о структуре, но не даёт живых данных.
4. После save/confirm прочитайте реальные строки через `get_report_ai_job_data`.
   Затем оцените пригодность для исходного вопроса:
   `rate_report_ai_job(job_id, score, intent_text)`; `score` и `intent_text`
   обязательны, `comment` необязателен. Для `failed` с `job_id` финальный шаг —
   оценка `score=1`; без job_id оценить вызов нельзя.

Report AI предпочитает деперсонализированный вывод: ФИО и телефоны могут
намеренно заменяться плейсхолдерами даже при токене с ПД. Это ожидаемое
поведение, но не гарантия очистки каждого отчёта. Оценивайте решение задачи
по доступным данным; не снижайте оценку только из-за отсутствия ПД, если
задача решена. Если отсутствуют нужный критерий, фильтр, агрегат или ФИО/
телефон, необходимые для контактной задачи, оцените фактическую пригодность
и объясните человеку ограничение.

## Как сформулировать `intent_text`

Назовите зерно результата: счёт или позиция счёта, платёж, приём,
лабораторная заявка или анализ. Для каждой метрики назовите роль колонки и
единицу: «сумма оплат, ₽», «число приёмов, шт.». Укажите основание периода,
фильтры и группировку. При уточнении существующего вопроса сохраняйте уже
согласованные метрику, фильтры, период и группировку; меняйте только то,
что назвал пользователь. После save/confirm сверяйте реальные строки с
вопросом: колонки, период, клинику, зерно и единицы. Статус `saved` сам по себе
не подтверждает правильность отчёта.

- Write in Russian.
- State the main Vetmanager concept: invoices, payments, clients, pets, admissions, medical cards, goods, warehouse movements, users.
- State the metric or list fields.
- State filters, period, date basis, grouping, and sorting when relevant.
- Prefer non-personal output by default: internal IDs and aggregates instead of names, phones, email, chip numbers, card numbers, or employee logins.
- For contact lists, include names/phones only when the user explicitly needs contact action such as calling, messaging, reminders, or mailing.
- If the user asks for a list, request only the columns needed to answer the question.

## Report AI journey

1. После подготовки интента вызовите `create_report_ai_job(wait_seconds=30)` один
   раз. Вызов делает один POST и ограниченное ожидание статуса на сервере MCP.
   Если вернулось ещё обрабатываемое задание или timeout, сохраните `job_id` и
   вызовите `get_report_ai_job(job_id=job_id, wait_seconds=30)` для того же задания: это тоже
   один ограниченный вызов. При необходимости повторите его позже; не создавайте
   job заново и не запускайте ручную серию быстрых GET.
2. При `needs_confirmation` сравните кандидатов с фильтрами, периодом и
   группировкой. Выберите **одно** действие: `confirm_report_ai_job_candidate`
   для подходящего кандидата или `reject_report_ai_job_candidate` один раз,
   если подходящего нет. После reject читайте тот же job через
   `get_report_ai_job(job_id=job_id, wait_seconds=30)`; первый ответ ещё может содержать
   устаревший `needs_confirmation`, повторять reject автоматически нельзя.
3. При `ready_to_save` вызовите `save_report_ai_job_as_report` с осмысленным
   названием. Поле `title` в `next_action.call` — шаблон; замените его целью и
   периодом отчёта, буквальный шаблон не отправляйте. Затем читайте реальные
   строки через `get_report_ai_job_data`.
   После confirm статус `existing_report_matched` позволяет сразу вызвать
   `get_report_ai_job_data` без save. При неопределённом исходе save сначала
   перечитайте тот же job, не повторяйте запись автоматически.
4. `preview_summary` и `preview_example_row` — только образец для решения о
   запуске полноценного отчёта, не живые данные клиники.
   Нельзя отвечать пользователю по превью, включая его числа, значения и
   вывод «данных нет».
   Для ответа используйте только реальные строки из `get_report_ai_job_data`
   после save или confirm.
5. После реальных строк вызовите `rate_report_ai_job(job_id, score, intent_text)`,
   передав тот же промпт, из которого строился отчёт. `intent_text` и `score`
   обязательны; `comment` необязателен:
   1 = отчёт даже не построился; 2 и выше — отчёт построился;
   2 = построился, но задачу почти не решил; 5–6 = решил частично;
   10 = задача решена полностью, ничего не пришлось добывать другими путями.
   Для failed job с `job_id` используйте 1; без `job_id` оценка невозможна.
   Оцените пригодность для исходного вопроса, включая необходимость добывать
   данные другими путями. При низкой оценке можно добавить короткий комментарий
   без ПД о том, что не хватило. Оценка сохраняется
   только в MCP и не влияет на отчёт в Ветменеджере.
   Отсутствие оценки не означает, что отчёт подошёл.

## Agent flow constraints

- Canonical MCP order: `get_report_ai_prompt_helper` → `create_report_ai_job` →
  `get_report_ai_job`, then confirm, save, read rows, or export according to the
  returned status.
- Report AI jobs are async. Use the bounded wait of create/get above; if the job
  is still pending after a bounded call, keep its `job_id` and check later.
- В замере аудита 14.10.2026 задания доходили до готовности за 6–10 секунд.
  Это наблюдение, не гарантия для каждого задания или контура. Если bounded
  ожидание вернуло queued, сохраните `job_id` и перечитайте тот же job позже.
- Один вопрос — один отчёт. Создавайте jobs последовательно.
- Дождитесь завершения предыдущего job, прежде чем создавать следующий. Не запускайте несколько отчётов одновременно.
- Если нужны несколько разрезов, сначала попробуйте один отчёт с нужной
  группировкой; если нужны отдельные отчёты, создавайте их по очереди. Не
  переносите замер одного задания на очередь из нескольких jobs.
- `ready_to_save` does not expose report rows. It exposes safe recognized structure and preview summary only.
- Rows are available only after `saved` or `existing_report_matched`.
- If rows are needed from `ready_to_save`, use an explicit save step with a meaningful report title.
- If status is `needs_confirmation`, confirm only a candidate with the same filters, period and grouping. If none fits, call `reject_report_ai_job_candidate` once and use bounded `get_report_ai_job(job_id=job_id, wait_seconds=30)` on the same job until `ready_to_save` or `failed`; the first status can still be `needs_confirmation`. Never repeat reject automatically after timeout or 409. After confirmation, rows are available through `get_report_ai_job_data` without saving a new report.
- `QUEUE_TIMEOUT` means the job failed after an hour in queue: stop checking it. `LLM_UNAVAILABLE` means provider timeout: wait at least five minutes, then retry the same intent only once. A `PREVIEW_FAILED` may contain SQL in the upstream diagnostic; use the MCP workaround and never quote raw SQL.
- `recognized.preview_example_row`, если присутствует, содержит намеренно
  выдуманные правдоподобные значения, а не данные клиники и не реальную строку.
  Используйте его только до получения реальных строк, чтобы проверить структуру
  таблицы: нужные ли колонки, их типы, группировку и соответствие ожидаемому
  отчёту. Если структура не совпала с ожиданием, переформулируйте `intent_text`
  до сохранения отчёта, а не получайте строки, чтобы обнаружить несоответствие
  потом. Никогда не пересказывайте значения preview пользователю: они выглядят
  настоящими, хотя выдуманы. Например, preview может показать «Собаки — 1250»,
  а реальные строки — «Кошки — 48»; preview выполнил задачу, если структура
  таблицы совпала.
- `intent_text` can be up to 20000 characters. Longer is not better by itself: keep the request structured around period, filters, metrics, grouping, and sorting.
- A saved report is visible in Vetmanager. Use concise titles that explain the question, period, and MCP origin, for example: `MCP debtors by negative balance 2026-06-15`.

## Clarifications

Ask a short clarification only when choosing silently would likely change the result. Do not over-warn the user and do not ask about every minor detail.

Clarify these cases before creating the job:

- Revenue, turnover, sales: если контекст требует фактических поступлений,
  уточните платежную базу даты и учёт возвратов/аванса. Для простой «выручки»
  действует дефолт исполненных счетов (начисление); вопрос «счета или деньги?»
  нужен лишь когда слова пользователя делают выбор существенным и дефолт не подходит.
- New clients: by client registration date or by first completed visit/purchase?
- Client balance/debt/advance: which balance sign means debt in this clinic, unless the user already specified negative or positive balance.
- Repeat visit: repeat within how many days, and for which domain: outpatient visit, hospitalization, revaccination.
- Clinic-specific directory values: exact product group, diagnosis, visit type, income/expense item, tag, acquisition channel, loyalty-card type.
- Contact data: whether the goal is contact action before adding names/phones/email.

If the user already gave a precise criterion, do not ask again. Example: "clients with negative balance" is precise enough; use balance `< 0` and label the column as balance/debt according to the request.

Если уточнить не у кого, выберите разумное умолчание, явно запишите его в
`intent_text` и назовите пользователю в ответе. Для выручки умолчание задано:
`Источник — выставленные счета со статусом «исполнен»`. Полученные деньги
(кассу) берите только тогда, когда пользователь спросил именно про кассу или
поступления.

## Empty results

Пустой результат — это результат, а не ошибка. Не пересоздавайте тот же job.
Сначала подходящим прямым read-инструментом проверьте, есть ли исходные записи
за период. Если записей нет, сообщите пользователю: «за период данных нет».
Если превью при `ready_to_save` показывает 0 строк, это ещё не результат
отчёта и не основание отвечать «данных нет». Сначала сравните структуру с
запросом и при необходимости проверьте исходные записи прямым read-инструментом
за тот же период и клинику. Реальные строки доступны только после save/confirm.

## Medical card text

Описание и рекомендации медкарт хранятся в HTML. Пустой на вид текст может
содержать `<div></div>`, поэтому условие пустоты для сырого поля может не
сработать. Формулируйте интент с учётом разметки: просите проверять смысловую
пустоту после удаления HTML, если конструктор это умеет. Для вывода выбирайте
короткие признаки вместо полного текста либо просите текст без разметки;
не печатайте сырой HTML в отчёт.

## Common anchors

- Revenue/sales/turnover: plain "выручка" defaults to executed invoices
  (accrual). Clarify invoices versus received payments only when context makes
  that choice material and the default does not fit; for actual cash receipts
  specify payment-date basis and treatment of refunds and advances.
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

## Лабораторные отчёты

- Дата создания заявки или зарегистрированного результата не доказывает время
  взятия пробы, загрузки или SLA: для этих выводов нужна отдельная временная
  отметка и проверка её смысла.
- Текущее значение показателя не является историей исправлений; для истории
  нужна подтверждённая последовательность версий.
- Отметка лабораторного экрана «оплачено» не доказывает получение денег.
  Для денежного факта сверяйте статус счёта и отдельные платежи.

## Статусы, деньги и время

- `accepted` — текущий обратимый статус записи на приём, не доказательство
  посещения и не оплата. Посещение подтверждайте отдельным фактом.
- Отрицательная исполненная запись платежа может быть возвратом; не называйте
  любую отрицательную строку возвратом без проверки назначения и связи.
  Применение ранее внесённого аванса к счёту не является новым приходом денег.
  Различайте дату платежа и дату счёта при выборе периода. Агрегат
  `get_revenue_summary(mode=received)` без отдельной сверки не доказывает
  исключение повторного учёта аванса.
- Складской остаток — количество, балансовый остаток — деньги. Одно название
  «остаток» не доказывает единицу; сверяйте источник, колонку и единицу до ответа.
- Экран уведомлений о сроке годности не равен списку партий; дата партии не
  даёт исторический остаток. Для исторического вывода нужна проверенная
  запись движения или снимок на дату.
- Плановая дата следующей вакцинации не дата проведённой вакцинации; текущий
  владелец питомца не доказывает, кто был владелец на дату события. Проверяйте
  запись события и историческую связь, если они доступны.

### Скидка и итог счёта

`invoice.discount` — процент скидки, `invoice.increase` — процент наценки,
`invoice.percent` — вычисляемое поле, а `invoice.amount` — рублёвый итог после
скидки и наценки. Для рублёвой скидки по позиции используйте суммы позиции
`invoice_document.default_price` и `price`: `default_price - price*((100-discount)/100)*((100+increase)/100)`.
Здесь `discount` и `increase` — проценты счёта; не суммируйте `invoice.discount`
как рубли и не умножайте суммы позиции повторно на `quantity`. Разница может
быть отрицательной при преобладании наценки. Для отчёта по скидкам явно
опишите эту метрику в `intent_text`, а результат проверьте с учётом округления.

## Вакцинации

Для одного пациента используйте прямые данные: `get_medical_cards(pet_id=...)`
для medicalCards и `get_vaccinations(pet_id=...)` для vaccinations. Для списка
по всей клинике сформулируйте `intent_text` для Report AI по таблице
`vaccine_pets`, указав период, клинику и нужные поля/группировку. Не собирайте
клиническую выборку многими per-pet вызовами без известного списка пациентов.

## Goods report workaround

For goods/product reports, ask for business columns such as product code, SKU/article, barcode when relevant, product title/name, group, quantity, revenue, cost, margin, and period grouping.
Do not ask Report AI to output a standalone `good.id` column. If an older Vetmanager contour or unresolved edge case still fails with an explicit `good.id` preview error, retry with "код/артикул/наименование товара" in Russian rather than `good.id`.
For goods sold through invoices, describe the business relation as "позиции счёта и связанные товары" without writing SQL.
Отчёт о составе комбинаций может завершиться известным дефектом ВМ с SQL-ошибкой. Не повторяйте тот же запрос; для одной комбинации используйте `get_good_combination` (позиции) и `calculate_good_combination_price` (цена), явно передавая `clinic_id` нужной клиники обоим инструментам.
Колонка Report AI «Текущий остаток на складе» суммирует остаток по всем складам базы и игнорирует фильтр клиники. Для остатка конкретной клиники используйте `get_good_stock_balance` и явно передайте обязательный `clinic_id` нужной клиники.

## Data and export

- `get_report_ai_job_data` returns JSON rows for `saved` or `existing_report_matched` jobs. Vetmanager caps this response at 10000 rows; `limited=true` means truncation.
- If `limited=true` or the total is close to 10000, avoid pasting the full table into chat. Narrow the report with period, filters, or aggregation when possible.
- `csv_export_url` — относительный путь апстрима, не готовая ссылка. Для
  выгрузки вызовите `get_report_ai_job_export` для сохранённого или совпавшего
  job либо `start_report_export` с известным `report_id`. Затем вызовите
  `get_report_export_download` с полученным `report_file_id` и используйте
  абсолютный `download_url`, который вернул MCP.

## Что делать после чтения справки

Если существенный критерий неясен, задайте короткий уточняющий вопрос. Иначе
сформулируйте `intent_text` и пройдите короткий маршрут выше до реальных строк
и оценки. Если отчёт не построился, следуйте ветке failed; не выдавайте
preview за результат. Для нескольких отдельных jobs выполняйте маршрут
последовательно и объединяйте только проверенные реальные результаты.
