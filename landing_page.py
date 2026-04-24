"""Static landing page for the public web entry point.

Stage 148 visual redesign: clinical-tech direction (ink-blue + moss-green +
warm-grey) with editorial typography, hero mock-chat showing real revenue
numbers, unified Lucide-style inline-SVG icon system, progressive disclosure
for tech/FAQ, and mobile-first sticky CTA. Content from Stage 146 (MCP
onboarding, agent tabs, fallbacks, role examples, errors) is preserved
verbatim so existing test_landing_page.py assertions continue to hold.
"""

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
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#1e3a4d">
  <title>Vetmanager MCP Service — AI-ассистент для ветклиник</title>
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
  <link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect width='100' height='100' rx='22' fill='%231e3a4d'/><text y='66' x='50' text-anchor='middle' font-size='48' font-weight='700' fill='%23f5f5f0' font-family='ui-sans-serif,system-ui,sans-serif' letter-spacing='-2'>VM</text><circle cx='78' cy='24' r='6' fill='%23bb4d24'/></svg>">
  <style>
    :root {
      /* Ink-blue clinical-tech palette */
      --ink-900: #0c1d27;
      --ink-800: #14303f;
      --ink-700: #1e3a4d;
      --ink-500: #3a5566;
      --ink-400: #4f6b7a;
      --ink-300: #7a909b;
      --ink-200: #aebac1;
      --ink-100: #d6dde1;
      --ink-50:  #ebeef0;

      --paper:       #f5f5f0;
      --paper-warm:  #faf8f3;
      --paper-card:  #ffffff;

      --accent:      #bb4d24;
      --accent-700:  #963c1a;
      --accent-50:   #fdf1ea;

      --moss:        #5a7a5e;
      --moss-50:     #e8efe9;

      --amber-50:    #fbf3e1;
      --amber-700:   #8a5a16;

      --line:        rgba(15, 31, 41, 0.10);
      --line-strong: rgba(15, 31, 41, 0.18);

      --shadow-sm: 0 1px 2px rgba(15, 31, 41, 0.05),
                   0 1px 1px rgba(15, 31, 41, 0.04);
      --shadow-md: 0 8px 22px rgba(15, 31, 41, 0.07),
                   0 2px 6px rgba(15, 31, 41, 0.04);
      --shadow-lg: 0 28px 60px rgba(15, 31, 41, 0.10),
                   0 6px 16px rgba(15, 31, 41, 0.06);

      --r-xs: 6px;
      --r-sm: 10px;
      --r-md: 14px;
      --r-lg: 20px;
      --r-xl: 28px;

      --font-display: "Iowan Old Style", "Source Serif Pro", "Charter", "Cambria", Georgia, serif;
      --font-body:    "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, "Helvetica Neue", Arial, sans-serif;
      --font-mono:    "JetBrains Mono", "SF Mono", "Cascadia Mono", Menlo, Consolas, monospace;
    }

    * { box-sizing: border-box; }

    html { scroll-behavior: smooth; -webkit-text-size-adjust: 100%; }

    body {
      margin: 0;
      color: var(--ink-700);
      background: var(--paper);
      font-family: var(--font-body);
      font-size: 16px;
      line-height: 1.6;
      font-feature-settings: "ss01", "cv01", "tnum";
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
    }

    /* Subtle clinical-tech atmosphere: faint dotted grain top-left,
       warm wash bottom-right. No grid paper. */
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      z-index: -1;
      background:
        radial-gradient(70% 50% at 0% 0%, rgba(30, 58, 77, 0.06), transparent 60%),
        radial-gradient(60% 50% at 100% 100%, rgba(187, 77, 36, 0.05), transparent 60%);
    }

    img, svg { display: block; max-width: 100%; }

    a { color: var(--ink-700); text-decoration: none; }
    a:hover { color: var(--ink-900); }

    h1, h2, h3, h4 { color: var(--ink-900); margin: 0; }

    .display {
      font-family: var(--font-display);
      font-weight: 600;
      letter-spacing: -0.015em;
      line-height: 1.04;
    }

    p { margin: 0; }

    /* Skip link for keyboard users */
    .skip-link {
      position: absolute;
      left: -9999px;
      top: 0;
      background: var(--ink-900);
      color: var(--paper);
      padding: 10px 14px;
      border-radius: 0 0 12px 0;
      font-weight: 600;
      z-index: 100;
    }
    .skip-link:focus { left: 0; }

    a:focus-visible,
    button:focus-visible,
    input:focus-visible,
    summary:focus-visible,
    label:focus-visible {
      outline: 2px solid var(--accent);
      outline-offset: 3px;
      border-radius: var(--r-xs);
    }

    /* ------------------------------------------------------------ Layout */

    .shell {
      width: min(1200px, calc(100% - 32px));
      margin: 0 auto;
    }

    .section {
      padding: clamp(56px, 8vw, 112px) 0;
      border-top: 1px solid var(--line);
    }
    .section.no-top { border-top: 0; }

    .section-label {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      font-size: 0.78rem;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: var(--ink-500);
      font-weight: 600;
      margin: 0 0 18px;
    }
    .section-label::before {
      content: "";
      display: block;
      width: 28px;
      height: 1px;
      background: var(--accent);
    }

    .section-title {
      font-family: var(--font-display);
      font-weight: 600;
      letter-spacing: -0.012em;
      line-height: 1.1;
      font-size: clamp(1.8rem, 3.6vw, 2.6rem);
      margin: 0 0 16px;
      color: var(--ink-900);
      max-width: 26ch;
    }

    .section-lede {
      max-width: 60ch;
      color: var(--ink-500);
      font-size: 1.05rem;
      line-height: 1.65;
    }

    /* ------------------------------------------------------------ Topbar */

    .topbar-wrap {
      position: sticky;
      top: 0;
      z-index: 30;
      background: rgba(245, 245, 240, 0.85);
      backdrop-filter: saturate(140%) blur(12px);
      -webkit-backdrop-filter: saturate(140%) blur(12px);
      border-bottom: 1px solid var(--line);
    }

    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 14px 0;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 12px;
      min-width: 0;
      flex: 1 1 auto;
    }
    .brand > div { min-width: 0; }
    .brand h1, .brand p { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

    .seal {
      width: 40px;
      height: 40px;
      border-radius: 12px;
      background: var(--ink-700);
      color: var(--paper);
      display: grid;
      place-items: center;
      font-weight: 700;
      font-size: 0.9rem;
      letter-spacing: 0.04em;
      box-shadow: var(--shadow-sm);
      position: relative;
    }
    .seal::after {
      content: "";
      position: absolute;
      top: 6px;
      right: 6px;
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--accent);
    }

    .brand h1 {
      margin: 0;
      font-size: 0.92rem;
      font-weight: 600;
      letter-spacing: -0.005em;
      color: var(--ink-900);
      text-transform: none;
      font-family: var(--font-body);
    }
    .brand p {
      margin: 1px 0 0;
      font-size: 0.78rem;
      color: var(--ink-300);
      letter-spacing: 0.005em;
    }

    nav { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }

    nav a {
      font-size: 0.92rem;
      font-weight: 500;
      color: var(--ink-500);
      padding: 9px 14px;
      border-radius: 10px;
      transition: background 160ms ease, color 160ms ease, transform 160ms ease;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }
    nav a:hover { background: var(--ink-50); color: var(--ink-900); }

    nav a.nav-cta {
      background: var(--ink-700);
      color: var(--paper);
      font-weight: 600;
    }
    nav a.nav-cta:hover { background: var(--ink-900); color: var(--paper); transform: translateY(-1px); }

    nav a.nav-ghost {
      border: 1px solid var(--line-strong);
      color: var(--ink-700);
    }
    nav a.nav-ghost:hover { background: var(--paper-card); border-color: var(--ink-300); }

    /* Hamburger */
    .menu-toggle { display: none; }
    .hamburger {
      display: none;
      cursor: pointer;
      width: 44px;
      height: 44px;
      align-items: center;
      justify-content: center;
      border: 1px solid var(--line-strong);
      border-radius: 10px;
      background: var(--paper-card);
      padding: 0;
    }
    .hamburger span,
    .hamburger span::before,
    .hamburger span::after {
      display: block;
      width: 18px;
      height: 1.5px;
      background: var(--ink-700);
      border-radius: 1px;
      transition: transform 200ms ease, opacity 200ms ease, background 200ms ease;
      position: relative;
    }
    .hamburger span::before,
    .hamburger span::after {
      content: "";
      position: absolute;
      left: 0;
      width: 100%;
    }
    .hamburger span::before { top: -6px; }
    .hamburger span::after  { top: 6px; }
    .menu-toggle:checked ~ nav { display: flex; }
    .menu-toggle:checked ~ .hamburger span { background: transparent; }
    .menu-toggle:checked ~ .hamburger span::before {
      top: 0; transform: rotate(45deg); background: var(--ink-700);
    }
    .menu-toggle:checked ~ .hamburger span::after {
      top: 0; transform: rotate(-45deg); background: var(--ink-700);
    }

    /* ------------------------------------------------------------ Hero */

    .hero {
      padding: clamp(56px, 8vw, 110px) 0 clamp(40px, 6vw, 80px);
      position: relative;
    }

    .hero-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.05fr) minmax(0, 0.95fr);
      gap: clamp(32px, 4vw, 64px);
      align-items: center;
    }

    .hero h1 {
      font-family: var(--font-display);
      font-weight: 600;
      letter-spacing: -0.018em;
      line-height: 1.02;
      font-size: clamp(2.4rem, 5.2vw, 4.4rem);
      color: var(--ink-900);
      max-width: 14ch;
    }
    .hero h1 em {
      font-style: italic;
      color: var(--accent);
      font-weight: 500;
    }

    .hero-lede {
      max-width: 52ch;
      color: var(--ink-500);
      font-size: 1.12rem;
      line-height: 1.6;
      margin: 22px 0 0;
    }

    .hero-fineprint {
      margin: 18px 0 0;
      max-width: 60ch;
      color: var(--ink-400);
      font-size: 0.92rem;
      line-height: 1.55;
      padding-left: 14px;
      border-left: 2px solid var(--line);
    }
    .hero-fineprint + .hero-fineprint { margin-top: 10px; }

    .cta-row {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      margin-top: 32px;
    }
    .cta-row .ghost-link {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      color: var(--ink-700);
      font-weight: 500;
      font-size: 0.95rem;
      padding: 12px 4px;
    }
    .cta-row .ghost-link:hover { color: var(--ink-900); }

    .cta {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: var(--accent);
      color: #fff;
      padding: 14px 22px;
      border-radius: 999px;
      font-weight: 600;
      font-size: 0.98rem;
      box-shadow: var(--shadow-md);
      transition: transform 180ms ease, background 180ms ease, box-shadow 180ms ease;
    }
    .cta:hover {
      background: var(--accent-700);
      transform: translateY(-1px);
      box-shadow: var(--shadow-lg);
      color: #fff;
    }

    .ghost {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      background: transparent;
      color: var(--ink-700);
      padding: 13px 20px;
      border-radius: 999px;
      font-weight: 600;
      font-size: 0.98rem;
      border: 1.5px solid var(--ink-200);
      transition: border-color 180ms ease, background 180ms ease;
    }
    .ghost:hover { border-color: var(--ink-700); background: var(--paper-card); }

    .returning-hint {
      margin-top: 14px;
      font-size: 0.92rem;
      color: var(--ink-400);
    }
    .returning-hint a {
      color: var(--ink-700);
      text-decoration: underline;
      text-decoration-color: var(--line-strong);
      text-underline-offset: 3px;
      font-weight: 500;
    }
    .returning-hint a:hover { text-decoration-color: var(--accent); color: var(--ink-900); }

    .trust-strip {
      display: flex;
      flex-wrap: wrap;
      gap: 6px 22px;
      margin-top: 36px;
      padding-top: 24px;
      border-top: 1px solid var(--line);
    }
    .trust-item {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-size: 0.85rem;
      color: var(--ink-500);
      font-weight: 500;
    }
    .trust-item svg { color: var(--moss); }

    /* Mock chat in hero */
    .mock-chat {
      background: var(--paper-card);
      border: 1px solid var(--line);
      border-radius: var(--r-lg);
      box-shadow: var(--shadow-lg);
      overflow: hidden;
      position: relative;
    }
    .mock-chat::before {
      content: "";
      position: absolute;
      inset: -40% -10% auto auto;
      width: 70%;
      height: 80%;
      background: radial-gradient(circle, rgba(187, 77, 36, 0.10), transparent 65%);
      pointer-events: none;
      z-index: 0;
    }

    .mock-head {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 14px 18px;
      border-bottom: 1px solid var(--line);
      background: var(--paper-warm);
      position: relative;
      z-index: 1;
    }
    .mock-head .dots { display: flex; gap: 6px; }
    .mock-head .dots i {
      display: block;
      width: 9px;
      height: 9px;
      border-radius: 50%;
      background: var(--ink-100);
    }
    .mock-head .dots i:nth-child(2) { background: var(--ink-200); }
    .mock-head .label {
      font-family: var(--font-mono);
      font-size: 0.76rem;
      color: var(--ink-300);
      letter-spacing: 0.04em;
      margin-left: 8px;
    }
    .mock-head .live {
      margin-left: auto;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 0.75rem;
      color: var(--moss);
      font-weight: 600;
    }
    .mock-head .live::before {
      content: "";
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--moss);
      box-shadow: 0 0 0 3px rgba(90, 122, 94, 0.18);
      animation: pulse 2.4s ease-in-out infinite;
    }

    .mock-body {
      padding: 22px 22px 24px;
      display: grid;
      gap: 16px;
      position: relative;
      z-index: 1;
    }

    .bubble {
      max-width: 88%;
      padding: 12px 16px;
      border-radius: 16px;
      line-height: 1.45;
      font-size: 0.95rem;
    }
    .bubble.user {
      background: var(--ink-50);
      color: var(--ink-800);
      border-top-left-radius: 6px;
      align-self: flex-start;
      border: 1px solid var(--line);
    }
    .bubble.user::before {
      content: "Вы";
      display: block;
      font-size: 0.72rem;
      font-weight: 600;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--ink-300);
      margin-bottom: 4px;
    }

    .answer-card {
      align-self: stretch;
      background: var(--paper-warm);
      border: 1px solid var(--line);
      border-radius: 16px;
      border-top-right-radius: 6px;
      padding: 16px 18px;
      margin-left: auto;
      width: 100%;
    }
    .answer-card .who {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-size: 0.72rem;
      font-weight: 600;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      color: var(--ink-300);
      margin-bottom: 10px;
    }
    .answer-card .who svg { color: var(--accent); }

    .revenue-headline {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 12px;
    }
    .revenue-headline .total {
      font-family: var(--font-display);
      font-weight: 600;
      font-size: 1.7rem;
      letter-spacing: -0.015em;
      color: var(--ink-900);
      font-variant-numeric: tabular-nums;
    }
    .revenue-headline .delta {
      font-size: 0.82rem;
      font-weight: 600;
      color: var(--moss);
      background: var(--moss-50);
      padding: 4px 8px;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      gap: 4px;
    }

    .bar-chart {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 10px;
      align-items: end;
      height: 78px;
      padding: 0 2px;
      margin: 8px 0 14px;
    }
    .bar {
      display: grid;
      grid-template-rows: 1fr auto;
      gap: 4px;
      height: 100%;
    }
    .bar .col {
      background: linear-gradient(180deg, var(--ink-700), var(--ink-500));
      border-radius: 6px 6px 2px 2px;
      align-self: end;
      width: 100%;
      position: relative;
    }
    .bar .col::after {
      content: attr(data-amount);
      position: absolute;
      top: -16px;
      left: 50%;
      transform: translateX(-50%);
      font-size: 0.66rem;
      color: var(--ink-300);
      font-variant-numeric: tabular-nums;
      white-space: nowrap;
    }
    .bar.peak .col {
      background: linear-gradient(180deg, var(--accent), var(--accent-700));
    }
    .bar .lbl {
      font-size: 0.68rem;
      color: var(--ink-400);
      text-align: center;
      letter-spacing: 0.02em;
    }

    .breakdown {
      list-style: none;
      padding: 0;
      margin: 4px 0 0;
      display: grid;
      gap: 6px;
      font-size: 0.84rem;
      font-variant-numeric: tabular-nums;
    }
    .breakdown li {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      padding: 4px 0;
      border-bottom: 1px dashed var(--line);
      color: var(--ink-500);
    }
    .breakdown li:last-child { border-bottom: 0; }
    .breakdown li b {
      color: var(--ink-900);
      font-weight: 600;
    }

    .mock-source {
      margin-top: 12px;
      padding-top: 12px;
      border-top: 1px solid var(--line);
      font-size: 0.78rem;
      color: var(--ink-400);
      display: flex;
      align-items: center;
      gap: 6px;
      flex-wrap: wrap;
    }
    .mock-source svg { color: var(--moss); flex-shrink: 0; }
    .mock-source span { color: var(--ink-300); }

    /* ------------------------------------------------------------ Cards */

    .card {
      background: var(--paper-card);
      border: 1px solid var(--line);
      border-radius: var(--r-lg);
      padding: clamp(20px, 2.5vw, 28px);
      transition: border-color 200ms ease, transform 200ms ease, box-shadow 200ms ease;
    }
    .card:hover {
      border-color: var(--ink-200);
      transform: translateY(-2px);
      box-shadow: var(--shadow-md);
    }

    .card .ic-wrap {
      width: 44px;
      height: 44px;
      border-radius: 12px;
      display: grid;
      place-items: center;
      background: var(--ink-50);
      color: var(--ink-700);
      margin-bottom: 18px;
    }
    .card .ic-wrap.accent { background: var(--accent-50); color: var(--accent); }
    .card .ic-wrap.moss   { background: var(--moss-50);   color: var(--moss); }
    .card .ic-wrap.amber  { background: var(--amber-50);  color: var(--amber-700); }

    .card h3 {
      font-family: var(--font-display);
      font-weight: 600;
      font-size: 1.18rem;
      letter-spacing: -0.005em;
      margin: 0 0 8px;
      color: var(--ink-900);
    }
    .card p {
      color: var(--ink-500);
      font-size: 0.96rem;
      line-height: 1.6;
    }
    .card ul {
      margin: 8px 0 0;
      padding: 0;
      list-style: none;
      display: grid;
      gap: 8px;
      color: var(--ink-500);
      font-size: 0.94rem;
      line-height: 1.55;
    }
    .card ul li {
      padding-left: 18px;
      position: relative;
    }
    .card ul li::before {
      content: "";
      position: absolute;
      left: 0;
      top: 0.62em;
      width: 6px;
      height: 6px;
      border-radius: 50%;
      background: var(--accent);
    }
    .card ul li strong { color: var(--ink-900); font-weight: 600; }

    /* ------------------------------------------------------------ MCP explainer */

    .explainer {
      display: grid;
      grid-template-columns: minmax(0, 0.45fr) minmax(0, 0.55fr);
      gap: clamp(28px, 5vw, 72px);
      align-items: start;
    }
    .explainer .label-block { position: sticky; top: 100px; }
    .explainer h2 {
      font-family: var(--font-display);
      font-weight: 600;
      font-size: clamp(1.7rem, 3vw, 2.4rem);
      letter-spacing: -0.012em;
      margin: 0 0 10px;
      color: var(--ink-900);
    }
    .explainer .body p {
      color: var(--ink-500);
      font-size: 1.02rem;
      line-height: 1.7;
      margin-bottom: 14px;
    }
    .explainer .body p:last-child { margin-bottom: 0; }
    .explainer .body strong { color: var(--ink-900); font-weight: 600; }

    /* ------------------------------------------------------------ Onboarding */

    .onboarding {
      display: grid;
      gap: clamp(36px, 5vw, 64px);
    }

    .onboarding-head {
      display: grid;
      grid-template-columns: minmax(0, 1.05fr) minmax(0, 0.95fr);
      gap: clamp(28px, 4vw, 56px);
      align-items: start;
    }
    .onboarding-head h2 {
      font-family: var(--font-display);
      font-weight: 600;
      font-size: clamp(2rem, 4vw, 3rem);
      letter-spacing: -0.015em;
      line-height: 1.05;
      max-width: 14ch;
    }
    .onboarding-head .lede {
      color: var(--ink-500);
      font-size: 1.05rem;
      line-height: 1.65;
      margin: 18px 0 0;
      max-width: 56ch;
    }
    .onboarding-head .lede strong { color: var(--ink-900); font-weight: 600; }

    /* Flow diagram (5 nodes) */
    .flow-map {
      display: grid;
      gap: 10px;
      padding: clamp(18px, 2vw, 24px);
      background: var(--paper-card);
      border: 1px solid var(--line);
      border-radius: var(--r-lg);
      position: relative;
    }
    .flow-map::before {
      content: "Поток";
      position: absolute;
      top: -10px;
      left: 18px;
      background: var(--paper);
      padding: 2px 10px;
      font-size: 0.7rem;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: var(--ink-400);
      font-weight: 600;
      border-radius: 999px;
      border: 1px solid var(--line);
    }
    .flow-node {
      display: grid;
      grid-template-columns: 36px minmax(0, 1fr);
      gap: 14px;
      align-items: start;
      padding: 12px 14px;
      border-radius: 12px;
      background: var(--paper-warm);
      border: 1px solid var(--line);
    }
    .flow-node:nth-child(2) { animation-delay: 80ms; }
    .flow-node .num {
      width: 32px;
      height: 32px;
      border-radius: 8px;
      background: var(--ink-700);
      color: var(--paper);
      display: grid;
      place-items: center;
      font-size: 0.82rem;
      font-weight: 700;
      letter-spacing: 0;
      font-family: var(--font-mono);
    }
    .flow-node strong {
      display: block;
      color: var(--ink-900);
      font-weight: 600;
      font-size: 0.95rem;
      margin-bottom: 2px;
    }
    .flow-node span {
      display: block;
      color: var(--ink-400);
      font-size: 0.86rem;
      line-height: 1.45;
    }
    .flow-arrow {
      text-align: center;
      color: var(--ink-200);
      font-size: 0.9rem;
      line-height: 1;
      padding: 2px 0;
    }

    /* Prompt chips */
    .prompts-wrap h3 {
      font-family: var(--font-display);
      font-weight: 600;
      font-size: 1.5rem;
      letter-spacing: -0.008em;
      margin: 0 0 14px;
    }
    .prompt-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 12px;
    }
    .prompt-chip {
      margin: 0;
      padding: 14px 16px;
      border-radius: 14px;
      background: var(--paper-card);
      border: 1px solid var(--line);
      color: var(--ink-800);
      font-size: 0.95rem;
      line-height: 1.45;
      font-weight: 500;
      display: flex;
      align-items: flex-start;
      gap: 10px;
      transition: border-color 180ms ease, transform 180ms ease;
    }
    .prompt-chip:hover { border-color: var(--ink-200); transform: translateY(-1px); }
    .prompt-chip svg { color: var(--ink-300); flex-shrink: 0; margin-top: 2px; }
    .prompt-chip:hover svg { color: var(--accent); }

    /* Quick steps */
    .quick-steps {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
      margin: 0;
    }
    .quick-step {
      padding: 18px 20px;
      border-radius: var(--r-md);
      background: var(--paper-card);
      border: 1px solid var(--line);
      display: grid;
      gap: 6px;
    }
    .quick-step .num {
      font-family: var(--font-mono);
      font-size: 0.78rem;
      letter-spacing: 0.06em;
      color: var(--accent);
      font-weight: 700;
    }
    .quick-step strong {
      font-family: var(--font-display);
      font-weight: 600;
      font-size: 1.08rem;
      color: var(--ink-900);
    }
    .quick-step span {
      color: var(--ink-500);
      font-size: 0.92rem;
      line-height: 1.5;
    }

    .privacy-note {
      margin-top: 18px;
      padding: 16px 18px;
      border-radius: var(--r-md);
      background: var(--amber-50);
      border: 1px solid rgba(187, 77, 36, 0.18);
      color: var(--amber-700);
      line-height: 1.55;
      font-size: 0.94rem;
      display: grid;
      grid-template-columns: 22px minmax(0, 1fr);
      gap: 12px;
      align-items: start;
    }
    .privacy-note svg { color: var(--accent); margin-top: 2px; }
    .privacy-note a { color: var(--ink-900); font-weight: 600; text-decoration: underline; text-decoration-color: rgba(187, 77, 36, 0.4); text-underline-offset: 2px; }

    /* Tabs */
    .agent-tabs { display: grid; gap: 18px; }
    .tab-list {
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      padding: 6px;
      background: var(--paper-card);
      border: 1px solid var(--line);
      border-radius: 14px;
      box-shadow: var(--shadow-sm);
    }
    .tab-button {
      border: 0;
      background: transparent;
      color: var(--ink-500);
      cursor: pointer;
      font: inherit;
      font-weight: 600;
      font-size: 0.92rem;
      padding: 9px 16px;
      border-radius: 9px;
      transition: background 160ms ease, color 160ms ease;
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }
    .tab-button:hover { background: var(--ink-50); color: var(--ink-900); }
    .tab-button[aria-selected="true"] {
      background: var(--ink-700);
      color: var(--paper);
    }
    .tab-button[aria-selected="true"]:hover { color: var(--paper); }

    .badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      width: fit-content;
      border-radius: 999px;
      padding: 4px 10px;
      background: var(--moss-50);
      color: var(--moss);
      font-size: 0.78rem;
      font-weight: 600;
      letter-spacing: 0;
    }

    .command-card {
      display: grid;
      gap: 14px;
      padding: 22px;
      background: var(--paper-card);
      border: 1px solid var(--line);
      border-radius: var(--r-lg);
      box-shadow: var(--shadow-sm);
    }
    .command-card[hidden] { display: none; }
    .command-card pre {
      margin: 0;
      padding: 18px 20px;
      background: var(--ink-900);
      color: #e6eaed;
      font: 0.86rem/1.65 var(--font-mono);
      border-radius: var(--r-md);
      overflow-x: auto;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
    }
    .command-actions {
      display: flex;
      align-items: center;
      gap: 14px;
      flex-wrap: wrap;
    }
    .copy-button {
      border: 0;
      cursor: pointer;
      background: var(--accent);
      color: #fff;
      font: inherit;
      font-weight: 600;
      font-size: 0.92rem;
      padding: 10px 18px;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      gap: 8px;
      transition: background 180ms ease, transform 180ms ease;
    }
    .copy-button:hover { background: var(--accent-700); transform: translateY(-1px); }
    .copy-status {
      min-height: 1.2em;
      color: var(--moss);
      font-size: 0.88rem;
      font-weight: 600;
    }
    .copy-status:empty { min-height: 0; }
    .command-card .mini { color: var(--ink-400); font-size: 0.88rem; line-height: 1.5; margin: 0; }

    #mcp-agent-instructions {
      display: grid;
      gap: 8px;
      padding-top: 16px;
      border-top: 1px solid var(--line);
    }

    /* Fallback / Errors / Roles */
    .grid-3 {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 14px;
    }
    .grid-5 {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 12px;
    }
    .mini-card {
      padding: 16px 18px;
      border-radius: var(--r-md);
      background: var(--paper-card);
      border: 1px solid var(--line);
      display: grid;
      gap: 6px;
    }
    .mini-card strong {
      color: var(--ink-900);
      font-family: var(--font-display);
      font-weight: 600;
      font-size: 1rem;
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }
    .mini-card strong svg { color: var(--ink-500); }
    .mini-card.error strong svg { color: var(--accent); }
    .mini-card span {
      color: var(--ink-500);
      font-size: 0.9rem;
      line-height: 1.5;
    }

    .subhead {
      font-family: var(--font-display);
      font-weight: 600;
      font-size: 1.5rem;
      letter-spacing: -0.008em;
      margin: 0 0 14px;
      color: var(--ink-900);
    }

    /* ------------------------------------------------------------ Benefits / Audience */

    .two-col {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
      gap: 18px;
    }

    .audience-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 14px;
      margin-top: 28px;
    }

    .step-list {
      display: grid;
      gap: 14px;
      counter-reset: step;
      margin-top: 22px;
    }
    .step-row {
      display: grid;
      grid-template-columns: 56px minmax(0, 1fr);
      gap: 18px;
      padding: 18px 20px;
      background: var(--paper-card);
      border: 1px solid var(--line);
      border-radius: var(--r-md);
      align-items: start;
    }
    .step-row::before {
      counter-increment: step;
      content: "0" counter(step);
      width: 44px;
      height: 44px;
      border-radius: 12px;
      background: var(--ink-700);
      color: var(--paper);
      display: grid;
      place-items: center;
      font-family: var(--font-mono);
      font-weight: 700;
      font-size: 0.9rem;
    }
    .step-row strong {
      font-family: var(--font-display);
      font-weight: 600;
      font-size: 1.08rem;
      color: var(--ink-900);
      display: block;
      margin-bottom: 4px;
    }
    .step-row span { color: var(--ink-500); font-size: 0.95rem; line-height: 1.55; }

    /* Examples list */
    .examples-list {
      list-style: none;
      padding: 0;
      margin: 22px 0 0;
      display: grid;
      gap: 10px;
    }
    .examples-list li {
      display: grid;
      grid-template-columns: 26px minmax(0, 1fr);
      gap: 12px;
      align-items: start;
      padding: 14px 18px;
      border-radius: 12px;
      background: var(--paper-card);
      border: 1px solid var(--line);
      color: var(--ink-700);
      font-size: 0.98rem;
      line-height: 1.5;
    }
    .examples-list li svg { color: var(--accent); margin-top: 2px; }

    /* ------------------------------------------------------------ Tech / FAQ (collapsed) */

    .disclosure {
      background: var(--paper-card);
      border: 1px solid var(--line);
      border-radius: var(--r-lg);
      overflow: hidden;
    }
    .disclosure + .disclosure { margin-top: 14px; }
    .disclosure summary {
      cursor: pointer;
      list-style: none;
      padding: 22px 24px;
      display: flex;
      align-items: center;
      gap: 14px;
      font-family: var(--font-display);
      font-weight: 600;
      font-size: 1.12rem;
      color: var(--ink-900);
    }
    .disclosure summary::-webkit-details-marker { display: none; }
    .disclosure summary .chev {
      margin-left: auto;
      transition: transform 220ms ease;
      color: var(--ink-300);
    }
    .disclosure[open] summary .chev { transform: rotate(180deg); color: var(--accent); }
    .disclosure summary .ic-pre {
      width: 36px;
      height: 36px;
      border-radius: 10px;
      background: var(--ink-50);
      color: var(--ink-700);
      display: grid;
      place-items: center;
      flex-shrink: 0;
    }
    .disclosure .body {
      padding: 0 24px 26px;
      color: var(--ink-500);
      line-height: 1.65;
      font-size: 0.98rem;
    }
    .disclosure .body p { margin: 0 0 12px; }
    .disclosure .body p:last-child { margin-bottom: 0; }
    .disclosure .body code,
    .disclosure .body pre {
      font-family: var(--font-mono);
      font-size: 0.86rem;
    }
    .disclosure .body code {
      background: var(--ink-50);
      padding: 1px 6px;
      border-radius: 5px;
      color: var(--ink-800);
    }
    .disclosure .body pre {
      margin: 12px 0 0;
      padding: 18px 20px;
      background: var(--ink-900);
      color: #e6eaed;
      border-radius: var(--r-md);
      line-height: 1.65;
      overflow-x: auto;
    }

    /* ------------------------------------------------------------ Final callout */

    .callout {
      background: var(--ink-700);
      color: var(--paper);
      border-radius: var(--r-xl);
      padding: clamp(40px, 6vw, 80px) clamp(24px, 4vw, 64px);
      display: grid;
      grid-template-columns: minmax(0, 1.1fr) minmax(0, 0.9fr);
      gap: clamp(28px, 4vw, 60px);
      align-items: center;
      position: relative;
      overflow: hidden;
    }
    .callout::before {
      content: "";
      position: absolute;
      inset: -50% -10% auto auto;
      width: 60%;
      height: 100%;
      background: radial-gradient(circle, rgba(187, 77, 36, 0.25), transparent 65%);
      pointer-events: none;
    }
    .callout h2 {
      font-family: var(--font-display);
      font-weight: 600;
      font-size: clamp(2rem, 4vw, 3rem);
      letter-spacing: -0.012em;
      line-height: 1.05;
      color: var(--paper);
      max-width: 16ch;
    }
    .callout p {
      color: rgba(245, 245, 240, 0.78);
      max-width: 52ch;
      font-size: 1.05rem;
      line-height: 1.65;
      margin-top: 18px;
    }
    .callout .cta-row { margin-top: 28px; }
    .callout .cta { background: var(--accent); }
    .callout .cta:hover { background: var(--accent-700); }
    .callout .ghost {
      color: var(--paper);
      border-color: rgba(245, 245, 240, 0.32);
      background: transparent;
    }
    .callout .ghost:hover { background: rgba(245, 245, 240, 0.08); border-color: var(--paper); }
    .callout .right {
      position: relative;
      z-index: 1;
    }
    .callout .right .label {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-size: 0.8rem;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: rgba(245, 245, 240, 0.7);
      font-weight: 600;
      margin-bottom: 12px;
    }
    .callout .right h3 {
      font-family: var(--font-display);
      font-weight: 600;
      font-size: 1.35rem;
      color: var(--paper);
      margin-bottom: 10px;
    }
    .callout .right p {
      margin: 0 0 20px;
      color: rgba(245, 245, 240, 0.74);
      font-size: 0.96rem;
    }
    .callout .right a.git-link {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 12px 18px;
      border: 1px solid rgba(245, 245, 240, 0.28);
      border-radius: 999px;
      color: var(--paper);
      font-weight: 600;
      font-size: 0.94rem;
      transition: background 180ms ease, border-color 180ms ease;
    }
    .callout .right a.git-link:hover {
      background: rgba(245, 245, 240, 0.06);
      border-color: var(--paper);
    }

    /* ------------------------------------------------------------ Footer */

    footer {
      padding: 48px 0 56px;
      border-top: 1px solid var(--line);
      display: grid;
      grid-template-columns: minmax(0, 1.4fr) minmax(0, 2fr) minmax(0, 1fr);
      gap: 32px;
      align-items: start;
      font-size: 0.9rem;
      color: var(--ink-400);
    }
    footer .brand-block strong { color: var(--ink-900); display: block; font-size: 1rem; font-weight: 600; }
    footer .brand-block p { margin: 4px 0 0; color: var(--ink-400); font-size: 0.88rem; }
    footer .links {
      display: flex;
      flex-wrap: wrap;
      gap: 6px 18px;
    }
    footer .links a {
      color: var(--ink-500);
      font-weight: 500;
      padding: 4px 0;
    }
    footer .links a:hover { color: var(--ink-900); }
    footer .copy { text-align: right; color: var(--ink-300); font-size: 0.84rem; }

    /* ------------------------------------------------------------ Mobile sticky CTA */

    .sticky-cta {
      display: none;
      position: fixed;
      left: 12px;
      right: 12px;
      bottom: max(12px, env(safe-area-inset-bottom, 12px));
      z-index: 25;
      background: var(--ink-700);
      color: var(--paper);
      padding: 12px 16px;
      border-radius: 16px;
      box-shadow: var(--shadow-lg);
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    .sticky-cta strong {
      display: block;
      font-size: 0.92rem;
      color: var(--paper);
      font-weight: 600;
    }
    .sticky-cta span { font-size: 0.78rem; color: rgba(245, 245, 240, 0.7); }
    .sticky-cta a {
      background: var(--accent);
      color: #fff;
      padding: 10px 16px;
      border-radius: 999px;
      font-weight: 600;
      font-size: 0.9rem;
      flex-shrink: 0;
    }
    .sticky-cta a:hover { background: var(--accent-700); }

    /* ------------------------------------------------------------ Animations */

    @keyframes rise {
      from { opacity: 0; transform: translateY(14px); }
      to   { opacity: 1; transform: translateY(0); }
    }
    @keyframes pulse {
      0%, 100% { box-shadow: 0 0 0 0 rgba(90, 122, 94, 0.35); }
      50%      { box-shadow: 0 0 0 6px rgba(90, 122, 94, 0); }
    }

    .rise-in    { animation: rise 480ms ease-out both; }
    .rise-in.d1 { animation-delay: 80ms; }
    .rise-in.d2 { animation-delay: 160ms; }
    .rise-in.d3 { animation-delay: 240ms; }
    .rise-in.d4 { animation-delay: 320ms; }

    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        animation-duration: 0.001ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.001ms !important;
        scroll-behavior: auto !important;
      }
    }

    /* Active section hint via scroll-margin */
    section[id],
    #mcp-agent-instructions {
      scroll-margin-top: 100px;
    }

    /* ------------------------------------------------------------ Mobile */

    @media (max-width: 920px) {
      .hero-grid,
      .explainer,
      .onboarding-head,
      .two-col,
      .callout {
        grid-template-columns: 1fr;
      }
      .hero h1 { font-size: clamp(2.2rem, 8vw, 3rem); max-width: 18ch; }
      .hero-lede { font-size: 1.02rem; }
      .explainer .label-block { position: static; }
      .section { padding: clamp(40px, 9vw, 72px) 0; }
      .topbar nav {
        display: none;
        width: 100%;
        flex-direction: column;
        align-items: stretch;
        gap: 4px;
        padding: 12px 0 4px;
        margin-top: 6px;
        border-top: 1px solid var(--line);
        order: 99;
      }
      .topbar nav a { padding: 12px 14px; }
      .topbar { flex-wrap: wrap; gap: 10px; }
      .hamburger { display: flex; }
      .topbar-wrap { position: static; backdrop-filter: none; }
      .sticky-cta { display: flex; }
      footer {
        grid-template-columns: 1fr;
        gap: 20px;
      }
      footer .copy { text-align: left; }
      .callout { padding: 32px 22px; }
    }

    @media (max-width: 540px) {
      .mock-head .label { display: none; }
      .revenue-headline { flex-wrap: wrap; }
      .revenue-headline .total { font-size: 1.45rem; }
      .breakdown li { font-size: 0.78rem; }
      .brand p { display: none; }
      .brand h1 { font-size: 0.98rem; }
    }
  </style>
