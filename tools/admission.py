from fastmcp import FastMCP

from tools.crud_helpers import crud_list, crud_get_by_id, crud_create, crud_update
from validators import LimitParam, parse_date_param


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

        combined_filters: list[dict] = list(filter or [])
        if effective_from:
            combined_filters.append(
                {
                    "property": "admission_date",
                    "value": f"{effective_from} 00:00:00",
                    "operator": ">=",
                }
            )
        if effective_to:
            # Use strict `<` against next day's midnight so records with
            # fractional seconds at 23:59:59.xxx on the target day are included.
            from datetime import date as _date, timedelta
            parsed = _date.fromisoformat(effective_to)
            next_day = (parsed + timedelta(days=1)).isoformat()
            combined_filters.append(
                {
                    "property": "admission_date",
                    "value": f"{next_day} 00:00:00",
                    "operator": "<",
                }
            )
        if doctor_id:
            combined_filters.append(
                {"property": "user_id", "value": doctor_id, "operator": "="}
            )
        if pet_id:
            combined_filters.append(
                {"property": "patient_id", "value": pet_id, "operator": "="}
            )
        if client_id:
            combined_filters.append(
                {"property": "client_id", "value": client_id, "operator": "="}
            )
        if status:
            combined_filters.append(
                {"property": "status", "value": status, "operator": "="}
            )

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
    async def create_admission(
        pet_id: int,
        client_id: int,
        doctor_id: int,
        date: str,
        reason: str = "",
        status: str = "assigned",
    ) -> dict:
        """Schedule a new admission (appointment) for a pet.

        Args:
            pet_id: ID of the pet being admitted.
            client_id: ID of the pet's owner.
            doctor_id: ID of the attending veterinarian.
            date: Appointment date/time in ISO 8601 format (YYYY-MM-DDTHH:MM:SS).
            reason: Reason for the visit (optional).
            status: Admission status: 'assigned' (default), 'booked', 'accepted'.
        """
        payload: dict = {
            "pet_id": pet_id,
            "client_id": client_id,
            "doctor_id": doctor_id,
            "date": date,
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

        Note: Vetmanager API does not allow deleting admissions via REST.

        Args:
            admission_id: ID of the admission to update.
            date: New date/time in ISO 8601 format (leave empty to keep current).
            doctor_id: New doctor ID (0 = no change).
            client_id: New client ID (0 = no change).
            pet_id: New pet ID (0 = no change).
            reason: Updated reason for the visit.
            status: New status value (e.g. 'assigned', 'accepted', 'booked', 'canceled').
            clinic_id: New clinic ID (0 = no change).
            type: Admission type (leave empty to keep current).
        """
        payload: dict = {}
        if date:
            payload["date"] = date
        if doctor_id:
            payload["doctor_id"] = doctor_id
        if client_id:
            payload["client_id"] = client_id
        if pet_id:
            payload["pet_id"] = pet_id
        if reason:
            payload["reason"] = reason
        if status:
            payload["status"] = status
        if clinic_id:
            payload["clinic_id"] = clinic_id
        if type:
            payload["type"] = type
        return await crud_update("/rest/api/admission", admission_id, payload)
