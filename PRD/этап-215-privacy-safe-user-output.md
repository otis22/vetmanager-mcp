# Этап 215. Privacy-safe выдача сотрудников и клиентов

## Цель

Закрыть feedback report `#39`: ограничить выдачу сотрудников и убрать
паспортные данные клиентов без изменения согласованных бизнес-сценариев.

## Проверенные факты

- `tools/user.py` вызывает `/rest/api/user` через `crud_list` в обычной и
  name-search ветках, а `/rest/api/user/{ID}` через `crud_get_by_id`; до этапа
  ответы возвращаются без projection.
- Подтверждённый пользователем backend source of truth —
  `rest/protected/models/User.php::attributeLabels` Vetmanager. Полная сущность:
  `id`, `last_name`, `first_name`, `middle_name`, `login`, `passwd`,
  `position_id`, `email`, `phone`, `cell_phone`, `address`, `role_id`,
  `is_active`, `calc_percents`, `nickname`, `last_change_pwd_date`, `user_inn`.
  Он приоритетнее OpenAPI/reference, где также упоминаются непроверенные для
  backend-модели computed-поля.
- `ERestController::outputHelper` Vetmanager (проверен пользователем, line 497)
  задаёт точный конверт для list и single-record ответов:
  `data = {totalCount, user}`. `crud_list`, `crud_get_by_id` и `crud_update`
  не разворачивают его; сами metadata не добавляют.

## Scope

1. Добавить в `tools/user.py` closed allowlist и единый projection helper для
   каждой точки выдачи пользователя: обычный `get_users`, name-search
   `get_users`, `get_user_by_id` и ответ `update_user`.
2. Сохранять только аналитически обоснованные поля:
   - `id`, `last_name`, `first_name`, `middle_name`, `nickname`, `position_id`,
     `role_id`, `is_active`, `email`, `phone`, `cell_phone` — идентификация,
     кадровые срезы и согласованные Владимиром контакты сотрудников.
3. Исключить `login`, `passwd`, `last_change_pwd_date`, `address`, `user_inn`,
   `calc_percents`: credential/auth metadata, адрес (не входит в согласованные
   контакты), персональный налоговый идентификатор и данные о вознаграждении.
4. В общем wrapper регистрации MCP-инструментов рекурсивно удалять
   `passport_series` и staff auth/compensation fields `passwd`, `login`,
   `last_change_pwd_date`, `user_inn`, `calc_percents` из каждого результата
   до выдачи модели. Это покрывает прямые client paths, вложенные
   `client`/`owner`/staff и инструменты с прямым `VetmanagerClient`, которые
   обходят `crud_*`; file-local denylist'ы не дублировать. Для вложенных staff
   намеренно выбран denylist: контекстные поля счёта/госпитализации нужны
   сценариям, поэтому allowlist прямых user tools здесь применять нельзя.
5. Сохранить transport envelope целиком независимо от `success` и всегда
   проецировать user records внутри `data`, в том числе во вложенных и error
   payload. Под контрактным ключом `user`/`users` projection безусловна и не
   зависит от набора полей записи. `totalCount` сохраняется во всех формах.
   Неизвестная форма `data` пропускается дословно и фиксируется штатным runtime
   logger; на неё не распространяется эвристическая projection. Прямые ответы
   Успешные `get_user_by_id` и `update_user` сначала обрабатывают контрактный
   `data.user`/`data.users`; bare record поддерживается только как legacy
   fallback. Неуспешный diagnostic `data` проходит без изменений с warning.
6. Добавить test-first регрессии: все точки выдачи не отдают `passwd`/`login`
   и сохраняют требуемые аналитические поля. Отдельно покрыть name-search
   ветку, поскольку она формирует ответ локально, и дословный passthrough
   неизвестной формы `data` с runtime warning.
7. Провести read-only аудит остальных callers `crud_list`; не менять их в этом
   этапе, а перечислить результат в handoff.

## Out of scope

- Изменение Vetmanager API, входного контракта `update_user`, иных tools или
  production/SSH действий.
- Глобальная sanitization в `crud_helpers`: разные сущности требуют отдельного
  contract-aware allowlist.
- `get_suppliers`: ИНН и банковские реквизиты остаются в выдаче по явному
  решению Владимира для его рабочих сценариев; это не дефект данного этапа.

## Декомпозиция

1. Создать failing regression tests для list, name-search и get-by-id
   projection (≤150 LOC).
2. Реализовать минимальный локальный helper в `tools/user.py` и довести тесты
   до green (≤150 LOC).
3. Проверить полный test contour, аудит и review gates; обновить Roadmap и
   AssumptionLog после завершения (≤150 LOC).

## Простота решения

Один file-local helper и константы покрывают все три read paths; новый generic
sanitizer или изменение `crud_helpers` создали бы не подтверждённую abstraction
для единственной сущности. Closed allowlist проще проверять и безопаснее
denylist: поле, добавленное Vetmanager позднее, не появится в ответе до явного
аналитического обоснования.

`update_user` принимает разрешённые его входным контрактом контактные поля и
возвращает их только в рамках обновлённого allowlist, согласованного Владимиром.

### Принятый риск: неизвестная форма `data`

Владимир выбрал пропускать неузнанный `data` без изменений, сохраняя warning в
runtime log. Цена решения: если upstream одновременно нарушит подтверждённый
`outputHelper` contract, переименует ключ `user` и все поля user record, такая
запись может выйти целиком, включая `passwd`. Это редкое нарушение контракта.
Альтернатива — выпотрошить диагностические и error responses — регулярно
лишает агентов причины сбоя и мешает рабочим сценариям. Поэтому диагностическая
польза перевешивает этот принятый риск; следующий review не должен возвращать
fail-closed поведение без нового решения Владимира.

## Acceptance criteria

- Ни одна точка выдачи из `tools/user.py`, включая `update_user`, не возвращает
  `passwd` или `login`.
- В user-ответах нет перечисленных auth/access полей, включая
  `role.super`; нужные аналитические поля и pagination сохраняются.
- Во всех путях выдачи клиента отсутствует `passport_series`, а остальные
  клиентские поля сохраняются, включая `get_debtors` и owner в
  `get_pet_profile`; это же правило действует для вложенных owner/client в
  результатах любых MCP-инструментов.
- Вложенные staff objects не содержат `passwd`, `login`,
  `last_change_pwd_date`, `user_inn`, `calc_percents`; прямые user tools
  сохраняют свой более строгий analytics allowlist.
- `get_suppliers` сохраняет ИНН и банковские реквизиты по явному решению
  Владимира.
- Все targeted и полный mock test contours проходят.
- В финальном handoff перечислены другие прямые `crud_list` passthrough и их
  потенциальные типы утечек без изменения их поведения.
