# Этап 215. Privacy-safe выдача сотрудников

## Цель

Закрыть feedback report `#39`: инструменты чтения сотрудников не должны
передавать модели credential, authentication/access metadata и персональные
поля, которые не нужны для аналитики.

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

## Scope

1. Добавить в `tools/user.py` closed allowlist и единый projection helper для
   каждой read-точки: обычный `get_users`, name-search `get_users` и
   `get_user_by_id`.
2. Сохранять только аналитически обоснованные поля:
   - `id`, `last_name`, `first_name`, `middle_name`, `nickname`, `position_id`,
     `role_id`, `is_active` — идентификация сотрудника и кадровые срезы,
     достаточные для аналитики.
3. Исключить `login`, `passwd`, `last_change_pwd_date`, `email`, `phone`,
   `cell_phone`, `address`, `user_inn`, `calc_percents`: это credential/auth
   metadata, частные контакты, персональный налоговый идентификатор и данные о
   вознаграждении; они не нужны для заявленной аналитики.
4. Сохранить transport envelope и pagination metadata, но не пробрасывать
   неизвестные поля объекта пользователя. Новые upstream поля поэтому не
   попадут в MCP-ответ автоматически.
5. Добавить test-first регрессии: обе read-ручки не отдают `passwd`/`login` и
   сохраняют требуемые аналитические поля. Отдельно покрыть name-search ветку,
   поскольку она формирует ответ локально.
6. Провести read-only аудит остальных callers `crud_list`; не менять их в этом
   этапе, а перечислить результат в handoff.

## Out of scope

- Изменение Vetmanager API, write-инструмента `update_user`, иных tools или
  production/SSH действий.
- Глобальная sanitization в `crud_helpers`: разные сущности требуют отдельного
  contract-aware allowlist.

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

## Acceptance criteria

- Ни одна read-ручка из `tools/user.py` не возвращает `passwd` или `login`.
- В read-ответах нет перечисленных non-analytic/auth/access полей, включая
  `role.super`; нужные аналитические поля и pagination сохраняются.
- Все targeted и полный mock test contours проходят.
- В финальном handoff перечислены другие прямые `crud_list` passthrough и их
  потенциальные типы утечек без изменения их поведения.
