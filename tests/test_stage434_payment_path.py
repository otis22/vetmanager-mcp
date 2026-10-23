"""The published prompt and tool description must not route debt via stale status."""

import pytest
from pathlib import Path

from server import mcp


@pytest.mark.asyncio
async def test_unpaid_prompt_uses_invoice_sums_and_discloses_incomplete_scan():
    prompt = await mcp.get_prompt("unpaid_invoices")
    body = "\n".join(
        message.content.text
        for message in (await prompt.render(arguments={"limit": 50})).messages
    )
    assert "get_invoices(" in body
    assert "limit=50" in body
    assert "create_date" in body and "DESC" in body
    assert "payment_status='none'" not in body
    assert "payment_status='partial'" not in body
    assert "paid_amount < amount" in body
    assert "amount - paid_amount" in body
    assert "totalCount" in body and "offset" in body
    assert "exceeds the number of rows fetched" in body
    assert "clearly label the result partial" in body
    assert "missing, null, invalid or non-finite" in body


@pytest.mark.asyncio
async def test_invoice_payment_status_description_warns_about_drift():
    source = (Path(__file__).resolve().parents[1] / "tools" / "invoice.py").read_text()
    payment_arg = source.split("payment_status: Filter by payment status.", 1)[1].split("\n            status:", 1)[0]
    assert "payment_status can be stale" in payment_arg
    assert "paid_amount" in payment_arg and "amount" in payment_arg
    assert "debt" in payment_arg.lower()
