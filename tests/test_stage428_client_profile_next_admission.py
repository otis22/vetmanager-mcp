"""Stage 428: the profile's first active admission respects today's lower bound."""

import json
from datetime import date
from unittest.mock import AsyncMock

import pytest

from resources import client_profile
from resources.admission_status import ACTIVE_ADMISSION_STATUSES


TODAY = date(2026, 10, 21)
OVERDUE = {"id": 1, "admission_date": "2026-10-20 09:00:00", "status": "accepted"}
EARLIER_TODAY = {"id": 2, "admission_date": "2026-10-21 09:00:00", "status": "accepted"}
LATER_TODAY = {"id": 3, "admission_date": "2026-10-21 17:00:00", "status": "accepted"}
FUTURE = {"id": 4, "admission_date": "2026-10-22 09:00:00", "status": "accepted"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rows", "expected_id"),
    [
        ([OVERDUE, FUTURE], 4),
        ([OVERDUE], None),
        ([FUTURE], 4),
        ([], None),
        ([EARLIER_TODAY, LATER_TODAY], 2),
    ],
    ids=["overdue-and-future", "only-overdue", "only-future", "empty", "today-day-window"],
)
async def test_profile_next_admission_server_filter(monkeypatch, rows, expected_id):
    monkeypatch.setattr(client_profile, "clinic_local_today", AsyncMock(return_value=TODAY), raising=False)
    next_params = []

    class FakeClient:
        async def get(self, path, params=None):
            if path.startswith("/rest/api/client/"):
                return {"data": {"client": {"id": 7}}}
            if path == "/rest/api/invoice":
                return {"data": {"invoice": []}}
            assert path == "/rest/api/admission"
            if params["limit"] != 1:
                return {"data": {"admission": []}}
            next_params.append(params)
            filters = json.loads(params["filter"])
            selected = list(rows)
            for clause in filters:
                if clause["property"] == "admission_date" and clause.get("operator") == ">=":
                    selected = [r for r in selected if r["admission_date"] >= clause["value"]]
                if clause["property"] == "status" and clause.get("operator") == "IN":
                    selected = [r for r in selected if r["status"] in clause["value"]]
            assert json.loads(params["sort"]) == [{"property": "admission_date", "direction": "ASC"}]
            selected.sort(key=lambda r: r["admission_date"])
            return {"data": {"admission": selected[:params["limit"]]}}

    monkeypatch.setattr(client_profile, "VetmanagerClient", FakeClient)
    result = await client_profile.fetch(7)
    assert (result["next_admission"] or {}).get("id") == expected_id
    assert len(next_params) == 1
    filters = json.loads(next_params[0]["filter"])
    assert {"property": "admission_date", "operator": ">=", "value": "2026-10-21 00:00:00"} in filters
    assert {"property": "status", "operator": "IN", "value": list(ACTIVE_ADMISSION_STATUSES)} in filters
