# Этап 130. Token presets + depersonalized bearer tokens

## Контекст

Нужно упростить настройку bearer token: не делать `custom`-ACL и не вводить права per-tool. Источником истины остаётся текущий `scopes_json`; UI должен давать только понятные preset'ы. Параллельно нужен режим деперсонализированного токена, который меняет формат ответа, но не сами права доступа.

## Цель

Добавить preset-based выпуск bearer token (`full_access`, `read_only`, `frontdesk`, `doctor`, `finance`, `inventory`) и отдельный флаг `is_depersonalized`, при котором ответы MCP централизованно очищаются от явных персональных данных.

## Матрица preset'ов

Источник истины прав остаётся `scopes_json`; preset хранится как user-facing policy и разворачивается в existing scopes.

Инвариант для `full_access`: это всегда полный `SUPPORTED_TOKEN_SCOPES` на момент выпуска токена. Появление нового scope в коде не меняет уже выпущенные токены задним числом; новые `full_access` token'ы получают полный актуальный набор на момент issuance.

| Preset | Scopes |
|---|---|
| `full_access` | полный `SUPPORTED_TOKEN_SCOPES` на момент выпуска токена |
| `read_only` | `admissions.read`, `analytics.read`, `clients.read`, `finance.read`, `inventory.read`, `medical_cards.read`, `pets.read`, `reference.read`, `users.read` |
| `frontdesk` | `admissions.read`, `admissions.write`, `clients.read`, `clients.write`, `finance.read`, `messaging.write`, `pets.read`, `pets.write`, `reference.read`, `users.read` |
| `doctor` | `admissions.read`, `medical_cards.read`, `medical_cards.write`, `pets.read`, `reference.read`, `users.read` |
| `finance` | `clients.read`, `finance.read`, `finance.write`, `reference.read` |
| `inventory` | `inventory.read`, `inventory.write`, `reference.read` |

Отдельно проверить и покрыть тестами спорные tool'ы расписания/слотов/нагрузки: `get_doctor_free_slots`, `daily-schedule`, `doctor-workload` должны опираться только на scopes своего preset mapping, без скрытых per-tool исключений. Базовый expectation v1: `frontdesk` имеет operational доступ к записи/слотам, `doctor` — read-only доступ к расписанию врача/пациента, `read_only` — только read-path.

## Scope

1. Добавить token policy флаг `is_depersonalized` и user-facing preset; существующие токены мигрировать как `preset=full_access`, `is_depersonalized=false` без изменения уже сохранённых scopes.
2. Обновить `/account`: preset selector + checkbox деперсонализации; редактирование уже выпущенного токена не требуется, только выпуск нового.
3. Для новых токенов выдавать scopes строго из выбранного preset'а; только `full_access` получает полный набор scopes. Перевыпуск legacy token'а как нового `full_access` token'а считается осознанным действием и может расширить права до полного актуального набора; это должно быть явно показано в UI.
4. Ввести единый registry `tool -> required scopes` как source of truth для token access policy. Новый tool не может задавать права локально/неявно и не может быть добавлен без записи в registry.
5. Добавить CI/test gate, который падает при появлении зарегистрированного tool без access mapping в registry.
6. Добавить preset coverage tests поверх этого registry: `read_only`, `frontdesk`, `doctor` и другие preset'ы проверяются against expected доступность/недоступность tools.
7. Реализовать единый centralized sanitizer через единый wrapper над зарегистрированными tools/runtime response path; точечные правки отдельных tool'ов запрещены.
8. Поведение sanitizer при ошибке — fail-closed для depersonalized token: клиент получает явную MCP/runtime error c безопасным сообщением `Depersonalization failed.`; исходный payload не возвращается. Ошибка пишется в существующие safe logs/metrics без raw PII.
9. Structured redaction опирается на concrete field names из `artifacts/api_entity_reference-ru.md` и работает рекурсивным обходом payload: строковые значения чувствительных ключей заменяются маской, объекты не заменяются целиком, а обходятся вглубь. Минимально покрыть поля клиента/владельца: `name`, `first_name`, `last_name`, `middle_name`, `fio`, `phone`, `cell_phone`, `email`, `address`, `client_name`, `owner_name`, `client`, `owner`.
10. Формат маскирования:
   - phone -> `[redacted-phone]`
   - email -> `[redacted-email]`
   - person/owner name -> `[redacted-name]`
   - address -> `[redacted-address]`
11. Free-text scrub применять только к whitelist-полям `description`, `diagnosis`, `treatment`, `comment`, `notes` и nested variants этих ключей.
12. В free-text искать только явные PII-паттерны:
   - ФИО/инициалы на кириллице и латинице
   - телефоны (включая `+7`, 10-11 digits, common separators)
   - email
   - конструкции `владелец ...`, `хозяин ...`, `owner ...`
   Адресные маркеры исключить из v1 free-text scrubber как слишком высокий риск false positive; адреса редактируются только структурно по ключам.
13. Логи и метрики не переписывать этим sanitizer'ом; для них действуют существующие redaction paths. Не допустить появления raw PII в новых audit/log полях этой feature.

## Не делать

- `custom`-режим выбора прав
- per-tool ACL
- глобальный regex scrub по всем строкам payload
- ML/NLP/NER для первой версии

## Верификация

- unit tests на mapping preset'ов и backward compatibility legacy token'ов
- tests на issuance UI/API
- tests на structured redaction и whitelist free-text scrubber
- e2e на обычный и depersonalized token

## Acceptance Criteria

1. Все 6 preset'ов имеют явный table-driven mapping на scopes и покрыты тестами.
2. Исторические токены продолжают работать с прежними scopes; migration не расширяет и не сужает их права.
3. Каждый зарегистрированный tool имеет явный access mapping в едином registry.
4. Появление нового tool без access mapping ломает тесты/CI.
5. Новый depersonalized token не возвращает raw phone/email/name/address в structured fields и whitelist free-text.
6. Обычный token не меняет формат ответа относительно текущего контракта.
7. Sanitizer применяется централизованно, а не через точечные правки отдельных tool'ов.
8. При ошибке sanitizer для depersonalized token клиент не получает исходный несанитизированный payload.
9. `get_doctor_free_slots`, `daily-schedule`, `doctor-workload` имеют явный preset-mapping и regression tests на отсутствие скрытых per-tool исключений.
10. Structured redaction не ломает shape ответа: объекты/списки/id/date поля сохраняют тип и структуру; маскируются только чувствительные строковые значения.
11. Sanitizer idempotent: повторный прогон не меняет уже замаскированный payload и не создаёт double-redaction noise.
12. Добавлены observability counters для rollout: `token_preset_issued_total{preset}` и `sanitizer_failures_total`.

## Rollout

1. Сначала migration + tests + hidden UI.
2. Затем выпуск новых preset-based token'ов без изменения существующих.
3. После smoke/e2e проверки включить depersonalized checkbox в UI.
4. Rollback: отключить UI выдачи новых preset/depersonalized token'ов; уже выпущенные preset/depersonalized token'ы продолжают работать по сохранённой policy, legacy token'ы продолжают работать без изменений.
