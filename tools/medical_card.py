import json
from datetime import date, timedelta

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from filters import (
    build_list_query_params,
    eq as _filter_eq,
    gte as _filter_gte,
    in_ as _filter_in,
    lt as _filter_lt,
)
from exceptions import ToolInputError, reportable_error
from tools.crud_helpers import crud_get_by_id, crud_create, crud_update, unwrap_single_record
from validators import DiagnosisIdParam, DiagnosisTypeParam, LimitParam, parse_date_param
from vetmanager_client import VetmanagerClient, VetmanagerError

# The correct Vetmanager REST endpoint for medical cards is /rest/api/MedicalCards
# (capital M and C, plural). The response key is "medicalCards" (camelCase).
# The old lowercase /rest/api/medicalcard returns 404 on all known installations.
_MC_ENDPOINT = "/rest/api/MedicalCards"
_MC_KEY = "medicalCards"
_CLIENT_PETS_PAGE_SIZE = 100
_CLIENT_PETS_MAX_PAGES = 20
_DEFAULT_DATE_SORT = [
    {"property": "date_create", "direction": "ASC"},
    {"property": "id", "direction": "ASC"},
]

_DIAGNOSES_TYPE_ERROR = "Cannot assign int to property Entity\\MedicalCard\\Diagnoses::$diagnoses of type array"

# The card's diagnosis field holds references, not text: a JSON array string of
# {"id": <diagnosis id>, "type": <diagnosis type>}. Ids come from get_diagnoses;
# types come from the clinic combo manual "diagnos_types" — verified on devtr6
# 2026-09-01: 1 final (the catalogue default), 2 preliminary, 3 differential,
# 4 probable. A value that decodes to a bare integer answers HTTP 500 upstream
# and is not saved; free text is accepted and stored verbatim, which silently
# turns the reference into a string that points at nothing.
_DIAGNOSIS_TYPES = (1, 2, 3, 4)
_DEFAULT_DIAGNOSIS_TYPE = 1
_DIAGNOSIS_CATALOGUE_HINT = (
    "Diagnosis ids come from get_diagnoses; free text belongs in 'diagnosis_text'."
)


def _diagnos_field(diagnosis_ids: list[int], diagnosis_type: int) -> str:
    """Build the `diagnos` value, or refuse before anything reaches the API."""
    if type(diagnosis_type) is not int or diagnosis_type not in _DIAGNOSIS_TYPES:
        raise ToolInputError(
            f"'diagnosis_type' must be one of {', '.join(str(t) for t in _DIAGNOSIS_TYPES)}"
            f" (1 final, 2 preliminary, 3 differential, 4 probable), got {diagnosis_type}."
        )
    if not isinstance(diagnosis_ids, list):
        raise ToolInputError(
            f"'diagnosis_ids' takes a list of diagnosis ids, got {type(diagnosis_ids).__name__}."
            f" {_DIAGNOSIS_CATALOGUE_HINT}"
        )
    if not diagnosis_ids:
        raise ToolInputError(
            "'diagnosis_ids' must name at least one diagnosis; an empty list is not a way"
            " to clear the diagnosis, and clearing it is not supported by this tool."
            f" {_DIAGNOSIS_CATALOGUE_HINT}"
        )
    for value in diagnosis_ids:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ToolInputError(
                f"'diagnosis_ids' takes positive diagnosis ids, got {value!r}."
                f" {_DIAGNOSIS_CATALOGUE_HINT}"
            )
    return json.dumps(
        [{"id": value, "type": diagnosis_type} for value in diagnosis_ids],
        separators=(",", ":"),
    )


def _refuse_legacy_diagnosis(diagnosis: str) -> None:
    """The removed free-text parameter: refuse loudly instead of writing junk."""
    if diagnosis:
        raise ToolInputError(
            "'diagnosis' no longer reaches the card. The field it used to fill holds"
            " references to the clinic diagnosis catalogue, so free text written there"
            " pointed at nothing and a bare number crashed the save."
            " Use 'diagnosis_ids' to record a diagnosis, or 'diagnosis_text' for a note."
        )


