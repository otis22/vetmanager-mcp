"""Tests for tools/_inactive_helpers.py."""

import asyncio
import json
from datetime import date

import pytest

from tools import _inactive_helpers as inactive_helpers
from tools._inactive_helpers import calculate_inactive_window


class TestCalculateInactiveWindow:
    def test_default_window_13_to_24_months(self):
        # Use fixed reference date for determinism
        cutoff_oldest, cutoff_newest = calculate_inactive_window(
            months_min=13, months_max=24, today=date(2026, 4, 7)
        )
        # months_max=24 → cutoff_oldest = 2024-04-07
        assert cutoff_oldest == "2024-04-07"
        # months_min=13 → cutoff_newest = 2025-03-07
        assert cutoff_newest == "2025-03-07"

    def test_custom_window_3_to_6_months(self):
        cutoff_oldest, cutoff_newest = calculate_inactive_window(
            months_min=3, months_max=6, today=date(2026, 4, 7)
        )
        assert cutoff_oldest == "2025-10-07"
        assert cutoff_newest == "2026-01-07"

    def test_calendar_accurate_month_subtraction(self):
        # Today=March 31, subtract 1 month → February 28 (not March 3)
        cutoff_oldest, cutoff_newest = calculate_inactive_window(
            months_min=1, months_max=1, today=date(2025, 3, 31)
        )
        assert cutoff_oldest == "2025-02-28"
        assert cutoff_newest == "2025-02-28"

    def test_handles_leap_year_boundary(self):
        # Today=Feb 29 leap year, subtract 12 months → Feb 28 of prev year
        cutoff_oldest, _ = calculate_inactive_window(
            months_min=12, months_max=12, today=date(2024, 2, 29)
        )
        assert cutoff_oldest == "2023-02-28"

    def test_validates_min_less_than_or_equal_max(self):
        with pytest.raises(ValueError, match="months_min must be <= months_max"):
            calculate_inactive_window(months_min=10, months_max=5)

    def test_validates_positive_min(self):
        with pytest.raises(ValueError, match="months_min must be >= 1"):
            calculate_inactive_window(months_min=0, months_max=5)


class _TrackingClient:
    def __init__(self, delay: float = 0.01):
        self.delay = delay
        self.current_in_flight = 0
        self.max_in_flight = 0

    async def get(self, endpoint, params=None):
        self.current_in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.current_in_flight)
        try:
            await asyncio.sleep(self.delay)
            offset = int((params or {}).get("offset", 0))
            if endpoint == "/rest/api/pet":
                filter_payload = params.get("filter")
                owner_filter = next(
                    item for item in json.loads(filter_payload)
                    if item["property"] == "owner_id"
                )
                owner_value = owner_filter["value"]
                owner_ids = owner_value if isinstance(owner_value, list) else [owner_value]
                pets = [
                    {
                        "id": int(owner_id) * 10,
                        "alias": f"Pet{owner_id}",
                        "type_id": 1,
                        "owner_id": int(owner_id),
                        "status": "alive",
                    }
                    for owner_id in owner_ids
                ]
                page = pets[offset:offset + 100]
                return {"data": {"totalCount": len(pets), "pet": page}}
            if endpoint == "/rest/api/invoice":
                return {"data": {"totalCount": 0, "invoice": []}}
            if endpoint == "/rest/api/MedicalCards":
                return {"data": {"totalCount": 0, "medicalCards": []}}
            raise AssertionError(f"unexpected endpoint {endpoint}")
        finally:
            self.current_in_flight -= 1


@pytest.mark.asyncio
async def test_find_pets_at_client_last_visit_limits_chunk_concurrency(monkeypatch):
    monkeypatch.setattr(inactive_helpers, "_BATCH_CONCURRENCY", 2)

    class SingleOwnerClient(_TrackingClient):
        async def get(self, endpoint, params=None):
            self.current_in_flight += 1
            self.max_in_flight = max(self.max_in_flight, self.current_in_flight)
            try:
                await asyncio.sleep(self.delay)
                offset = int((params or {}).get("offset", 0))
                if endpoint == "/rest/api/pet":
                    pets = [
                        {
                            "id": idx,
                            "alias": f"Pet{idx}",
                            "type_id": 1,
                            "owner_id": 77,
                            "status": "alive",
                        }
                        for idx in range(1, 401)
                    ]
                    page = pets[offset:offset + 100]
                    return {"data": {"totalCount": len(pets), "pet": page}}
                if endpoint == "/rest/api/invoice":
                    return {"data": {"totalCount": 0, "invoice": []}}
                if endpoint == "/rest/api/MedicalCards":
                    return {"data": {"totalCount": 0, "medicalCards": []}}
                raise AssertionError(f"unexpected endpoint {endpoint}")
            finally:
                self.current_in_flight -= 1

    client = SingleOwnerClient()
    result = await inactive_helpers.find_pets_at_client_last_visit(
        client,
        client_id=77,
        last_visit_date="2024-09-15 10:00:00",
    )

    assert result == []
    assert 1 < client.max_in_flight <= 2


