# Этап 174. Daily schedule pagination

## Контекст

Production feedback report `#14`: `get_daily_schedule` может вернуть только
первую страницу насыщенного дневного расписания. Сейчас tool принимает `limit`,
всегда отправляет `offset=0` в `/rest/api/admission`, возвращает
`returnedCount`, `totalCount` и `truncated`, но не даёт агенту безопасного
способа дочитать следующую страницу через тот же специализированный tool.

Stage 140 уже добавил явную truncation semantics, но намеренно оставил
`offset=0`. Stage 174 расширяет этот контракт без unbounded auto-fetch.

## Цель

Добавить в `get_daily_schedule` явную pagination page semantics: caller может
передать `offset`, получить текущую страницу и понять, есть ли следующая.
Существующий default first-page behavior сохраняется.

## Scope

В scope:

- добавить параметр `offset: int = 0` в `get_daily_schedule`;
- валидировать `limit/offset` тем же контрактом, что list tools:
  `limit 1..100`, `offset 0..10000`;
- передавать `offset` в `/rest/api/admission`;
- сохранить фильтры:
  - date window `[date 00:00:00, next_day 00:00:00)`;
  - active statuses через `status IN ACTIVE_ADMISSION_STATUSES`;
  - optional `doctor_id -> user_id`;
  - optional `clinic_id`;
- сохранить deterministic sort `admission_date ASC`;
- расширить response metadata:
  - `limit`;
  - `offset`;
  - `returnedCount`;
  - `totalCount`;
  - `has_more`;
  - `next_offset`;
  - `pagination_limit_reached`;
  - `pagination_stalled`;
  - `truncated`;
- сохранить `data.admission` и `data.totalCount` для backward compatibility.

Out of scope:

- автоматическая загрузка всех страниц;
- изменение `get_admissions`;
- изменение набора active statuses;
- production DB / `known_issues` updates после deploy, кроме финального
  связывания feedback `#14` как fixed после успешного smoke.

## Контракт ответа

`truncated = totalCount > offset + returnedCount`.

`next_offset_candidate = offset + returnedCount`.

`pagination_limit_reached = truncated && next_offset_candidate > 10000`.

`pagination_stalled = truncated && returnedCount == 0`.

`has_more = truncated && !pagination_limit_reached && !pagination_stalled`.

`next_offset = next_offset_candidate`, если `has_more=true`, иначе `null`.

`truncated` означает “текущая страница не покрывает все записи после offset”.
`has_more` означает “есть безопасный следующий `offset`, который не будет
отвергнут runtime-валидатором”. В обычном сценарии эти поля совпадают; на
границе `offset=10000` `truncated` может быть `true`, а `has_more=false`.
Если upstream возвращает пустую страницу при `totalCount > offset`,
`pagination_stalled=true`: агент не должен повторять тот же `offset`.

Если upstream вернул нечисловой/отсутствующий `totalCount`, helper сейчас
нормализует total через длину rows; Stage 174 не меняет этот общий helper.

## Acceptance criteria

1. `get_daily_schedule(date, limit=100, offset=0)` отправляет в Vetmanager
   `limit=100`, `offset=0`, date/status/doctor/clinic filters и sort
   `admission_date ASC`.
2. При upstream `totalCount=150`, `returnedCount=100`, `offset=0` response
   содержит `has_more=true`, `next_offset=100`, `truncated=true`.
3. `get_daily_schedule(date, limit=100, offset=100)` отправляет
   `offset=100`, возвращает `offset=100`, `has_more=false`,
   `next_offset=null`, `truncated=false`, если returned rows покрывают total.
4. Если `next_offset_candidate > 10000`, response не должен рекламировать
   unusable `next_offset`: `truncated=true`, `has_more=false`,
   `next_offset=null`, `pagination_limit_reached=true`.
5. Если `next_offset_candidate == 10000`, response должен вернуть
   `has_more=true`, `next_offset=10000`, потому что `offset=10000` валиден.
6. Если upstream вернул пустую страницу при `totalCount > offset`, response
   должен вернуть `truncated=true`, `has_more=false`, `next_offset=null`,
   `pagination_stalled=true`.
7. Invalid offset (`-1`, `10001`) rejected before upstream request.
8. Existing doctor/clinic/status/date filters unchanged.
9. `tools/list` schema exposes `offset` for `get_daily_schedule`.

## Tests

- Extend `tests/test_convenience_tools.py`:
  - first page pagination metadata;
  - second page sends `offset=100`;
  - invalid offset rejected before HTTP;
  - unusable next offset is not returned at the safe offset boundary;
  - exact `next_offset=10000` is allowed;
  - empty stalled page does not return the same `offset`;
  - filters/sort preservation.
- Add or extend schema assertion if existing `tools/list` tests do not cover
  `get_daily_schedule.offset`.

## Risks

- Some agents may still ignore `has_more`; descriptions/docs should use clear
  metadata names.
- `offset` pagination over a changing appointment list can race with concurrent
  schedule edits. Deterministic sort reduces duplicates/skips but cannot make
  external API pages snapshot-consistent.
