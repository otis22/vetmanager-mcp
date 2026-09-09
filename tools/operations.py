"""Operational entity tools: Clinics, Timesheet, Properties, AnonymousClient, Messages."""

from typing import Annotated
from exceptions import ToolInputError
from datetime import datetime, timedelta

from fastmcp import FastMCP
from pydantic import Field
from filters import FILTER_FIELDS_BY_ENTITY, eq as _filter_eq, gt as _filter_gt, lt as _filter_lt
from tools.crud_helpers import crud_list, crud_get_by_id, crud_create, crud_update, crud_delete
from validators import LimitParam
from vetmanager_client import VetmanagerClient
from vm_datetime import normalize_vm_datetime

UserIdsParam = Annotated[
    list[int],
    Field(min_length=1, description="Target user IDs (at least one user ID)."),
]

RolesParam = Annotated[
    list[str],
    Field(min_length=1, description="Target role names (at least one role)."),
]


# The two boundaries of a day, as the schedule form writes them when «весь
# день» is ticked and as `editSmena` reads the flag back out of them.
_FULL_DAY_BEGIN = "00:00:00"
_FULL_DAY_END = "23:59:59"


def _shift_time_fields(
    begin_datetime: str,
    end_datetime: str,
    all_day: bool | None,
    night: bool | None,
) -> dict:
    """Time and flags of one shift, checked against each other.

    Vetmanager stores `all_day` and `night` and validates neither: a live
    probe on the stand took a row with both flags on, and a night shift that
    ended the day it started. Neither is a row the interface can produce, so
    the meaning of the flags is kept here or nowhere.

    Both arguments are already normalised — the checks compare what goes on
    the wire, not what the caller typed. An empty string means the field was
    not passed at all, which only an edit can do.
    """
    if all_day and night:
        raise ToolInputError(
            "A shift is either all_day or night, never both: ticking one flag "
            "clears the other in the schedule form."
        )

    fields: dict = {}
    if begin_datetime:
        fields["begin_datetime"] = begin_datetime
    if end_datetime:
        fields["end_datetime"] = end_datetime

    if (all_day or night) and not (begin_datetime and end_datetime):
        # Both flags describe when the shift runs. On an edit the current
        # times are unknown, and reading the row to learn them would spend a
        # request on a value the caller has to state anyway.
        raise ToolInputError(
            "Pass begin_datetime and end_datetime together with all_day or "
            "night: both flags describe the time of the shift."
        )

    if bool(begin_datetime) != bool(end_datetime):
        # One boundary alone cannot be checked: the other one lives in the
        # row, and the tool does not read it. Upstream would take the result
        # either way, so a shift whose end lands before its start can only be
        # kept out by asking for the pair.
        raise ToolInputError(
            "Change begin_datetime and end_datetime together: with one "
            "boundary alone there is nothing to check the other against."
        )

    if all_day:
        # The dates stay as given: the form sets the time on each end
        # separately, so an all-day span of several days is a row it makes.
        fields["begin_datetime"] = f"{begin_datetime[:10]} {_FULL_DAY_BEGIN}"
        fields["end_datetime"] = f"{end_datetime[:10]} {_FULL_DAY_END}"

    if night and end_datetime[:10] <= begin_datetime[:10]:
        raise ToolInputError(
            "A night shift ends on a later date than it starts: "
            f"{begin_datetime} — {end_datetime} runs inside one day."
        )

    begin = fields.get("begin_datetime", "")
    end = fields.get("end_datetime", "")
    if begin and end and end <= begin:
        # Neither schedule form saves this, and no flag is needed to make it
        # wrong. With one boundary missing there is nothing to compare.
        raise ToolInputError(
            f"A shift ends after it begins: {begin} — {end} does not."
        )

    # Turning a flag on puts out the other one, the way the form does. Turning
    # one off says nothing about the other, so it leaves it alone.
    if all_day is not None:
        fields["all_day"] = 1 if all_day else 0
        if all_day:
            fields["night"] = 0
    if night is not None:
        fields["night"] = 1 if night else 0
        if night:
            fields["all_day"] = 0
    return fields


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_clinics(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List clinic branches in the system.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
            filter/sort: Optional raw clauses. Allowed properties for both: address, city_id,
                email, end_time, guest_client_id, id, internet_address,
                logo_url, phone, start_time, status, telegram, time_zone,
                title, whatsapp.
        """
        return await crud_list(
            "/rest/api/clinics", limit=limit, offset=offset, sort=sort, filters=filter,
            allowed_filter_properties=FILTER_FIELDS_BY_ENTITY["clinics"],
        )

    @mcp.tool
    async def get_clinic_by_id(clinic_id: int) -> dict:
        """Get a clinic branch by its unique ID.

        Args:
            clinic_id: Unique numeric ID of the clinic.
        """
        return await crud_get_by_id("/rest/api/clinics", clinic_id)

    @mcp.tool
    async def get_timesheets(
        limit: LimitParam = 20,
        offset: int = 0,
        doctor_id: int = 0,
        date: str = "",
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List staff work schedule entries (timesheets).

        Args:
            limit: Max records to return.
            offset: Pagination offset.
            doctor_id: Filter by staff doctor ID (0 = no filter). Vetmanager
                timesheet entity uses `doctor_id` as FK to user.id.
            date: Filter by date in YYYY-MM-DD format (optional).
            filter/sort: Optional raw clauses. Allowed properties for both: action_id, all_day,
                begin_datetime, clinic_id, doctor_id, end_datetime, id, night,
                shedule_id, shift, title, type.
        """
        combined_filters: list = list(filter or [])
        if doctor_id:
            combined_filters.append(_filter_eq("doctor_id", doctor_id))
        if date:
            day = datetime.strptime(date, "%Y-%m-%d").date()
            next_day = day + timedelta(days=1)
            combined_filters.append(
                _filter_lt("begin_datetime", f"{next_day.isoformat()} 00:00:00")
            )
            combined_filters.append(
                _filter_gt("end_datetime", f"{day.isoformat()} 00:00:00")
            )
        return await crud_list(
            "/rest/api/timesheet", limit=limit, offset=offset,
            sort=sort,
            filters=combined_filters if combined_filters else None,
            allowed_filter_properties=FILTER_FIELDS_BY_ENTITY["timesheet"],
        )

    @mcp.tool
    async def get_timesheet_by_id(timesheet_id: int) -> dict:
        """Get a timesheet entry by its unique ID.

        Args:
            timesheet_id: Unique numeric ID of the timesheet entry.
        """
        return await crud_get_by_id("/rest/api/timesheet", timesheet_id)

    @mcp.tool
    async def get_timesheet_types(
        limit: LimitParam = 20,
        offset: int = 0,
    ) -> dict:
        """List shift types used by the work schedule.

        `type` on a timesheet entry is an id from this table, not a free
        value, and the ids differ between clinics. Read it before creating a
        shift: `is_working_hours` marks the types that count as work.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
        """
        # Case matters: `/rest/api/timesheettypes` answers 404.
        return await crud_list("/rest/api/timesheetTypes", limit=limit, offset=offset)

    @mcp.tool
    async def create_timesheet(
        doctor_id: int,
        begin_datetime: str,
        end_datetime: str,
        clinic_id: int,
        type: int,
        title: str = "",
        all_day: bool = False,
        night: bool = False,
    ) -> dict:
        """Create a new work schedule entry (timesheet) for a staff member.

        Args:
            doctor_id: ID of the staff member/doctor.
            begin_datetime: Start date/time in ISO 8601 format (YYYY-MM-DDTHH:MM:SS).
            end_datetime: End date/time in ISO 8601 format (YYYY-MM-DDTHH:MM:SS).
            clinic_id: ID of the clinic branch.
            type: Shift type id from `get_timesheet_types`. Required by
                Vetmanager: a shift without it is refused.
            title: Schedule entry title/label, up to 50 characters (optional).
            all_day: Mark the shift as lasting whole days. The times are then
                set to 00:00:00 and 23:59:59 — the dates you pass are kept, so
                a span of several whole days is allowed. Cannot be combined
                with `night`.
            night: Mark the shift as a night one. It must end on a later date
                than it starts. Cannot be combined with `all_day`.
        """
        payload: dict = {
            "doctor_id": doctor_id,
            "clinic_id": clinic_id,
            "type": type,
            # Required by the model and absent from every payload this tool
            # used to send. Real rows carry 0: shifts belong to no template.
            "shedule_id": 0,
        }
        # `False` here is the absence of a flag, not a decision to clear it:
        # upstream writes a zero into an unmentioned field by itself.
        payload.update(
            _shift_time_fields(
                normalize_vm_datetime(begin_datetime, field_name="begin_datetime"),
                normalize_vm_datetime(end_datetime, field_name="end_datetime"),
                all_day or None,
                night or None,
            )
        )
        if title:
            payload["title"] = title
        return await crud_create("/rest/api/timesheet", payload)

    @mcp.tool
    async def update_timesheet(
        timesheet_id: int,
        begin_datetime: str = "",
        end_datetime: str = "",
        doctor_id: int | None = None,
        clinic_id: int | None = None,
        type: int | None = None,
        title: str | None = None,
        all_day: bool | None = None,
        night: bool | None = None,
    ) -> dict:
        """Update an existing work schedule entry (timesheet).

        Only the fields you pass are sent. Use this to fix a shift loaded by
        mistake instead of deleting and recreating it.

        Args:
            timesheet_id: ID of the schedule entry to update.
            begin_datetime: New start date/time (optional). Times are
                changed in pairs: pass end_datetime with it.
            end_datetime: New end date/time (optional). Times are changed in
                pairs: pass begin_datetime with it.
            doctor_id: New staff member ID (optional).
            clinic_id: New clinic branch ID (optional).
            type: New shift type id from `get_timesheet_types` (optional).
            title: New title, up to 50 characters (optional).
            all_day: Turn the all-day flag on or off. Turning it on rewrites
                the times to 00:00:00 and 23:59:59, clears `night`, and
                requires both dates — the current ones are unknown here.
            night: Turn the night flag on or off, under the same rules; a
                night shift must end on a later date than it starts.
        """
        payload: dict = {}
        payload.update(
            _shift_time_fields(
                normalize_vm_datetime(begin_datetime, field_name="begin_datetime")
                if begin_datetime
                else "",
                normalize_vm_datetime(end_datetime, field_name="end_datetime")
                if end_datetime
                else "",
                all_day,
                night,
            )
        )
        # Absence, not falseness: treating 0 as "not passed" would silently
        # drop a value the caller wrote down, while the docstring promises the
        # fields it is given are the fields that are sent.
        if doctor_id is not None:
            payload["doctor_id"] = doctor_id
        if clinic_id is not None:
            payload["clinic_id"] = clinic_id
        if type is not None:
            payload["type"] = type
        # An empty title is a value: upstream limits its length, not its
        # emptiness, so this is how a label typed by mistake is removed. An
        # empty date is not — there is no such moment in time.
        if title is not None:
            payload["title"] = title
        if not payload:
            # Vetmanager answers 406 `No params` to an empty body. Refusing
            # here says which call was pointless; the upstream code does not.
            raise ToolInputError(
                "Pass at least one field to change: begin_datetime, "
                "end_datetime, doctor_id, clinic_id, type, title, all_day "
                "or night."
            )
        return await crud_update("/rest/api/timesheet", timesheet_id, payload)

    @mcp.tool
    async def delete_timesheet(timesheet_id: int) -> dict:
        """Delete a work schedule entry (timesheet).

        Removal is permanent: unlike an admission, a shift has no deleted
        status, so the row is gone. Prefer `update_timesheet` when the shift
        only needs correcting.

        Args:
            timesheet_id: ID of the schedule entry to delete.
        """
        return await crud_delete("/rest/api/timesheet", timesheet_id)

    @mcp.tool
    async def get_properties(
        limit: LimitParam = 50,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List system configuration properties of the clinic.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
            filter/sort: Optional raw clauses. Allowed properties for both: clinic_id, id,
                property_name, property_title, property_value.
        """
        return await crud_list(
            "/rest/api/properties", limit=limit, offset=offset, sort=sort, filters=filter,
            allowed_filter_properties=FILTER_FIELDS_BY_ENTITY["properties"],
        )

    @mcp.tool
    async def get_anonymous_clients(
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List anonymous (walk-in) client records in the system.

        Args:
            limit: Max records to return.
            offset: Pagination offset.
        """
        return await crud_list(
            "/rest/api/user/anonymousList", limit=limit, offset=offset, sort=sort, filters=filter,
        )

    @mcp.tool
    async def send_message_to_all(
        message: str,
        campaign: str,
    ) -> dict:
        """Send an in-app notification to all clinic users.

        WARNING: Sending is irreversible; the Vetmanager API cannot cancel or
        recall a sent message.
        """
        payload = {"message": message, "campaign": campaign}
        return await VetmanagerClient().post("/rest/api/messages/all", json=payload)

    @mcp.tool
    async def send_message_to_users(
        message: str,
        campaign: str,
        user_ids: UserIdsParam,
    ) -> dict:
        """Send an in-app notification to specific users by ID.

        WARNING: Sending is irreversible; the Vetmanager API cannot cancel or
        recall a sent message.
        """
        payload = {
            "message": message,
            "campaign": campaign,
            "user_ids": user_ids,
        }
        return await VetmanagerClient().post("/rest/api/messages/users", json=payload)

    @mcp.tool
    async def get_message_reports(
        limit: LimitParam = 20,
        offset: int = 0,
        campaign: str = "",
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List in-app notification delivery reports and campaign stats."""
        campaign_name = campaign.strip()
        if not campaign_name:
            raise ToolInputError("campaign is required")
        return await crud_list(
            "/rest/api/messages/reports", limit=limit, offset=offset,
            sort=sort, filters=filter, extra={"campaign": campaign_name},
        )

    @mcp.tool
    async def send_message_to_roles(
        message: str,
        campaign: str,
        roles: RolesParam,
    ) -> dict:
        """Send an in-app notification to all users with the specified roles.

        WARNING: Sending is irreversible; the Vetmanager API cannot cancel or
        recall a sent message.
        """
        payload = {
            "message": message,
            "campaign": campaign,
            "roles": roles,
        }
        return await VetmanagerClient().post("/rest/api/messages/roles", json=payload)