@pytest.mark.asyncio
async def test_find_pets_for_clients_last_visit_limits_chunk_concurrency(monkeypatch):
    monkeypatch.setattr(inactive_helpers, "_BATCH_CONCURRENCY", 2)
    client = _TrackingClient()
    clients = [
        {
            "id": 1000 + idx,
            "last_visit_date": "2024-09-15 10:00:00",
        }
        for idx in range(500)
    ]

    result = await inactive_helpers.find_pets_for_clients_last_visit(
        client,
        clients=clients,
        limit=10,
    )

    assert len(result) == len(clients)
    assert all(pets == [] for _, pets in result)
    assert 1 < client.max_in_flight <= 2


@pytest.mark.asyncio
async def test_gather_bounded_preserves_order_and_empty_input(monkeypatch):
    monkeypatch.setattr(inactive_helpers, "_BATCH_CONCURRENCY", 2)

    async def _value_after_delay(value, delay):
        await asyncio.sleep(delay)
        return value

    result = await inactive_helpers._gather_bounded(
        _value_after_delay("first", 0.02),
        _value_after_delay("second", 0.01),
        _value_after_delay("third", 0.0),
    )

    assert result == ["first", "second", "third"]
    assert await inactive_helpers._gather_bounded() == []


@pytest.mark.asyncio
async def test_gather_bounded_cancels_pending_siblings_on_failure(monkeypatch):
    monkeypatch.setattr(inactive_helpers, "_BATCH_CONCURRENCY", 2)
    sibling_started = asyncio.Event()
    sibling_cancelled = asyncio.Event()

    async def _blocked_sibling():
        sibling_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            sibling_cancelled.set()
            raise

    async def _failing():
        await sibling_started.wait()
        raise RuntimeError("chunk failed")

    with pytest.raises(RuntimeError, match="chunk failed"):
        await inactive_helpers._gather_bounded(_blocked_sibling(), _failing())

    assert sibling_cancelled.is_set()


@pytest.mark.asyncio
async def test_find_pets_for_clients_last_visit_stops_after_limit_filled_by_day(monkeypatch):
    monkeypatch.setattr(inactive_helpers, "_BATCH_CONCURRENCY", 2)

    class LimitedClient(_TrackingClient):
        def __init__(self):
            super().__init__(delay=0.0)
            self.pet_owner_requests: list[list[int]] = []
            self.medcard_calls = 0

        async def get(self, endpoint, params=None):
            if endpoint == "/rest/api/pet":
                owner_filter = next(
                    item for item in json.loads(params["filter"])
                    if item["property"] == "owner_id"
                )
                owner_ids = owner_filter["value"]
                owner_ids = owner_ids if isinstance(owner_ids, list) else [owner_ids]
                self.pet_owner_requests.append([int(owner_id) for owner_id in owner_ids])
                pets = [
                    {
                        "id": int(owner_id) * 10,
                        "alias": f"Pet{owner_id}",
                        "type_id": 1,
                        "owner_id": int(owner_id),
                        "status": "alive",
                    }
                    for owner_id in owner_ids
                ]
                return {"data": {"totalCount": len(pets), "pet": pets}}
            if endpoint == "/rest/api/invoice":
                return {
                    "data": {
                        "totalCount": 1,
                        "invoice": [{"id": 1, "pet_id": 10, "invoice_date": "2024-09-15 10:00:00"}],
                    }
                }
            if endpoint == "/rest/api/MedicalCards":
                self.medcard_calls += 1
                return {"data": {"totalCount": 0, "medicalCards": []}}
            raise AssertionError(f"unexpected endpoint {endpoint}")

    client = LimitedClient()
    clients = [
        {"id": 1, "last_visit_date": "2024-09-15 10:00:00"},
        {"id": 2, "last_visit_date": "2024-09-16 10:00:00"},
    ]

    result = await inactive_helpers.find_pets_for_clients_last_visit(
        client,
        clients=clients,
        limit=1,
    )

    assert client.pet_owner_requests == [[1]]
    assert client.medcard_calls == 0
    assert result[0][1][0]["visit_source"] == "invoice"
