# Этап 168. Account token table responsive layout hotfix

## Цель

Исправить верстку блока “Текущие токены” в account console, где таблица с 10 колонками выходит за контейнер и уводит `Actions/Revoke` вправо.

## Контекст

Пользователь показал screenshot 2026-05-21: список токенов с длинными именами, датами, IP mask, privacy/access/status columns не помещается в текущую карточку шириной около 760px. Горизонтальный scroll как основной UX нежелателен, потому что экран токенов является частым операторским сценарием.

## Scope

1. Не использовать горизонтальный scroll как основной режим.
2. Оставить в основной desktop/tablet таблице только частые поля:
   - `Token` (name + prefix);
   - `Access`;
   - `Status`;
   - `Last used`;
   - `Requests`;
   - `Actions`.
3. Перенести редкие поля в per-token `<details>`:
   - `Privacy`;
   - `IP mask`;
   - `Expires`.
4. Для tablet/mobile добавить responsive CSS:
   - на ширинах `390`, `640`, `760`, `900`, `1024` px token list не создаёт горизонтальный scroll;
   - на ширинах до `780` px строка таблицы становится компактным stacked list/card;
   - `Actions/Revoke` остаётся внутри viewport/container при длинных token names.
5. Расширить account dashboard shell умеренно только для account page, не меняя register/login landing-style cards.

## Out of Scope

- Новая data model или API.
- Изменение token issuing/revoke semantics.
- Показ raw token после создания.
- Большой redesign account console.

## Acceptance Criteria

1. Rendered account token list больше не содержит 10 видимых колонок.
2. `Privacy`, `IP mask`, `Expires` доступны в per-token details.
3. `Revoke` остается внутри token list/action column и не требует горизонтального scroll на `390`, `640`, `760`, `900`, `1024` px.
4. Long token names and expanded per-token details wrap/truncate within their cell and do not push actions outside container.
5. Tablet/mobile CSS: на `390`, `640` и `760` px token rows переходят в stacked list/card layout; на `900` и `1024` px компактная table layout не overflow-ит.
6. Existing raw-token privacy tests still pass.
7. Targeted web tests, browser/UI contract checks, full suite, review gates, commit/push/deploy/smoke completed.

## Simplicity rationale

- Chosen approach: compact existing table markup plus CSS and `<details>`.
- Rejected: full component redesign or JS-driven responsive table; not needed for this layout bug.
- Rejected: horizontal scroll as main solution; user explicitly does not want frequent horizontal scrolling.
- No new abstractions beyond small HTML/CSS helpers in existing `web_html.py`.

## Проверки

- `docker compose --profile test run --rm test pytest tests/test_web_auth.py::test_account_token_issue_shows_raw_token_once_and_stores_only_hash tests/test_stage168_account_token_layout.py -q`
  - `tests/test_stage168_account_token_layout.py` обязан проверять DOM/viewport contract: `documentElement.scrollWidth <= window.innerWidth` and `Actions/Revoke` inside viewport for `390`, `640`, `760`, `900`, `1024` px with long token names, both with collapsed details and after expanding all per-token `<details>`.
- `docker compose --profile test run --rm test pytest tests/test_web_auth.py tests/test_stage168_account_token_layout.py -q`
- `docker compose --profile test run --rm test`
- `git diff --check`
