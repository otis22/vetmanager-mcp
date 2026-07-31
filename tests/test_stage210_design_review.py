"""Stage 210 design-review regression tests for the landing page and account cabinet.

The stage implements a production design review: it restores the affordance of the
collapsed technical block, moves clinic-facing content out of it, removes duplicated
sections, states that the service is free, and makes the cabinet speak Russian with a
readable destructive-action hierarchy.
"""

from __future__ import annotations

from html.parser import HTMLParser

import pytest

from landing_page import render_landing_page
from storage_models import Account
from tool_access_registry import TOKEN_PRESET_LABELS
from web_html import render_account_page

# --------------------------------------------------------------------------- helpers

_NON_TEXT_TAGS = {"script", "style"}


class _VisibleText(HTMLParser):
    """Collect text nodes and button/submit labels, skipping script and style."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _NON_TEXT_TAGS:
            self._skip_depth += 1
        if tag == "input":
            for name, value in attrs:
                if name == "value" and value:
                    self.chunks.append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag in _NON_TEXT_TAGS and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.chunks.append(data)


def visible_text(html: str) -> str:
    """Return only what a person actually reads: no markup, classes or testids."""
    parser = _VisibleText()
    parser.feed(html)
    return " ".join(" ".join(parser.chunks).split())


def _developer_block(html: str) -> str:
    start = html.find('id="developer-onboarding"')
    assert start != -1, "developer disclosure is missing"
    return html[start : html.find("</details>", start)]


def _account_html(**overrides) -> str:
    account = Account(id=1, email="ops@example.com", status="active")
    kwargs = dict(
        csrf_token="csrf-token",
        script_nonce="nonce",
        active_connection_count=1,
        bearer_token_count=3,
        active_connection=None,
        integration_health_status="active",
        integration_health_reason="ok",
        bearer_tokens=[
            {
                "id": 10,
                "name": "codex bridge",
                "token_prefix": "vm_st_Q9Uwh5",
                "access_label": "Настроен вручную",
                "privacy_label": "Обычные данные",
                "status": "active",
                "ip_mask": "*.*.*.*",
                "expires_at": "2027-06-07 18:29 UTC",
                "expires_at_raw": "2027-06-07T18:29:00+00:00",
                "last_used_at": "2026-04-24 22:22 UTC",
                "last_used_at_raw": "2026-04-24T22:22:00+00:00",
                "request_count": 2818,
            },
            {
                "id": 11,
                "name": "старый ключ",
                "token_prefix": "vm_st_QE53hD",
                "access_label": "Только чтение",
                "privacy_label": "Без персональных данных",
                "status": "expired",
                "ip_mask": "10.20.30.*",
                "expires_at": "2026-06-20 08:27 UTC",
                "expires_at_raw": "2026-06-20T08:27:00+00:00",
                "last_used_at": "Не использовался",
                "last_used_at_raw": None,
                "request_count": 0,
            },
            {
                "id": 12,
                "name": "отозванный ключ",
                "token_prefix": "vm_st_E3uCx7",
                "access_label": "Только чтение",
                "privacy_label": "Без персональных данных",
                "status": "revoked",
                "ip_mask": "*.*.*.*",
                "expires_at": "Без срока",
                "expires_at_raw": None,
                "last_used_at": "Не использовался",
                "last_used_at_raw": None,
                "request_count": 0,
            },
        ],
        oauth_grants=[
            {
                "id": 1,
                "client_name": "ChatGPT",
                "client_id": "cid-1",
                "access_label": "Аналитика",
                "scope_summary": "admissions.read, analytics.read, clients.read +7",
                "legacy_full_access": False,
                "privacy_label": "Скрыты",
                "legacy_privacy": True,
                "status": "active",
                "connection_id": 1,
                "created_at": "2026-06-22 18:29 UTC",
                "created_at_raw": "2026-06-22T18:29:00+00:00",
                "last_used_at": "2026-06-22 18:29 UTC",
                "last_used_at_raw": "2026-06-22T18:29:00+00:00",
                "is_last_used": True,
            },
        ],
    )
    kwargs.update(overrides)
    return render_account_page(account, **kwargs)


# ------------------------------------------------------------------- landing: D-1

def test_technical_block_has_a_visible_affordance() -> None:
    """D-1: the collapsed block must look like a disclosure, as every other one does."""
    html = render_landing_page()
    block = _developer_block(html)

    assert 'class="chev"' in block, "collapsed technical block has no chevron"
    assert 'class="ic-pre"' in block, "collapsed technical block has no leading icon"
    assert "Подключить агента вручную" in block
    assert "Техническая настройка" in html


def test_technical_block_summary_says_who_it_is_for() -> None:
    """D-1: the label alone does not tell a clinic admin whether to open it."""
    block = _developer_block(render_landing_page())
    summary = block[: block.find("</summary>")]

    assert "Codex" in summary and "Claude" in summary
    assert "ключ доступа" in summary.lower()


# ------------------------------------------------------------------- landing: D-2

def test_flow_diagram_is_public_and_jargon_free() -> None:
    """D-2: the best explainer on the page must not be hidden behind a disclosure."""
    html = render_landing_page()
    block = _developer_block(html)
    public_html = html.replace(block, "")

    assert 'class="flow-map"' in public_html, "flow diagram is not visible publicly"
    assert 'class="flow-map"' not in block, "flow diagram is still duplicated inside the block"

    flow_start = public_html.find('class="flow-map"')
    flow = public_html[flow_start : public_html.find("</div>", public_html.find("Ответ по данным", flow_start))]
    for jargon in ("MCP", "OAuth", "API", "Bearer", "token", "scope"):
        assert jargon not in flow, f"public flow diagram leaks {jargon!r}"


def test_public_jargon_invariant_survives_the_move() -> None:
    """The stage 208/209 invariant still holds after the flow diagram moves out.

    "Vetmanager MCP" in the footer copyright is the product's own name, not
    jargon explaining the mechanism, so the check runs on visible prose above it.
    """
    html = render_landing_page()
    public_html = html.replace(_developer_block(html), "")
    main = public_html[public_html.find("<main") : public_html.find("</main>")]

    for jargon in ("MCP", "OAuth", "Bearer", "scope"):
        assert jargon not in visible_text(main), f"{jargon!r} leaked outside the technical block"


def test_duplicated_content_is_removed_from_the_technical_block() -> None:
    """D-2: role cards and prompt chips duplicate public sections verbatim."""
    html = render_landing_page()

    assert "Примеры задач по ролям" not in html
    assert "Что можно спросить после подключения" not in html
    # The examples themselves stay on the page, in their public homes.
    assert "Какая выручка была за март?" in html
    assert "Кому из пациентов пора на прививку?" in html


def test_technical_block_heading_does_not_outrank_page_sections() -> None:
    """D-2: a heading hidden inside a disclosure must not be an h2."""
    block = _developer_block(render_landing_page())

    assert "<h3>Подключите ИИ-агента к вашему Vetmanager за 5 минут</h3>" in block
    assert "<h2>Подключите ИИ-агента" not in block


# ------------------------------------------------------------------- landing: D-3

def test_connection_config_lives_in_one_place() -> None:
    """D-3: two developer disclosures 3000px apart split the setup instructions."""
    html = render_landing_page()

    assert html.count("mcpServers") == 1, "connection config appears more than once"
    assert "Для разработчиков: формат подключения" not in html
    assert "mcpServers" in _developer_block(html), "config must sit with the commands"


# ------------------------------------------------------------------- landing: L-1..L-4

def test_start_steps_are_not_repeated_twice() -> None:
    """L-1: two sections described the same three steps 2000px apart."""
    html = render_landing_page()

    assert "Как начать работу" not in html
    assert "Регистрация вынесена в главный сценарий" not in html
    assert html.count('class="step-list"') == 1


def test_interface_does_not_explain_itself() -> None:
    """L-2: meta-copy about which button is 'above' creates doubt, not clarity."""
    assert "Это необязательно" not in render_landing_page()


def test_landing_has_exactly_one_h1() -> None:
    """L-3: the topbar brand and the hero both claimed to be the page heading."""
    html = render_landing_page()

    assert html.count("<h1") == 1
    assert 'class="brand-name"' in html


def test_low_contrast_captions_use_a_readable_ink() -> None:
    """L-4: three captions measured 3.05:1 where 4.5:1 is required."""
    html = render_landing_page()

    assert ".brand p {\n      margin: 1px 0 0;\n      font-size: 0.78rem;\n      color: var(--ink-500);" in html
    assert "footer .copy { text-align: right; color: var(--ink-500);" in html
    assert "color: var(--ink-300);\n      letter-spacing: 0.04em;" not in html


# ------------------------------------------------------------------- landing: L-6

def test_landing_states_the_service_is_free() -> None:
    """L-6: price was mentioned once, only in the mobile sticky bar."""
    html = render_landing_page()

    hero = html[html.find('class="hero"') : html.find("</section>", html.find('class="hero"'))]
    faq = html[html.find('id="faq"') : html.find("</section>", html.find('id="faq"'))]
    sticky = html[html.find('class="sticky-cta') :]

    assert "Бесплатно" in hero
    assert "Бесплатно" in faq
    assert "Бесплатно" in sticky


def test_landing_promises_no_future_billing() -> None:
    """L-6: the service is free, so nothing may hint at a tariff arriving later."""
    text = visible_text(render_landing_page()).lower()

    for hedge in ("тариф", "пробный", "триал", "подписк", "пока бесплатно", "без карты"):
        assert hedge not in text, f"landing hints at future billing via {hedge!r}"


def test_time_estimate_is_stated_once() -> None:
    """Stage 209 invariant: exactly one time promise on the page."""
    assert render_landing_page().count("2 минуты") == 1


# ------------------------------------------------------------------- landing: L-5

def test_sticky_bar_waits_until_the_hero_cta_scrolls_away() -> None:
    """L-5: the bar covered the bottom 90px of content from the first screen."""
    html = render_landing_page()

    assert "IntersectionObserver" in html
    assert 'class="sticky-cta is-hidden"' in html
    assert ".sticky-cta.is-hidden { display: none; }" in html
    assert "body { padding-bottom: calc(88px" in html, "content must clear the fixed bar"


# ------------------------------------------------------------------- cabinet: K-1

def test_destructive_actions_are_not_styled_as_the_primary_action() -> None:
    """K-1: 13 terracotta buttons, each irreversibly breaking a connection."""
    html = _account_html()

    assert "button.danger" in html
    assert html.count('class="danger"') >= 2
    assert "button {\n      background: var(--accent);" not in html
    assert "button.primary {" in html


def test_logout_is_secondary_and_destructive_actions_confirm() -> None:
    """K-1: the most prominent button on the page was logout."""
    html = _account_html()
    logout = html[html.find('data-testid="logout-submit"') - 200 : html.find('data-testid="logout-submit"') + 80]

    assert 'class="primary"' not in logout
    assert "data-confirm=" in html, "irreversible actions must ask before firing"


# ------------------------------------------------------------------- cabinet: K-3

def test_cabinet_speaks_russian() -> None:
    """K-3: half the interface was English, mixed with Russian in adjacent cells."""
    text = visible_text(_account_html())

    for english in (
        "ChatGPT connections",
        "Full access",
        "Read only",
        "Legacy/custom",
        "Custom/legacy",
        "Revoke",
        "Disconnect",
        "Actions",
        "Details",
        "Never",
        "No expiry",
        "Depersonalized",
        "Privacy и auth transparency",
    ):
        assert english not in text, f"cabinet still shows {english!r} to the user"


def test_agent_facing_preset_labels_stay_in_english() -> None:
    """K-3: these labels go into MCP error text read by an AI agent, not a human."""
    assert TOKEN_PRESET_LABELS["full_access"] == "Full access"
    assert TOKEN_PRESET_LABELS["read_only"] == "Read only"
    assert TOKEN_PRESET_LABELS["report_ai"] == "Analytics"


def test_cabinet_keeps_technical_identifiers_in_latin() -> None:
    """Token prefixes and scope names are identifiers, not prose."""
    html = _account_html()

    assert "vm_st_Q9Uwh5" in html
    assert "admissions.read" in html


# ------------------------------------------------------------------- cabinet: K-2

def test_legacy_warning_gets_a_full_width_row() -> None:
    """K-2: the warning was wrapped into a 78px column and broke mid-word."""
    html = _account_html()

    assert 'class="note-row"' in html
    assert "colspan=" in html
    assert 'class="warning"' in html, "a warning must not reuse the error style"
    assert "Legacy connection: personal data is hidden now" not in html
    assert "подключите ChatGPT заново" in html


# ------------------------------------------------------------------- cabinet: K-4

def test_finished_tokens_are_folded_away_from_working_ones() -> None:
    """K-4: 9 of 13 rows were expired or revoked and took 70% of the section."""
    html = _account_html()

    assert 'data-testid="token-list"' in html
    assert 'data-testid="finished-token-list"' in html
    finished = html[html.find('data-testid="finished-tokens"') :]
    assert "Завершённые" in finished
    assert "2" in finished, "the folded group must carry a counter"


def test_token_status_is_colour_coded() -> None:
    """K-4: the most important column was the only one with no visual signal."""
    html = _account_html()

    assert "token-status status-active" in html
    assert "token-status status-expired" in html
    assert "token-status status-revoked" in html
    assert ".status-active {" in html
    assert ".status-revoked {" in html


def test_connection_table_drops_empty_and_broken_columns() -> None:
    """K-4: 'Connection' held '1' in every row; 'Scopes' broke words mid-token."""
    html = _account_html()
    grants = html[html.find('data-testid="oauth-grant-list"') :]
    header = grants[: grants.find("</tr>")]

    assert "Connection" not in header
    assert "Scopes" not in header
    assert "admissions.read" in grants, "full scope list moves into the details block"


def test_the_connection_in_use_is_marked() -> None:
    """K-4: with nine identical rows, Disconnect was a guess."""
    html = _account_html()

    assert "Используется сейчас" in html


# ------------------------------------------------------------------- cabinet: K-6, K-7, K-8

def test_summary_metrics_come_before_the_long_lists() -> None:
    """K-6: the two longest lists were open, the reason to visit was collapsed."""
    html = _account_html()

    metrics = html.find('class="grid"')
    tokens = html.find('data-testid="token-list"')
    assert 0 < metrics < tokens, "counters must precede the token table"


def test_readiness_checklist_is_a_status_not_a_sequence() -> None:
    """K-6: an <ol> whose every item also carried a tick — two markers per line."""
    html = _account_html()
    checklist = html[html.find('class="activation-status"') :]
    checklist = checklist[: checklist.find("</div>")]

    assert "<ol>" not in checklist


def test_timestamps_carry_machine_and_human_values() -> None:
    """K-7: UTC is three hours off for a Moscow clinic."""
    html = _account_html()

    assert '<time datetime="2026-04-24T22:22:00+00:00"' in html
    assert "2026-04-24 22:22 UTC</time>" in html, "server text is the no-JS fallback"
    assert "Intl.DateTimeFormat" in html


def test_access_mode_choices_are_finger_sized() -> None:
    """K-8: 13px radio buttons choose how much of the clinic database is exposed."""
    html = _account_html()

    assert ".choice-option input {\n      width: 20px;\n      height: 20px;" in html
    assert "accent-color: var(--accent)" in html


# ------------------------------------------------------------------- cabinet: K-5, K-9

def test_cabinet_uses_the_same_typography_as_the_landing() -> None:
    """K-5: two screens of one product rendered in different typefaces."""
    html = _account_html()

    assert '--font-body: "Inter"' in html
    assert "system-ui" in html
    assert '"Avenir Next"' not in html


def test_cabinet_has_a_header_with_the_brand() -> None:
    """K-5: no logo, no navigation, 'На лендинг' after 7600px of scrolling."""
    html = _account_html()

    assert 'class="account-topbar"' in html
    assert 'aria-label="Vetmanager"' in html
    assert "ops@example.com" in html


def test_cabinet_disclosures_match_the_landing() -> None:
    """K-9: native ▸ triangles next to the landing's animated chevron."""
    html = _account_html()

    assert "summary::-webkit-details-marker" in html
    assert "Подробнее" in html


