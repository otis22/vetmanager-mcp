"""HTTP tests for the public landing page."""

import httpx
import pytest

from landing_page import render_landing_page
from server import mcp


@pytest.mark.asyncio
async def test_root_landing_page_renders_product_message():
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Vetmanager MCP Service" in response.text
    assert "Authorization: Bearer" in response.text
    assert "/mcp" in response.text
    assert "не сохраняет бизнес-данные из Vetmanager" in response.text
    assert "логин и пароль Vetmanager не сохраняются" in response.text
    assert "для ветврачей, администраторов и руководителей клиник" in response.text
    assert "Зарегистрироваться" in response.text
    assert "/register" in response.text
    assert "Cursor" in response.text


@pytest.mark.asyncio
async def test_topbar_nav_contains_login_link():
    """Topbar navigation must have a visible login link."""
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")

    html = response.text
    # Login link must be inside <nav> in the topbar, not just in the hero
    nav_start = html.find("<nav>")
    nav_end = html.find("</nav>", nav_start)
    nav_html = html[nav_start:nav_end]
    assert '/login' in nav_html, "Login link missing from topbar <nav>"
    assert 'Войти' in nav_html, "'Войти' text missing from topbar <nav>"


@pytest.mark.asyncio
async def test_hero_has_returning_user_hint():
    """Hero section should have a hint for returning users near the CTA."""
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")

    html = response.text
    hero_start = html.find('class="hero"')
    hero_end = html.find("</section>", hero_start)
    hero_html = html[hero_start:hero_end]
    assert "Уже зарегистрированы" in hero_html
    assert "/login" in hero_html


@pytest.mark.asyncio
async def test_topbar_has_hamburger_menu():
    """Topbar must contain a CSS-only hamburger toggle for mobile."""
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")

    html = response.text
    assert 'class="menu-toggle"' in html
    assert 'class="hamburger"' in html
    assert 'aria-label="Открыть меню"' in html


@pytest.mark.asyncio
async def test_seal_has_aria_label():
    """The VM seal in topbar must have an aria-label for accessibility."""
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")

    assert 'aria-label="Vetmanager MCP"' in response.text


@pytest.mark.asyncio
async def test_seo_meta_tags():
    """Landing page must include essential SEO meta tags."""
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")

    html = response.text
    assert 'name="robots"' in html
    assert 'property="og:title"' in html
    assert 'property="og:description"' in html
    assert 'property="og:type"' in html
    assert 'name="twitter:card"' in html
    assert 'rel="icon"' in html


@pytest.mark.asyncio
async def test_a11y_focus_visible_styles():
    """Landing page must define :focus-visible outline styles."""
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")

    assert "focus-visible" in response.text


@pytest.mark.asyncio
async def test_mcp_explanation_section():
    """Landing page must explain what MCP is."""
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")

    assert "Что такое MCP" in response.text
    assert "Model Context Protocol" in response.text


@pytest.mark.asyncio
async def test_faq_section():
    """Landing page must have a FAQ section with details/summary elements."""
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")

    html = response.text
    assert 'id="faq"' in html
    assert "<details" in html
    assert "<summary" in html
    assert "Какие данные сохраняются" in html


@pytest.mark.asyncio
async def test_footer_has_links_and_copyright():
    """Footer must have nav links, copyright and contact."""
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")

    html = response.text
    footer_start = html.find("<footer")
    footer_end = html.find("</footer>", footer_start)
    footer_html = html[footer_start:footer_end]
    assert "/register" in footer_html
    assert "/login" in footer_html
    assert "Поддержка" in footer_html
    assert "Политика конфиденциальности" in footer_html
    assert "2026" in footer_html
    assert "GitHub" in footer_html
    assert "github.com/otis22/vetmanager-mcp" in footer_html


@pytest.mark.asyncio
async def test_topbar_has_github_link():
    """Topbar navigation must include a GitHub repository link."""
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")

    html = response.text
    nav_start = html.find("<nav>")
    nav_end = html.find("</nav>", nav_start)
    nav_html = html[nav_start:nav_end]
    assert "github.com/otis22/vetmanager-mcp" in nav_html
    assert "GitHub" in nav_html


@pytest.mark.asyncio
async def test_topbar_links_to_agent_instructions():
    """Topbar navigation must expose the MCP agent instructions block."""
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")

    html = response.text
    nav_start = html.find("<nav>")
    nav_end = html.find("</nav>", nav_start)
    nav_html = html[nav_start:nav_end]
    assert "#mcp-agent-instructions" in nav_html
    assert "Инструкции" in nav_html


@pytest.mark.asyncio
async def test_open_source_section():
    """Landing page must have an Open Source section with self-hosted info."""
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/")

    html = response.text
    assert "Open Source" in html
    assert "Разверните у себя" in html
    assert "github.com/otis22/vetmanager-mcp" in html


def _extract_mcp_onboarding(html: str) -> str:
    start = html.find('id="mcp-onboarding"')
    assert start != -1
    section_start = html.rfind("<section", 0, start)
    section_end = html.find("</section>", start)
    assert section_start != -1
    assert section_end != -1
    return html[section_start : section_end + len("</section>")]


