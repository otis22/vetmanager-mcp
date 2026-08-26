"""Stage 264: a caller without the right access hears what exists, not just "denied".

A read-only token can read Report AI rows but cannot save the report that makes
those rows exist (known issue 20). Until now that dead end read as
`Bearer token lacks required scope 'report_ai.write'` — technically true and
useless: the model cannot tell whether the capability is missing, the request
is malformed, or somebody simply has to grant access.
"""

from __future__ import annotations

import pytest

from exceptions import AuthError
from token_scopes import SCOPE_ANALYTICS_READ
from tests.runtime_factories import make_client_with_resolved_runtime


def _read_only_client():
    return make_client_with_resolved_runtime(
        "clinic.example", "key", scopes=(SCOPE_ANALYTICS_READ,)
    )


@pytest.mark.asyncio
async def test_denied_write_says_the_capability_exists_and_who_can_grant_it():
    client = _read_only_client()

    with pytest.raises(AuthError) as denied:
        await client.post("/rest/api/report-ai-job/1/save", json={"title": "x"})

    message = str(denied.value)
    # The capability is real — say so, instead of implying a broken call.
    assert "report_ai.write" in message
    # Name the access that grants it, in the words the account page uses.
    assert "Analytics" in message
    # And tell the caller what to do, since retrying changes nothing.
    assert "administrator" in message.lower()
    assert denied.value.status_code == 403


@pytest.mark.asyncio
async def test_allowed_scope_is_not_touched_by_the_new_message():
    """The explanation must not leak into calls that are permitted."""
    client = _read_only_client()

    # A read is within this token's rights; it must fail on transport, not scope.
    with pytest.raises(Exception) as failure:
        await client.get("/rest/api/report-ai-job/1")

    assert "lacks required scope" not in str(failure.value)


def test_presets_granting_scope_covers_the_edges():
    """The list feeds a user-facing sentence, so its edges must be boring."""
    from tool_access_registry import get_presets_granting_scope

    # A scope several presets grant: full access first, then the specific one.
    assert get_presets_granting_scope("report_ai.write") == ("Full access", "Analytics")
    # A scope only full access grants must not name anything else.
    assert get_presets_granting_scope("users.write") == ("Full access",)
    # An unknown scope yields nothing rather than an odd sentence fragment.
    assert get_presets_granting_scope("not.a.real.scope") == ()


@pytest.mark.asyncio
async def test_denial_is_recognised_by_code_not_by_wording():
    """Error handling used to match a substring, which went stale on rewording."""
    from tool_access_registry import SCOPE_DENIED_ERROR_CODE

    client = _read_only_client()
    with pytest.raises(AuthError) as denied:
        await client.post("/rest/api/report-ai-job/1/save", json={"title": "x"})

    assert denied.value.error_code == SCOPE_DENIED_ERROR_CODE


def test_export_error_handler_uses_the_code():
    """The Report AI export path must classify a scope denial as such."""
    import tools.report_ai as report_ai
    from tool_access_registry import SCOPE_DENIED_ERROR_CODE

    denial = AuthError("wording may change", status_code=403, error_code=SCOPE_DENIED_ERROR_CODE)
    generic = AuthError("some other 403", status_code=403)

    assert "wording may change" in str(report_ai._safe_export_error(denial, "start export"))
    assert "wording may change" not in str(report_ai._safe_export_error(generic, "start export"))


def test_the_denial_the_agent_actually_reads_says_what_to_do():
    """The tool-level check fires first — this is the text agents really see.

    Stage 264 first improved the message in the HTTP client, one layer below,
    where execution never arrives when a tool is denied. The words have to be
    here, or they help nobody.
    """
    from tool_access_registry import PRESET_READ_ONLY, TOKEN_PRESET_SCOPES
    from tool_scope_security import _format_scope_denied_message

    message = _format_scope_denied_message(
        "save_report_ai_job_as_report",
        required_scopes=("report_ai.write",),
        token_scopes=TOKEN_PRESET_SCOPES[PRESET_READ_ONLY],
    )

    # What is missing and who has it — already there before this stage.
    assert "report_ai.write" in message
    assert "Read only" in message
    assert "Analytics" in message
    # What to do about it, and that retrying is pointless — the missing half.
    assert "administrator" in message.lower()
    assert "same way" in message or "will not change" in message
    # And say it once: the old text repeated the same sentence twice.
    assert message.count("is not permitted for this token") == 1
