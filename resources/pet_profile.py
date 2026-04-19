"""Pet profile aggregator (stage 103c).

Composes the pet's full record with last 5 medical card entries and all
vaccination records into a single response. Owns entity-specific field
mapping (`patient_id` filter for MedicalCards — NOT `pet_id`), response
key fallback (`medicalCards` vs `medicalcards` from different upstream
versions), and the `last_vaccination_date` / `next_vaccination_date`
derivation from the latest vaccination record.
"""

from __future__ import annotations

from filters import build_list_query_params, eq as _filter_eq
from resources._aggregation import gather_sections
from vetmanager_client import VetmanagerClient


async def fetch(pet_id: int) -> dict:
    """Build a comprehensive pet profile.

    Aggregates:
    - Full pet record (`/rest/api/pet/{id}`).
    - Last 5 medical card entries (filter by `patient_id`, sort id DESC).
    - All vaccination records (`/rest/api/MedicalCards/Vaccinations`).

    Derives `last_vaccination_date` (date part of the latest vaccination)
    and `next_vaccination_date` (`date_nexttime` of that same record) as
    explicit top-level fields so LLMs don't need to scan the vaccinations
    list to answer "when is the next vaccination due".
    """
    vc = VetmanagerClient()
    medical_cards_params = build_list_query_params(
        limit=5,
        offset=0,
        sort=[{"property": "id", "direction": "DESC"}],
        filters=[_filter_eq("patient_id", str(pet_id))],
    )

    payloads, section_errors = await gather_sections(
        tool_name="get_pet_profile",
        context={"pet_id": pet_id},
        sections=[
            ("pet", vc.get(f"/rest/api/pet/{pet_id}"),
             {"data": {"pet": {}}}),
            ("medical_cards", vc.get(
                "/rest/api/MedicalCards",
                params=medical_cards_params,
            ), {"data": {"medicalCards": []}}),
            ("vaccinations", vc.get(
                "/rest/api/MedicalCards/Vaccinations",
                params={"pet_id": pet_id, "limit": 100},
            ), {"data": {"medicalcards": []}}),
        ],
    )
    pet_payload, mc_payload, vacc_payload = payloads

    pet_data = pet_payload.get("data", {}).get("pet", {})
    mc_data = mc_payload.get("data", {})
    medical_cards = (
        mc_data.get("medicalCards")
        or mc_data.get("medicalcards")
        or []
    ) if isinstance(mc_data, dict) else []

    vaccinations_raw = vacc_payload.get("data", {}).get("medicalcards", [])
    vaccinations = [
        {
            "id": r.get("id"),
            "name": r.get("name"),
            "date": r.get("date"),
            "date_nexttime": r.get("date_nexttime"),
            "vaccine_id": r.get("vaccine_id"),
            "medcard_id": r.get("medcard_id"),
        }
        for r in vaccinations_raw
    ]

    sorted_vacc = sorted(
        vaccinations,
        key=lambda r: r.get("date") or "",
        reverse=True,
    )
    last_vaccination_date: str | None = None
    next_vaccination_date: str | None = None
    if sorted_vacc:
        last_vacc = sorted_vacc[0]
        last_vaccination_date = (last_vacc.get("date") or "").split(" ")[0] or None
        next_raw = last_vacc.get("date_nexttime") or ""
        next_vaccination_date = next_raw.strip() or None

    result: dict = {
        "pet": pet_data,
        "last_medical_cards": medical_cards,
        "vaccinations": vaccinations,
        "last_vaccination_date": last_vaccination_date,
        "next_vaccination_date": next_vaccination_date,
    }
    if section_errors:
        result["partial"] = True
        result["section_errors"] = section_errors
    return result
