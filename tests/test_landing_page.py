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
