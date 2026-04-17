from fastmcp import FastMCP

from filters import eq as _filter_eq, gte as _filter_gte, in_ as _filter_in, lt as _filter_lt
from tools.crud_helpers import crud_list, crud_get_by_id, crud_create, crud_update
from validators import LimitParam, parse_date_param

# Admission statuses that represent a real upcoming or in-progress visit.
# Used by get_client_upcoming_visits and get_daily_schedule to filter out
# cancelled/deleted/not-yet-approved records.
ACTIVE_ADMISSION_STATUSES = (
    "save",
    "directed",
    "accepted",
    "in_treatment",
    "delayed",
    "not_confirmed",
)


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_admissions(
        limit: LimitParam = 20,
        offset: int = 0,
        date: str = "",
        date_from: str = "",
        date_to: str = "",
        doctor_id: int = 0,
        pet_id: int = 0,
        client_id: int = 0,
        status: str = "",
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List clinic admissions (appointments/visits).

        For a date range use date_from/date_to (preferred). For a single day
        use either date="YYYY-MM-DD" or date_from=date_to="YYYY-MM-DD". Do not
        combine `date` with `date_from`/`date_to` — it is rejected.

        Args:
            limit: Max records to return (1–100, default 20).
            offset: Pagination offset (0–10000).
            date: Filter by a single day. Accepts YYYY-MM-DD or relative
                forms: today, yesterday, tomorrow, +Nd/-Nd, +Nw/-Nw, +Nm/-Nm.
                Back-compat alias for date_from=date_to=<date>.
            date_from: Start of admission_date range (inclusive). Same
                accepted formats as `date`.
            date_to: End of admission_date range (inclusive). Same
                accepted formats as `date`.
            doctor_id: Filter by doctor ID (internally mapped to `user_id`
                on the admission entity).
            pet_id: Filter by pet ID (internally mapped to `patient_id`).
            client_id: Filter by owner/client ID.
            status: Filter by admission status. Known enum values:
                save, directed, accepted, deleted, delayed, not_approved,
                in_treatment, not_confirmed.
            sort: Sort specification, e.g. [{"property": "admission_date",
                "direction": "ASC"}].
            filter: Additional raw filter conditions (merged with named filters).
        """
        if date and (date_from or date_to):
            raise ValueError(
                "use either `date` or `date_from`/`date_to`, not both"
            )

        effective_from = parse_date_param(date_from or date)
        effective_to = parse_date_param(date_to or date)

        combined_filters: list = list(filter or [])
        if effective_from:
            combined_filters.append(
                _filter_gte("admission_date", f"{effective_from} 00:00:00")
            )
        if effective_to:
            # Use strict `<` against next day's midnight so records with
            # fractional seconds at 23:59:59.xxx on the target day are included.
            from datetime import date as _date, timedelta
            parsed = _date.fromisoformat(effective_to)
            next_day = (parsed + timedelta(days=1)).isoformat()
            combined_filters.append(
                _filter_lt("admission_date", f"{next_day} 00:00:00")
            )
        if doctor_id:
            combined_filters.append(_filter_eq("user_id", doctor_id))
        if pet_id:
            combined_filters.append(_filter_eq("patient_id", pet_id))
        if client_id:
            combined_filters.append(_filter_eq("client_id", client_id))
        if status:
            combined_filters.append(_filter_eq("status", status))

        if sort is None and (effective_from or effective_to):
            sort = [{"property": "admission_date", "direction": "ASC"}]

        return await crud_list(
            "/rest/api/admission", limit=limit, offset=offset,
            sort=sort, filters=combined_filters if combined_filters else None,
        )

    @mcp.tool
    async def get_admission_by_id(
        admission_id: int,
    ) -> dict:
        """Get an admission (visit/appointment) by its unique ID.

        Args:
            admission_id: Unique numeric ID of the admission.
        """
        return await crud_get_by_id("/rest/api/admission", admission_id)

    @mcp.tool
    async def get_client_upcoming_visits(
        client_id: int,
        pet_id: int = 0,
        date_from: str = "today",
        days: int = 90,
        limit: LimitParam = 20,
    ) -> dict:
        """List upcoming visits (appointments) for a client or a specific pet.

        Domain synonyms: будущие визиты, предстоящие приёмы, следующий визит,
        upcoming appointments, next visit.

        Returns active admissions (excluding deleted/not_approved) sorted
        by date ascending within the window [date_from, date_from + days].

        Args:
            client_id: Required. The client whose visits to list.
            pet_id: Optional. If > 0, limit to admissions for this pet only.
            date_from: Window start (YYYY-MM-DD or relative: today, +1w,
                -7d, ...). Default: today.
            days: Window length in days from date_from (default 90).
            limit: Max records to return (1–100, default 20).
        """
        if client_id <= 0:
            raise ValueError("client_id is required")
        if days <= 0 or days > 366:
            raise ValueError("days must be between 1 and 366")

        resolved_from = parse_date_param(date_from)
        if not resolved_from:
            raise ValueError("date_from is required")

        from datetime import date as _date, timedelta as _td
        start_d = _date.fromisoformat(resolved_from)
        end_d = start_d + _td(days=days)

        filters: list = [
            _filter_eq("client_id", client_id),
            _filter_gte("admission_date", f"{start_d.isoformat()} 00:00:00"),
            _filter_lt("admission_date", f"{end_d.isoformat()} 00:00:00"),
            # API-level active status filter via IN operator
            # (verified during Stage 83 probe on devtr6).
            _filter_in("status", list(ACTIVE_ADMISSION_STATUSES)),
        ]
        if pet_id > 0:
            filters.append(_filter_eq("patient_id", pet_id))

        resp = await crud_list(
            "/rest/api/admission",
            limit=limit,
            offset=0,
            sort=[{"property": "admission_date", "direction": "ASC"}],
            filters=filters,
        )

        data = resp.get("data", {}) if isinstance(resp, dict) else {}
        if isinstance(data, list):
            rows = data
            total = len(data)
        elif isinstance(data, dict):
            rows = data.get("admission") or data.get("admissions") or []
            total = int(data.get("totalCount", len(rows)))
        else:
            rows = []
            total = 0

        return {
            "success": True,
            "data": {"admission": rows, "totalCount": total},
        }

    @mcp.tool
    async def get_daily_schedule(
        date: str = "today",
        doctor_id: int = 0,
        clinic_id: int = 0,
        limit: LimitParam = 100,
    ) -> dict:
        """List active appointments scheduled for a given day.

        Domain synonyms: расписание на день, приёмы сегодня, график на завтра,
        daily schedule, appointments today.

        Returns admissions sorted by time ascending, excluding cancelled
        (deleted/not_approved) statuses.

        Args:
            date: Target day (YYYY-MM-DD or relative: today, tomorrow, +1d,
                ...). Default: today.
            doctor_id: Optional. Filter to a specific doctor (maps to
                user_id on the admission entity).
            clinic_id: Optional. Filter to a specific clinic.
            limit: Max records to return (1–100, default 100).
        """
        resolved = parse_date_param(date)
        if not resolved:
            raise ValueError("date is required")

        from datetime import date as _date, timedelta as _td
        d = _date.fromisoformat(resolved)
        next_day = (d + _td(days=1)).isoformat()

        filters: list = [
            _filter_gte("admission_date", f"{resolved} 00:00:00"),
            _filter_lt("admission_date", f"{next_day} 00:00:00"),
            # API-level active status filter via IN operator
            # (verified during Stage 83 probe on devtr6).
            _filter_in("status", list(ACTIVE_ADMISSION_STATUSES)),
        ]
        if doctor_id > 0:
            filters.append(_filter_eq("user_id", doctor_id))
        if clinic_id > 0:
            filters.append(_filter_eq("clinic_id", clinic_id))

        resp = await crud_list(
            "/rest/api/admission",
            limit=limit,
            offset=0,
            sort=[{"property": "admission_date", "direction": "ASC"}],
            filters=filters,
        )

        data = resp.get("data", {}) if isinstance(resp, dict) else {}
        if isinstance(data, list):
            rows = data
            total = len(data)
        elif isinstance(data, dict):
            rows = data.get("admission") or data.get("admissions") or []
            total = int(data.get("totalCount", len(rows)))
        else:
            rows = []
            total = 0

        return {
            "success": True,
            "date": resolved,
            "data": {"admission": rows, "totalCount": total},
        }

    @mcp.tool
    async def create_admission(
        pet_id: int,
        client_id: int,
        doctor_id: int,
        date: str,
        reason: str = "",
        status: str = "save",
    ) -> dict:
        """Schedule a new admission (appointment) for a pet.

        External param names follow MCP conventions (pet_id / doctor_id / date);
        this tool translates them to the Vetmanager API field names
        (patient_id / user_id / admission_date) at the boundary.

        Args:
            pet_id: ID of the pet being admitted.
            client_id: ID of the pet's owner.
            doctor_id: ID of the attending veterinarian.
            date: Appointment date/time in ISO 8601 format (YYYY-MM-DDTHH:MM:SS).
            reason: Reason for the visit (optional).
            status: Admission status (default 'save'). Valid values per
                Vetmanager enum: save, directed, accepted, delayed,
                in_treatment, not_approved, not_confirmed, deleted.
        """
        payload: dict = {
            "patient_id": pet_id,
            "client_id": client_id,
            "user_id": doctor_id,
            "admission_date": date,
            "status": status,
        }
        if reason:
            payload["reason"] = reason
        return await crud_create("/rest/api/admission", payload)

    @mcp.tool
    async def update_admission(
        admission_id: int,
        date: str = "",
        doctor_id: int = 0,
        client_id: int = 0,
        pet_id: int = 0,
        reason: str = "",
        status: str = "",
        clinic_id: int = 0,
        type: str = "",
    ) -> dict:
        """Update an existing admission (appointment) record.

        External param names follow MCP conventions; payload fields are mapped
        to Vetmanager API names (user_id / admission_date / patient_id) at the
        boundary. Same pattern as create_admission (stage 86).

        Note: Vetmanager API does not allow deleting admissions via REST.

        Args:
            admission_id: ID of the admission to update.
            date: New date/time in ISO 8601 format (leave empty to keep current).
            doctor_id: New doctor ID (0 = no change).
            client_id: New client ID (0 = no change).
            pet_id: New pet ID (0 = no change).
            reason: Updated reason for the visit.
            status: New status (one of: save, directed, accepted, delayed,
                in_treatment, not_approved, not_confirmed, deleted).
            clinic_id: New clinic ID (0 = no change).
            type: Admission type (leave empty to keep current).
        """
        payload: dict = {}
        if date:
            payload["admission_date"] = date
        if doctor_id:
            payload["user_id"] = doctor_id
        if client_id:
            payload["client_id"] = client_id
        if pet_id:
            payload["patient_id"] = pet_id
        if reason:
            payload["reason"] = reason
        if status:
            payload["status"] = status
        if clinic_id:
            payload["clinic_id"] = clinic_id
        if type:
            payload["type"] = type
        return await crud_update("/rest/api/admission", admission_id, payload)
