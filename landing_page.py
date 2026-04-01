"""Static landing page for the public web entry point."""

from __future__ import annotations


def render_landing_page() -> str:
    """Return the public landing page HTML."""
    return """<!doctype html>
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
  <meta property="og:url" content="https://342915.simplecloud.ru/">
  <link rel="canonical" href="https://342915.simplecloud.ru/">
  <meta name="twitter:card" content="summary">
  <meta name="twitter:title" content="Vetmanager MCP Service">
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90' font-weight='700' fill='%23bb4d24'>VM</text></svg>">
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
      .grid {
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
        <a class="nav-link" href="#product">Возможности</a>
        <a class="nav-link" href="#audience">Для кого</a>
        <a class="nav-link" href="#examples">Примеры</a>
        <a class="ghost" href="/login">Войти</a>
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
          <span>Записи на сегодня, долги клиентов, выручка и остатки доступны через один AI-интерфейс.</span>
        </div>
        <div class="stat">
          <strong>Безопасное подключение</strong>
          <span>Интеграция подключается один раз на уровне аккаунта клиники, а доступ выдаётся через service token.</span>
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
          <li><strong>Руководитель:</strong> финансы, склад, выручка, сотрудники и общая операционная картина.</li>
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
          <li>Какие товары заканчиваются на складе?</li>
          <li>Покажи выручку и последние оплаты.</li>
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
      "url": "http://localhost:8000/mcp",
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
        <a class="ghost" href="mailto:support@vetmanager.cloud" style="padding: 8px 16px; font-size: 0.9rem;">Поддержка</a>
      </nav>
      <div style="text-align: right; font-size: 0.9rem; color: var(--muted);">
        <p style="margin: 0;">&copy; 2026 Vetmanager MCP</p>
        <p style="margin: 4px 0 0;"><a href="#" style="text-decoration: none; color: var(--accent);">Политика конфиденциальности</a></p>
      </div>
    </footer>
  </div>
</body>
</html>
"""
