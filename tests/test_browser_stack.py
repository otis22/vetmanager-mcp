"""Regression coverage for default browser-test infrastructure."""

import pytest


@pytest.mark.browser
def test_browser_stack_available_in_default_pytest(page, browser_name):
    """Default pytest run must provide a working browser page fixture."""
    page.goto("data:text/html,<html><body><h1>browser-ok</h1></body></html>")

    assert browser_name == "chromium"
    assert page.locator("h1").inner_text() == "browser-ok"
