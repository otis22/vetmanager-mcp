# Этап 155. IP mask UX & restrictive default

## Цель

Убрать «забыл mask = открытый токен» по умолчанию. После этого этапа `allowed_ip_mask` всегда строка (не NULL), wildcard `*.*.*.*` хранится явно (а не как NULL), и `get_allowed_ip_mask()` + сопутствующая dual-API логика удаляется как dead code.

## Контекст

Prod 2026-05-02 показал `token_auth_failed_ip_denied: 7 за 7d` — реальные denied события. Kimi-ревью F21: `ServiceBearerToken.get_allowed_ip_mask()` дефолтит к `*.*.*.*` для NULL → забывание mask делает токен открытым.

Текущее состояние (на основе чтения кода):

- **Schema**: `service_bearer_tokens.allowed_ip_mask: VARCHAR(64) NULL` (alembic 20260401_000005).
- **Model**: `ServiceBearerToken.allowed_ip_mask: Mapped[str | None]`. Метод `get_allowed_ip_mask() -> str` возвращает `self.allowed_ip_mask or "*.*.*.*"` (storage_models.py:241-243).
- **Service**: `service_token_service.create_service_bearer_token`/`issue_service_bearer_token` (line 49-51) делает `if ip_mask is not None and ip_mask.strip() != "*.*.*.*": effective_ip_mask = validate_ip_mask(ip_mask)` — для wildcard или None сохраняет NULL в БД (даже когда web layer передал явный `*.*.*.*` после confirm checkbox).
- **Web form** (`web_routes_account.py:243-280`): empty mask → fallback на request_ip → если unknown, ValueError. Wildcard `*.*.*.*` без `confirm_wildcard_ip` → ValueError. Это уже restrictive по UX, но service слой потом разрушает явность, сохраняя NULL.
- **3 call sites** `get_allowed_ip_mask()`:
  - `service_token_service.py:79` — audit log payload `"ip_mask"`.
  - `web.py:343` — dashboard render dict `"ip_mask"`.
  - `auth/bearer.py:277` — IP enforcement: `if effective_mask != "*.*.*.*": ip_matches_mask(...)`.
- **`web_html.py:550`** делает `token.get('ip_mask', '*.*.*.*')` — это default на dict-уровне, не модель; останется как defensive fallback в шаблоне.

## Scope

### S1. Migration backfill + NOT NULL

Новая alembic миграция `20260503_000013_allowed_ip_mask_not_null.py`:

- `op.execute("UPDATE service_bearer_tokens SET allowed_ip_mask = '*.*.*.*' WHERE allowed_ip_mask IS NULL")` — backfill ВНУТРИ той же транзакции, что и ALTER COLUMN (alembic envelope гарантирует, single migration → single transaction в PG; SQLite использует batch).
- **Использовать `op.batch_alter_table` для совместимости с SQLite** (где `ALTER COLUMN` не работает напрямую) — pattern уже использован в `alembic/versions/20260426_000011_agent_feedback_possible_pii.py`:
  ```python
  with op.batch_alter_table("service_bearer_tokens") as batch:
      batch.alter_column(
          "allowed_ip_mask",
          existing_type=sa.String(64),
          nullable=False,
      )
  ```
- Без `server_default` — create-flow обязан явно ставить значение; новые rows с NULL запрещены NOT NULL constraint.
- Race-window mitigation: backfill UPDATE и ALTER в одной транзакции означает, что concurrent INSERT с NULL не может произойти (PG `BEGIN` envelope от alembic). Если кто-то всё же commit'нет NULL до начала миграции — backfill UPDATE его поймает.
- Downgrade: `with op.batch_alter_table(...) as batch: batch.alter_column("allowed_ip_mask", existing_type=sa.String(64), nullable=True)` — без обратного backfill (backfilled `*.*.*.*` НЕ возвращаются в NULL; downgrade — emergency operation, потеря NULL-vs-explicit-wildcard семантики acceptable).

### S2. Model: drop dead code

`storage_models.py`:

- `allowed_ip_mask: Mapped[str | None]` → `allowed_ip_mask: Mapped[str] = mapped_column(String(64), nullable=False)`.
- Удалить метод `get_allowed_ip_mask(self) -> str` (line 241-243). Все 3 caller'а переходят на прямой `token.allowed_ip_mask`.

### S3. Service layer: explicit contract

`service_token_service.py`:

- Сигнатура `issue_service_bearer_token(..., ip_mask: str, ...)` — убрать `| None = None` default. Caller responsibility: web layer уже гарантирует non-empty (см. ContextS).
- Удалить ветку `if ip_mask is not None and ip_mask.strip() != "*.*.*.*": effective_ip_mask = validate_ip_mask(ip_mask)` + `effective_ip_mask: str | None = None`. Заменить на:
  ```python
  effective_ip_mask = validate_ip_mask(ip_mask)
  ```
  `validate_ip_mask` уже принимает `*.*.*.*` (см. `domain_validation.py:38-52`).
