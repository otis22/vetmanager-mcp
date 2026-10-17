import asyncio
import base64
import binascii
import json
import re
from datetime import date

from fastmcp import FastMCP

from depersonalization import build_addressed_placeholder
from exceptions import ToolInputError
from filters import FILTER_FIELDS_BY_ENTITY, build_list_query_params, eq as _filter_eq, in_ as _filter_in, like as _filter_like
from resources.pet_profile import fetch as _fetch_pet_profile
from service_metrics import instrument_call as _instrument_call
from tools._inactive_helpers import (
    fetch_inactive_clients_page,
    find_pets_for_clients_last_visit,
)
from tools.crud_helpers import crud_list, crud_get_by_id, crud_create, crud_update, crud_delete
from validators import LimitParam, PositiveReferenceIdParam
from vetmanager_client import VetmanagerClient

# How far `get_inactive_pets` is allowed to walk the lapsed-client window.
# Module level so a test can shrink the walk instead of mocking two thousand
# clients to see what the tool says when it runs out of budget.
CLIENT_PAGE_SIZE = 100
MAX_CLIENT_PAGES = 20  # safety cap: 20 * 100 = 2000 clients scanned


def _owner_summary(client: object) -> dict:
    """Project only the owner fields required to disambiguate a pet candidate."""
    if not isinstance(client, dict):
        return {"name": None, "phone": None}
    name = " ".join(
        str(client.get(field) or "").strip()
        for field in ("last_name", "first_name", "middle_name")
    ).strip()
    return {
        "name": name or None,
        "phone": client.get("cell_phone") or client.get("home_phone") or None,
    }


