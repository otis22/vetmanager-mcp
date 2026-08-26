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