</head>
<body>
  <a class="skip-link" href="#main">Перейти к содержимому</a>

  <div class="topbar-wrap">
    <header class="shell topbar">
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
        <a class="nav-link" href="https://github.com/otis22/vetmanager-mcp" target="_blank" rel="noopener" aria-label="GitHub репозиторий">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
          GitHub
        </a>
        <a class="nav-link" href="#mcp-agent-instructions">Инструкции</a>
        <a class="nav-ghost" href="/login">Войти</a>
        <a class="nav-cta" href="/register">Создать аккаунт</a>
      </nav>
    </header>
  </div>

  <main id="main">
    <section class="hero">
      <div class="shell hero-grid">
        <div class="rise-in">
          <p class="section-label">Для ветклиник и врачей</p>
          <h1>Данные клиники <em>по запросу</em><br>за&nbsp;секунды</h1>
          <p class="hero-lede">
            Сервис для ветврачей, администраторов и руководителей клиник помогает быстрее
            получать данные из Vetmanager через AI-ассистента: по клиентам, пациентам,
            приёмам, финансам и складу. Без ручного поиска по разделам и без передачи
            секретов клиники в каждое подключение.
          </p>
          <p class="hero-fineprint">
            Сервис не сохраняет бизнес-данные из Vetmanager для постоянного хранения. Он хранит только технические данные интеграции и сервисные bearer-метаданные, необходимые для авторизации и работы MCP runtime.
          </p>
          <p class="hero-fineprint">
            Если выбран режим авторизации через Vetmanager login/password, логин и пароль Vetmanager не сохраняются: они нужны только для получения user token. При смене пароля в Vetmanager такой token может стать невалидным, и потребуется повторная авторизация.
          </p>
          <div class="cta-row">
            <a class="cta" href="/register">
              Зарегистрироваться
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>
            </a>
            <a class="ghost" href="#mcp-agent-instructions">Инструкции для агентов</a>
          </div>
          <p class="returning-hint">Уже зарегистрированы? <a href="/login">Войти в кабинет</a></p>
          <div class="trust-strip">
            <span class="trust-item">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>
              Bearer-only авторизация
            </span>
            <span class="trust-item">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M16 18 22 12 16 6"/><path d="M8 6 2 12 8 18"/></svg>
              Open Source
            </span>
            <span class="trust-item">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12a9 9 0 1 1-6.219-8.56"/><path d="M22 4 12 14.01l-3-3"/></svg>
              IP-маска на каждый токен
            </span>
          </div>
        </div>

        <aside class="mock-chat rise-in d2" aria-label="Пример ответа AI-ассистента">
          <div class="mock-head">
            <div class="dots"><i></i><i></i><i></i></div>
            <span class="label">vetmanager · march 2026</span>
            <span class="live">Live</span>
          </div>
          <div class="mock-body">
            <div class="bubble user">Какая выручка за март 2026?</div>
            <div class="answer-card">
              <span class="who">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 15.5 9.937l6.135 1.582a.5.5 0 0 1 0 .962L15.5 14.063a2 2 0 0 0-1.437 1.437l-1.582 6.135a.5.5 0 0 1-.963 0z"/></svg>
                AI-ассистент · из Vetmanager
              </span>
              <div class="revenue-headline">
                <span class="total">₽&nbsp;487 200</span>
                <span class="delta">
                  <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m7 17 10-10"/><path d="M7 7h10v10"/></svg>
                  +14% к февралю
                </span>
              </div>
              <div class="bar-chart" aria-hidden="true">
                <div class="bar"><div class="col" style="height: 86%" data-amount="₽112k"></div><span class="lbl">1–7 мар</span></div>
                <div class="bar"><div class="col" style="height: 95%" data-amount="₽125k"></div><span class="lbl">8–14 мар</span></div>
                <div class="bar"><div class="col" style="height: 90%" data-amount="₽119k"></div><span class="lbl">15–21 мар</span></div>
                <div class="bar peak"><div class="col" style="height: 100%" data-amount="₽131k"></div><span class="lbl">22–28 мар</span></div>
              </div>
              <ul class="breakdown">
                <li><span>Неделя 1 · 1–7 марта</span><b>₽ 112 400</b></li>
                <li><span>Неделя 2 · 8–14 марта</span><b>₽ 124 800</b></li>
                <li><span>Неделя 3 · 15–21 марта</span><b>₽ 118 600</b></li>
                <li><span>Неделя 4 · 22–28 марта</span><b>₽ 131 400</b></li>
              </ul>
              <div class="mock-source">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>
                Vetmanager · 234 платежа · <span>обновлено сейчас</span>
              </div>
            </div>
          </div>
        </aside>
      </div>
    </section>

    <section class="section">
      <div class="shell explainer">
        <div class="label-block">
          <p class="section-label">Контекст</p>
          <h2>Что такое MCP?</h2>
        </div>
        <div class="body">
          <p>
            <strong>MCP</strong> (Model Context Protocol) — открытый стандарт, который позволяет AI-ассистентам
            безопасно подключаться к внешним системам. Этот сервис — MCP-мост к Vetmanager:
            ваша клиника подключается один раз, а дальше команда получает данные через
            привычный AI-интерфейс, без необходимости переключаться между экранами Vetmanager.
          </p>
          <p>
            Под капотом — bearer-only авторизация и сервисные токены, которые можно ограничить
            по IP-маске. На уровне UI — никакой технической специфики: вы задаёте вопрос
            на русском, агент возвращает ответ по вашим данным.
          </p>
        </div>
      </div>
    </section>

    <section class="section">
      <div class="shell">
        <section class="onboarding" id="mcp-onboarding" data-testid="mcp-onboarding">
          <div data-testid="mcp-onboarding-main-copy">
            <div class="onboarding-head">
              <div>
                <p class="section-label">Подключение агента</p>
                <h2>Подключите ИИ-агента к вашему Vetmanager за 5 минут</h2>
                <p class="lede">
                  Работает через MCP: <strong>Codex, Claude, Cursor, Manus</strong> и другие совместимые агенты смогут находить клиентов,
                  смотреть записи, проверять счета и считать выручку по данным вашей клиники.
                </p>
                <p class="lede">
                  MCP — это мост между ИИ-агентом и Vetmanager. Вы задаёте вопрос обычным языком, агент обращается
                  к Vetmanager через разрешённые команды и возвращает ответ по вашим данным.
                </p>
              </div>
              <div class="flow-map" aria-label="Как работает подключение">
                <div class="flow-node"><span class="num">1</span><div><strong>Вы задаёте вопрос</strong><span>Например, про выручку, записи или клиента.</span></div></div>
                <div class="flow-arrow">↓</div>
                <div class="flow-node"><span class="num">2</span><div><strong>ИИ-агент</strong><span>Codex, Claude, Cursor, Manus или другой совместимый агент.</span></div></div>
                <div class="flow-arrow">↓</div>
                <div class="flow-node"><span class="num">3</span><div><strong>MCP-мост</strong><span>Передаёт запрос через разрешённые команды.</span></div></div>
                <div class="flow-arrow">↓</div>
                <div class="flow-node"><span class="num">4</span><div><strong>Ваш Vetmanager</strong><span>Данные остаются в вашей рабочей системе.</span></div></div>
                <div class="flow-arrow">↓</div>
                <div class="flow-node"><span class="num">5</span><div><strong>Ответ по данным клиники</strong><span>Агент возвращает понятный результат.</span></div></div>
              </div>
            </div>

            <div class="prompts-wrap" style="margin-top: 36px;">
              <h3 class="subhead">Что можно спросить после подключения</h3>
              <div class="prompt-grid">
                <p class="prompt-chip"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3v16a2 2 0 0 0 2 2h16"/><path d="M7 16h8"/><path d="M7 11h12"/><path d="M7 6h3"/></svg>Какая выручка была за март?</p>
                <p class="prompt-chip"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/></svg>Покажи записи врача на завтра</p>
                <p class="prompt-chip"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/></svg>Найди клиента по телефону</p>
                <p class="prompt-chip"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="20" height="14" x="2" y="5" rx="2"/><line x1="2" x2="22" y1="10" y2="10"/></svg>Какие счета оплачены частично?</p>
                <p class="prompt-chip"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 12 2 2 4-4"/><circle cx="12" cy="12" r="10"/></svg>Кому из пациентов пора на прививку?</p>
              </div>
            </div>

            <div style="margin-top: 36px;">
              <h3 class="subhead">Подключение в 3 шага</h3>
              <div class="quick-steps">
                <div class="quick-step"><span class="num">01 — ВЫБОР</span><strong>Выберите агента</strong><span>Если сомневаетесь, начните с Codex.</span></div>
                <div class="quick-step"><span class="num">02 — КОМАНДА</span><strong>Отправьте команду</strong><span>Скопируйте готовый текст ниже и дайте его агенту.</span></div>
                <div class="quick-step"><span class="num">03 — КЛЮЧ</span><strong>Вставьте ключ</strong><span>Добавьте ключ доступа в настройки и перезапустите сессию.</span></div>
              </div>
              <div class="privacy-note">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="18" height="11" x="3" y="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                <div>
                  Ключ доступа не нужно отправлять в чат. Он хранится в настройках агента или на вашем компьютере.
                  Настройку удобнее делать с компьютера. Ключ доступа выдаётся в кабинете после регистрации и подключения Vetmanager:
                  <a href="/register">создать аккаунт</a> или <a href="/login">войти в кабинет</a>.
                </div>
              </div>
            </div>
          </div>

          <div id="mcp-agent-instructions">
            <p class="section-label">Готовые инструкции</p>
            <h3 class="subhead" style="margin-bottom: 8px;">Инструкции для агентов</h3>
            <p style="color: var(--ink-500); font-size: 0.98rem; line-height: 1.6; margin-bottom: 4px;">
              Выберите Codex, Claude, Cursor, Manus или другой MCP-совместимый агент. Скопируйте готовую команду
              и отправьте её агенту: он сам найдёт файл настроек, а ключ доступа вы вставите вручную.
            </p>
          </div>

          <div class="agent-tabs" data-testid="mcp-agent-tabs">
            <div class="tab-list" role="tablist" aria-label="Выберите ИИ-агента">
              <button class="tab-button" id="mcp-tab-codex" role="tab" aria-selected="true" aria-controls="mcp-panel-codex" tabindex="0" type="button">Codex</button>
              <button class="tab-button" id="mcp-tab-claude" role="tab" aria-selected="false" aria-controls="mcp-panel-claude" tabindex="-1" type="button">Claude</button>
              <button class="tab-button" id="mcp-tab-cursor" role="tab" aria-selected="false" aria-controls="mcp-panel-cursor" tabindex="-1" type="button">Cursor</button>
              <button class="tab-button" id="mcp-tab-manus" role="tab" aria-selected="false" aria-controls="mcp-panel-manus" tabindex="-1" type="button">Manus</button>
              <button class="tab-button" id="mcp-tab-other" role="tab" aria-selected="false" aria-controls="mcp-panel-other" tabindex="-1" type="button">Другой агент</button>
            </div>

            <div class="command-card" id="mcp-panel-codex" role="tabpanel" aria-labelledby="mcp-tab-codex">
              <span class="badge">
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z"/></svg>
                Рекомендуем для старта
              </span>
              <pre id="mcp-command-codex">Настрой мне MCP-сервер Vetmanager.

