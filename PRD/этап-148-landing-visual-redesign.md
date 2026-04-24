# PRD Этап 148. Landing visual redesign

**Статус:** done (2026-04-25)
**Связанные артефакты:** `landing_page.py`, `tests/test_landing_page.py`, `prod-desktop-full.png`, `prod-mobile-full.png`, `redesign-desktop-final-full.png`, `redesign-mobile-full-v2.png`

## Контекст

Stage 146 закрыл контентный gap (MCP onboarding, copy-ready команды для Codex/Claude/Cursor/Manus), но визуально лендинг `vetmanager-mcp.vromanichev.ru` не считывался как clinical-tech B2B-сервис:

- «Крафтовая» cream + ржавый orange палитра + bg grid-paper уводила к эстетике кофейни.
- Hero перегружен: serif h1 на 4 строки + 3 stat-карточки справа (это features, не stats) → primary CTA выпадал ниже above-the-fold на 1366×768.
- **Bug**: MCP tab panels рендерились всеми 5 открытыми, потому что JS init происходил после первого render — на load страница выглядела как куча тёмных code-блоков.
- Tech block + FAQ навалены одной кучей с promo-копи.
- Два хвостовых CTA («Open Source» + «Готовы начать?») дублировали друг друга.
- Mobile first-screen занят h1 на 7 строк без CTA.
- Broken privacy link `href="#"` в футере.
- Иконок не было ни в одной секции.

Источник: ревью лендинга 2026-04-25 через Playwright.

## Цель

Полный визуальный редизайн при сохранении контента Stage 146, новой clinical-tech палитрой (направление A), hero с реальным mock-chat, исправленным tab init, progressive disclosure для tech/FAQ, унифицированной card-системой с inline SVG иконками и mobile-first layout с sticky CTA.

## Сторонние ограничения

- Контент Stage 146 трогаем минимально: тесты `test_landing_page.py` зависят от русских строк, agent commands и MCP onboarding структуры.
- Сервинг не меняется: HTML рендерится из `landing_page.py` как inline string. Без template engine, без external assets.
- `SITE_BASE_URL` / `MCP_PATH` validation остаётся (Stage 100.5).
- Без runtime-зависимостей и CDN-шрифтов: system stack или inline.
- Privacy link удалить (отдельная страница вне scope этого этапа).

## Дизайн-решения (направление A — clinical-tech)

- **Палитра:** ink-blue primary `#1e3a4d`, warm-grey background `#f5f5f0`, accent orange `#bb4d24` только для primary CTA и важных индикаторов; moss-green `#5a7a5e` для positive deltas (+14% chip).
- **Типографика:** sans-serif body (Inter если установлен, иначе system-ui); serif только для display h1 hero (Iowan Old Style → Charter → Source Serif Pro → Cambria → Georgia).
- **Hero:** mock-chat illustration — пример «Какая выручка за март 2026?» → таблица с реальными цифрами (₽ 487 200 итог, +14% delta chip, weekly bar chart 4 столбца, breakdown table, source line «Vetmanager · 234 платежа · обновлено сейчас»). CTA above the fold на 1366×768 и 1440×900.
- **MCP tabs:** panels `hidden` в HTML по умолчанию, JS только переключает.
- **Cards:** единая система с inline SVG icons (Lucide-style 24×24, stroke 2).
- **Tech блок и FAQ:** progressive disclosure через `<details>` (collapsed by default).
- **Footer-CTA:** один dark callout вместо двух — объединены «Готовы начать?» + Open Source mention.
- **Mobile:** sticky compact CTA с `safe-area-inset`, drawer-nav через CSS-only hamburger, hero h1 ≤3 строк на 390 viewport, brand subtitle скрыт ниже 540px.

## Acceptance criteria

- [x] Контент Stage 146 сохранён: все русские строки, agent commands, fallback-grid, role examples, error grid, copy buttons работают.
- [x] `tests/test_landing_page.py` зелёные (18 passed).
- [x] Full Docker test suite зелёный: 921 passed, 57 deselected.
- [x] 0 console errors на load (ранее был 1).
- [x] 0 horizontal overflow на 390/768/1440 viewports.
- [x] Tab init bug исправлен: при первом render visible только Codex panel, остальные 4 — `hidden`.
- [x] Hero CTA (`Зарегистрироваться` + `Инструкции для агентов`) above the fold на 1440×900.
- [x] Mobile sticky CTA виден ниже 920px viewport.
- [x] Privacy link удалён из футера; тест переписан на `not in`.
- [x] `prefers-reduced-motion` глобально гасит keyframes.

## Workflow allowance (по согласованию с пользователем 2026-04-25)

Пользователь явно разрешил отклониться от per-substage Core Loop ради единого visual rewrite вместо 6 коммитов 148a..148f. Условия:

- Тесты починить перед push.
- Финальное ревью сторонней моделью на committed diff с устранением адекватных findings.
- Локальная визуальная проверка через Playwright перед push.

## Out of scope

- Брендбук / новый логотип — оставлен «VM seal» как есть.
- Реальные screenshot'ы интерфейса агента в hero (используется HTML/CSS mock + inline SVG bar chart).
- Внешние шрифты с CDN.
- A/B тестирование, analytics.
- Routing для `/privacy` — отдельный этап.
- Перевод на template engine (Jinja2 / fastapi.templating).
- Helper-split `landing_page.py` на `_render_*` функции — оценено через simplicity eval как излишняя абстракция при single-pass редизайне; вернёмся к split, когда добавятся новые секции.

## Связанные тесты и проверки

- `tests/test_landing_page.py` — 18 ассертов на структуру, метатеги, hero, topbar, MCP onboarding, FAQ, footer.
- `docker compose --profile test run --rm test` — full unit suite.
- Playwright локальный QA: viewport 390/768/1440, full-page screenshots, overflow detection, console error scan.