def _positive_owner_id(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        owner_id = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return owner_id if owner_id > 0 else None


def _reference_title(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    title = value.get("title")
    return str(title) if title else None


async def _fetch_owner_summary(vc: VetmanagerClient, owner_id: int) -> tuple[int, dict]:
    payload = await vc.get(f"/rest/api/client/{owner_id}")
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    client = data.get("client") if isinstance(data, dict) else None
    if isinstance(client, list):
        client = client[0] if client else None
    return owner_id, _owner_summary(client)


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def get_pets(
        limit: LimitParam = 20,
        offset: int = 0,
        owner_id: int = 0,
        alias: str = "",
        sort: list[dict] | None = None,
        filter: list[dict] | None = None,
    ) -> dict:
        """List pets in the clinic, optionally filtered by owner and/or nickname.

        To find a specific pet by its nickname (кличка / alias): first resolve
        the owner via `get_clients(name=...)` to obtain the client id, then
        call `get_pets(owner_id=..., alias=...)`. Searching by alias alone is
        not supported — pet nicknames are not unique per clinic, so standalone
        alias search would return a mix of unrelated patients.

        Args:
            limit: Max records to return (1–100, default 20).
            offset: Pagination offset (0–10000).
            owner_id: Filter pets by owner's client ID (0 = no filter).
                MCP maps this to the pet owner's foreign key in Vetmanager.
            alias: Filter pets by nickname (partial LIKE match). MUST be
                combined with owner_id — standalone alias search is rejected
                to prevent wrong-patient results.
            sort: Optional sort spec (forwarded to API).
            filter/sort: Optional raw clauses. Allowed properties for both: alias, birthday,
                breed_id, chip_number, color_id, date_register, deathdate,
                deathnote, edit_date, id, lab_number, note, old_id, owner_id,
                picture, sex, status, type_id, weight.
        """
        if alias and not owner_id:
            raise ToolInputError(
                "alias filter requires owner_id — pet nicknames are not "
                "unique per clinic. Resolve the owner first via "
                "get_clients(name=...), then pass owner_id and alias together."
            )

        combined_filters: list = list(filter or [])
        if owner_id:
            combined_filters.append(_filter_eq("owner_id", owner_id))
        if alias:
            combined_filters.append(_filter_like("alias", alias))
        return await crud_list(
            "/rest/api/pet",
            limit=limit,
            offset=offset,
            sort=sort,
            filters=combined_filters if combined_filters else None,
            allowed_filter_properties=FILTER_FIELDS_BY_ENTITY["pet"],
        )

    @mcp.tool
    async def find_pets_by_alias(
        alias: str,
        limit: LimitParam = 20,
        offset: int = 0,
    ) -> dict:
        """Find candidate patients by nickname with owner context for disambiguation.

        Domain synonyms: найти питомца, найти пациента, поиск по кличке,
        кличка животного, find pet by name, patient lookup.

        Pet nicknames are not unique. Each candidate includes owner_id and
        projected owner name/phone, plus human-readable pet type, breed,
        birthday, and status. Owner, type, and breed are taken from the
        embedded list response; the client endpoint is a compatibility fallback
        only when a particular upstream response omits its embedded owner.
        Never choose the first candidate when several remain plausible: ask a
        clarifying question using the available distinguishing facts. In a
        depersonalized runtime owner name and phone are masked by the global
        privacy wrapper; use the non-PII pet facts and ask for clarification
        rather than guessing.
        """
        if not alias.strip():
            raise ToolInputError("alias is required")
        payload = await crud_list(
            "/rest/api/pet",
            limit=limit,
            offset=offset,
            filters=[_filter_like("alias", alias)],
        )
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        rows = data.get("pet", []) if isinstance(data, dict) else []
        total = int(data.get("totalCount", len(rows)) or 0) if isinstance(data, dict) else 0
        pets = [pet for pet in rows if isinstance(pet, dict)]
        fallback_owner_ids = list(dict.fromkeys(
            owner_id for pet in pets
            if not isinstance(pet.get("owner"), dict)
            and (owner_id := _positive_owner_id(pet.get("owner_id"))) is not None
        ))
        fallback_owners: dict[int, dict] = {}
        if fallback_owner_ids:
            vc = VetmanagerClient()
            fallback_owners = dict(await asyncio.gather(*(
                _fetch_owner_summary(vc, owner_id) for owner_id in fallback_owner_ids
            )))
        candidates = [
            {
                **{
                    key: pet.get(key)
                    for key in ("id", "alias", "owner_id", "type_id", "breed_id", "birthday", "status")
                },
                "type": _reference_title(pet.get("type")),
                "breed": _reference_title(pet.get("breed")),
                "owner": _owner_summary(pet.get("owner")) if isinstance(pet.get("owner"), dict) else fallback_owners.get(
                    _positive_owner_id(pet.get("owner_id")),
                    {"name": None, "phone": None},
                ),
            }
            for pet in pets
        ]
        return {
            "success": True,
            "data": {"pets": candidates, "totalCount": total},
            "limit": limit,
            "offset": offset,
            "has_more": offset + len(candidates) < total,
        }

    @mcp.tool
    async def get_pet_by_id(
        pet_id: int,
    ) -> dict:
        """Get a pet by its unique ID.

        Args:
            pet_id: Unique numeric ID of the pet.
        """
        return await crud_get_by_id("/rest/api/pet", pet_id)

    @mcp.tool
    async def create_pet(
        alias: str,
        owner_id: int,
        type_id: PositiveReferenceIdParam,
        breed_id: PositiveReferenceIdParam,
        birthday: str = "",
        note: str = "",
    ) -> dict:
        """Register a new pet for a client.

        Args:
            alias: Pet's name/alias.
            owner_id: ID of the owning client. MCP maps this to the pet owner's
                foreign key in Vetmanager.
            type_id: Animal type (species) ID.
            breed_id: Breed ID for that animal type.
            birthday: Date of birth in YYYY-MM-DD format (optional).
            note: Additional notes about the pet.
        """
        payload: dict = {
            "alias": alias,
            "owner_id": owner_id,
            "type_id": type_id,
            "breed_id": breed_id,
        }
        if birthday:
            payload["birthday"] = birthday
        if note:
            payload["note"] = note
        return await crud_create("/rest/api/pet", payload)

    @mcp.tool
    async def update_pet(
        pet_id: int,
        alias: str = "",
        owner_id: int = 0,
        type_id: int = 0,
        breed_id: int = 0,
        sex: str = "",
        birthday: str = "",
        note: str = "",
        color_id: int = 0,
        chip_number: str = "",
        weight: str = "",
        status: str = "",
    ) -> dict:
        """Update an existing pet's details.

        Args:
            pet_id: ID of the pet to update.
            alias: New pet name/alias (leave empty to keep current).
            owner_id: New owner (client) ID (0 = no change).
            type_id: New animal type ID (0 = no change).
            breed_id: New breed ID (0 = no change).
            sex: Pet sex: 'male', 'female', 'castrated', 'sterilized' (leave empty to keep current).
            birthday: Date of birth in YYYY-MM-DD format (leave empty to keep current).
            note: Updated notes about the pet.
            color_id: New color ID (0 = no change).
            chip_number: Microchip number (leave empty to keep current).
            weight: Pet weight as string, e.g. '5.2' (leave empty to keep current).
            status: New status (leave empty to keep current).
        """
        payload: dict = {}
        if alias:
            payload["alias"] = alias
        if owner_id:
            payload["owner_id"] = owner_id
        if type_id:
            payload["type_id"] = type_id
        if breed_id:
            payload["breed_id"] = breed_id
        if sex:
            payload["sex"] = sex
        if birthday:
            payload["birthday"] = birthday
        if note:
            payload["note"] = note
        if color_id:
            payload["color_id"] = color_id
        if chip_number:
            payload["chip_number"] = chip_number
        if weight:
            payload["weight"] = weight
        if status:
            payload["status"] = status
        return await crud_update("/rest/api/pet", pet_id, payload)

    @mcp.tool
    async def delete_pet(
        pet_id: int,
    ) -> dict:
        """Delete a pet by its ID.

        WARNING: This permanently removes the pet record. Use with caution.

        Args:
            pet_id: ID of the pet to delete.
        """
        return await crud_delete("/rest/api/pet", pet_id)

    @mcp.tool
    async def get_pet_profile(
        pet_id: int,
    ) -> dict:
        """Get a comprehensive profile for a pet in one call.

        Aggregates:
        - Full pet record (with breed and type data)
        - Owner/client record when the runtime token has clients.read
        - Up to 100 latest medical card records, with total/truncation metadata
        - Resolved diagnosis titles when the reference section is available
        - Last 5 invoices with line items when the runtime token has finance.read
        - All vaccination records (date, next vaccination date, vaccine name)
        - Computed last_vaccination_date and next_vaccination_date

        Stage 102.2: tool-level instrumentation wraps the aggregator.

        Args:
            pet_id: Unique numeric ID of the pet.
        """
        return await _instrument_call(
            "/rest/api/pet",
            "GET",
            lambda: _fetch_pet_profile(pet_id),
            operation="aggregate_profile",
            tool_name="get_pet_profile",
        )

    @mcp.tool
    async def get_inactive_pets(
        months_min: int = 13,
        months_max: int = 24,
        limit: LimitParam = 50,
        cursor: str = "",
    ) -> dict:
        """Find pets whose owners have not visited the clinic recently.

        Uses client.last_visit_date for the 13–24 month default window, then
        confirms each pet at that visit through an invoice or medical card.
        An owner with several pets may have brought only some of them.

        The result is ordered by client last visit DESC, client ID DESC, then
        pet ID ASC. Pass `next_cursor` as `cursor` to continue. A cursor fixes
        the window's reference day; keep months_min/months_max unchanged.
        `has_more=true` means another pet was found, `false` proves the end,
        and null means unscanned clients remain after a scan cap or an
        unexpectedly short upstream page. With null, next_cursor continues
        searching. A truncated page is not the full lapsed-pet list.
        `clients_total_in_window` counts clients, not pets, and can be null
        when upstream does not report it. Pagination is not a snapshot:
        changes to clients or pets between calls can shift positions.

        Args:
            months_min: Minimum age of owner's last visit in months.
            months_max: Maximum age of owner's last visit in months.
            limit: Max pets to return (1–100, default 50).
            cursor: Opaque next_cursor from the previous page, if any.
        """
        today = date.today()
        client_offset = 0
        after_pet_id = 0
        if cursor:
            try:
                if len(cursor) > 512 or re.fullmatch(r"[A-Za-z0-9_-]+", cursor) is None:
                    raise ToolInputError("invalid cursor encoding")
                raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
                if base64.urlsafe_b64encode(raw).decode().rstrip("=") != cursor:
                    raise ToolInputError("non-canonical cursor encoding")
                state = json.loads(raw)
                if not isinstance(state, dict) or set(state) != {"v", "min", "max", "day", "client", "after_pet"}:
                    raise ToolInputError("invalid cursor structure")
                if type(state["v"]) is not int or state["v"] != 2 or type(state["min"]) is not int or type(state["max"]) is not int:
                    raise ToolInputError("invalid cursor version or window")
                if (state["min"], state["max"]) != (months_min, months_max):
                    raise ToolInputError("cursor window differs from months_min/months_max")
                if type(state["client"]) is not int or type(state["after_pet"]) is not int:
                    raise ToolInputError("invalid cursor position")
                client_offset, after_pet_id = state["client"], state["after_pet"]
                if client_offset < 0 or client_offset > 1_000_000 or after_pet_id < 0:
                    raise ToolInputError("cursor position out of range")
                today = date.fromisoformat(state["day"])
                if today > date.today():
                    raise ToolInputError("cursor day is in the future")
            except (ValueError, TypeError, KeyError, UnicodeError, binascii.Error) as exc:
                raise ToolInputError(f"invalid cursor: {exc}") from exc

        def encode_position(offset: int, last_pet_id: int) -> str:
            if offset > 1_000_000:
                raise ToolInputError("inactive client offset exceeds 1000000; narrow the date window")
            state = {"v": 2, "min": months_min, "max": months_max,
                     "day": today.isoformat(), "client": offset, "after_pet": last_pet_id}
            return base64.urlsafe_b64encode(json.dumps(state, separators=(",", ":")).encode()).decode().rstrip("=")

        vc = VetmanagerClient()
        result_pets: list[dict] = []
        clients_scanned = 0
        cutoff_oldest = cutoff_newest = ""
        clients_total_in_window: int | None = None
        next_cursor: str | None = None
        has_more: bool | None = False
        safety_cap_reached = False
        short_page_with_remaining = False
        offset = client_offset
        last_returned_client: int | None = None
        last_returned_pet_id = 0

        for page_num in range(MAX_CLIENT_PAGES):
            clients, cutoff_oldest, cutoff_newest, page_total = await fetch_inactive_clients_page(
                months_min=months_min, months_max=months_max,
                limit=CLIENT_PAGE_SIZE, offset=offset, today=today,
            )
            if clients_total_in_window is None:
                clients_total_in_window = page_total
            if not clients:
                if page_total is not None and page_total > offset:
                    raise ToolInputError("inactive client page is empty before reported totalCount")
                break

            # Process only the next same-day group. The helper fully
            # resolves that group so a cursor can resume inside one owner;
            # other days are not fetched after the one-pet probe succeeds.
            group_start = 0
            while group_start < len(clients):
                group_day = str(clients[group_start].get("last_visit_date") or "").split(" ")[0]
                group_end = group_start + 1
                continuing_owner = offset + group_start == client_offset and after_pet_id > 0
                if not continuing_owner:
                    while (group_end < len(clients)
                           and str(clients[group_end].get("last_visit_date") or "").split(" ")[0] == group_day):
                        group_end += 1
                pairs = await find_pets_for_clients_last_visit(
                    vc, clients=clients[group_start:group_end], limit=None,
                    min_pet_id=after_pet_id if continuing_owner else 0,
                )
                for local_index, (client, visited_pets) in enumerate(pairs, start=group_start):
                    clients_scanned += 1
                    absolute_client = offset + local_index
                    client_id = client.get("id")
                    last_visit = client.get("last_visit_date", "")
                    if client_id is None or not last_visit:
                        continue
                    client_name = " ".join(
                        str(client.get(k) or "") for k in ("last_name", "first_name", "middle_name")
                    ).strip()
                    for pet in sorted(visited_pets, key=lambda p: int(p["id"])):
                        if len(result_pets) == limit:
                            has_more = True
                            next_cursor = encode_position(
                                absolute_client,
                                last_returned_pet_id if last_returned_client == absolute_client else 0,
                            )
                            break
                        result_pets.append({
                            "id": pet.get("id"), "alias": pet.get("alias", ""),
                            "type_id": pet.get("type_id"), "owner_id": pet.get("owner_id", client_id),
                            "owner_name": client_name, "owner_phone": client.get("cell_phone", ""),
                            "last_visit_date": last_visit, "visit_source": pet.get("visit_source"),
                            "doctor_id": pet.get("visit_doctor_id"),
                            "doctor_name": pet.get("visit_doctor_name"),
                            "doctor_resolution": "resolved" if pet.get("visit_doctor_name") else (
                                "not_specified" if not pet.get("visit_doctor_id") else "unresolved"
                            ),
                        })
                        last_returned_client = absolute_client
                        last_returned_pet_id = int(pet["id"])
                    if next_cursor:
                        break
                if next_cursor:
                    break
                group_start = group_end
            if next_cursor:
                break

            following_offset = offset + len(clients)
            if clients_total_in_window is not None:
                if following_offset >= clients_total_in_window:
                    break
            if len(clients) < CLIENT_PAGE_SIZE:
                if clients_total_in_window is not None:
                    short_page_with_remaining = True
                    has_more = None
                    next_cursor = encode_position(following_offset, 0)
                break
            offset = following_offset
            if page_num + 1 == MAX_CLIENT_PAGES:
                safety_cap_reached = True
                has_more = None
                next_cursor = encode_position(offset, 0)

        reasons = []
        if has_more is True:
            reasons.append("limit_reached")
        if safety_cap_reached:
            reasons.append("client_scan_cap")
        if short_page_with_remaining:
            reasons.append("upstream_short_page")
        truncation_reason = "+".join(reasons) if reasons else None

        unresolved_doctor_ids = list({
            int(pet["doctor_id"]) for pet in result_pets
            if pet.get("doctor_resolution") == "unresolved" and str(pet.get("doctor_id", "")).isdigit()
        })
        if unresolved_doctor_ids:
            users_payload = await vc.get(
                "/rest/api/user",
                params=build_list_query_params(
                    limit=len(unresolved_doctor_ids),
                    offset=0,
                    filters=[_filter_in("id", unresolved_doctor_ids)],
                ),
            )
            users_data = users_payload.get("data", {}) if isinstance(users_payload, dict) else {}
            users = users_data.get("user", []) if isinstance(users_data, dict) else []
            users_by_id = {user.get("id"): user for user in users if isinstance(user, dict)}
            for pet in result_pets:
                if pet.get("doctor_resolution") != "unresolved":
                    continue
                user = users_by_id.get(pet.get("doctor_id"))
                if user:
                    pet["doctor_name"] = " ".join(str(user.get(k) or "") for k in ("last_name", "first_name", "middle_name")).strip() or None
                    pet["doctor_resolution"] = "resolved" if pet["doctor_name"] else "not_found"
                else:
                    pet["doctor_resolution"] = "not_found"

        # The schedule returns the final display value for a doctor in every
        # access mode. Keep this list consistent even for personal-data tokens.
        for pet in result_pets:
            doctor_id = _positive_owner_id(pet.get("doctor_id"))
            pet["doctor_name"] = (
                build_addressed_placeholder("user", doctor_id, "first_name")
                if doctor_id else None
            )

        return {
            "inactive_pets": result_pets,
            "limit_applied": limit,
            "truncated": bool(reasons),
            "truncation_reason": truncation_reason,
            "has_more": has_more,
            "next_cursor": next_cursor,
            "clients_total_in_window": clients_total_in_window,
            "clients_scanned": clients_scanned,
            "cutoff_window": {"from": cutoff_oldest, "to": cutoff_newest},
            "months_min": months_min,
            "months_max": months_max,
            "safety_cap_reached": safety_cap_reached,
            "note": "Continue with next_cursor while present; has_more=null means unscanned clients remain but pet count is unknown.",
        }