Адрес сервера: __MCP_SERVER_URL__

Ключ доступа / Bearer token я вставлю сам, но покажи путь к файлу или настройке, куда его нужно вставить.

После настройки скажи, как перезапустить сессию Codex и как проверить, что инструменты Vetmanager подключились.</pre>
              <div class="command-actions">
                <button class="copy-button" type="button" data-copy-target="mcp-command-codex" aria-describedby="mcp-copy-status-codex">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>
                  Скопировать
                </button>
                <span class="copy-status" id="mcp-copy-status-codex" role="status" aria-live="polite"></span>
              </div>
            </div>

            <div class="command-card" id="mcp-panel-claude" role="tabpanel" aria-labelledby="mcp-tab-claude" hidden>
              <pre id="mcp-command-claude">Подключи MCP-сервер Vetmanager.

Адрес сервера: __MCP_SERVER_URL__

Ключ доступа / Bearer token я вставлю сам, но покажи путь к файлу или настройке, куда его нужно вставить.

После настройки скажи, как перезапустить Claude и проверить список доступных MCP-инструментов.</pre>
              <div class="command-actions">
                <button class="copy-button" type="button" data-copy-target="mcp-command-claude" aria-describedby="mcp-copy-status-claude">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>
                  Скопировать
                </button>
                <span class="copy-status" id="mcp-copy-status-claude" role="status" aria-live="polite"></span>
              </div>
            </div>

            <div class="command-card" id="mcp-panel-cursor" role="tabpanel" aria-labelledby="mcp-tab-cursor" hidden>
              <pre id="mcp-command-cursor">Добавь MCP-сервер Vetmanager в настройки Cursor.

