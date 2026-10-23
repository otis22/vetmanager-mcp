"""Stage 427: registered MCP prompts describe callable tool routes."""

import pytest
from fastmcp import Client

from server import mcp


async def _render(name: str, arguments: dict) -> str:
    async with Client(mcp) as client:
        rendered = await client.get_prompt(name, arguments=arguments)
    assert len(rendered.messages) == 1
    assert rendered.messages[0].role == "user"
    return rendered.messages[0].content.text


@pytest.mark.asyncio
async def test_find_client_routes_digits_to_phone_and_other_text_to_name():
    digits = await _render("find_client", {"query": "79184140259"})
    letters = await _render("find_client", {"query": "Иванов"})
    assert "get_clients(phone=query, limit=20)" in digits
    assert "get_clients(name=query, limit=20)" not in digits
    assert "get_clients(name=query, limit=20)" in letters
    assert "get_clients(phone=query, limit=20)" not in letters
    assert "digits" in digits and "otherwise" in digits
    assert "at least 4 digits" in digits


@pytest.mark.asyncio
async def test_client_balance_uses_client_balance_and_labels_bounded_details():
    body = await _render("client_balance", {"client_id": 42})
    assert "get_clients(status='', filter=[{'property':'id','operator':'=','value':client_id}])" in body
    assert "Use the returned client's balance field as the server balance" in body
    assert "get_invoices(client_id=client_id, limit=100" in body
    assert "get_client_payment_applications(client_id=client_id, limit=100" in body
    assert body.count("sort=[{'property':'create_date','direction':'DESC'}]") == 2
    assert "last 100" in body
    assert "Summarise total debt" not in body
    assert "do not derive" in body


@pytest.mark.asyncio
async def test_add_medical_note_requires_clinic_and_saves_text_after_create():
    async with Client(mcp) as client:
        prompt = next(p for p in await client.list_prompts() if p.name == "add_medical_note")
        arguments = {a.name: a.required for a in (prompt.arguments or [])}
        assert arguments["clinic_id"] is True
    body = await _render("add_medical_note", {
        "pet_id": 7, "doctor_id": 8, "clinic_id": 9,
        "note": "Observation", "diagnosis": "Text diagnosis",
    })
    assert "create_medical_card(patient_id=pet_id, doctor_id=doctor_id, clinic_id=clinic_id" in body
    assert "date_create=today, description=note)" in body
    assert "update_medical_card(card_id=created_card_id, diagnosis_text=diagnosis)" in body
    assert "only after successful creation" in body
    assert "never repeat create" in body
    assert "report the created card ID and partial result" in body
    assert "get_medical_card_by_id(created_card_id)" in body
    assert "diagnos_text field" in body
    assert "if that date is unknown, ask before creating" in body
    assert "diagnosis=diagnosis" not in body
