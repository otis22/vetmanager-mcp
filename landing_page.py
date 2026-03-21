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
    content="Bearer-only MCP service for Vetmanager with account-scoped clinic integration and service tokens."
  >
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
    .hero h2,
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
    }

    .topbar nav a:hover,
    .cta:hover,
    .ghost:hover {
      transform: translateY(-1px);
    }

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

    .hero h2 {
      margin: 0;
      font-size: clamp(2.8rem, 6vw, 5.4rem);
      line-height: 0.95;
      max-width: 10ch;
    }

    .hero h2 span {
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
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.48);
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
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <div class="seal">VM</div>
        <div>
          <h1>Vetmanager MCP Service</h1>
          <p>Bearer-only gateway for clinic operations through AI clients</p>
        </div>
      </div>
      <nav>
        <a href="#product">Продукт</a>
        <a href="#flow">Подключение</a>
        <a href="#runtime">MCP runtime</a>
      </nav>
    </header>

    <section class="hero" id="product">
      <div>
        <p class="eyebrow">Vetmanager x MCP</p>
        <h2>Один <span>service token</span> вместо ручной прокладки секретов.</h2>
        <p class="lede">
          Vetmanager MCP Service переводит клинику на bearer-only контур:
          MCP-клиент видит только <code>Authorization: Bearer &lt;service_token&gt;</code>,
          а домен клиники и Vetmanager API key остаются внутри account-level integration.
        </p>
        <div class="cta-row">
          <a class="cta" href="#runtime">Посмотреть MCP-подключение</a>
          <a class="ghost" href="/mcp">Открыть MCP endpoint</a>
        </div>
      </div>
      <div class="hero-side">
        <div class="stat">
          <strong>75</strong>
          <span>инструментов уже доступны через bearer-authenticated runtime.</span>
        </div>
        <div class="stat">
          <strong>20</strong>
          <span>готовых prompts для администратора, врача, финансового и складского контуров.</span>
        </div>
        <div class="stat">
          <strong>1</strong>
          <span>активная Vetmanager integration на account, которую разделяют все токены этого аккаунта.</span>
        </div>
      </div>
    </section>

    <section class="grid">
      <article class="panel wide">
        <h3 class="section-title">Что уже умеет сервис</h3>
        <p class="body-copy">
          Bearer runtime, account-scoped Vetmanager integration, encrypted secret storage,
          hash-only token storage и tool/prompt слой уже работают как единый контракт.
          Следующий шаг продукта — вынести это в полноценный web-кабинет.
        </p>
        <ul class="list">
          <li>Account хранит активное подключение к Vetmanager через <code>domain + rest_api_key</code>.</li>
          <li>Bearer-токены живут отдельно, имеют статус, срок действия и безопасный <code>token_prefix</code>.</li>
          <li>Tools не принимают runtime credentials в аргументах и работают только через account context.</li>
        </ul>
      </article>

      <article class="panel tall">
        <h3 class="section-title">Текущий статус продукта</h3>
        <p class="body-copy">
          Self-service кабинет ещё в работе. Лендинг уже публичный, а регистрация,
          настройка интеграции и выпуск токенов идут следующим этапом web-контура.
        </p>
        <p class="mini">
          Иначе говоря: runtime и storage уже продуктовые, а пользовательский UI
          только начинает обрастать интерфейсом.
        </p>
      </article>

      <article class="panel tall" id="flow">
        <h3 class="section-title">Как выглядит путь подключения</h3>
        <div class="steps">
          <div class="step">
            <div>
              <p class="body-copy"><strong>Создать account</strong><br>Зарегистрировать рабочее пространство клиники в сервисе.</p>
            </div>
          </div>
          <div class="step">
            <div>
              <p class="body-copy"><strong>Подключить Vetmanager</strong><br>Указать <code>domain</code> и Vetmanager <code>rest_api_key</code> один раз на уровне аккаунта.</p>
            </div>
          </div>
          <div class="step">
            <div>
              <p class="body-copy"><strong>Выпустить service token</strong><br>Использовать Bearer в Cursor или другом MCP-клиенте без прокидывания секретов клиники.</p>
            </div>
          </div>
        </div>
      </article>

      <article class="panel wide" id="runtime">
        <h3 class="section-title">Bearer-only MCP runtime</h3>
        <p class="body-copy">
          Конфигурация клиента теперь сводится к одному заголовку. MCP endpoint
          остаётся на <code>/mcp</code>, а доменные credentials больше не живут в локальном клиентском конфиге.
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
        <p class="mini">
          Runtime errors для missing, invalid, expired и revoked bearer уже реализованы
          и не раскрывают секреты Vetmanager.
        </p>
      </article>
    </section>

    <footer class="footer">
      <div><strong>Endpoint:</strong> <code>/mcp</code></div>
      <div><strong>Mode:</strong> bearer-only, account-scoped Vetmanager connection</div>
      <div><strong>Next:</strong> регистрация, кабинет, выпуск токенов</div>
    </footer>
  </div>
</body>
</html>
"""
