"""Stage 423: unknown Report AI writes stop at the REST scope boundary."""

import httpx
import pytest
import respx
from unittest.mock import AsyncMock

from exceptions import AuthError
from tests.runtime_factories import make_client_with_resolved_runtime
from token_scopes import (
    REQUEST_NOT_MAPPED,
    SCOPE_ANALYTICS_READ,
    SCOPE_REPORT_AI_WRITE,
    SUPPORTED_TOKEN_SCOPES,
    required_scope_for_request,
)


BASE = "https://clinic.example"


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
@pytest.mark.parametrize("path", [
    "/rest/api/report-ai-job",
    "/rest/api/report-ai-job/23",
    "/REST/API/REPORT-AI-JOB/23/?trace=1",
])
@pytest.mark.asyncio
async def test_report_ai_unknown_writes_are_refused_before_upstream(method, path):
    client = make_client_with_resolved_runtime(
        "clinic.example", "key", scopes=tuple(SUPPORTED_TOKEN_SCOPES)
    )
    client._resolve_host = AsyncMock(return_value=BASE)
    with respx.mock(base_url=BASE, assert_all_called=False) as router:
        route = router.request(method, path.split("?", 1)[0]).mock(
            return_value=httpx.Response(200, json={"unexpected": True})
        )
        with pytest.raises(AuthError) as refused:
            await getattr(client, method.lower())(path)
        assert refused.value.status_code == 403
        assert route.call_count == 0
    assert required_scope_for_request(method, path) == REQUEST_NOT_MAPPED


@pytest.mark.parametrize("method, path, scope", [
    ("GET", "/rest/api/report-ai-job/23", SCOPE_ANALYTICS_READ),
    ("GET", "/rest/api/report-ai-job/23/data", SCOPE_ANALYTICS_READ),
    ("POST", "/rest/api/report-ai-job", SCOPE_REPORT_AI_WRITE),
    ("POST", "/rest/api/report-ai-job/23/confirm", SCOPE_REPORT_AI_WRITE),
])
@pytest.mark.asyncio
async def test_existing_report_ai_methods_reach_upstream(method, path, scope):
    assert required_scope_for_request(method, path) == scope
    client = make_client_with_resolved_runtime("clinic.example", "key", scopes=(scope,))
    client._resolve_host = AsyncMock(return_value=BASE)
    with respx.mock(base_url=BASE) as router:
        route = router.request(method, path).mock(
            return_value=httpx.Response(200, json={"success": True})
        )
        if method == "GET":
            await client.get(path)
        else:
            await client.post(path, json={})
        assert route.call_count == 1


def test_report_ai_entity_matching_does_not_consume_neighbor_or_unknown_reads():
    assert required_scope_for_request("GET", "/rest/api/report-ai-job/23/unknown") == SCOPE_ANALYTICS_READ
    assert required_scope_for_request("GET", "/rest/api/report-ai-jobs/23") is None
    assert required_scope_for_request("PUT", "/rest/api/report-ai-jobs/23") == REQUEST_NOT_MAPPED
    assert required_scope_for_request("DELETE", "/report-ai-job/23") == REQUEST_NOT_MAPPED
