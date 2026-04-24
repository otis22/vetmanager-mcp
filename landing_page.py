"""Static landing page for the public web entry point."""

from __future__ import annotations

import os

# Default to the production host so existing deployments render correctly.
# Self-hosted operators override via SITE_BASE_URL env (no trailing slash).
_DEFAULT_SITE_BASE_URL = "https://vetmanager-mcp.vromanichev.ru"


def _resolve_site_base_url() -> str:
    """Stage 100.5: validate SITE_BASE_URL env — must start with http(s),
    contain no control chars / quotes / whitespace, length ≤ 255. Invalid
    input falls back to the prod default so an operator typo doesn't
    inject markup into landing template."""
    raw = (os.environ.get("SITE_BASE_URL") or _DEFAULT_SITE_BASE_URL).strip()
    raw = raw.rstrip("/")
    if not raw:
        return _DEFAULT_SITE_BASE_URL
    if len(raw) > 255:
        return _DEFAULT_SITE_BASE_URL
    if not (raw.startswith("http://") or raw.startswith("https://")):
        return _DEFAULT_SITE_BASE_URL
    # Reject any whitespace / quote / angle bracket / control char.
    if any(c in raw for c in ('"', "'", "<", ">", " ", "\t", "\n", "\r", "\x00")):
        return _DEFAULT_SITE_BASE_URL
    return raw


def _resolve_mcp_path() -> str:
    """Validate MCP_PATH for display in public onboarding instructions."""
    raw = (os.environ.get("MCP_PATH") or "/mcp").strip()
    if not raw:
        return "/mcp"
    if len(raw) > 128:
        return "/mcp"
    if not raw.startswith("/"):
        return "/mcp"
    if any(c in raw for c in ('"', "'", "<", ">", " ", "\t", "\n", "\r", "\x00")):
        return "/mcp"
    return raw


