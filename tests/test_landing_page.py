"""HTTP tests for the public landing page."""

import httpx
import pytest

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
    assert "Cursor" not in response.text


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
