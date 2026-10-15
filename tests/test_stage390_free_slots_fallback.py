"""Stage 390: explain unknown timesheet types and require an explicit fallback."""

import pytest
import respx

from server import mcp
from exceptions import ToolInputError
from tests.test_stage321_field_contracts import (
    BASE, bearer_runtime_patch, billing_mock, empty_admissions, timesheet_response,
)


def row(row_id, row_type, title, ttype=None, *, begin="09:00:00"):
    result = {
        "id": row_id, "doctor_id": 1, "clinic_id": 1, "type": row_type,
        "title": title, "begin_datetime": f"2034-03-21 {begin}",
        "end_datetime": f"2034-03-21 {int(begin[:2]) + 1:02d}:00:00",
    }
    if ttype is not None:
        result["ttype"] = ttype
    return result


async def call(rows, **kwargs):
    billing_mock()
    respx.get(f"{BASE}/rest/api/timesheet").mock(
        return_value=timesheet_response(rows)
    )
    respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=empty_admissions()
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        return await mcp.call_tool("get_doctor_free_slots", {
            "doctor_id": 1, "date_from": "2034-03-21",
            "date_to": "2034-03-21", **kwargs,
        })


@pytest.mark.asyncio
@respx.mock
async def test_unknown_types_refusal_names_count_type_title_and_remedy():
    rows = [row(1, 0, "Рабочее время"), row(2, 0, "Рабочее время")]
    with pytest.raises(Exception) as exc:
        await call(rows)
    message = str(exc.value)
    assert "2" in message
    assert "type=0" in message
    assert "Рабочее время" in message
    assert "timesheet_types" in message
    assert "work_title" in message


@pytest.mark.asyncio
@respx.mock
async def test_unknown_title_with_person_name_is_redacted_in_refusal():
    with pytest.raises(Exception) as exc:
        await call([row(1, 0, "Иван Иванов")])
    assert "Иван Иванов" not in str(exc.value)
    assert "get_timesheets" in str(exc.value)


@pytest.mark.asyncio
@respx.mock
async def test_arbitrary_fallback_title_not_echoed_in_success():
    data = (await call([row(1, 0, "Иван Иванов")], work_title="Иван Иванов")).structured_content
    assert data["total_slots"] == 2
    assert "Иван Иванов" not in str(data)


@pytest.mark.asyncio
@respx.mock
async def test_exact_title_fallback_returns_slots_with_overestimate_warning():
    rows = [row(1, 0, "Рабочее время"), row(2, 0, "Выходной", begin="11:00:00")]
    result = await call(rows, work_title="Рабочее время")
    data = result.structured_content
    assert data["total_slots"] == 2
    assert data["slots"][0]["start"] == "2034-03-21T09:00:00"
    assert all(slot["start"] < "2034-03-21T11:00:00" for slot in data["slots"])
    assert "work_title" in data["warning"]
    assert "завыш" in data["warning"]


@pytest.mark.asyncio
@respx.mock
async def test_known_nonworking_type_cannot_be_overridden_by_title():
    rows = [row(1, 3, "Рабочее время", {"is_working_hours": 0})]
    data = (await call(rows, work_title="Рабочее время")).structured_content
    assert data["total_slots"] == 0


@pytest.mark.asyncio
@respx.mock
async def test_known_working_type_is_kept_even_with_other_fallback_title():
    rows = [row(1, 2, "Рабочее время", {"is_working_hours": 1})]
    data = (await call(rows, work_title="Дежурство")).structured_content
    assert data["total_slots"] == 2


@pytest.mark.asyncio
@respx.mock
async def test_unmatched_fallback_still_refuses_unknown_schedule():
    with pytest.raises(Exception, match="timesheet_types.*work_title"):
        await call([row(1, 0, "Рабочее время")], work_title="Дежурство")


@pytest.mark.asyncio
@respx.mock
async def test_unmatched_fallback_does_not_echo_person_name():
    with pytest.raises(Exception) as exc:
        await call([row(1, 0, "Рабочее время")], work_title="Иван Иванов")
    assert "Иван Иванов" not in str(exc.value)


@pytest.mark.asyncio
@respx.mock
async def test_fallback_title_is_case_sensitive():
    with pytest.raises(Exception, match="timesheet_types.*work_title"):
        await call([row(1, 0, "Рабочее время")], work_title="рабочее время")


@pytest.mark.asyncio
@respx.mock
async def test_partial_unknown_schedule_refuses_without_rule():
    rows = [
        row(1, 2, "Рабочее время", {"is_working_hours": 1}),
        row(2, 0, "Неизвестное"),
    ]
    with pytest.raises(Exception, match="timesheet_types.*work_title"):
        await call(rows)


@pytest.mark.asyncio
@respx.mock
async def test_other_unknown_title_blocks_overlapping_known_work():
    rows = [
        row(1, 2, "Обычная смена", {"is_working_hours": 1}),
        row(2, 0, "Выходной"),
        row(3, 0, "Рабочее время", begin="11:00:00"),
    ]
    data = (await call(rows, work_title="Рабочее время")).structured_content
    assert [slot["start"] for slot in data["slots"]] == [
        "2034-03-21T11:00:00", "2034-03-21T11:30:00",
    ]


@pytest.mark.asyncio
@respx.mock
async def test_other_unknown_title_blocks_selected_unknown_work():
    rows = [
        row(1, 0, "Рабочее время"),
        row(2, 0, "Выходной"),
    ]
    data = (await call(rows, work_title="Рабочее время")).structured_content
    assert data["total_slots"] == 0
    assert "завыш" in data["warning"]


@pytest.mark.asyncio
@respx.mock
async def test_blank_work_title_is_input_error_before_upstream():
    with pytest.raises(ToolInputError, match="work_title"):
        await call([], work_title="  ")