def render_landing_page() -> str:
    """Return the public landing page HTML."""
    html = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Vetmanager MCP Service</title>
  <meta
    name="description"
    content="MCP-сервис для Vetmanager: AI-ассистент для ветклиник с bearer-авторизацией и безопасным хранением credentials."
  >
  <meta name="robots" content="index, follow">
  <meta property="og:title" content="Vetmanager MCP Service">
  <meta property="og:description" content="AI-ассистент для ветклиник. Данные клиники по запросу за секунды через MCP.">
  <meta property="og:type" content="website">
  <meta property="og:url" content="https://vetmanager-mcp.vromanichev.ru/">
  <link rel="canonical" href="https://vetmanager-mcp.vromanichev.ru/">
  <meta name="twitter:card" content="summary">
  <meta name="twitter:title" content="Vetmanager MCP Service">
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><circle cx='50' cy='50' r='46' fill='%23bb4d24'/><text y='72' x='50' text-anchor='middle' font-size='52' font-weight='700' fill='white' font-family='sans-serif'>VM</text><text y='28' x='72' text-anchor='middle' font-size='22' fill='white'>+</text></svg>">
  <style>
    :root {
      --bg: #f3efe4;
      --paper: rgba(255, 252, 246, 0.88);
      --ink: #1d2321;
      --muted: #51605b;
      --accent: #bb4d24;
      --accent-deep: #7d2d14;
      --teal: #2f6d73;
      --sand: #d6b98d;
      --line: rgba(29, 35, 33, 0.12);
      --shadow: 0 24px 80px rgba(58, 41, 22, 0.12);
      --radius: 28px;
    }

    * { box-sizing: border-box; }

    html {
      scroll-behavior: smooth;
    }

    body {
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(47, 109, 115, 0.18), transparent 34%),
        radial-gradient(circle at 85% 15%, rgba(187, 77, 36, 0.18), transparent 28%),
        linear-gradient(180deg, #f9f4ea 0%, var(--bg) 46%, #efe6d8 100%);
      font-family: "Avenir Next", "Segoe UI", sans-serif;
    }

    body::before {
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      background-image:
        linear-gradient(rgba(29, 35, 33, 0.04) 1px, transparent 1px),
        linear-gradient(90deg, rgba(29, 35, 33, 0.04) 1px, transparent 1px);
      background-size: 32px 32px;
      mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.38), transparent 78%);
    }

    .shell {
      width: min(1180px, calc(100% - 32px));
      margin: 0 auto;
      padding: 24px 0 72px;
    }

    .topbar,
    .hero,
    .panel,
    .footer {
      backdrop-filter: blur(16px);
      background: var(--paper);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
    }

    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      border-radius: 24px;
      padding: 14px 18px;
      position: sticky;
      top: 16px;
      z-index: 10;
      margin-bottom: 24px;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 14px;
    }

    .seal {
      width: 48px;
      height: 48px;
      border-radius: 16px;
      background:
        linear-gradient(135deg, var(--accent) 0%, #d9782b 100%);
      color: #fffaf1;
      display: grid;
      place-items: center;
      font: 700 18px/1 "Avenir Next Condensed", "Franklin Gothic Medium", sans-serif;
      letter-spacing: 0.08em;
    }

    .brand h1,
    .hero h1,
    .section-title,
    .stat strong {
      font-family: "Iowan Old Style", "Palatino Linotype", "Book Antiqua", serif;
    }

    .brand h1 {
      margin: 0;
      font-size: 1rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .brand p,
    .topbar nav a,
    .eyebrow,
    .lede,
    .body-copy,
    .stat span,
    .mini,
    li {
      color: var(--muted);
    }

    .brand p {
      margin: 2px 0 0;
      font-size: 0.92rem;
    }

    .topbar nav {
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
    }

    .topbar nav a,
    .cta,
    .ghost {
      text-decoration: none;
      transition: transform 180ms ease, background 180ms ease, color 180ms ease;
    }

    .topbar nav a {
      font-size: 0.95rem;
      border-radius: 999px;
      padding: 8px 16px;
      border: 1px solid transparent;
    }

    .topbar nav a.nav-link {
      border-color: var(--line);
      background: rgba(255, 255, 255, 0.48);
    }

    .topbar nav a.nav-link:hover {
      background: rgba(255, 255, 255, 0.82);
      border-color: var(--sand);
    }

    .topbar nav a.nav-cta {
      background: var(--accent);
      color: #fff9f3;
      font-weight: 600;
      padding: 8px 20px;
    }

    .topbar nav a.nav-cta:hover {
      background: var(--accent-deep);
    }

    .topbar nav a:hover,
    .cta:hover,
    .ghost:hover {
      transform: translateY(-1px);
    }

    a:focus-visible,
    button:focus-visible,
    input:focus-visible,
    label:focus-visible {
      outline: 2px solid var(--accent);
      outline-offset: 2px;
    }

    .mini, .mini a { color: #3e4a45; }

    .hero {
      position: relative;
      overflow: hidden;
      border-radius: calc(var(--radius) + 8px);
      padding: clamp(28px, 4vw, 56px);
      display: grid;
      gap: 24px;
      grid-template-columns: minmax(0, 1.2fr) minmax(280px, 0.8fr);
      animation: rise 520ms ease-out both;
    }

    .hero::after {
      content: "";
      position: absolute;
      inset: auto -8% -16% auto;
      width: 320px;
      height: 320px;
      border-radius: 50%;
      background: radial-gradient(circle, rgba(47, 109, 115, 0.2), transparent 68%);
      pointer-events: none;
    }

    .eyebrow {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      margin: 0 0 10px;
      font-size: 0.88rem;
      letter-spacing: 0.14em;
      text-transform: uppercase;
    }

    .eyebrow::before {
      content: "";
      width: 38px;
      height: 1px;
      background: var(--accent);
    }

    .hero h1 {
      margin: 0;
      font-size: clamp(2.8rem, 6vw, 5.4rem);
      line-height: 0.95;
      max-width: 10ch;
    }

    .hero h1 span {
      color: var(--accent-deep);
    }

    .lede {
      max-width: 56ch;
      font-size: 1.08rem;
      line-height: 1.7;
      margin: 18px 0 0;
    }

    .cta-row {
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      margin-top: 28px;
    }

    .cta,
    .ghost {
      border-radius: 999px;
      padding: 14px 18px;
      font-weight: 600;
    }

    .cta {
      background: var(--accent);
      color: #fff9f3;
    }

    .ghost {
      color: var(--ink);
      border: 2px solid var(--sand);
      background: rgba(255, 255, 255, 0.58);
    }

    .hero-side {
      display: grid;
      gap: 14px;
      align-content: start;
    }

    .stat {
      border-radius: 24px;
      padding: 18px 20px;
      border: 1px solid var(--line);
      background: linear-gradient(180deg, rgba(255, 255, 255, 0.74), rgba(255, 255, 255, 0.54));
    }

    .stat strong {
      display: block;
      font-size: 2rem;
      margin-bottom: 6px;
    }

    .stat span {
      display: block;
      line-height: 1.5;
    }

    .grid {
      display: grid;
      gap: 18px;
      grid-template-columns: repeat(12, minmax(0, 1fr));
      margin-top: 22px;
    }

    .panel {
      border-radius: var(--radius);
      padding: 24px;
      animation: rise 620ms ease-out both;
    }

    .panel.wide { grid-column: span 7; }
    .panel.tall { grid-column: span 5; }
    .panel.full { grid-column: 1 / -1; }

    .section-title {
      margin: 0 0 14px;
      font-size: 2rem;
      line-height: 1;
    }

    .body-copy {
      margin: 0;
      line-height: 1.7;
      font-size: 1rem;
    }

    .list {
      margin: 18px 0 0;
      padding: 0;
      list-style: none;
      display: grid;
      gap: 14px;
    }

    .list li {
      padding-left: 18px;
      position: relative;
      line-height: 1.6;
    }

    .list li::before {
      content: "";
      position: absolute;
      left: 0;
      top: 0.7em;
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--accent);
      box-shadow: 0 0 0 4px rgba(187, 77, 36, 0.12);
    }

    .steps {
      counter-reset: step;
      display: grid;
      gap: 14px;
      margin-top: 16px;
    }

    .step {
      display: grid;
      grid-template-columns: 52px minmax(0, 1fr);
      gap: 14px;
      align-items: start;
    }

    .step::before {
      counter-increment: step;
      content: "0" counter(step);
      display: grid;
      place-items: center;
      width: 52px;
      height: 52px;
      border-radius: 16px;
      background: #f3dfc4;
      color: var(--accent-deep);
      font-weight: 700;
    }

    .onboarding {
      margin-top: 22px;
      display: grid;
      gap: 22px;
    }

    .onboarding-head {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(280px, 0.74fr);
      gap: 22px;
      align-items: start;
    }

    .onboarding-head .section-title {
      font-size: clamp(2rem, 4vw, 3.6rem);
      max-width: 12ch;
    }

    .flow-map {
      display: grid;
      gap: 10px;
    }

    .flow-node {
      display: grid;
      gap: 4px;
      padding: 14px 16px;
      border-radius: 18px;
      background: rgba(255, 255, 255, 0.7);
      border: 1px solid var(--line);
    }

    .flow-node strong {
      color: var(--ink);
    }

    .flow-node span {
      color: var(--muted);
      line-height: 1.45;
      font-size: 0.94rem;
    }

    .flow-arrow {
      color: var(--accent);
      font-weight: 700;
      text-align: center;
    }

    .prompt-grid,
    .role-grid,
    .error-grid,
    .quick-steps,
    .fallback-grid {
      display: grid;
      gap: 12px;
    }

    .prompt-grid {
      grid-template-columns: repeat(5, minmax(0, 1fr));
      margin: 18px 0 0;
    }

    .prompt-chip,
    .role-card,
    .error-card,
    .fallback-card,
    .quick-step {
      border-radius: 18px;
      padding: 14px 16px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.66);
    }

    .prompt-chip {
      margin: 0;
      line-height: 1.45;
      color: var(--ink);
      font-weight: 600;
    }

    .quick-steps {
      grid-template-columns: repeat(3, minmax(0, 1fr));
      margin-top: 16px;
    }

    .quick-step strong,
    .role-card strong,
    .error-card strong,
    .fallback-card strong {
      display: block;
      margin-bottom: 6px;
      color: var(--ink);
    }

    .agent-tabs {
      display: grid;
      gap: 16px;
    }

    .tab-list {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }

    .tab-button,
    .copy-button {
      border: 1px solid var(--line);
      border-radius: 999px;
      background: rgba(255, 255, 255, 0.72);
      color: var(--ink);
      cursor: pointer;
      font: inherit;
      font-weight: 700;
      padding: 10px 14px;
      transition: background 180ms ease, color 180ms ease, transform 180ms ease;
    }

    .tab-button:hover,
    .copy-button:hover {
      transform: translateY(-1px);
    }

    .tab-button[aria-selected="true"] {
      background: var(--teal);
      color: #fffaf1;
      border-color: transparent;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      width: fit-content;
      border-radius: 999px;
      padding: 5px 10px;
      background: #e7f1ee;
      color: var(--teal);
      font-size: 0.82rem;
      font-weight: 700;
      margin-bottom: 10px;
    }

    .tab-panel {
      margin-top: 0;
    }

    .command-card {
      display: grid;
      gap: 12px;
    }

    .command-card pre {
      margin-top: 0;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }

    .copy-button {
      justify-self: start;
      background: var(--accent);
      color: #fff9f3;
      border-color: transparent;
    }

    .copy-status {
      min-height: 1.2em;
      color: var(--teal);
      font-size: 0.92rem;
      font-weight: 700;
    }

    .copy-status:empty {
      min-height: 0;
    }

    .privacy-note {
      margin-top: 16px;
      padding: 14px 16px;
      border-radius: 18px;
      background: #fff7e7;
      border: 1px solid rgba(187, 77, 36, 0.24);
      color: #6f3b17;
      line-height: 1.55;
    }

    .role-grid,
    .error-grid {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }

    .fallback-grid {
      grid-template-columns: repeat(5, minmax(0, 1fr));
      margin-top: 14px;
    }

    pre {
      margin: 18px 0 0;
      padding: 18px;
      border-radius: 22px;
      overflow-x: auto;
      background: #1f2427;
      color: #f3ede4;
      font: 0.9rem/1.6 "JetBrains Mono", "SFMono-Regular", Consolas, monospace;
    }

    .mini {
      margin-top: 14px;
      font-size: 0.92rem;
      line-height: 1.6;
    }

    .footer {
      margin-top: 22px;
      border-radius: 26px;
      padding: 18px 22px;
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 12px;
    }

    .footer strong {
      color: var(--ink);
    }

    @keyframes rise {
      from {
        opacity: 0;
        transform: translateY(18px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }

    /* Hamburger toggle (CSS-only) */
    .menu-toggle { display: none; }
    .hamburger {
      display: none;
      cursor: pointer;
      width: 44px;
      height: 44px;
      align-items: center;
      justify-content: center;
      border: none;
      background: none;
      padding: 0;
    }
    .hamburger span,
    .hamburger span::before,
    .hamburger span::after {
      display: block;
      width: 22px;
      height: 2px;
      background: var(--ink);
      border-radius: 1px;
      transition: transform 200ms ease, opacity 200ms ease;
      position: relative;
    }
    .hamburger span::before,
    .hamburger span::after {
      content: "";
      position: absolute;
      left: 0;
      width: 100%;
    }
    .hamburger span::before { top: -7px; }
    .hamburger span::after  { top: 7px; }

    .menu-toggle:checked ~ nav {
      display: flex;
    }
    .menu-toggle:checked ~ .hamburger span {
      background: transparent;
    }
    .menu-toggle:checked ~ .hamburger span::before {
      top: 0;
      transform: rotate(45deg);
      background: var(--ink);
    }
    .menu-toggle:checked ~ .hamburger span::after {
      top: 0;
      transform: rotate(-45deg);
      background: var(--ink);
    }

    /* Active section hint via scroll-margin */
    section[id] {
      scroll-margin-top: 100px;
    }

    @media (max-width: 920px) {
      .hero,
      .onboarding-head,
      .grid {
        grid-template-columns: 1fr;
      }

      .prompt-grid,
      .quick-steps,
      .role-grid,
      .error-grid,
      .fallback-grid {
        grid-template-columns: 1fr;
      }

      .panel.wide,
      .panel.tall {
        grid-column: auto;
      }

      .topbar {
        position: static;
        flex-wrap: wrap;
      }

      .hamburger {
        display: flex;
      }

      .topbar nav {
        display: none;
        width: 100%;
        flex-direction: column;
        gap: 8px;
        padding-top: 8px;
        border-top: 1px solid var(--line);
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <div class="seal" aria-label="Vetmanager MCP">VM</div>
        <div>
          <h1>Vetmanager MCP Service</h1>
          <p>Bearer-only gateway for clinic operations through AI clients</p>
        </div>
      </div>
      <input type="checkbox" id="menu-toggle" class="menu-toggle" aria-hidden="true">
      <label class="hamburger" for="menu-toggle" aria-label="Открыть меню"><span></span></label>
      <nav>
        <a class="nav-link" href="https://github.com/otis22/vetmanager-mcp" target="_blank" rel="noopener"><svg width="18" height="18" viewBox="0 0 16 16" fill="currentColor" style="vertical-align: text-bottom; margin-right: 4px;"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>GitHub</a>
        <a class="nav-cta" href="/login" style="background: transparent; color: var(--accent); border: 2px solid var(--accent);">Войти</a>
        <a class="nav-cta" href="/register">Создать аккаунт</a>
      </nav>
    </header>

    <section class="hero" id="product">
      <div>
        <p class="eyebrow">Для ветклиник и врачей</p>
        <h1>Данные клиники и команды <span>по запросу за секунды</span>.</h1>
        <p class="lede">
          Сервис для ветврачей, администраторов и руководителей клиник помогает быстрее
          получать данные из Vetmanager через AI-ассистента: по клиентам, пациентам,
          приёмам, финансам и складу. Без ручного поиска по разделам и без передачи
          секретов клиники в каждое подключение.
        </p>
        <p class="mini">
          Сервис не сохраняет бизнес-данные из Vetmanager для постоянного хранения. Он хранит только технические данные интеграции и сервисные bearer-метаданные, необходимые для авторизации и работы MCP runtime.
        </p>
        <p class="mini">
          Если выбран режим авторизации через Vetmanager login/password, логин и пароль Vetmanager не сохраняются: они нужны только для получения user token. При смене пароля в Vetmanager такой token может стать невалидным, и потребуется повторная авторизация.
        </p>
        <div class="cta-row">
          <a class="cta" href="/register">Зарегистрироваться</a>
          <a class="ghost" href="#examples">Посмотреть примеры</a>
        </div>
        <p class="mini" style="margin-top:8px;">Уже зарегистрированы? <a href="/login">Войти в кабинет</a></p>
      </div>
      <div class="hero-side">
        <div class="stat">
          <strong>Клиенты и пациенты</strong>
          <span>Быстрый доступ к карточкам, истории и последним обращениям без ручной навигации по системе.</span>
        </div>
        <div class="stat">
          <strong>Приёмы, финансы, склад</strong>
          <span>Записи на сегодня, долги клиентов, карточки и история визитов доступны через один AI-интерфейс.</span>
        </div>
        <div class="stat">
          <strong>Безопасное подключение</strong>
          <span>Интеграция подключается один раз на уровне аккаунта клиники, а доступ выдаётся через service token. Каждый токен можно ограничить по IP-маске — вплоть до конкретного адреса.</span>
        </div>
      </div>
    </section>

    <section class="panel" style="border-radius: var(--radius); margin-bottom: 24px; padding: clamp(20px, 3vw, 40px);">
      <h3 class="section-title">Что такое MCP?</h3>
      <p class="body-copy">
        MCP (Model Context Protocol) — открытый стандарт, который позволяет AI-ассистентам
        безопасно подключаться к внешним системам. Этот сервис — MCP-мост к Vetmanager:
        ваша клиника подключается один раз, а дальше команда получает данные через
        привычный AI-интерфейс, без необходимости переключаться между экранами Vetmanager.
      </p>
    </section>

    <section class="panel onboarding" id="mcp-onboarding" data-testid="mcp-onboarding">
      <div data-testid="mcp-onboarding-main-copy">
        <div class="onboarding-head">
          <div>
            <p class="eyebrow">Подключение агента</p>
            <h3 class="section-title">Подключите ИИ-агента к вашему Vetmanager за 5 минут</h3>
            <p class="body-copy">
              Работает через MCP: Codex, Claude, Cursor, Manus и другие совместимые агенты смогут находить клиентов,
              смотреть записи, проверять счета и считать выручку по данным вашей клиники.
            </p>
            <p class="body-copy" style="margin-top: 14px;">
              MCP — это мост между ИИ-агентом и Vetmanager. Вы задаёте вопрос обычным языком, агент обращается
              к Vetmanager через разрешённые команды и возвращает ответ по вашим данным.
            </p>
          </div>
          <div class="flow-map" aria-label="Как работает подключение">
            <div class="flow-node"><strong>Вы задаёте вопрос</strong><span>Например, про выручку, записи или клиента.</span></div>
            <div class="flow-arrow">↓</div>
            <div class="flow-node"><strong>ИИ-агент</strong><span>Codex, Claude, Cursor, Manus или другой совместимый агент.</span></div>
            <div class="flow-arrow">↓</div>
            <div class="flow-node"><strong>MCP-мост</strong><span>Передаёт запрос через разрешённые команды.</span></div>
            <div class="flow-arrow">↓</div>
            <div class="flow-node"><strong>Ваш Vetmanager</strong><span>Данные остаются в вашей рабочей системе.</span></div>
            <div class="flow-arrow">↓</div>
            <div class="flow-node"><strong>Ответ по данным клиники</strong><span>Агент возвращает понятный результат.</span></div>
          </div>
        </div>

        <div style="margin-top: 22px;">
          <h4 class="section-title" style="font-size: 1.45rem;">Что можно спросить после подключения</h4>
          <div class="prompt-grid">
            <p class="prompt-chip">Какая выручка была за март?</p>
            <p class="prompt-chip">Покажи записи врача на завтра</p>
            <p class="prompt-chip">Найди клиента по телефону</p>
            <p class="prompt-chip">Какие счета оплачены частично?</p>
            <p class="prompt-chip">Кому из пациентов пора на прививку?</p>
          </div>
        </div>

        <div style="margin-top: 22px;">
          <h4 class="section-title" style="font-size: 1.45rem;">Подключение в 3 шага</h4>
          <div class="quick-steps">
            <div class="quick-step"><strong>1. Выберите агента</strong><span>Если сомневаетесь, начните с Codex.</span></div>
            <div class="quick-step"><strong>2. Отправьте команду</strong><span>Скопируйте готовый текст ниже и дайте его агенту.</span></div>
            <div class="quick-step"><strong>3. Вставьте ключ</strong><span>Добавьте ключ доступа в настройки и перезапустите сессию.</span></div>
          </div>
          <p class="privacy-note">
            Ключ доступа не нужно отправлять в чат. Он хранится в настройках агента или на вашем компьютере.
            Настройку удобнее делать с компьютера. Ключ доступа выдаётся в кабинете после регистрации и подключения Vetmanager:
            <a href="/register">создать аккаунт</a> или <a href="/login">войти в кабинет</a>.
          </p>
        </div>
      </div>

      <div class="agent-tabs" data-testid="mcp-agent-tabs">
        <div class="tab-list" role="tablist" aria-label="Выберите ИИ-агента">
          <button class="tab-button" id="mcp-tab-codex" role="tab" aria-selected="true" aria-controls="mcp-panel-codex" tabindex="0" type="button">Codex</button>
          <button class="tab-button" id="mcp-tab-claude" role="tab" aria-selected="false" aria-controls="mcp-panel-claude" tabindex="-1" type="button">Claude</button>
          <button class="tab-button" id="mcp-tab-cursor" role="tab" aria-selected="false" aria-controls="mcp-panel-cursor" tabindex="-1" type="button">Cursor</button>
          <button class="tab-button" id="mcp-tab-manus" role="tab" aria-selected="false" aria-controls="mcp-panel-manus" tabindex="-1" type="button">Manus</button>
          <button class="tab-button" id="mcp-tab-other" role="tab" aria-selected="false" aria-controls="mcp-panel-other" tabindex="-1" type="button">Другой агент</button>
        </div>

        <div class="tab-panel command-card" id="mcp-panel-codex" role="tabpanel" aria-labelledby="mcp-tab-codex">
          <span class="badge">Рекомендуем для старта</span>
          <pre id="mcp-command-codex">Настрой мне MCP-сервер Vetmanager.

Адрес сервера: __MCP_SERVER_URL__

Ключ доступа / Bearer token я вставлю сам, но покажи путь к файлу или настройке, куда его нужно вставить.

После настройки скажи, как перезапустить сессию Codex и как проверить, что инструменты Vetmanager подключились.</pre>
          <button class="copy-button" type="button" data-copy-target="mcp-command-codex" aria-describedby="mcp-copy-status-codex">Скопировать</button>
          <span class="copy-status" id="mcp-copy-status-codex" role="status" aria-live="polite"></span>
        </div>

        <div class="tab-panel command-card" id="mcp-panel-claude" role="tabpanel" aria-labelledby="mcp-tab-claude">
          <pre id="mcp-command-claude">Подключи MCP-сервер Vetmanager.

Адрес сервера: __MCP_SERVER_URL__

Ключ доступа / Bearer token я вставлю сам, но покажи путь к файлу или настройке, куда его нужно вставить.

После настройки скажи, как перезапустить Claude и проверить список доступных MCP-инструментов.</pre>
          <button class="copy-button" type="button" data-copy-target="mcp-command-claude" aria-describedby="mcp-copy-status-claude">Скопировать</button>
          <span class="copy-status" id="mcp-copy-status-claude" role="status" aria-live="polite"></span>
        </div>

        <div class="tab-panel command-card" id="mcp-panel-cursor" role="tabpanel" aria-labelledby="mcp-tab-cursor">
          <pre id="mcp-command-cursor">Добавь MCP-сервер Vetmanager в настройки Cursor.

Адрес сервера: __MCP_SERVER_URL__

Ключ доступа / Bearer token я вставлю сам, но покажи путь к файлу или настройке, куда его нужно вставить.

После настройки покажи, как перезапустить Cursor-сессию и проверить подключение.</pre>
          <button class="copy-button" type="button" data-copy-target="mcp-command-cursor" aria-describedby="mcp-copy-status-cursor">Скопировать</button>
          <span class="copy-status" id="mcp-copy-status-cursor" role="status" aria-live="polite"></span>
        </div>

        <div class="tab-panel command-card" id="mcp-panel-manus" role="tabpanel" aria-labelledby="mcp-tab-manus">
          <pre id="mcp-command-manus">Подключи Vetmanager MCP.

Адрес сервера: __MCP_SERVER_URL__

Ключ доступа / Bearer token я вставлю сам, но покажи путь к файлу или настройке, куда его нужно вставить.

После подключения проверь, что доступны инструменты Vetmanager.</pre>
          <button class="copy-button" type="button" data-copy-target="mcp-command-manus" aria-describedby="mcp-copy-status-manus">Скопировать</button>
          <span class="copy-status" id="mcp-copy-status-manus" role="status" aria-live="polite"></span>
        </div>

        <div class="tab-panel command-card" id="mcp-panel-other" role="tabpanel" aria-labelledby="mcp-tab-other">
          <pre id="mcp-command-other">Подключи MCP-сервер Vetmanager.

Адрес сервера: __MCP_SERVER_URL__
Авторизация: ключ доступа / Bearer token

Ключ доступа я вставлю сам, но покажи путь к файлу или настройке, куда его нужно вставить.

После настройки перезапусти сессию или объясни, как это сделать, и проверь список доступных инструментов.</pre>
          <button class="copy-button" type="button" data-copy-target="mcp-command-other" aria-describedby="mcp-copy-status-other">Скопировать</button>
          <span class="copy-status" id="mcp-copy-status-other" role="status" aria-live="polite"></span>
          <p class="mini">Если ваш агент поддерживает MCP, используйте тот же принцип: адрес сервера, ключ доступа и перезапуск сессии.</p>
        </div>
      </div>

      <div>
        <h4 class="section-title" style="font-size: 1.45rem;">Если агент не открыл файл настроек</h4>
        <p class="body-copy">
          Попросите его ещё раз показать путь к конфигурации. Если не получилось, откройте ручную подсказку для вашего агента.
        </p>
        <div class="fallback-grid">
          <div class="fallback-card"><strong>Codex</strong><span>Попросите Codex показать путь к MCP config именно для вашей системы.</span></div>
          <div class="fallback-card"><strong>Claude</strong><span>Откройте настройки Claude Desktop / MCP servers и перезапустите Claude.</span></div>
          <div class="fallback-card"><strong>Cursor</strong><span>Откройте MCP settings в Cursor и перезапустите Cursor-сессию.</span></div>
          <div class="fallback-card"><strong>Manus</strong><span>Проверьте настройки подключений и список доступных tools.</span></div>
          <div class="fallback-card"><strong>Другой агент</strong><span>Найдите раздел MCP servers, укажите URL и авторизацию через ключ доступа.</span></div>
        </div>
      </div>

      <div>
        <h4 class="section-title" style="font-size: 1.45rem;">Примеры задач по ролям</h4>
        <div class="role-grid">
          <div class="role-card"><strong>Администратор</strong><span>Найди клиента по телефону<br>Покажи записи на завтра<br>Какие счета оплачены частично?</span></div>
          <div class="role-card"><strong>Врач</strong><span>Покажи историю питомца<br>Кому из пациентов пора на прививку?<br>Покажи последние приёмы клиента</span></div>
          <div class="role-card"><strong>Руководитель клиники</strong><span>Какая выручка была за март?<br>Собери отчёт по оплатам за неделю<br>Найди клиентов с долгом</span></div>
        </div>
      </div>

      <div>
        <h4 class="section-title" style="font-size: 1.45rem;">Частые ошибки</h4>
        <div class="error-grid">
          <div class="error-card"><strong>Агент не видит Vetmanager</strong><span>Перезапустите сессию и попросите показать список подключённых MCP-серверов.</span></div>
          <div class="error-card"><strong>Ошибка 401 / ключ доступа не подошёл</strong><span>Проверьте, что ключ вставлен в настройки и скопирован полностью.</span></div>
          <div class="error-card"><strong>Инструменты не появились</strong><span>Проверьте адрес MCP-сервера и перезапустите приложение или сессию.</span></div>
        </div>
      </div>
    </section>

    <section class="grid">
      <article class="panel wide">
        <h3 class="section-title">Что получает клиника</h3>
        <p class="body-copy">
          Сервис помогает быстрее отвечать на ежедневные вопросы клиники:
          кто записан на сегодня, какая история у пациента, есть ли долг у клиента,
          что осталось на складе и какие сотрудники свободны или загружены.
        </p>
        <ul class="list">
          <li>Врач быстрее получает историю пациента, прививки, назначения и последние приёмы.</li>
          <li>Администратор быстрее проверяет записи, клиентов, задолженности и расписание.</li>
          <li>Руководитель быстрее смотрит финансы, склад и общую картину по клинике.</li>
          <li>Доступ настраивается один раз, а дальше команда работает через AI-ассистента и service token.</li>
        </ul>
      </article>

      <article class="panel tall" id="audience">
        <h3 class="section-title">Для кого сервис</h3>
        <p class="body-copy">
          Сервис сделан для ветврачей, администраторов и руководителей клиник,
          которым нужен быстрый доступ к данным Vetmanager через AI-ассистента.
        </p>
        <ul class="list">
          <li><strong>Ветврач:</strong> история пациента, прививки, медицинские карты, последние визиты.</li>
          <li><strong>Администратор:</strong> записи, клиенты, контакты, сотрудники, задолженности.</li>
          <li><strong>Руководитель:</strong> сотрудники, загрузка врачей, сводные операционные вопросы.</li>
        </ul>
      </article>

      <article class="panel tall" id="flow">
        <h3 class="section-title">Как начать работу</h3>
        <div class="steps">
          <div class="step">
            <div>
              <p class="body-copy"><strong>Зарегистрироваться</strong><br>Создать аккаунт клиники и открыть личный кабинет.</p>
            </div>
          </div>
          <div class="step">
            <div>
              <p class="body-copy"><strong>Подключить Vetmanager</strong><br>Указать домен клиники и настроить безопасную авторизацию один раз.</p>
            </div>
          </div>
          <div class="step">
            <div>
              <p class="body-copy"><strong>Работать через AI-ассистента</strong><br>Задавать вопросы по клиентам, пациентам, приёмам, финансам и складу в одном интерфейсе.</p>
            </div>
          </div>
        </div>
      </article>

      <article class="panel wide" id="examples">
        <h3 class="section-title">Какие вопросы можно задавать</h3>
        <p class="body-copy">
          Сервис рассчитан на повседневные вопросы, которые обычно требуют
          нескольких переходов по Vetmanager или помощи администратора.
        </p>
        <ul class="list">
          <li>Покажи записи на сегодня и ближайшие приёмы по врачам.</li>
          <li>Найди клиента и покажи историю обращений его питомца.</li>
          <li>Какие пациенты давно не приходили на повторный приём?</li>
          <li>Покажи должников и суммы задолженности.</li>
          <li>Покажи неоплаченные счета и сумму задолженности.</li>
        </ul>
        <p class="mini">
          Регистрация вынесена в главный сценарий страницы, потому что именно с
          неё начинается настройка клиники и безопасного доступа команды.
        </p>
      </article>

      <article class="panel wide" id="runtime">
        <h3 class="section-title">Технический блок</h3>
        <p class="body-copy">
          Для технической команды сервис остаётся совместимым с MCP-клиентами и
          использует bearer-only runtime, но эти детали не нужны для старта работы
          клиники и спрятаны ниже как вторичный слой страницы.
        </p>
        <p class="mini">
          Формат подключения: <code>Authorization: Bearer &lt;service_token&gt;</code>.
        </p>
        <pre>{
  "mcpServers": {
    "vetmanager": {
      "url": "https://vetmanager-mcp.vromanichev.ru/mcp",
      "headers": {
        "Authorization": "Bearer vm_st_your_service_token"
      }
    }
  }
}</pre>
      </article>
    </section>

    <section class="panel" id="faq" style="border-radius: var(--radius); margin-bottom: 24px; padding: clamp(20px, 3vw, 40px);">
      <h3 class="section-title">Часто задаваемые вопросы</h3>
      <details style="margin-bottom: 12px;">
        <summary style="cursor: pointer; font-weight: 600; color: var(--ink);">Какие данные сохраняются на сервисе?</summary>
        <p class="body-copy" style="margin-top: 8px;">
          Сервис хранит только учётные данные подключения к Vetmanager (зашифрованные) и service-токены.
          Бизнес-данные клиники (клиенты, пациенты, счета) не сохраняются — они запрашиваются из Vetmanager в момент обращения.
        </p>
      </details>
      <details style="margin-bottom: 12px;">
        <summary style="cursor: pointer; font-weight: 600; color: var(--ink);">Чем это отличается от прямого использования Vetmanager API?</summary>
        <p class="body-copy" style="margin-top: 8px;">
          Vetmanager API требует знания эндпоинтов, фильтров и структуры данных.
          MCP-сервис позволяет задавать вопросы на естественном языке через AI-ассистента,
          а сервис сам выбирает нужные API-вызовы.
        </p>
      </details>
      <details style="margin-bottom: 12px;">
        <summary style="cursor: pointer; font-weight: 600; color: var(--ink);">Безопасно ли это?</summary>
        <p class="body-copy" style="margin-top: 8px;">
          Credentials клиники хранятся в зашифрованном виде. Доступ осуществляется только через
          bearer-токены, которые можно отозвать в любой момент. Логин и пароль Vetmanager не сохраняются.
        </p>
      </details>
    </section>

    <section class="panel" style="text-align: center; padding: 40px 24px; margin-top: 22px; border-radius: var(--radius); animation-delay: 0.65s;">
      <p class="eyebrow">Open Source</p>
      <h3 class="section-title" style="font-size: 1.6rem; margin-bottom: 12px;">Разверните у себя</h3>
      <p class="body-copy" style="max-width: 52ch; margin: 0 auto 20px;">
        Проект полностью открыт. Вы можете развернуть собственный экземпляр MCP-сервера
        на своём сервере для полного контроля над данными. Docker, три команды — и готово.
      </p>
      <div class="cta-row" style="justify-content: center;">
        <a class="ghost" href="https://github.com/otis22/vetmanager-mcp" target="_blank" rel="noopener" style="display: inline-flex; align-items: center; gap: 6px;">
          <svg width="18" height="18" viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
          Репозиторий на GitHub
        </a>
      </div>
    </section>

    <section class="panel" style="text-align: center; padding: 40px 24px; margin-top: 22px; border-radius: var(--radius); animation-delay: 0.7s;">
      <h3 class="section-title" style="font-size: 1.6rem; margin-bottom: 12px;">Готовы начать?</h3>
      <p class="body-copy" style="max-width: 48ch; margin: 0 auto 20px;">Регистрация занимает пару минут. Подключите AI-ассистента к данным вашей клиники уже сегодня.</p>
      <div class="cta-row" style="justify-content: center;">
        <a class="cta" href="/register">Создать аккаунт</a>
        <a class="ghost" href="/login">Войти</a>
      </div>
    </section>

    <footer class="footer" style="display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 16px;">
      <div>
        <strong>Vetmanager MCP Service</strong>
        <p style="margin: 4px 0 0; font-size: 0.9rem; color: var(--muted);">AI-ассистент для ветеринарных клиник</p>
      </div>
      <nav style="display: flex; gap: 10px; flex-wrap: wrap; font-size: 0.95rem;">
        <a class="ghost" href="/register" style="padding: 8px 16px; font-size: 0.9rem;">Регистрация</a>
        <a class="ghost" href="/login" style="padding: 8px 16px; font-size: 0.9rem;">Вход</a>
        <a class="ghost" href="#faq" style="padding: 8px 16px; font-size: 0.9rem;">FAQ</a>
        <a class="ghost" href="https://github.com/otis22/vetmanager-mcp" target="_blank" rel="noopener" style="padding: 8px 16px; font-size: 0.9rem;">GitHub</a>
        <a class="ghost" href="mailto:support@vetmanager.cloud" style="padding: 8px 16px; font-size: 0.9rem;">Поддержка</a>
      </nav>
      <div style="text-align: right; font-size: 0.9rem; color: var(--muted);">
        <p style="margin: 0;">&copy; 2026 Vetmanager MCP</p>
        <p style="margin: 4px 0 0;"><a href="#" style="text-decoration: none; color: var(--accent);">Политика конфиденциальности</a></p>
      </div>
    </footer>
  </div>
  <script>
    (() => {
      const root = document.getElementById("mcp-onboarding");
      if (!root) return;

      const tabs = Array.from(root.querySelectorAll('[role="tab"]'));
      const panels = Array.from(root.querySelectorAll('[role="tabpanel"]'));

      const activateTab = (activeTab) => {
        tabs.forEach((tab) => {
          const isActive = tab === activeTab;
          tab.setAttribute("aria-selected", isActive ? "true" : "false");
          tab.setAttribute("tabindex", isActive ? "0" : "-1");
        });
        panels.forEach((panel) => {
          panel.hidden = panel.id !== activeTab.getAttribute("aria-controls");
        });
      };

      tabs.forEach((tab) => {
        tab.addEventListener("click", () => activateTab(tab));
        tab.addEventListener("keydown", (event) => {
          const currentIndex = tabs.indexOf(tab);
          let nextIndex = currentIndex;
          if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % tabs.length;
          if (event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
          if (event.key === "Home") nextIndex = 0;
          if (event.key === "End") nextIndex = tabs.length - 1;
          if (nextIndex === currentIndex) return;
          event.preventDefault();
          activateTab(tabs[nextIndex]);
          tabs[nextIndex].focus();
        });
      });
      const initiallyActive = tabs.find((tab) => tab.getAttribute("aria-selected") === "true") || tabs[0];
      if (initiallyActive) activateTab(initiallyActive);

      root.querySelectorAll("[data-copy-target]").forEach((button) => {
        button.addEventListener("click", async () => {
          const target = document.getElementById(button.getAttribute("data-copy-target"));
          const status = document.getElementById(button.getAttribute("aria-describedby"));
          const showStatus = (message) => {
            if (!status) return;
            status.textContent = message;
            window.setTimeout(() => {
              status.textContent = "";
            }, 2000);
          };
          if (!target || !navigator.clipboard || !navigator.clipboard.writeText) {
            showStatus("Выделите текст вручную");
            return;
          }
          try {
            await navigator.clipboard.writeText(target.textContent);
            showStatus("Скопировано");
          } catch (error) {
            showStatus("Выделите текст вручную");
          }
        });
      });
    })();
  </script>
</body>
</html>
"""
    base_url = _resolve_site_base_url()
    mcp_url = f"{base_url}{_resolve_mcp_path()}"
    html = html.replace("__MCP_SERVER_URL__", mcp_url)
    if base_url != _DEFAULT_SITE_BASE_URL:
        html = html.replace(_DEFAULT_SITE_BASE_URL, base_url)
    if "__MCP_SERVER_URL__" in html:
        raise RuntimeError("MCP server URL placeholder was not replaced")
    return html
