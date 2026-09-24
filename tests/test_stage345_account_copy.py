"""Stage 345: user-facing activation and visual evidence guards."""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs

from playwright.sync_api import Page

from first_request_examples import FIRST_REQUEST_EXAMPLES
from landing_page import render_landing_page
from tests.test_stage197_token_quick_issue import _account_page, _token_view


def _oauth(*, used: bool) -> dict[str, object]:
    return {"id": 1, "status": "active", "client_name": "ChatGPT", "has_live_access": True,
            "created_at": "сегодня", "last_used_at": "2026-09-24 12:00 UTC" if used else "Не использовался",
            "last_used_at_raw": "2026-09-24T12:00:00+00:00" if used else None}


def _status(html: str) -> str:
    return html.split('data-testid="activation-status"', 1)[1].split('</section>', 1)[0]


def test_ready_has_four_pilot_answer_pairs_and_existing_access_below() -> None:
    html = _account_page(bearer_tokens=[_token_view(request_count=5)], bearer_token_count=1)
    block = html.split('data-testid="ready-examples"', 1)[1].split('</section>', 1)[0]
    assert block.count('data-example-pair="ready"') == 4
    assert block.count('data-copy-kind="example"') == 4
    for index in (0, 1, 3, 4):
        question, answer = FIRST_REQUEST_EXAMPLES[index]
        assert question in block and answer in block
    assert "пример оформления, цифры вымышленные" in block
    assert html.index('data-testid="account-summary"') < html.index('data-testid="ready-examples"')
    assert 'data-testid="tokens-list-section"' in html
    assert 'data-testid="chatgpt-section"' in html


def test_three_checklist_steps_are_readable_and_chatgpt_optional() -> None:
    scenes = (
        _account_page(active_connection=None, integration_health_status="unknown", active_connection_count=0),
        _account_page(),
        _account_page(bearer_tokens=[_token_view()], bearer_token_count=1),
        _account_page(bearer_tokens=[_token_view(request_count=5)], bearer_token_count=1),
        _account_page(oauth_grants=[_oauth(used=False)]),
        _account_page(oauth_grants=[_oauth(used=True)]),
    )
    for html in scenes:
        status = _status(html)
        assert status.count('class="activation-step"') == 3
        assert status.count('class="activation-badge ') == 3
        assert 'data-testid="optional-chatgpt"' in status
        assert not re.search(r'(?:ожидает|следующий шаг)\s+(?:ChatGPT|Помощник|Vetmanager)', status)
    oauth_ready = _status(scenes[-1])
    assert 'data-activation-state="ready"' in scenes[-1]
    assert "Bearer-ключ выпущен" not in oauth_ready
    assert "ChatGPT подключён" in oauth_ready
    assert "Bearer-ключи всего</span>\n            <strong>0</strong>" in scenes[-1]
    bearer_ready = _status(scenes[3])
    assert "Bearer-ключ выпущен" in bearer_ready
    assert "ChatGPT подключён" not in bearer_ready
    assert "Bearer-ключи всего</span>\n            <strong>1</strong>" in scenes[3]
    assert "Подключение Vetmanager" in _status(scenes[0])
    assert "Vetmanager подключён" not in _status(scenes[0])
    assert "Задайте первый вопрос" in _status(scenes[2])
    assert "Помощник сделал первый запрос" not in _status(scenes[2])


def test_waiting_guide_has_one_question_and_no_empty_disclaimer() -> None:
    html = _account_page(bearer_tokens=[_token_view()], bearer_token_count=1)
    relevant = html.split('data-testid="activation-status"', 1)[1].split('data-testid="account-summary"', 1)[0]
    assert relevant.count(FIRST_REQUEST_EXAMPLES[0][0]) == 1
    assert "пример оформления, цифры вымышленные" not in relevant
    assert "Authorization bearer token" not in relevant
    assert 'class="support-link"' in relevant
    assert 'class="waiting-indicator"' in relevant


