# Этап 163. Historical API key literal redaction

## Контекст

Security/privacy audit 2026-05-17 обнаружил в tracked historical notes literal старого/test `devtr6` API key. Это противоречит `artifacts/prd-vetmanager-mcp-ru.md` §4.2.11-4.2.12: Vetmanager credentials не должны раскрываться в логах, ошибках и артефактах проекта, а тестовые значения не должны быть захардкожены.

Пользовательское решение: historical API literal убрать; security notes, review artifacts и исправленные замечания не прятать. Общий cleanup stage не нужен.

Stage 162 остаётся `todo`, но Stage 163 взят раньше как user-directed critical security/privacy priority.

## Цель

Удалить конкретный API-key-like literal из текущего tracked tree, сохранив диагностический смысл записи и видимость security notes/review artifacts.

## Scope

- Current-tree redaction в tracked файлах.
- Проверка отсутствия конкретного literal после правки.
- `scripts/check_no_historical_api_key_literal.py`: hash-based проверка конкретного historical literal без записи самого literal в tracked файлы. Скрипт хранит только SHA-256 fingerprint, ищет token-like значения в indexed/untracked non-ignored files, при совпадении печатает только `file:line` и никогда не печатает literal.
- Pattern scan tracked tree на API-key-like literals с triage совпадений.
- Проверка, что security note остаётся видимым и не превращается в удаление истории.
- `artifacts/security/stage-163-pattern-scan-triage.md`: triage artifact для remaining pattern-scan matches; green criterion — нет unclassified matches.
- AssumptionLog запись о решении current-tree redaction vs git-history rewrite.

## Out of scope

- Git history rewrite. Он ломает shared history и требует отдельного coordinated secret incident process. Stage 163 обязан явно записать residual exposure: literal остаётся доступен через git history у всех, кто уже имеет доступ к истории; current-tree redaction не удаляет historical disclosure.
- Скрытие или удаление review/security artifacts.
- Ротация ключа внутри Vetmanager: если ключ мог быть валиден, это external operator action, а не repo-only fix. Stage 163 должен либо зафиксировать operator confirmation/invalid evidence, либо вынести unresolved rotate/revoke action в Roadmap/AssumptionLog.
- Stage 164 OpenAPI PII sanitization и Stage 165 findings inventory.

## Acceptance criteria

- Hash-based check конкретного historical literal возвращает 0 совпадений в indexed/untracked non-ignored tree, при этом сам literal не записывается ни в один tracked файл, включая PRD/Roadmap/tests/script/AssumptionLog.
- Pattern scan по tracked tree выполнен; `artifacts/security/stage-163-pattern-scan-triage.md` классифицирует remaining matches как sanitized placeholders, known non-secret hashes/commit ids, Stage 164 scope, либо Stage 165/follow-up. Green criterion: no unclassified matches.
- Историческая запись в `AssumptionLog.md` остаётся и объясняет в одной строке, что для `devtr6` с `<redacted historical devtr6 API key>` API вернул `Invalid or missing API key`.
- `Roadmap.md` Stage 163 отмечает завершённые пункты.
- `AssumptionLog.md` фиксирует:
  - что redaction выполнен в current tree;
  - что git-history rewrite не выполнялся в этом этапе;
  - что literal всё ещё может быть доступен через git history/blame/forks/caches, а effective mitigation для валидного ключа — rotate/revoke;
  - что security notes/review artifacts не скрывались;
  - что сделано с rotate/revoke risk: подтверждение invalid/rotated, либо explicit follow-up;
  - результат Spark-review и strong review.
- `git diff --check` проходит.

## Проверки

Red:

```bash
python3 scripts/check_no_historical_api_key_literal.py
git grep -nE '([[:xdigit:]]{32}|[A-Za-z0-9_-]{40,})' -- ':!artifacts/vetmanager_openapi_v6.json'
```

Green:

```bash
python3 scripts/check_no_historical_api_key_literal.py
git grep -nE '([[:xdigit:]]{32}|[A-Za-z0-9_-]{40,})' -- ':!artifacts/vetmanager_openapi_v6.json'
rg -n "redacted historical devtr6 API key" AssumptionLog.md
rg -n "Invalid or missing API key" AssumptionLog.md
rg -n "Stage 163 rotate/revoke status|git history residual exposure|no unclassified matches" AssumptionLog.md artifacts/security/stage-163-pattern-scan-triage.md
git diff --check
```

## Review gates

- Spark PRD review: `gpt-5.3-codex-spark`, review-only.
- Strong PRD review: Claude Opus, review-only, принять только важные и проверяемые findings.
- Spark committed-diff review before push.
- Strong committed-diff review before push.

## Simplicity decision

Самое простое корректное решение: заменить один literal на placeholder и не переписывать историю в рамках этого этапа. Это закрывает current-tree exposure без риска сломать shared history. Если позже подтвердится, что ключ оставался валидным, правильная remediation — revoke/rotate на стороне `devtr6`, а не попытка “спрятать” уже опубликованные commits.
