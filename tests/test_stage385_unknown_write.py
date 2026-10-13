"""A lost write response must lead to read-only reconciliation, never a retry."""

import json

import httpx
import pytest
import respx

from tests.test_stage356_sale_param_status import call, mocks


@pytest.mark.asyncio
@respx.mock
async def test_applied_put_with_lost_response_is_not_replayed():
    state, put = mocks()
    preview = await call(sale_param_id=38, clinic_id=1, target_status="disabled")

    def applied_then_disconnected(request):
        state["status"] = json.loads(request.content)["status"]
        raise httpx.ReadError("response lost", request=request)

    put.mock(side_effect=applied_then_disconnected)
    with pytest.raises(Exception, match="outcome is unknown; read the row before retrying"):
        await call(sale_param_id=38, clinic_id=1, target_status="disabled",
                   confirm=True, confirmation=preview["confirmation"])

    assert put.call_count == 1
    assert state["status"] == "disabled"
    reconciled = await call(sale_param_id=38, clinic_id=1, target_status="disabled")
    assert reconciled["current_status"] == "disabled"
    assert put.call_count == 1