def _diagnosis_fields(
    diagnosis: str, diagnosis_ids: list[int] | None,
    diagnosis_type: int, diagnosis_text: str, *, on_create: bool = False,
) -> dict:
    """The diagnosis part of an outgoing payload — or a refusal, or nothing.

    Called before anything else touches the network, so a bad argument never
    costs an upstream request and never hides behind a read error.
    """
    _refuse_legacy_diagnosis(diagnosis)
    if diagnosis_text and on_create:
        # Verified on devtr6 2026-09-01: the create endpoint answers 201 and
        # drops this field, while update stores it. Refusing beats writing a
        # note the clinic will never see.
        raise ToolInputError(
            "'diagnosis_text' is not saved when the card is created: Vetmanager"
            " accepts the request and drops the field. Create the card first,"
            " then set the note with update_medical_card."
        )
    fields: dict = {}
    if diagnosis_ids is not None:
        fields["diagnos"] = _diagnos_field(diagnosis_ids, diagnosis_type)
    if diagnosis_text:
        fields["diagnos_text"] = diagnosis_text
    return fields


def _medical_card_update_error(exc: VetmanagerError) -> ToolError | None:
    """Translate the confirmed upstream Diagnoses type defect, and nothing else."""
    if exc.status_code == 500 and _DIAGNOSES_TYPE_ERROR in str(exc):
        return reportable_error(
            "Vetmanager did not update this medical card: its current diagnosis triggers "
            "a known upstream compatibility error. The record was not saved; do not clear "
            "the diagnosis to retry. Contact Vetmanager support or retry after their fix."
        )
    return None


def _next_day_start(value: str) -> str:
    return (date.fromisoformat(value) + timedelta(days=1)).isoformat() + " 00:00:00"


def _day_start(value: str) -> str:
    return f"{value} 00:00:00"