def test_oauth_waiting_and_access_choice_are_channel_aware() -> None:
    needs_clinic = _status(_account_page(active_connection=None, active_connection_count=0,
                                        integration_health_status="unknown"))
    assert 'href="#integration-section"' in needs_clinic
    assert needs_clinic.index('href="#integration-section"') < needs_clinic.index('<ul>')
    needs_access = _status(_account_page())
    assert 'href="#token-quick"' in needs_access
    assert 'href="#chatgpt-section"' in needs_access
    oauth = _account_page(oauth_grants=[_oauth(used=False)])
    relevant = oauth.split('data-testid="activation-status"', 1)[1].split('data-testid="account-summary"', 1)[0]
    assert 'Шаг 3 из 3 — Первый запрос' in oauth
    assert 'Проверьте ChatGPT' in relevant
    assert relevant.count(FIRST_REQUEST_EXAMPLES[0][0]) == 1
    assert 'data-testid="client-connect-instructions"' not in relevant

    bearer = _account_page(bearer_tokens=[_token_view()])
    status = _status(bearer)
    assert 'href="#client-connect-config"' in status
    assert 'id="client-connect-config"' in bearer


def test_issued_page_keeps_manual_form_closed_below_the_one_time_key() -> None:
    html = _account_page(issued_raw_token="vm_st_FICTIONAL_ONLY", bearer_tokens=[_token_view()])
    assert 'data-testid="token-manual-form" open' not in html
    assert "Новый токен показывается только один раз" not in html


def test_landing_has_distinct_scenarios_and_answer_labels() -> None:
    html = render_landing_page().split('id="examples"', 1)[1].split('id="faq"', 1)[0]
    assert html.count('data-example-pair="landing"') == 6
    assert html.count('class="example-answer-label"') == 6
    questions = re.findall(r'<strong class="example-question">([^<]+)</strong>', html)
    assert len(questions) == len(set(questions)) == 6
    assert not any("свободны сегодня после 15:00" in q for q in questions)


def test_visual_contract_is_shared_by_agent_instructions() -> None:
    marker = "<!-- stage-345-visual-contract:start -->"
    for path in ("AGENTS.md", "CLAUDE.md", ".cursor/rules/agent-workflow.mdc"):
        text = Path(path).read_text()
        assert marker in text
        assert "full_page" in text.split(marker, 1)[1].split("<!-- stage-345-visual-contract:end -->", 1)[0]


def test_ready_copy_sends_only_existing_aggregate_telemetry(page: Page) -> None:
    html = _account_page(bearer_tokens=[_token_view(request_count=5)], csrf_token="fictional-csrf")
    requests: list[str] = []
    page.route("https://local.invalid/account", lambda route: route.fulfill(body=html, content_type="text/html"))
    page.route("https://local.invalid/account/telemetry/example-copied",
               lambda route: (requests.append(route.request.post_data or ""), route.fulfill(status=204)))
    page.route("https://local.invalid/account/telemetry/motivator-shown",
               lambda route: route.fulfill(status=204))
    page.goto("https://local.invalid/account")
    page.evaluate("Object.defineProperty(navigator, 'clipboard', {value: {writeText: async value => {window.copiedQuestion = value}}})")
    page.locator('[data-testid="ready-examples"] button').first.click()
    page.wait_for_function("window.copiedQuestion !== undefined")
    page.wait_for_timeout(50)
    assert page.evaluate("window.copiedQuestion") == FIRST_REQUEST_EXAMPLES[0][0]
    assert len(requests) == 1
    assert parse_qs(requests[0]) == {"csrf_token": ["fictional-csrf"]}
    assert FIRST_REQUEST_EXAMPLES[0][0] not in requests[0]


def test_bearer_setup_action_opens_its_config(page: Page) -> None:
    html = _account_page(bearer_tokens=[_token_view()])
    page.route("https://local.invalid/account", lambda route: route.fulfill(body=html, content_type="text/html"))
    page.goto("https://local.invalid/account")
    page.get_by_role("link", name="Настроить Cursor / Claude Code").click()
    assert page.locator("#client-connect-config").evaluate("node => node.open") is True
    assert "Bearer &lt;ВАШ_ТОКЕН&gt;" in html
