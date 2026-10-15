"""Contradictory upstream totals must not become a claimed end of a cursor walk."""

import pytest
import respx

from exceptions import ToolInputError
from tools._inactive_helpers import _fetch_all_entity_pages, find_pets_for_clients_last_visit
from tests.test_stage389_inactive_pets_cursor import _call, _client, _mock_data


@pytest.mark.asyncio
@respx.mock
async def test_empty_client_page_with_remaining_total_is_error():
    _mock_data([], {}, total=10)
    with pytest.raises(Exception, match="empty before reported totalCount"):
        await _call({"limit": 1})


class _ShortPageClient:
    def __init__(self, entity):
        self.entity = entity

    async def get(self, endpoint, params=None):
        key = "pet" if endpoint.endswith("/pet") else self.entity
        return {"data": {"totalCount": 2, key: [{"id": 1, "owner_id": 1}]}}


@pytest.mark.asyncio
async def test_short_pet_page_with_remaining_total_is_error():
    client = _client(1)
    with pytest.raises(ToolInputError, match="pet page ended"):
        await find_pets_for_clients_last_visit(
            _ShortPageClient("pet"), clients=[client], limit=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint,key", [
    ("/rest/api/invoice", "invoice"),
    ("/rest/api/MedicalCards", "medicalCards"),
])
async def test_short_related_page_with_remaining_total_is_error(endpoint, key):
    with pytest.raises(ToolInputError, match="page ended before reported totalCount"):
        await _fetch_all_entity_pages(
            _ShortPageClient(key), endpoint=endpoint,
            entity_keys=(key,), filters=[])