# ------------------------------------------------------------------- contract guards

def test_raw_token_never_leaks_into_the_lists() -> None:
    """Contract 4.2.14: the raw token is shown exactly once, at creation."""
    html = _account_html()

    assert "vm_st_Q9Uwh5" in html
    tokens_section = html[html.find('data-testid="token-list"') :]
    for attribute in ("data-token", "data-raw", 'type="hidden" name="raw'):
        assert attribute not in tokens_section


@pytest.mark.parametrize("status", ["active", "expired", "revoked"])
def test_every_token_status_renders(status: str) -> None:
    """A status with no branch would silently render an empty pill."""
    html = _account_html(
        bearer_tokens=[
            {
                "id": 1,
                "name": "ключ",
                "token_prefix": "vm_st_AAAAAA",
                "access_label": "Только чтение",
                "privacy_label": "Без персональных данных",
                "status": status,
                "ip_mask": "*.*.*.*",
                "expires_at": "Без срока",
                "expires_at_raw": None,
                "last_used_at": "Не использовался",
                "last_used_at_raw": None,
                "request_count": 0,
            }
        ]
    )

    assert f"status-{status}" in html


# ------------------------------------------------- external review follow-ups

def test_issued_key_block_speaks_russian() -> None:
    """The one-time block after creating a key kept English privacy labels.

    Found by the external committed-diff review: the smoke check never issues a
    key, so this path had no coverage.
    """
    html = _account_html(
        issued_raw_token="vm_st_freshly_created_value",
        issued_token_access_label="Аналитика",
        issued_token_privacy_label="Без персональных данных",
    )
    text = visible_text(html)

    assert "Depersonalized" not in text
    assert "Standard" not in text
    assert "Без персональных данных" in text


def test_full_width_rows_do_not_become_their_own_mobile_card() -> None:
    """K-2/K-4 on 390px: colspan rows carry no data-label.

    Without an explicit rule the card layout renders them as right-aligned
    fragments that read like a separate connection.
    """
    html = _account_html()

    assert ".token-table .detail-row td,\n      .token-table .note-row td {\n        display: block;" in html
    assert "content: none;" in html
    assert "td.grant-name-cell {\n        display: block;\n      }" in html


def test_action_cells_keep_their_mobile_label() -> None:
    """The header became screen-reader-only, so the cell needs its own label."""
    html = _account_html()

    assert html.count('data-label="Действия"') >= 2


def test_a_record_is_separated_from_the_next_one_not_from_its_own_details() -> None:
    """A connection spans up to three rows; the rule goes after the last of them."""
    html = _account_html()

    assert ".token-table tbody tr:has(+ .detail-row) > td { border-bottom: 0; }" in html
    assert ".token-table .detail-row:has(+ .note-row) > td { border-bottom: 0; }" in html