- `allowed_ip_mask=effective_ip_mask` остаётся; теперь это всегда строка.
- Audit log payload `"ip_mask": token.get_allowed_ip_mask()` → `"ip_mask": token.allowed_ip_mask`.

### S4. Web layer: form sanity preserved

`web_routes_account.py`:

- Existing flow остаётся: empty → request_ip fallback → если unknown, ValueError; `*.*.*.*` без confirm → ValueError.
- Дополнительно: после успешного create — audit log row `TOKEN_EVENT_CREATED` уже создаётся в service layer; для wildcard mask добавить отдельный structured log `RUNTIME_LOGGER.warning("token_created_with_wildcard_ip", extra={...})` — operator-visible сигнал что выпущен wildcard token.

### S5. Auth path

`auth/bearer.py:277`:

- `effective_mask = token.get_allowed_ip_mask()` → `effective_mask = token.allowed_ip_mask`.
- Логика `if effective_mask != "*.*.*.*"` остаётся.

### S6. ip_denied audit log payload

`auth/bearer.py` _reject path для `TOKEN_EVENT_AUTH_FAILED_IP_DENIED`: расширить existing audit log details `{"reason": "ip_denied", ...}` следующими полями:

- `account_email_masked`: через `_mask_email`. **Подтверждено существование**: `scripts/product_metrics_report.py:85` определяет `_mask_email(email: str | None) -> str` (e.g. `"alice@example.com"` → `"al***@ex***.com"`). Сейчас функция script-private (префикс `_`), поэтому **нужно extract её в новый shared utility модуль** `privacy_utils.py` (или в существующий `auth_audit.py`), импортировать и из `auth/bearer.py`, и из `scripts/product_metrics_report.py`. Тесты для `_mask_email` (test_stage110_product_metrics.py:273+) follow по новому пути import.
- `client_ip_last_segment`: privacy-safe segment client IP (rename из `_last_octet` после Sonnet/Spark feedback). Логика: для IPv4 — `ip.split('.')[-1]`; для IPv6 — `ip.split(':')[-1]`. Если `client_ip` is None или `"unknown"` — записать `"unknown"`. Реализовать helper `_extract_client_ip_tail(ip: str | None) -> str` в том же `privacy_utils.py`.
- `expected_mask`: `token.allowed_ip_mask` (значение, по которому отказали — operator знает что должно было совпасть).

**Schema-change consumer impact** (per Spark MEDIUM): downstream log parsers, если есть, могут assume старый shape. Проверка: текущий `token_usage_logs.details_json` парсится только operator'ом ad-hoc через psql (нет в коде потребителя details_json по schema). Новые ключи добавляются, существующие не убираются — backwards-compatible additive change. Documented в AssumptionLog.

Counter `record_auth_failure(source="bearer_runtime", reason="ip_denied")` уже существует — не трогаем.

### S7. Web HTML defensive default

`web_html.py:550` `token.get('ip_mask', '*.*.*.*')` — оставить, но добавить inline-комментарий `# Stage 155: defensive default after NOT NULL migration — render dict always populates ip_mask, kept as guard for future dict-shape changes.` Иначе future developer прочитает default как active fallback.

### S8. Operator runbook

Создать `artifacts/runbook-operator-ip-mask.md`:

- Как посмотреть текущий mask токена: `SELECT id, account_id, name, allowed_ip_mask, status FROM service_bearer_tokens WHERE id=X;`.
- Как обновить mask после смены IP пользователем: `UPDATE service_bearer_tokens SET allowed_ip_mask='1.2.3.4' WHERE id=X;` (single IP) или `'1.2.3.*'` (subnet).
- Как найти denied события: `SELECT created_at, details_json FROM token_usage_logs WHERE event_type='token_auth_failed_ip_denied' AND bearer_token_id=X ORDER BY id DESC LIMIT 20;`.
- Без раскрытия pepper/secrets: ни одна команда не требует доступа к `FEEDBACK_FINGERPRINT_PEPPER` или к raw token.
- Секция «когда выпустить новый токен вместо изменения mask»: если IP user'а постоянно меняется (mobile, dynamic ISP) — выдай wildcard token + warn operator-у. Ссылка на web UI confirm-checkbox.

### S9. Tests

