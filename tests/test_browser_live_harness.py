"""Regression coverage for live HTTP browser harness."""

import pytest


@pytest.mark.browser
def test_browser_can_open_live_register_page(page, live_server_url):
    """Browser tests must navigate through a real localhost HTTP server."""
    page.goto(f"{live_server_url}/register")

    assert page.url == f"{live_server_url}/register"
    assert page.locator("h1").inner_text() == "Регистрация аккаунта"
    assert page.locator('input[name="email"]').count() == 1