def _extract_medical_cards(data: dict) -> list[dict]:
    return (
        data.get(_MC_KEY)
        or data.get("medicalcards")
        or data.get("medicalcard")
        or []
    )


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_medical_cards(
        pet_id: int,
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List medical card records for a specific pet.

        Args:
            pet_id: ID of the pet whose records to retrieve.
            limit: Max records to return (1–100, default 20).
            offset: Pagination offset (0–10000).
        """
        vc = VetmanagerClient()
        # patient_id filter is required — pet_id param alone is ignored by the API
        extra_filters: list = []
        if filter:
            extra_filters = filter if isinstance(filter, list) else []
        combined_filters = [
            _filter_eq("patient_id", str(pet_id)),
            *extra_filters,
        ]
        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort,
            filters=combined_filters,
        )
        result = await vc.get(_MC_ENDPOINT, params=params)
        return result

    @mcp.tool
    async def get_medical_cards_by_date(
        date: str = "",
        date_from: str = "",
        date_to: str = "",
        clinic_id: int | None = None,
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
    ) -> dict:
        """List medical card records by clinic-local date range.

        Use this for daily medical-card control across all branches by default.
        Pass clinic_id only when the user explicitly asks for one branch; it
        narrows results and can exclude relevant medical cards or analyses from
        other branches.

        Args:
            date: Single clinic-local day (YYYY-MM-DD or relative date).
            date_from: Start clinic-local day for range mode.
            date_to: End clinic-local day for range mode.
            clinic_id: Optional branch filter. Omit for all branches.
            limit: Max records to return (1-100, default 20).
            offset: Pagination offset (0-10000).
            sort: Optional Vetmanager sort list. Defaults to date_create ASC, id ASC.
        """
        if date and (date_from or date_to):
            raise ToolInputError("use either `date` or `date_from`/`date_to`, not both")
        if bool(date_from) != bool(date_to):
            raise ToolInputError("date_from and date_to must be provided together")
        if not date and not (date_from and date_to):
            raise ToolInputError("date or date_from/date_to is required")

        resolved_from = parse_date_param(date or date_from)
        resolved_to = parse_date_param(date or date_to)
        if resolved_from > resolved_to:
            raise ToolInputError("date_from must be on or before date_to")

        filters = [
            _filter_gte("date_create", _day_start(resolved_from)),
            _filter_lt("date_create", _next_day_start(resolved_to)),
        ]
        clinic_filter_applied = clinic_id is not None and clinic_id > 0
        if clinic_filter_applied:
            filters.append(_filter_eq("clinic_id", str(clinic_id)))

        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort or _DEFAULT_DATE_SORT,
            filters=filters,
        )
        result = await VetmanagerClient().get(_MC_ENDPOINT, params=params)
        data = result.get("data", {})
        cards = _extract_medical_cards(data) if isinstance(data, dict) else []
        raw_total = data.get("totalCount") if isinstance(data, dict) else None
        total_known = raw_total is not None
        total = int(raw_total) if total_known else None
        count = len(cards)
        truncated = (offset + count) < total if total_known else None

        return {
            "success": result.get("success", True),
            "date_from": resolved_from,
            "date_to": resolved_to,
            "clinic_filter_applied": clinic_filter_applied,
            "clinic_id": clinic_id if clinic_filter_applied else None,
            "limit": limit,
            "offset": offset,
            "total": total,
            "total_known": total_known,
            "medical_cards_count": count,
            "truncated": truncated,
            "owner_context_available": False,
            "medical_cards": cards,
        }

    @mcp.tool
    async def get_medical_cards_by_client_id(
        client_id: int,
        limit: LimitParam = 20,
        offset: int = 0,
        sort: list[dict] | None = None,
    ) -> dict:
        """List all medical card records for all pets belonging to a client.

        Use this tool when the user asks to see medical cards / history for a
        client identified by their client ID (not a pet ID).  The tool fetches
        all pets of the client first, then returns their medical cards in a
        single aggregated response.

        Args:
            client_id: Unique numeric ID of the client (owner).
            limit: Max records per pet to return (1–100, default 20).
            offset: Pagination offset (0–10000).
        """
        vc = VetmanagerClient()

        # Step 1: get all pets of the client.
        # Pet entity FK to client is `owner_id` (migrated stage 77.4;
        # legacy `client_id` filter returns empty silently).
        pets: list[dict] = []
        pets_total = 0
        pets_truncated = False
        for page_index in range(_CLIENT_PETS_MAX_PAGES):
            pet_params = build_list_query_params(
                limit=_CLIENT_PETS_PAGE_SIZE,
                offset=page_index * _CLIENT_PETS_PAGE_SIZE,
                filters=[_filter_eq("owner_id", str(client_id))],
            )
            pets_resp = await vc.get("/rest/api/pet", params=pet_params)
            pets_data = pets_resp.get("data", {})
            page_pets = pets_data.get("pet", []) if isinstance(pets_data, dict) else []
            page_total = (
                pets_data.get("totalCount", len(page_pets))
                if isinstance(pets_data, dict)
                else len(page_pets)
            )
            pets_total = max(pets_total, int(page_total or 0))
            pets.extend(page_pets)
            if not page_pets:
                if len(pets) < pets_total:
                    pets_truncated = True
                break
            if len(pets) >= pets_total:
                break
        else:
            pets_truncated = True

        if not pets:
            return {
                "success": True,
                "client_id": client_id,
                "pets_count": 0,
                "pets_total": pets_total,
                "pets_truncated": pets_truncated,
                "medical_cards": [],
                "message": "No pets found for this client.",
            }

        # Step 2: fetch medical cards for ALL pets in a single IN-batched call.
        pet_ids = [pet.get("id") for pet in pets if pet.get("id")]
        pet_by_id = {pet.get("id"): pet for pet in pets if pet.get("id")}

        if not pet_ids:
            # Pets returned without usable ids — treat as no medical cards.
            return {
                "success": True,
                "client_id": client_id,
                "pets_count": len(pets),
                "pets_total": pets_total,
                "pets_truncated": pets_truncated,
                "medical_cards_count": 0,
                "medical_cards": [],
            }

        params = build_list_query_params(
            limit=limit,
            offset=offset,
            sort=sort,
            filters=[_filter_in("patient_id", pet_ids)],
        )
        cards_resp = await vc.get(_MC_ENDPOINT, params=params)
        cards_data = cards_resp.get("data", {})
        if isinstance(cards_data, dict):
            all_cards = (
                cards_data.get(_MC_KEY)
                or cards_data.get("medicalcards")
                or []
            )
        else:
            all_cards = []
        for card in all_cards:
            pid = card.get("patient_id")
            # VM API can return patient_id as int or as digit-string
            # depending on endpoint; normalize for dict lookup.
            int_pid = int(pid) if isinstance(pid, str) and pid.isdigit() else pid
            pet = pet_by_id.get(pid) or pet_by_id.get(int_pid)
            if pet:
                card["_pet_alias"] = pet.get("alias") or pet.get("name") or str(pid)
                card["_pet_id"] = pid

        return {
            "success": True,
            "client_id": client_id,
            "pets_count": len(pets),
            "pets_total": pets_total,
            "pets_truncated": pets_truncated,
            "medical_cards_count": len(all_cards),
            "medical_cards": all_cards,
        }

    @mcp.tool
    async def get_medical_card_by_id(
        card_id: int,
    ) -> dict:
        """Get a medical card record by its unique ID.

        Args:
            card_id: Unique numeric ID of the medical card record.
        """
        return await crud_get_by_id(_MC_ENDPOINT, card_id)

    @mcp.tool
    async def create_medical_card(
        patient_id: int,
        doctor_id: int,
        date_create: str,
        description: str = "",
        diagnosis: str = "",
        diagnosis_ids: list[DiagnosisIdParam] | None = None,
        diagnosis_type: DiagnosisTypeParam = _DEFAULT_DIAGNOSIS_TYPE,
        diagnosis_text: str = "",
        treatment: str = "",
        recomendation: str = "",
        clinic_id: int = 0,
        admission_type: str = "",
        meet_result_id: int = 0,
        weight: float = 0.0,
        temperature: float = 0.0,
    ) -> dict:
        """Add a new medical card record for a pet.

        Use patient_id (pet ID) to identify the animal.  All other fields are
        optional but should be filled in when provided by the user.

        A diagnosis is a reference, not a sentence: pass `diagnosis_ids` with
        ids from `get_diagnoses`. Anything the catalogue does not cover goes in
        `diagnosis_text`. The tool checks the shape of the ids, not whether the
        clinic actually has them — an unknown id is stored as written.

        Args:
            patient_id: ID of the pet (patient).  Also accepted as pet_id.
            doctor_id: ID of the veterinarian creating the record.
            date_create: Record date in YYYY-MM-DD or YYYY-MM-DD HH:MM:SS format.
            description: Clinical description / anamnesis (optional).
            diagnosis: Removed. A non-empty value is refused and names what to
                use instead; an empty one is ignored.
            diagnosis_ids: Diagnosis ids from get_diagnoses. Omit to leave the
                diagnosis alone; an empty list is refused, not treated as
                "clear it".
            diagnosis_type: How certain the diagnosis is, from the clinic
                `diagnos_types` catalogue: 1 final (default), 2 preliminary,
                3 differential, 4 probable.
            diagnosis_text: Not saved on create — Vetmanager answers 201 and
                drops the field. Set the note with update_medical_card after
                the card exists.
            treatment: Prescribed treatment (optional).
            recomendation: Recommendations for the owner (optional).
            clinic_id: ID of the clinic branch (optional, 0 = default).
            admission_type: Type of admission, e.g. "Взятие анализа",
                            "Первичный прием", "Плановый осмотр" (optional).
            meet_result_id: ID of the visit result from the combo manual (optional, 0 = none).
            weight: Animal weight in kg at the time of visit (optional, 0 = not recorded).
            temperature: Animal body temperature in °C (optional, 0 = not recorded).
        """
        diagnosis_fields = _diagnosis_fields(
            diagnosis, diagnosis_ids, diagnosis_type, diagnosis_text, on_create=True,
        )
        payload: dict = {
            "patient_id": patient_id,
            "doctor_id": doctor_id,
            "date_create": date_create,
        }
        if description:
            payload["description"] = description
        payload.update(diagnosis_fields)
        if treatment:
            payload["treatment"] = treatment
        if recomendation:
            payload["recomendation"] = recomendation
        if clinic_id:
            payload["clinic_id"] = clinic_id
        if admission_type:
            payload["admission_type"] = admission_type
        if meet_result_id:
            payload["meet_result_id"] = meet_result_id
        if weight:
            payload["weight"] = weight
        if temperature:
            payload["temperature"] = temperature
        return await crud_create(_MC_ENDPOINT, payload)

    @mcp.tool
    async def update_medical_card(
        card_id: int,
        description: str = "",
        diagnosis: str = "",
        diagnosis_ids: list[DiagnosisIdParam] | None = None,
        diagnosis_type: DiagnosisTypeParam = _DEFAULT_DIAGNOSIS_TYPE,
        diagnosis_text: str = "",
        treatment: str = "",
        recomendation: str = "",
        weight: float = 0.0,
        temperature: float = 0.0,
    ) -> dict:
        """Update an existing medical card record.

        Editing a card requires the patient, doctor and clinic it already
        belongs to: Vetmanager refuses a body without them and answers
        `400 Patient does not exist` even when the patient exists and reads
        fine. This tool reads the stored card and sends those three back
        unchanged, so pass only the fields you want to change — there is no
        need to look up the pet first.

        If the stored card has no patient, doctor or clinic, the update is not
        sent and the error names what is missing; fix the card in Vetmanager
        before retrying.

        Do not use `date_edit` to verify this update: Vetmanager may leave that
        field unchanged even after a successful write. Read the changed field
        back instead.

        A diagnosis is a reference, not a sentence: pass `diagnosis_ids` with
        ids from `get_diagnoses`. Anything the catalogue does not cover goes in
        `diagnosis_text`. The tool checks the shape of the ids, not whether the
        clinic actually has them — an unknown id is stored as written.

        Args:
            card_id: ID of the medical card record to update.
            description: Updated clinical description/anamnesis.
            diagnosis: Removed. A non-empty value is refused and names what to
                use instead; an empty one is ignored.
            diagnosis_ids: Diagnosis ids from get_diagnoses; they replace the
                ones on the card. Omit to leave the diagnosis alone; an empty
                list is refused, not treated as "clear it".
            diagnosis_type: How certain the diagnosis is, from the clinic
                `diagnos_types` catalogue: 1 final (default), 2 preliminary,
                3 differential, 4 probable.
            diagnosis_text: Free-text note about the diagnosis. Stored beside
                the references, never instead of them.
            treatment: Updated treatment notes.
            recomendation: Updated recommendations for the owner.
            weight: Updated animal weight in kg (0 = no change).
            temperature: Updated body temperature in °C (0 = no change).
        """
        diagnosis_fields = _diagnosis_fields(
            diagnosis, diagnosis_ids, diagnosis_type, diagnosis_text,
        )
        current_response = await crud_get_by_id(_MC_ENDPOINT, card_id)
        current = unwrap_single_record(current_response, "medicalCards")
        if current is None:
            raise reportable_error("Medical card read returned no record; update was not sent.")
        required_context = ("patient_id", "doctor_id", "clinic_id")
        missing_context = [field for field in required_context if not current.get(field)]
        if missing_context:
            raise reportable_error(
                "Medical card lacks required update context: "
                + ", ".join(missing_context)
                + ". Vetmanager requires patient, doctor and clinic on every card"
                " edit; set them on the card in Vetmanager, then retry."
            )
        payload: dict = {field: current[field] for field in required_context}
        if description:
            payload["description"] = description
        payload.update(diagnosis_fields)
        if treatment:
            payload["treatment"] = treatment
        if recomendation:
            payload["recomendation"] = recomendation
        if weight:
            payload["weight"] = weight
        if temperature:
            payload["temperature"] = temperature
        try:
            return await crud_update(_MC_ENDPOINT, card_id, payload)
        except VetmanagerError as exc:
            mapped_error = _medical_card_update_error(exc)
            if mapped_error is not None:
                raise mapped_error from None
            raise

    @mcp.tool
    async def get_vaccinations(
        pet_id: int,
        limit: LimitParam = 50,
    ) -> dict:
        """Get vaccination records for a pet.

        Returns up to `limit` vaccinations plus truncation metadata. The
        Vetmanager endpoint uses a top-level `pet_id` parameter.

        Args:
            pet_id: Unique numeric ID of the pet.
            limit: Max number of records to return (1–100, default 50).
        """
        vc = VetmanagerClient()
        params: dict = {"pet_id": pet_id, "limit": limit}
        result = await vc.get("/rest/api/MedicalCards/Vaccinations", params=params)
        data = result.get("data", {})
        records = data.get("medicalcards", []) if isinstance(data, dict) else []
        total_count = data.get("totalCount") if isinstance(data, dict) else None
        returned_records = records[:limit]
        returned_count = len(returned_records)
        try:
            total_count_int = int(total_count) if total_count is not None else None
        except (TypeError, ValueError):
            total_count_int = None
        if total_count_int is None:
            truncated = len(records) > returned_count or len(records) >= limit
        else:
            truncated = total_count_int > returned_count
        return {
            "pet_id": pet_id,
            "total": returned_count,
            "returnedCount": returned_count,
            "totalCount": total_count,
            "truncated": truncated,
            "vaccinations": [
                {
                    "id": r.get("id"),
                    "name": r.get("name"),
                    "date": r.get("date"),
                    "date_nexttime": r.get("date_nexttime"),
                    "vaccine_id": r.get("vaccine_id"),
                    "medcard_id": r.get("medcard_id"),
                    "doza_value": r.get("doza_value"),
                    "next_admission_id": r.get("next_admission_id"),
                    "pet_age_at_time_vaccination": r.get("pet_age_at_time_vaccination"),
                }
                for r in returned_records
            ],
        }