- **Migration round-trip**: upgrade сохраняет существующие masks, NULL backfill'ятся в `*.*.*.*`; downgrade ставит nullable обратно (но не возвращает NULL для backfilled rows — это OK).
- **NOT NULL constraint**: insert without `allowed_ip_mask` через ORM raises (SQLite `NOT NULL constraint failed` или PG `null value in column violates not-null`).
- **`get_allowed_ip_mask` removed (project-wide)**: grep-test по ВСЕМ `*.py` файлам в репо (production + tests) — ни один не содержит `get_allowed_ip_mask`. Это означает что test-файлы (см. ниже) тоже должны быть обновлены в одном diff'е.
- **Test-file update list** (обнаружено grep'ом перед implementation):
  - `tests/test_token_scopes.py` lines 76, 112, 148 — 3 caller'а `issue_service_bearer_token` без `ip_mask`. Передать `ip_mask="*.*.*.*"` (или специфичный) в каждый.
  - `tests/test_web_auth.py:1240` — `assert token.get_allowed_ip_mask() == "*.*.*.*"` → `assert token.allowed_ip_mask == "*.*.*.*"`.
- **service_token_service explicit ip_mask**: вызов с `ip_mask='*.*.*.*'` сохраняет `'*.*.*.*'` в БД (а не NULL). Вызов с `ip_mask='1.2.3.4'` сохраняет `'1.2.3.4'`. Вызов без `ip_mask` (positional/keyword) — `TypeError` (signature без default).
- **Audit log payload для wildcard create**: содержит `ip_mask='*.*.*.*'` в details, плюс RUNTIME_LOGGER.warning emit'ится при wildcard.
- **ip_denied payload расширен**: содержит `account_email_masked`, `client_ip_last_segment`, `expected_mask`. Privacy: НЕ содержит `account.email` raw, НЕ содержит full client_ip.
- **`_extract_client_ip_tail` для IPv6**: `"::1"` → `"1"`; `"2001:db8::42"` → `"42"`; `"192.168.1.5"` → `"5"`; `None` → `"unknown"`; `"unknown"` → `"unknown"`.
- **`_mask_email` shared module**: импорт из нового `privacy_utils` работает одинаково из `auth/bearer.py` и `scripts/product_metrics_report.py`; existing test_stage110_product_metrics.py update path import.

## Out of Scope

- Self-service web UI для смены mask пользователем (operator handles вручную через runbook).
- Email/notification оператора при denied burst (counter уже есть, alerting — отдельный stage 156).
- IP mask формат расширений (CIDR `1.2.3.0/24` etc.) — текущий glob-нотация (`1.2.*.*`) сохраняется.
- Auto-rotation tokens при смене IP (security risk без явного user opt-in).
- Web admin UI для просмотра ip_denied логов (psql достаточен per текущему workflow).

## Acceptance Criteria

1. Alembic migration `20260503_000013_allowed_ip_mask_not_null.py`: backfill NULL → `*.*.*.*` + `ALTER COLUMN ... SET NOT NULL`. Round-trip test покрывает.
2. `ServiceBearerToken.allowed_ip_mask: Mapped[str]` (без `| None`). `get_allowed_ip_mask()` метод удалён.
3. `service_token_service.issue_service_bearer_token(..., ip_mask: str, ...)` — без default `None`. Тест через `pytest.raises(TypeError)`.
4. Service layer хранит wildcard как `'*.*.*.*'` строка в БД. Тест проверяет row после insert.
5. 3 call sites (`service_token_service.py:79`, `web.py:343`, `auth/bearer.py:277`) переписаны на прямой `token.allowed_ip_mask`. Grep-test: production `*.py` не содержит `get_allowed_ip_mask`.
6. Existing test `test_account_token_issue_allows_confirmed_full_access_and_wildcard_ip` обновлён на новый API (`token.allowed_ip_mask`); проходит с `'*.*.*.*'` строкой.
7. ip_denied audit log row (через `add_token_usage_log`) содержит `account_email_masked`, `client_ip_last_segment`, `expected_mask`; не содержит `account.email` raw или full IP. `_mask_email` импортируется из нового shared `privacy_utils.py`.
8. Wildcard token issue emit'ит `RUNTIME_LOGGER.warning("token_created_with_wildcard_ip", ...)` со structured fields (account_id, token_id, token_name).
9. `artifacts/runbook-operator-ip-mask.md` существует с recipes для view/update mask + denied query, без mention pepper/secrets.
10. Полный suite `docker compose --profile test run --rm test` — green.
11. Committed diff проходит ревью сторонней моделью (Codex gpt-5.5, 2/2 budget) или явный exhaust с rationale.

## Decomposition

- 155a PRD/review/simplicity gates. ≤2h.
- 155b Migration (batch_alter_table) + model (drop method) + service (drop dual-path) + 3 prod call-site refactor + 4 test-file callers (test_token_scopes.py × 3, test_web_auth.py × 1) + tests. ≤2h, ~50 LOC migration + ~40 LOC прод + ~150 LOC tests.
- 155c Extract `_mask_email` + new `_extract_client_ip_tail` в `privacy_utils.py`; update import в `scripts/product_metrics_report.py` + tests path. Audit log payload расширение (`account_email_masked` + `client_ip_last_segment` + `expected_mask`) + wildcard-create RUNTIME_LOGGER.warning + tests. ≤2h, ~40 LOC privacy_utils + ~40 LOC bearer + ~100 LOC tests.
- 155d Operator runbook (`artifacts/runbook-operator-ip-mask.md`). ≤30min, ~80 LOC markdown.
- 155e Full suite + audit + commit. ≤1h.
- 155f Diff review (Sonnet + Codex 1/2 + applied + Codex 2/2 if substantial) + push + AssumptionLog + self-attestation. ≤1.5h.

Итого ≤8.5 LOC-часов, ~400 LOC прод/тест-кода + 80 LOC runbook.

## Risks

- **Migration on prod with existing NULL**: если есть много NULL-токенов и `UPDATE` блокирует table — risk minor (`service_bearer_tokens` ~10 rows на prod per metrics 2026-05-02). На больших инсталляциях potentially нужен chunked update; не сейчас.
- **Downgrade asymmetry**: после downgrade backfilled `*.*.*.*` НЕ возвращаются в NULL (downgrade просто меняет nullable=True). Это acceptable: downgrade — emergency operation, потеря NULL-vs-explicit-wildcard семантики (которую мы как раз убираем) не критична.
- **Email masking helper отсутствует** — проверить `_mask_email` (per memory 2026-04-19); если нет, реализовать минимально в audit_audit.py / shared utility. Недоступность не блокер — можно использовать local-part-truncation.
- **client_ip absent (resolved as None)** — payload поле `client_ip_last_octet` ставим как `"unknown"` (не пустую строку — operator должен видеть что IP не resolved'ился, не интерпретировать как valid octet).
- **3 call-site refactor scope creep** — есть тесты которые могут вызывать `get_allowed_ip_mask()` напрямую (`test_account_token_issue_allows_confirmed_full_access_and_wildcard_ip` line 1240). Нужно обновить ВСЕ test refs одним diff'ом, чтобы grep-test (AC #5) прошёл.
- **`web_html.py:550`** оставлен с `.get('ip_mask', '*.*.*.*')` — defensive, не нарушает goal. Возможный перфекционистский pass: убрать default раз model гарантирует ключ. Skip per ROI.

## Rationale для выбранной сложности

**Альтернатива 1: оставить NULL семантику + добавить server_default `'*.*.*.*'` для новых rows**. Pros: zero call-site changes, чистая backwards-compat. **Cons (отвергнуто per Roadmap решение пользователя)**:

- Dual-API surface остаётся (NULL vs строка означают одно и то же).
- `get_allowed_ip_mask()` не удаляется — dead-code persistance.
- Future bug class: новый разработчик может legitimately spustит NULL (т.к. nullable=True), и оно молча станет wildcard. PRD goal "забыл = открытый" не достигается.

**Альтернатива 2: NULL → fail-closed без backfill** (NULL = deny). **Cons (отвергнуто)**:

- Существующие NULL-токены (могут быть в prod после prior wildcard creates) сразу перестают работать → outage.
- Требует customer outreach перед migration.

**Выбранный путь — backfill + NOT NULL + dead-code removal** даёт:

- Zero-downtime migration: NULL'ы становятся явным `'*.*.*.*'` (current operational behavior preserved), затем NOT NULL запрещает новые NULL'ы.
- Чистая single-source-of-truth: `token.allowed_ip_mask` — единственное место чтения mask, всегда строка, всегда от primary column.
- Удалены ~30 LOC dual-path кода (`get_allowed_ip_mask`, NULL-conversion в service).
- Совместимо с existing web UX (confirm для wildcard уже есть).
- Cost: 1 migration + 3 trivial call-site replacements.

### Simplicity-eval pass (§4.1) применён

Триггеры проверены:

- **Abstraction без 2+ call-sites**: `get_allowed_ip_mask()` — 3 call sites, но все trivially заменяются на attribute access. Helper нужен только для NULL-handling, который мы как раз убираем. Удаление justified.
- **Premature flexibility**: `allowed_ip_mask: Mapped[str | None]` — flexibility для NULL не используется (web layer не передаёт None), но позволяет dual-API. Убираем nullable.
- **Dual-API surface**: NULL и `'*.*.*.*'` означают одно и то же (unrestricted) — это чистый dual-API workaround, удаляем.
- **Sync mechanisms paired**: `get_allowed_ip_mask` (NULL → string) + service `effective_ip_mask = None` (string → NULL) — это inverse-pair, обе ветки удаляются.
- **Helper из 1 места**: `get_allowed_ip_mask` — 3 use sites, но все удаляются, так что helper становится 0-use → удаляем.

PRD финализирован.
