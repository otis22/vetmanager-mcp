# Этап 425 — active-account gate для браузерной сессии

Дата: 20.10.2026. Источник: `artifacts/review/2026-10-20-full-stage-420.md`, R5.

## Проблема и цель

Подписанная cookie содержит account id, но после деактивации владельца обработчики кабинета продолжают читать данные и менять интеграцию. Новая проверка должна отклонять все защищённые browser routes и OAuth consent при неактивном аккаунте. Runtime bearer auth и его правила не меняются.

## Проверенные факты

`web.py:_get_account_id_from_request` только декодирует cookie. `web_routes_account.py` проверяет отсутствие id, а `web_routes_oauth.py` использует тот же helper для consent. `web_auth.authenticate_account` уже требует `ACCOUNT_STATUS_ACTIVE`. Текущая схема `accounts.status` разрешает только `active`; для реального сценария отключения нужна миграция с `inactive`. Это состояние не смешиваем с `archived_at` (архивирование метрик).

## Покрытые маршруты

`GET /account`, `POST /account/agent-feedback`, `POST /account/integration`, `POST /account/integration/reauth`, `POST /account/tokens`, `POST /account/tokens/{token_id:int}/revoke`, `POST /account/oauth-grants/{grant_id:int}/revoke`, `POST /account/telemetry/token-copied`, `POST /account/telemetry/motivator-shown`, `POST /account/telemetry/example-copied`, `GET /account/activation-status`, `GET /oauth/authorize`, `POST /oauth/authorize/consent`.

Публичные регистрация/логин/выход, OAuth discovery/register/token, export download и MCP bearer endpoint вне browser gate. `auth/bearer.py:287` уже требует active Account. Export download проверяет статус выдавшего токена/grant, но не Account; ранее выданные OAuth/export доступы составляют отдельный остаточный риск и требуют отдельного этапа, поскольку здесь запрещено менять bearer auth и задан scope browser+consent. OAuth code, выданный до деактивации, также вне этого gate.

## Архитектурное решение

Проблема: каждый обработчик сейчас принимает id из cookie; поштучная проверка даст пропуски. Выбранная точка — общий decorator `_observed_custom_route` в `web.py`: для `/account` и `/account/*` и ровно двух OAuth authorize маршрутов при валидной cookie загрузить `Account.status` из БД до вызова handler. `read_account_session_token` возвращает `None` для отсутствующей, неверной и истёкшей cookie, и старый login flow остаётся. При `status != active` или исчезнувшем Account вернуть 403 страницу «Аккаунт отключён. Обратитесь к администратору», удалить session cookie, `Cache-Control: no-store`. Для JSON telemetry и activation poll вернуть JSON 403 `account_inactive`; JS poll перенаправит на страницу отказа или покажет текст. Для OAuth consent — отказ без показа consent и без выдачи code. Если авторизация уже начата, 403 безопаснее redirect на внешний callback до проверки статуса; клиент получит отказ завершения.

Варианты: проверка в каждом handler проще локально, но легко забыть новый маршрут; middleware по всем путям шире нужного и рискует затронуть bearer. Общий decorator совпадает с существующей регистрацией и ограничивает scope. Guard тест сопоставляет зарегистрированные browser-session routes с явным ожидаемым списком и ломается при добавлении неучтённого маршрута; параметризованная проверка каждого маршрута подтверждает 403. Инварианты: gate действует перед чтением кабинета и всеми мутациями; неактивная cookie удаляется; bearer auth не меняется. Допускается узкое окно между входным gate и завершением уже начатого запроса, который совпал с административной деактивацией; исключение этой гонки потребует транзакционной блокировки всех мутаций и отдельного scope. Rollback кода при наличии inactive rows недопустим: сначала остановить browser traffic или вернуть gate, затем принять явное решение о статусах. Downgrade схемы запрещён при inactive rows; он не активирует их автоматически.

Миграция `accounts.status` расширяет именованный CHECK `ck_accounts_status` с `active` до `active,inactive` через batch alter (SQLite rebuild, PostgreSQL constraint rewrite); upgrade не меняет существующие записи. SQLAlchemy `ACCOUNT_STATUSES` меняется вместе с миграцией. SQLite migration test сверяет связанные строки до/после rebuild и проверяет работу с foreign keys; downgrade с inactive rows отказывает до DDL. Административной UI-команды деактивации в данном этапе нет: стендовый сценарий устанавливает статус напрямую в тестовой БД, а production изменение аккаунтов остаётся вне scope. Нельзя откатывать только gate при наличии inactive rows; rollback требует решения владельца о восстановлении статусов или сохранении защитного gate до нового исправления.

Architecture Critique и PRD-review объединены: сильная пара проверяет границу auth, список маршрутов, миграцию, UX, red/green и rollback до реализации.

## Подзадачи и критерии

1. 425.1 (≤2 ч / ≤150 строк): этот PRD и гейты; схема/миграция как предпосылка красного теста; integration guard: создать browser session, затем установить `inactive` в БД и показать красным, что GET кабинета даёт 200 и POST integration меняет connection. Guard также проверяет 403, понятное сообщение и удаление cookie после исправления. Затем расширить тест до инвентаря всех защищённых маршрутов и доказать красным, что при удалении gate проверка падает.
2. 425.2 (≤2 ч / ≤150 строк): единый gate, фокусные web/OAuth/migration tests, живой локальный ASGI web-прогон с кодами; аудит, committed diff гейт, mock+real suite по финальному SHA, push dev-ветки и зелёный Tests CI. Выпуск = зелёный CI ветки; пост-релизные проверки после мержа.

Стенд для live web — локальный SQLite/ASGI с тестовым аккаунтом и mocked Vetmanager connection verification; реальный Vetmanager не нужен, так как отказ происходит до upstream. `TEST_DOMAIN`/`TEST_API_KEY` применяются только для отдельного обязательного real suite, его контур выбирается до запуска.
