"""Stage 273 — the page says what the preset gives, and the refusal offers the
smallest key that would work.

Before this, the account page offered seven words and one line of copy claiming
the level decides "what the assistant can see" — while five of the seven
presets also allow writing. Nothing on the page said whether a key could delete
a client, and that silence is what the user report was about.
"""

import pytest

from access_summary import ACCESS_AREAS, DELETABLE_RECORDS, NOTHING, summarize_access
from tool_access_registry import (
    PRESET_FULL_ACCESS,
    TOKEN_PRESET_CHOICES,
    TOKEN_PRESET_LABELS,
    TOKEN_PRESET_SCOPES,
    TOOL_REQUIRED_SCOPES,
    get_presets_allowing_tool,
    get_presets_granting_scope,
)
from token_scopes import (
    SCOPE_CLIENTS_READ,
    SCOPE_RECORDS_DELETE,
    SUPPORTED_TOKEN_SCOPES,
)


def _lines(preset):
    return dict(summarize_access(TOKEN_PRESET_SCOPES[preset]))


def test_every_right_is_shown_somewhere():
    """A right missing from the table disappears from the page silently, and
    the summary starts understating what the key can do."""
    covered = {area.read_scope for area in ACCESS_AREAS} | {area.write_scope for area in ACCESS_AREAS}
    covered.discard(None)
    covered.add(SCOPE_RECORDS_DELETE)

    assert set(SUPPORTED_TOKEN_SCOPES) == covered


def test_the_delete_line_names_what_is_actually_deletable():
    """If a third deleting tool appears, this text stops being true — better to
    fail here than to keep telling owners it is only clients and pets."""
    deleting = {
        name for name, scopes in TOOL_REQUIRED_SCOPES.items() if SCOPE_RECORDS_DELETE in scopes
    }

    assert deleting == {"delete_client", "delete_pet"}
    assert DELETABLE_RECORDS == "клиенты и питомцы"


@pytest.mark.parametrize("preset", TOKEN_PRESET_CHOICES)
def test_all_three_lines_are_always_there(preset):
    lines = summarize_access(TOKEN_PRESET_SCOPES[preset])

    assert [name for name, _ in lines] == ["Чтение", "Изменение", "Удаление"]


@pytest.mark.parametrize("preset", [p for p in TOKEN_PRESET_CHOICES if p != PRESET_FULL_ACCESS])
def test_only_full_access_says_it_can_delete(preset):
    assert _lines(preset)["Удаление"] == NOTHING
    assert _lines(PRESET_FULL_ACCESS)["Удаление"] == DELETABLE_RECORDS


def test_read_only_says_it_changes_nothing():
    assert _lines("read_only")["Изменение"] == NOTHING


def test_front_desk_admits_what_it_changes():
    changing = _lines("frontdesk")["Изменение"]

    assert "клиенты" in changing and "питомцы" in changing and "рассылки" in changing


def test_analytics_reads_widely_and_changes_only_reports():
    lines = _lines("report_ai")

    assert "медкарты и госпитализация" in lines["Чтение"]
    assert lines["Изменение"] == "отчёты"


def _narrower_first(labels):
    """Presets ordered by how much they grant, in the labels' own order."""
    by_label = {TOKEN_PRESET_LABELS[preset]: len(TOKEN_PRESET_SCOPES[preset]) for preset in TOKEN_PRESET_CHOICES}
    return [by_label[label] for label in labels]


def test_the_refusal_offers_the_smallest_key_first():
    """The list is what an agent reads to decide what to ask its owner for.
    Full access first taught it to ask for everything."""
    for tool_name, required in TOOL_REQUIRED_SCOPES.items():
        if not required:
            continue
        labels = get_presets_allowing_tool(tool_name)
        if len(labels) < 2:
            continue
        sizes = _narrower_first(labels)

        assert sizes == sorted(sizes), (tool_name, labels)
        assert labels[-1] == TOKEN_PRESET_LABELS[PRESET_FULL_ACCESS], (tool_name, labels)


def test_the_rest_path_refusal_orders_the_same_way():
    """`get_presets_granting_scope` is the other place that names presets — the
    refusal a REST call gets. One order, or half the refusals keep teaching the
    old lesson."""
    labels = get_presets_granting_scope(SCOPE_CLIENTS_READ)
    sizes = _narrower_first(labels)

    assert sizes == sorted(sizes), labels
    assert labels[-1] == TOKEN_PRESET_LABELS[PRESET_FULL_ACCESS], labels


def _account_html(**overrides):
    from storage_models import Account
    from web_html import render_account_page

    account = Account(id=1, email="owner@example.com", status="active")
    defaults = dict(
        csrf_token="csrf-token",
        script_nonce="nonce",
        active_connection_count=1,
        bearer_token_count=0,
        active_connection=None,
        integration_health_status="active",
        integration_health_reason="ok",
        bearer_tokens=[],
        oauth_grants=[],
    )
    defaults.update(overrides)
    return render_account_page(account, **defaults)


def _rendered(name, value):
    return f"<strong>{name}:</strong> {value}"


def test_the_account_page_says_see_and_change_not_just_see():
    html = _account_html()

    assert "видеть и менять" in html
    assert "определяет, что помощник сможет видеть." not in html


def test_the_account_page_shows_the_summary_of_every_preset():
    html = _account_html()

    for preset in TOKEN_PRESET_CHOICES:
        for name, value in summarize_access(TOKEN_PRESET_SCOPES[preset]):
            assert _rendered(name, value) in html
    # The line that was missing when a reader concluded the token deletes
    # whatever it likes.
    assert _rendered("Удаление", NOTHING) in html


def test_the_summary_does_not_bring_a_card_inside_a_card_or_block_wrapping():
    """The owner asked that the page not get worse looking. Nested cards and a
    no-wrap list are the two ways a summary of ten areas does that."""
    html = _account_html()
    summary_start = html.index('data-testid="token-access-summary"')
    summary_end = html.index("</div>", summary_start)
    summary = html[summary_start:summary_end]

    assert "panel-card" not in summary
    assert "<code>" not in summary
    assert "nowrap" not in summary


def test_the_consent_screen_shows_the_same_three_lines():
    from web_html import render_oauth_consent_page

    html = render_oauth_consent_page(
        client_name="ChatGPT",
        scopes=["clients.read"],
        request_state="state",
        csrf_token="csrf",
        connections=[{"id": 1, "domain": "clinic-a"}],
        script_nonce="nonce",
    )

    assert _rendered("Удаление", "нет") in html
    assert _rendered("Изменение", "отчёты") in html