def _extract_main_copy(section_html: str) -> str:
    start = section_html.find('data-testid="mcp-onboarding-main-copy"')
    assert start != -1
    container_start = section_html.rfind("<div", 0, start)
    container_end = section_html.find('data-testid="mcp-agent-tabs"', start)
    assert container_start != -1
    assert container_end != -1
    return section_html[container_start:container_end]


def test_stage146_mcp_onboarding_core_copy_and_privacy():
    html = render_landing_page()
    section_html = _extract_mcp_onboarding(html)
    main_copy = _extract_main_copy(section_html)

    assert "Подключите ИИ-агента к вашему Vetmanager за 5 минут" in main_copy
    assert "MCP — это мост между ИИ-агентом и Vetmanager" in main_copy
    assert "Какая выручка была за март?" in main_copy
    assert "Покажи записи врача на завтра" in main_copy
    assert "Найди клиента по телефону" in main_copy
    assert "Какие счета оплачены частично?" in main_copy
    assert "Кому из пациентов пора на прививку?" in main_copy
    assert "Ключ доступа не нужно отправлять в чат" in main_copy
    assert "/register" in main_copy
    assert "/login" in main_copy
    assert "Настройку удобнее делать с компьютера" in main_copy

    for forbidden in ("JSON-RPC", "stdio", "transport", "schema", "endpoint"):
        assert forbidden not in main_copy
    assert "вставьте ключ в чат" not in section_html.lower()
    assert "отправьте token в чат" not in section_html.lower()


def test_stage146_agent_tabs_commands_and_real_mcp_url(monkeypatch):
    monkeypatch.delenv("SITE_BASE_URL", raising=False)
    monkeypatch.delenv("MCP_PATH", raising=False)

    html = render_landing_page()
    section_html = _extract_mcp_onboarding(html)

    assert "<MCP_SERVER_URL>" not in html
    assert "__MCP_SERVER_URL__" not in html
    assert "https://vetmanager-mcp.vromanichev.ru/mcp" in section_html
    assert '#mcp-agent-instructions {\n      scroll-margin-top: 100px;' in html
    assert '<div id="mcp-agent-instructions">' in section_html
    assert "Инструкции для агентов" in section_html
    assert "Скопируйте готовую команду" in section_html
    assert "Рекомендуем для старта" in section_html

    for agent in ("Codex", "Claude", "Cursor", "Manus", "Другой агент"):
        assert agent in section_html
    for prompt in (
        "Настрой мне MCP-сервер Vetmanager.",
        "Подключи MCP-сервер Vetmanager.",
        "Добавь MCP-сервер Vetmanager в настройки Cursor.",
        "Подключи Vetmanager MCP.",
    ):
        assert prompt in section_html
    assert section_html.count("Ключ доступа / Bearer token я вставлю сам") >= 4
    assert "Ключ доступа я вставлю сам" in section_html


def test_stage146_mcp_url_uses_site_base_url(monkeypatch):
    monkeypatch.setenv("SITE_BASE_URL", "https://clinic.example.com")
    monkeypatch.delenv("MCP_PATH", raising=False)

    html = render_landing_page()
    section_html = _extract_mcp_onboarding(html)

    assert "https://clinic.example.com/mcp" in section_html
    assert "https://vetmanager-mcp.vromanichev.ru/mcp" not in section_html
    assert "<MCP_SERVER_URL>" not in html
    assert "__MCP_SERVER_URL__" not in html


def test_stage146_mcp_url_uses_mcp_path(monkeypatch):
    monkeypatch.setenv("SITE_BASE_URL", "https://clinic.example.com")
    monkeypatch.setenv("MCP_PATH", "/custom/mcp")

    html = render_landing_page()
    section_html = _extract_mcp_onboarding(html)

    assert "https://clinic.example.com/custom/mcp" in section_html
    assert "https://clinic.example.com/mcp" not in section_html


def test_stage146_tabs_and_copy_controls_are_structurally_wired():
    html = render_landing_page()
    section_html = _extract_mcp_onboarding(html)

    assert 'role="tablist"' in section_html
    assert section_html.count('role="tab"') == 5
    assert section_html.count('role="tabpanel"') == 5
    assert section_html.count('aria-selected="true"') == 1
    assert 'id="mcp-tab-codex"' in section_html
    assert 'aria-selected="true" aria-controls="mcp-panel-codex"' in section_html

    for agent in ("codex", "claude", "cursor", "manus", "other"):
        assert f'id="mcp-tab-{agent}"' in section_html
        assert f'aria-controls="mcp-panel-{agent}"' in section_html
        assert f'id="mcp-panel-{agent}"' in section_html
        assert f'aria-labelledby="mcp-tab-{agent}"' in section_html
        assert f'id="mcp-command-{agent}"' in section_html
        assert f'data-copy-target="mcp-command-{agent}"' in section_html
        assert f'id="mcp-copy-status-{agent}"' in section_html
        assert f'aria-describedby="mcp-copy-status-{agent}"' in section_html

    assert section_html.count('role="status" aria-live="polite"') == 5
    assert "navigator.clipboard.writeText" in html
    assert ".textContent" in html
    assert "2000" in html
    assert 'event.key === "ArrowRight"' in html
    assert 'event.key === "ArrowLeft"' in html
    assert 'event.key === "Home"' in html
    assert 'event.key === "End"' in html
    assert "Выделите текст вручную" in html
