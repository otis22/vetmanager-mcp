# PRD: Этап 26. Vetmanager auth mode #2: `user login/password -> token`

## Цель

Добавить второй способ подключения аккаунта к Vetmanager: оператор вводит
`user login` и `password`, сервис получает Vetmanager user token через
отдельный auth flow и затем использует этот token как runtime credential для
рабочей интеграции аккаунта.

## Что подтверждено локальными артефактами

- В продуктовых артефактах второй auth mode уже предусмотрен как часть целевой
  модели подключения аккаунта.
- В `artifacts/vetmanager_openapi_v6.json` есть `POST /token_auth.php` с
  summary `Get Token (by User Login & Password)`.
- В `artifacts/vetmanager_postman_collection.json` есть отдельный item
  `token_auth.php -> Get Token (by User Login & Password)`.
- Response schema в OpenAPI и Postman остаётся generic:
  `success`, `message`, `data`.

## Что пока не подтверждено локальными артефактами

- Точная форма request payload для `POST /token_auth.php`:
  неизвестно, это JSON, form-urlencoded или multipart.
- Точные имена полей запроса:
  локальные артефакты не доказывают, что это именно `login` и `password`,
  хотя это наиболее вероятная интерпретация summary.
- Требование `X-REST-API-KEY` для этого endpoint остаётся неоднозначным:
  в Postman item request header не содержит этот header, но example response
  inherited `originalRequest` всё ещё показывает глобальную security-схему.
- Форма успешного `data` для user token тоже не раскрыта локальными схемами.

## Решение для workflow

- `26.1` считается этапом уточнения контракта на уровне доступных локальных
  артефактов, а не этапом полной runtime-реализации.
- Для `26.2` принимается консервативное runtime assumption:
  пока локальные артефакты не показывают отдельный security header для user
  token, abstraction layer переиспользует `X-REST-API-KEY` как transport header
  и различает режимы через `auth_mode` и формат сохранённых credentials.
- Для `26.3` принимается временное UI assumption:
  кабинет на этом шаге принимает уже выданный `user_token`, а не выполняет
  login/password exchange сам. Автоматический exchange остаётся предметом
  следующих задач, когда контракт `token_auth.php` будет подтверждён лучше.
- Следующие задачи `26.2–26.4` должны строиться через отдельный abstraction
  layer, чтобы bearer runtime не зависел от конкретного Vetmanager auth mode.
- До появления real API proof нельзя жёстко вшивать payload/headers в way,
  который трудно будет скорректировать.

## Границы этапа

- `26.1` фиксирует подтверждённые факты и открытые вопросы по `token_auth.php`.
- `26.2` добавляет второй connection mode в внутренний auth abstraction layer.
- `26.3` добавляет web-настройку для user-token mode.
- `26.4` вводит runtime validation/test connection для этого режима.
- `26.5` проверяет bearer runtime independence от конкретного Vetmanager mode.
- `26.6` добавляет unit/mock/real smoke tests.

## Декомпозиция

### 26.1 Уточнение контракта
- Зафиксировать, что endpoint существует и предназначен для login/password flow.
- Отдельно перечислить недостающие contract details, которые не видны в
  локальных артефактах.

### 26.2 Auth abstraction
- Добавить второй `connection_mode` для account connection.
- Подготовить отдельный resolver, который умеет обменивать user credentials на
  runtime token.

### 26.3 Web cabinet
- Добавить в кабинет выбор auth mode.
- Добавить форму для user login/password flow без утечки секретов.

### 26.4 Validation
- При сохранении integration проверять, что сохранённый `user_token` проходит
  runtime probe на Vetmanager API.

### 26.5 Runtime compatibility
- Убедиться, что bearer runtime получает уже унифицированный auth context и не
  знает, из какого Vetmanager mode он был произведён.

### 26.6 Tests
- Добавить unit/mock tests второго режима.
- Добавить real smoke test, если локальный test harness позволяет безопасно
  прокинуть отдельные credentials.

## Критерии готовности для 26.1

- В репозитории есть отдельный PRD этапа 26.
- В PRD зафиксированы подтверждённые факты по `POST /token_auth.php`.
- В PRD явно отмечены недостающие детали request/response контракта.
- `Roadmap.md` и `AssumptionLog.md` синхронизированы с этим решением.
