"""Regression coverage for live HTTP browser harness."""

import pytest


@pytest.mark.browser
def test_browser_can_open_live_register_page(page, live_server_url):
    """Browser tests must navigate through a real localhost HTTP server."""
    page.goto(f"{live_server_url}/register")

    assert page.url == f"{live_server_url}/register"
    assert page.locator("h1").inner_text() == "Регистрация аккаунта"
    assert page.get_by_test_id("register-email").count() == 1


@pytest.mark.browser
def test_landing_agent_choice_is_usable_on_mobile_and_desktop(page, live_server_url):
    for viewport in (
        {"width": 375, "height": 812},
        {"width": 768, "height": 900},
        {"width": 1440, "height": 900},
    ):
        page.set_viewport_size(viewport)
        page.goto(f"{live_server_url}/")
        choices = page.get_by_test_id("agent-choice")

        assert choices.is_visible()
        assert choices.locator("a").count() == 3
        assert choices.get_by_role("link", name="ChatGPT").bounding_box()["height"] >= 44
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


@pytest.mark.browser
def test_account_connector_entry_is_usable_on_mobile_and_desktop(
    page, live_server_url, browser_account_cleanup
):
    account_email = "browser-connector-layout@example.com"
    browser_account_cleanup.track_account_email(account_email)

    page.goto(f"{live_server_url}/register")
    page.get_by_test_id("register-email").fill(account_email)
    page.get_by_test_id("register-password").fill("Browser-Connector-Pass-123")
    page.get_by_test_id("register-submit").click()
    page.wait_for_load_state("networkidle")

    for viewport in ({"width": 375, "height": 812}, {"width": 1440, "height": 900}):
        page.set_viewport_size(viewport)
        assert page.locator("h1").inner_text() == "Мой помощник"
        assert page.get_by_test_id("activation-status").is_visible()
        assert page.get_by_test_id("integration-section").is_visible()
        assert page.get_by_test_id("integration-submit").bounding_box()["height"] >= 44
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


@pytest.mark.browser
def test_selected_agent_is_preserved_through_registration(page, live_server_url, browser_account_cleanup):
    account_email = "browser-claude-choice@example.com"
    browser_account_cleanup.track_account_email(account_email)

    page.goto(f"{live_server_url}/")
    page.get_by_test_id("agent-choice").get_by_role("link", name="Claude").click()
    page.get_by_test_id("register-email").fill(account_email)
    page.get_by_test_id("register-password").fill("Browser-Claude-Choice-123")
    page.get_by_test_id("register-submit").click()
    page.wait_for_load_state("networkidle")

    assert "agent=claude" in page.url
    assert "Вы выбрали Claude." in page.content()