Адрес сервера: __MCP_SERVER_URL__

Ключ доступа / Bearer token я вставлю сам, но покажи путь к файлу или настройке, куда его нужно вставить.

После настройки покажи, как перезапустить Cursor-сессию и проверить подключение.</pre>
              <div class="command-actions">
                <button class="copy-button" type="button" data-copy-target="mcp-command-cursor" aria-describedby="mcp-copy-status-cursor">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>
                  Скопировать
                </button>
                <span class="copy-status" id="mcp-copy-status-cursor" role="status" aria-live="polite"></span>
              </div>
            </div>

            <div class="command-card" id="mcp-panel-manus" role="tabpanel" aria-labelledby="mcp-tab-manus" hidden>
              <pre id="mcp-command-manus">Подключи Vetmanager MCP.

Адрес сервера: __MCP_SERVER_URL__

Ключ доступа / Bearer token я вставлю сам, но покажи путь к файлу или настройке, куда его нужно вставить.

После подключения проверь, что доступны инструменты Vetmanager.</pre>
              <div class="command-actions">
                <button class="copy-button" type="button" data-copy-target="mcp-command-manus" aria-describedby="mcp-copy-status-manus">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>
                  Скопировать
                </button>
                <span class="copy-status" id="mcp-copy-status-manus" role="status" aria-live="polite"></span>
              </div>
            </div>

            <div class="command-card" id="mcp-panel-other" role="tabpanel" aria-labelledby="mcp-tab-other" hidden>
              <pre id="mcp-command-other">Подключи MCP-сервер Vetmanager.

