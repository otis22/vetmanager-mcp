"""Live check for stage 223: the lapsed lists say whether they are complete.

Read-only — both tools only list. Nothing on the contour is created or changed.

Run against the dedicated test contour:

    docker compose --env-file .env --profile test run --rm -T test \\
        pytest -m real_api tests/test_stage223_live_inactive_completeness.py
"""

import json
import os

import pytest

from server import mcp
from tests.runtime_factories import patch_runtime_credentials

TEST_DOMAIN = os.environ.get("TEST_DOMAIN", "")
TEST_API_KEY = os.environ.get("TEST_API_KEY", "")

skip_if_no_creds = pytest.mark.skipif(
    not TEST_DOMAIN or not TEST_API_KEY,
    reason="TEST_DOMAIN and TEST_API_KEY not set — skipping real API tests",
)


async def _call(tool: str, args: dict) -> dict:
    headers_patch, runtime_patch = patch_runtime_credentials(TEST_DOMAIN, TEST_API_KEY)
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(tool, args)
    return json.loads(result.content[0].text)


@skip_if_no_creds
@pytest.mark.real_api
@pytest.mark.asyncio
async def test_real_lapsed_clients_carry_a_window_total() -> None:
    data = await _call("get_inactive_clients", {"months_min": 1, "months_max": 240, "limit": 2})
    print("get_inactive_clients:", json.dumps(
        {k: v for k, v in data.items() if k != "inactive_clients"}, ensure_ascii=False
    ))

    assert "total_in_window" in data and "truncated" in data
    total = data["total_in_window"]
    assert total is None or isinstance(total, int)
    if isinstance(total, int) and total > 2:
        assert data["truncated"] is True
        assert len(data["inactive_clients"]) == 2


@skip_if_no_creds
@pytest.mark.real_api
@pytest.mark.asyncio
async def test_real_lapsed_pets_say_whether_the_list_is_cut() -> None:
    """A one-pet request over a wide window: whatever the contour holds, the
    answer must state whether more was left behind."""
    data = await _call("get_inactive_pets", {"months_min": 1, "months_max": 240, "limit": 1})
    print("get_inactive_pets:", json.dumps(
        {k: v for k, v in data.items() if k != "inactive_pets"}, ensure_ascii=False
    ))

    assert isinstance(data["truncated"], bool)
    assert data["truncation_reason"] in (None, "limit_reached", "client_scan_cap",
                                         "limit_reached+client_scan_cap")
    assert len(data["inactive_pets"]) <= 1
    if data["truncated"]:
        assert data["truncation_reason"] is not None
    else:
        assert data["truncation_reason"] is None
