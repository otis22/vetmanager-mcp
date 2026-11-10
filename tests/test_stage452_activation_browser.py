"""Исполняем настоящий JS кабинета с управляемым таймером опроса."""

import pytest
from playwright.sync_api import expect

from tests.test_stage197_token_quick_issue import _account_page, _token_view


BOOTSTRAP = """
window.__stopped = false;
window.__pollCount = 0;
window.setInterval = (callback, delay) => {
  if (delay === 15000) { window.__poll = callback; return 452; }
  return 0;
};
window.clearInterval = () => { window.__stopped = true; };
window.fetch = async (url) => {
  if (url === '/account/activation-status') {
    window.__pollCount++;
    if (window.__hold) await new Promise(resolve => { window.__release = resolve; });
    return {ok: true, status: 200, json: async () => ({state: window.__state || 'ready'})};
  }
  return {ok: true, json: async () => ({})};
};
"""


def _open(page, *, issued=False, post=False):
    page.set_default_timeout(3000)
    html = _account_page(bearer_tokens=[_token_view()],
                         issued_raw_token="vm_st_FICTIONAL_ONLY" if issued else None)
    requests = []
    page.add_init_script(BOOTSTRAP)

    def serve(route):
        requests.append(route.request.method)
        route.fulfill(status=200, content_type="text/html", body=html)

    page.route("http://testserver/**", serve)
    if post:
        page.goto("http://testserver/start")
        page.evaluate("""() => {
          const form = document.createElement('form');
          form.method = 'POST'; form.action = '/account/tokens';
          document.body.append(form); form.submit();
        }""")
        page.wait_for_url("**/account/tokens")
    else:
        page.goto("http://testserver/account")
    page.wait_for_function("typeof window.__poll === 'function'")
    return requests


@pytest.mark.browser
@pytest.mark.parametrize("interaction", ["input", "change", "focus", "other_form", "in_flight", "issued"])
def test_forms_and_one_time_key_prevent_automatic_navigation(page, interaction):
    requests = _open(page, issued=interaction == "issued")
    before = len(requests)
    page.locator('[data-testid="token-section"]').evaluate("el => el.open = true")
    page.locator('[data-testid="token-manual-form"]').evaluate("el => el.open = true")
    field = page.locator('input[name="token_name"]')
    if interaction == "in_flight":
        page.evaluate("() => { window.__hold = true; window.__pending = window.__poll(); }")
        page.wait_for_function("typeof window.__release === 'function'")
    if interaction in {"input", "in_flight"}:
        field.fill("452")
        field.blur()
    elif interaction == "change":
        field.evaluate("el => { el.value = '452'; el.dispatchEvent(new Event('change', {bubbles:true})); }")
    elif interaction == "focus":
        field.focus()
    elif interaction == "other_form":
        page.evaluate("""() => {
          const field = document.querySelector('form:not(:has(input[name="token_name"])) input:not([type="hidden"])');
          field.dispatchEvent(new Event('input', {bubbles:true}));
        }""")
    if interaction == "in_flight":
        page.evaluate("async () => { window.__release(); await window.__pending; }")
    else:
        page.evaluate("async () => { await window.__poll(); }")
    notice = page.get_by_test_id("activation-update-notice")
    expect(notice).to_be_visible()
    expect(page.get_by_test_id("activation-waiting")).to_be_hidden()
    expect(notice.get_by_role("link", name="Обновить страницу")).to_have_attribute("href", "/account")
    assert page.evaluate("window.__stopped")
    assert len(requests) == before
    page.set_viewport_size({"width": 390, "height": 844})
    page.evaluate("scrollTo(0, 0)")
    assert 0 <= notice.bounding_box()["y"] < 844
    if interaction in {"input", "change", "in_flight"}:
        expect(field).to_have_value("452")
    if interaction == "issued":
        expect(page.locator("#issued-token-panel")).to_be_visible()


@pytest.mark.browser
@pytest.mark.parametrize("post", [False, True])
def test_first_request_uses_get_even_after_post(page, post):
    requests = _open(page, post=post)
    before = len(requests)
    with page.expect_navigation(url="http://testserver/account", wait_until="domcontentloaded") as navigation:
        page.evaluate("setTimeout(() => { void window.__poll(); }, 0)")
    assert navigation.value.request.method == "GET"
    assert len(requests) == before + 1


@pytest.mark.browser
def test_twentieth_poll_does_not_navigate_and_eightieth_stops(page):
    requests = _open(page)
    before = len(requests)
    page.evaluate("window.__state = 'needs_client_use'")
    page.evaluate("async () => { for(let i=0; i<80 && !window.__stopped; i++) await window.__poll(); }")
    assert len(requests) == before
    assert page.evaluate("window.__pollCount") == 80
    assert page.evaluate("window.__stopped")
