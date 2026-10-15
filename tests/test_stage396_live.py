"""Opt-in Report AI conversion witness; prints only HTTP codes and type counts."""

import asyncio
import os
import re
from collections import Counter
from decimal import Decimal, InvalidOperation
from unittest.mock import patch

import httpx
import pytest

from server import mcp
from tests.runtime_factories import patch_runtime_credentials


INTENT = ("Сумма счетов по месяцам за 2026 год без персональных данных. "
          "Покажи общую сумму для каждого месяца.")


@pytest.mark.real_api
@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"),
                    reason="Requires the .env TEST_DOMAIN/TEST_API_KEY contour")
async def test_stage396_live_report_rows(capsys):
    original = httpx.AsyncClient.request
    codes = []
    raw_rows = []

    async def capture(client, method, url, **kwargs):
        response = await original(client, method, url, **kwargs)
        if "/rest/api/report-ai-job" in str(url):
            codes.append((method, response.status_code))
        if method == "GET" and "/data" in str(url) and response.status_code == 200:
            raw_rows[:] = response.json().get("data", {}).get("rows", [])
        return response

    headers, runtime = patch_runtime_credentials(
        os.environ["TEST_DOMAIN"], os.environ["TEST_API_KEY"], is_depersonalized=False,
    )
    with headers, runtime, patch.object(httpx.AsyncClient, "request", capture):
        created = await mcp.call_tool("create_report_ai_job", {"intent_text": INTENT})
        job = created.structured_content["data"]["job"]
        job_id, status = job["id"], job.get("status")
        for _ in range(8):
            if status not in {"queued", "recognizing", "building_preview"}:
                break
            await asyncio.sleep(3)
            viewed = await mcp.call_tool("get_report_ai_job", {"job_id": job_id})
            status = viewed.structured_content["data"]["job"].get("status")
        if status == "ready_to_save":
            saved = await mcp.call_tool("save_report_ai_job_as_report", {
                "job_id": job_id, "title": "MCP stage 396 amount by month 2026-10-15",
            })
            assert saved.structured_content.get("success") is True
            status = "saved"
        assert status in {"saved", "existing_report_matched"}
        result = await mcp.call_tool("get_report_ai_job_data", {"job_id": job_id})

    data = result.structured_content["data"]
    rows = data["rows"]
    assert rows and raw_rows and len(rows) == len(raw_rows)
    pairs = Counter((type(before).__name__, type(after).__name__)
                    for raw, clean in zip(raw_rows, rows)
                    for key, before in raw.items()
                    if key in clean for after in (clean[key],))
    witnesses = 0
    for raw, clean in zip(raw_rows, rows):
        for key, before in raw.items():
            if not isinstance(key, str) or not re.search(r"сумм|amount|total", key, re.I):
                continue
            after = clean.get(key)
            if isinstance(before, str) and isinstance(after, (int, float)) and not isinstance(after, bool):
                try:
                    exact = Decimal(before) == Decimal(str(after))
                except InvalidOperation:
                    exact = False
                assert exact
                witnesses += 1
    assert witnesses > 0
    safe = {"http_codes": codes, "rows_count": len(rows),
            "columns_count": len(data.get("columns", [])),
            "type_pairs": {f"{before}->{after}": count for (before, after), count in pairs.items()}}
    with capsys.disabled():
        print(f"stage396 live body={safe}")
    assert any(method == "POST" and code in {200, 201} for method, code in codes)
    assert any(method == "GET" and code == 200 for method, code in codes)
