"""Stage 276 — live proof that the export really goes through MCP.

A mock cannot show this one. The whole stage rests on what the Vetmanager
locator actually is, and on 01.09.2026 that turned out to be an unauthenticated
public CDN address. This test starts a real export on the test contour,
downloads it through the tool, and reads the file back off the link the tool
returned.

    docker compose --env-file .env --profile test run --rm -T test \\
        python -m pytest -m real_api tests/test_stage276_live_export_download.py
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

import report_export
from server import mcp
from tests.runtime_factories import patch_runtime_credentials


TEST_DOMAIN = os.environ.get("TEST_DOMAIN", "")
TEST_API_KEY = os.environ.get("TEST_API_KEY", "")
LIVE_REPORT_ID = int(os.environ.get("REPORT_EXPORT_PROBE_REPORT_ID", "84"))

pytestmark = pytest.mark.skipif(
    not (TEST_DOMAIN and TEST_API_KEY),
    reason="TEST_DOMAIN and TEST_API_KEY are required for the live export test",
)


@pytest.fixture
def live_export_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "report-exports"
    monkeypatch.setenv("REPORT_EXPORT_DIR", str(root))
    monkeypatch.setenv("WEB_SESSION_SECRET", "stage-276-live-secret")
    monkeypatch.setenv("SITE_BASE_URL", "https://mcp.example")
    report_export.reset_link_key_cache()
    return root


@pytest.mark.real_api
@pytest.mark.asyncio
async def test_real_export_is_downloaded_cleaned_and_served_by_us(live_export_root: Path) -> None:
    headers_patch, runtime_patch = patch_runtime_credentials(
        TEST_DOMAIN, TEST_API_KEY, is_depersonalized=True
    )
    with headers_patch, runtime_patch:
        started = await mcp.call_tool("start_report_export", {"report_id": LIVE_REPORT_ID})
        report_file_id = started.structured_content["data"]["report"]["report_file_id"]

        payload = None
        for _ in range(12):
            try:
                result = await mcp.call_tool(
                    "get_report_export_download", {"report_file_id": int(report_file_id)}
                )
            except Exception as exc:  # build not ready yet is an ordinary state here
                if "not ready" not in str(exc):
                    raise
                await asyncio.sleep(5)
                continue
            payload = result.structured_content
            break

    if payload is None:
        pytest.skip("Vetmanager did not finish the export build within the polling window")

    assert payload["download_url"].startswith("https://mcp.example/report-export/")
    assert "selcdn" not in str(payload)
    assert payload["depersonalized"] is True

    stored = list(live_export_root.rglob("*.csv"))
    assert len(stored) == 1
    body = stored[0].read_text(encoding="utf-8-sig")
    assert body
    assert body.splitlines()[0]

    owner, name = payload["download_url"].rsplit("/", 2)[-2:]
    resolved = report_export.resolve_export(owner, name.removesuffix(".csv"))
    assert resolved is not None
    assert resolved.path == stored[0]
