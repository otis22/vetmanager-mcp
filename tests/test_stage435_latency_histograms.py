"""New histogram exposition must preserve distribution and bounded labels."""

import httpx
import pytest

import service_metrics as metrics
from server import mcp


BOUNDS = ("0.1", "0.25", "0.5", "1", "2.5", "5", "10", "20", "30", "60", "+Inf")


def _samples(text, name, labels):
    return {
        line.split("} ", 1)[0].rsplit('le="', 1)[1][:-1]: int(line.rsplit(" ", 1)[1])
        for line in text.splitlines()
        if line.startswith(name + "_bucket{" + labels + ',le="')
    }


def test_histogram_families_and_buckets_are_exported_after_observations():
    metrics.reset_service_metrics()
    metrics.record_tool_call(endpoint="/rest/api/MedicalCards#list", method="GET",
                             outcome="success", duration_seconds=0.2,
                             tool_name="get_medical_cards_by_date")
    metrics.record_tool_call(endpoint="/rest/api/MedicalCards#list", method="GET",
                             outcome="error", duration_seconds=25,
                             tool_name="get_medical_cards_by_date")
    metrics.record_upstream_request(target="billing_api", status="read_timeout",
                                    duration_seconds=10.1)
    metrics.record_host_resolution(duration_seconds=10.3, outcome="error")
    output = metrics.render_prometheus_metrics()

    families = (
        ("vetmanager_tool_call_duration_seconds", 'tool="get_medical_cards_by_date",method="GET"', 2),
        ("vetmanager_billing_api_duration_seconds", 'status="read_timeout"', 1),
        ("vetmanager_host_resolution_duration_seconds", 'outcome="error"', 1),
    )
    for name, labels, count in families:
        assert f"# TYPE {name} histogram" in output
        buckets = _samples(output, name, labels)
        assert tuple(buckets) == BOUNDS
        assert list(buckets.values()) == sorted(buckets.values())
        assert buckets["+Inf"] == count
        assert f"{name}_count{{{labels}}} {count}" in output
    tool = _samples(output, *families[0][:2])
    assert tool["0.1"] == 0 and tool["0.25"] == 1
    assert tool["20"] == 1 and tool["30"] == 2
    assert 'vetmanager_tool_call_duration_seconds_sum{tool="get_medical_cards_by_date",method="GET"} 25.2' in output
    assert "vetmanager_tool_call_latency_seconds_count" in output


@pytest.mark.asyncio
async def test_histogram_is_visible_on_metrics_endpoint():
    metrics.reset_service_metrics()
    metrics.record_tool_call(endpoint="/rest/api/invoice#list", method="GET",
                             outcome="success", duration_seconds=0.2)
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://testserver") as client:
        response = await client.get("/metrics")
    assert response.status_code == 200
    assert '# TYPE vetmanager_tool_call_duration_seconds histogram' in response.text
    assert 'vetmanager_tool_call_duration_seconds_bucket{tool="invoice.list",method="GET",le="0.25"} 1' in response.text