Адрес сервера: __MCP_SERVER_URL__
Авторизация: ключ доступа / Bearer token

Ключ доступа я вставлю сам, но покажи путь к файлу или настройке, куда его нужно вставить.

После настройки перезапусти сессию или объясни, как это сделать, и проверь список доступных инструментов.</pre>
              <div class="command-actions">
                <button class="copy-button" type="button" data-copy-target="mcp-command-other" aria-describedby="mcp-copy-status-other">
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>
                  Скопировать
                </button>
                <span class="copy-status" id="mcp-copy-status-other" role="status" aria-live="polite"></span>
              </div>
              <p class="mini">Если ваш агент поддерживает MCP, используйте тот же принцип: адрес сервера, ключ доступа и перезапуск сессии.</p>
            </div>
          </div>

          <div>
            <h3 class="subhead">Если агент не открыл файл настроек</h3>
            <p style="color: var(--ink-500); font-size: 0.98rem; line-height: 1.6; max-width: 64ch;">
              Попросите его ещё раз показать путь к конфигурации. Если не получилось, откройте ручную подсказку для вашего агента.
            </p>
            <div class="grid-5" style="margin-top: 18px;">
              <div class="mini-card"><strong><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="4 17 10 11 4 5"/><line x1="12" x2="20" y1="19" y2="19"/></svg>Codex</strong><span>Попросите Codex показать путь к MCP config именно для вашей системы.</span></div>
              <div class="mini-card"><strong><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>Claude</strong><span>Откройте настройки Claude Desktop / MCP servers и перезапустите Claude.</span></div>
              <div class="mini-card"><strong><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/></svg>Cursor</strong><span>Откройте MCP settings в Cursor и перезапустите Cursor-сессию.</span></div>
              <div class="mini-card"><strong><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="m9 12 2 2 4-4"/></svg>Manus</strong><span>Проверьте настройки подключений и список доступных tools.</span></div>
              <div class="mini-card"><strong><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>Другой агент</strong><span>Найдите раздел MCP servers, укажите URL и авторизацию через ключ доступа.</span></div>
            </div>
          </div>

          <div>
            <h3 class="subhead">Примеры задач по ролям</h3>
            <div class="grid-3">
              <div class="mini-card"><strong><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>Администратор</strong><span>Найди клиента по телефону<br>Покажи записи на завтра<br>Какие счета оплачены частично?</span></div>
              <div class="mini-card"><strong><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 2v2"/><path d="M5 2v2"/><path d="M5 3H4a2 2 0 0 0-2 2v4a6 6 0 0 0 12 0V5a2 2 0 0 0-2-2h-1"/><path d="M8 15a6 6 0 0 0 12 0v-3"/><circle cx="20" cy="10" r="2"/></svg>Врач</strong><span>Покажи историю питомца<br>Кому из пациентов пора на прививку?<br>Покажи последние приёмы клиента</span></div>
              <div class="mini-card"><strong><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg>Руководитель клиники</strong><span>Какая выручка была за март?<br>Собери отчёт по оплатам за неделю<br>Найди клиентов с долгом</span></div>
            </div>
          </div>

          <div>
            <h3 class="subhead">Частые ошибки</h3>
            <div class="grid-3">
              <div class="mini-card error"><strong><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/></svg>Агент не видит Vetmanager</strong><span>Перезапустите сессию и попросите показать список подключённых MCP-серверов.</span></div>
              <div class="mini-card error"><strong><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m21 2-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0 3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>Ошибка 401 / ключ доступа не подошёл</strong><span>Проверьте, что ключ вставлен в настройки и скопирован полностью.</span></div>
              <div class="mini-card error"><strong><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 8v4"/><path d="M12 16h.01"/></svg>Инструменты не появились</strong><span>Проверьте адрес MCP-сервера и перезапустите приложение или сессию.</span></div>
            </div>
          </div>
        </section>
      </div>
    </section>

    <section class="section">
      <div class="shell">
        <p class="section-label">Ценность</p>
        <h2 class="section-title">Что получает клиника</h2>
        <p class="section-lede">
          Сервис помогает быстрее отвечать на ежедневные вопросы клиники:
          кто записан на сегодня, какая история у пациента, есть ли долг у клиента,
          что осталось на складе и какие сотрудники свободны или загружены.
        </p>

        <div class="audience-grid">
          <div class="card">
            <div class="ic-wrap accent">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M11 2v2"/><path d="M5 2v2"/><path d="M5 3H4a2 2 0 0 0-2 2v4a6 6 0 0 0 12 0V5a2 2 0 0 0-2-2h-1"/><path d="M8 15a6 6 0 0 0 12 0v-3"/><circle cx="20" cy="10" r="2"/></svg>
            </div>
            <h3>Ветврач</h3>
            <p>история пациента, прививки, медицинские карты, последние визиты.</p>
            <ul>
              <li>Покажи историю питомца</li>
              <li>Кому пора на прививку?</li>
              <li>Последние приёмы клиента</li>
            </ul>
          </div>
          <div class="card">
            <div class="ic-wrap moss">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect width="18" height="18" x="3" y="4" rx="2"/><path d="M16 2v4"/><path d="M8 2v4"/><path d="M3 10h18"/><path d="M8 14h.01"/><path d="M12 14h.01"/><path d="M16 14h.01"/></svg>
            </div>
            <h3>Администратор</h3>
            <p>записи, клиенты, контакты, сотрудники, задолженности.</p>
            <ul>
              <li>Найди клиента по телефону</li>
              <li>Записи на завтра</li>
              <li>Какие счета оплачены частично?</li>
            </ul>
          </div>
          <div class="card">
            <div class="ic-wrap amber">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg>
            </div>
            <h3>Руководитель</h3>
            <p>сотрудники, загрузка врачей, сводные операционные вопросы.</p>
            <ul>
              <li>Выручка за период</li>
              <li>Отчёт по оплатам за неделю</li>
              <li>Клиенты с долгом</li>
            </ul>
          </div>
        </div>

        <p style="color: var(--ink-500); font-size: 0.96rem; line-height: 1.65; max-width: 80ch; margin-top: 28px;">
          Сервис сделан для <strong style="color: var(--ink-900)">ветврачей, администраторов и руководителей клиник</strong>,
          которым нужен быстрый доступ к данным Vetmanager через AI-ассистента.
        </p>
      </div>
    </section>

    <section class="section">
      <div class="shell">
        <p class="section-label">Старт</p>
        <h2 class="section-title">Как начать работу</h2>
        <p class="section-lede">
          Регистрация вынесена в главный сценарий, потому что именно с
          неё начинается настройка клиники и безопасного доступа команды.
        </p>
        <div class="step-list">
          <div class="step-row"><div><strong>Зарегистрироваться</strong><span>Создать аккаунт клиники и открыть личный кабинет.</span></div></div>
          <div class="step-row"><div><strong>Подключить Vetmanager</strong><span>Указать домен клиники и настроить безопасную авторизацию один раз.</span></div></div>
          <div class="step-row"><div><strong>Работать через AI-ассистента</strong><span>Задавать вопросы по клиентам, пациентам, приёмам, финансам и складу в одном интерфейсе.</span></div></div>
        </div>
      </div>
    </section>

    <section class="section" id="examples">
      <div class="shell">
        <p class="section-label">Примеры</p>
        <h2 class="section-title">Какие вопросы можно задавать</h2>
        <p class="section-lede">
          Сервис рассчитан на повседневные вопросы, которые обычно требуют
          нескольких переходов по Vetmanager или помощи администратора.
        </p>
        <ul class="examples-list">
          <li><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg><span>Покажи записи на сегодня и ближайшие приёмы по врачам.</span></li>
          <li><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg><span>Найди клиента и покажи историю обращений его питомца.</span></li>
          <li><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg><span>Какие пациенты давно не приходили на повторный приём?</span></li>
          <li><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg><span>Покажи должников и суммы задолженности.</span></li>
          <li><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg><span>Покажи неоплаченные счета и сумму задолженности.</span></li>
        </ul>
      </div>
    </section>

    <section class="section" id="faq">
      <div class="shell">
        <p class="section-label">Детали</p>
        <h2 class="section-title">Технические детали и FAQ</h2>
        <p class="section-lede">
          Эти блоки скрыты по умолчанию: их полезно открыть, если вы — IT-специалист
          клиники или хотите понять, что именно сохраняется на сервисе.
        </p>

        <details class="disclosure" style="margin-top: 24px;">
          <summary>
            <span class="ic-pre">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
            </span>
            Технический блок: формат подключения и MCP config
            <svg class="chev" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>
          </summary>
          <div class="body">
            <p>
              Для технической команды сервис остаётся совместимым с MCP-клиентами и
              использует bearer-only runtime, но эти детали не нужны для старта работы
              клиники.
            </p>
            <p>
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
          </div>
        </details>

        <details class="disclosure">
          <summary>
            <span class="ic-pre">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
            </span>
            Какие данные сохраняются на сервисе?
            <svg class="chev" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>
          </summary>
          <div class="body">
            <p>
              Сервис хранит только учётные данные подключения к Vetmanager (зашифрованные) и service-токены.
              Бизнес-данные клиники (клиенты, пациенты, счета) не сохраняются — они запрашиваются из Vetmanager в момент обращения.
            </p>
          </div>
        </details>

        <details class="disclosure">
          <summary>
            <span class="ic-pre">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m9 12 2 2 4-4"/><path d="M21 12c-1 0-3-1-3-3s2-3 3-3 3 1 3 3-2 3-3 3"/><path d="M3 12c1 0 3-1 3-3s-2-3-3-3-3 1-3 3 2 3 3 3"/><path d="M3 12c1 0 3 1 3 3s-2 3-3 3-3-1-3-3 2-3 3-3"/><path d="M21 12c-1 0-3 1-3 3s2 3 3 3 3-1 3-3-2-3-3-3"/></svg>
            </span>
            Чем это отличается от прямого использования Vetmanager API?
            <svg class="chev" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>
          </summary>
          <div class="body">
            <p>
              Vetmanager API требует знания эндпоинтов, фильтров и структуры данных.
              MCP-сервис позволяет задавать вопросы на естественном языке через AI-ассистента,
              а сервис сам выбирает нужные API-вызовы.
            </p>
          </div>
        </details>

        <details class="disclosure">
          <summary>
            <span class="ic-pre">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
            </span>
            Безопасно ли это?
            <svg class="chev" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6 9 12 15 18 9"/></svg>
          </summary>
          <div class="body">
            <p>
              Credentials клиники хранятся в зашифрованном виде. Доступ осуществляется только через
              bearer-токены, которые можно отозвать в любой момент. Логин и пароль Vetmanager не сохраняются.
            </p>
          </div>
        </details>
      </div>
    </section>

    <section class="section">
      <div class="shell">
        <div class="callout">
          <div>
            <p class="section-label" style="color: rgba(245, 245, 240, 0.7);">Готовы начать?</p>
            <h2>Подключите AI-ассистента к данным вашей клиники уже сегодня</h2>
            <p>Регистрация занимает пару минут. Сервис не требует установки и совместим с любым MCP-клиентом.</p>
            <div class="cta-row">
              <a class="cta" href="/register">
                Создать аккаунт
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>
              </a>
              <a class="ghost" href="/login">Войти</a>
            </div>
          </div>
          <div class="right">
            <span class="label">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
              Open Source
            </span>
            <h3>Разверните у себя</h3>
            <p>Проект полностью открыт. Развернуть собственный экземпляр MCP-сервера на своём сервере — три команды Docker.</p>
            <a class="git-link" href="https://github.com/otis22/vetmanager-mcp" target="_blank" rel="noopener">
              <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
              github.com/otis22/vetmanager-mcp
            </a>
          </div>
        </div>
      </div>
    </section>
  </main>

  <footer class="shell">
    <div class="brand-block">
      <strong>Vetmanager MCP Service</strong>
      <p>AI-ассистент для ветеринарных клиник</p>
    </div>
    <nav class="links" aria-label="Подвал">
      <a href="/register">Регистрация</a>
      <a href="/login">Вход</a>
      <a href="#faq">FAQ</a>
      <a href="https://github.com/otis22/vetmanager-mcp" target="_blank" rel="noopener">GitHub</a>
      <a href="mailto:support@vetmanager.cloud">Поддержка</a>
    </nav>
    <div class="copy">
      <p>&copy; 2026 Vetmanager MCP</p>
    </div>
  </footer>

  <div class="sticky-cta" role="complementary" aria-label="Быстрый старт">
    <div>
      <strong>Подключите за 5 минут</strong>
      <span>Регистрация без оплаты</span>
    </div>
    <a href="/register">Создать</a>
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
