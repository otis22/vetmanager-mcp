"""Stage 432.2: agents can find files linked from medical-card text."""

import pytest

from server import mcp
from tests.runtime_factories import patch_runtime_credentials
from vetmanager_client import VetmanagerClient


@pytest.mark.asyncio
async def test_medical_card_and_pet_profile_descriptions_explain_file_links():
    descriptions = {
        tool.name: tool.to_mcp_tool().description
        for tool in await mcp.list_tools()
    }
    names = (
        "get_medical_cards",
        "get_medical_cards_by_date",
        "get_medical_cards_by_client_id",
        "get_medical_card_by_id",
        "get_pet_profile",
    )
    for name in names:
        description = descriptions[name]
        for fragment in (
            "description", "HTML", "<a href>", "file storage",
            "open and use", "no separate file-list tool", "do not retry",
            "publicly accessible S3 link", "relevant to the user's request",
            "keep the file URL private", "closed or expired link",
            "only over HTTPS", "trusted by the client", "IP literal",
            "no trusted host configured, do not open",
        ):
            assert fragment in description, f"{name}: missing {fragment!r}"

    by_id = descriptions["get_medical_card_by_id"]
    assert "Fetch one medical card / clinical record by ID" in by_id
    assert "exact record identifier" in by_id
    assert "Domain synonyms: медкарта" in by_id


@pytest.mark.asyncio
async def test_html_file_link_survives_full_and_description_fields(monkeypatch):
    link = '<a href="https://files.example.test/public">lab file</a>'

    async def get(_self, _path, **_kwargs):
        return {"success": True, "data": {"medicalCards": [
            {"id": 7, "patient_id": 2, "description": link}], "totalCount": 1}}

    monkeypatch.setattr(VetmanagerClient, "get", get)
    headers, runtime = patch_runtime_credentials("testclinic", "mock-key")
    with headers, runtime:
        full = await mcp.call_tool("get_medical_cards", {"pet_id": 2})
        projected = await mcp.call_tool("get_medical_cards", {
            "pet_id": 2, "fields": ["description"]})
    assert link in full.structured_content["data"]["medicalCards"][0]["description"]
    assert projected.structured_content["data"]["medicalCards"] == [{"description": link}]
