"""Stage 432.2: agents can find files linked from medical-card text."""

import pytest

from server import mcp


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
