"""Opt-in real API probe for the shift flags `all_day` and `night` (stage 311).

Stage 311 rests on two kinds of claim. The first is about Vetmanager: the
fields are writable, survive a round trip, and are validated by nobody — a
probe on 09.09.2026 saw the stand accept both flags at once and a night shift
inside one day. The second is about us: `_shift_time_fields` turns a flag into
the times the schedule form would have written. Mocks encode the first and
compute the second; only a real call checks that the pair agrees.

Requires TEST_DOMAIN and TEST_API_KEY. Writes to the stand and removes what it
created: the deletes run in `finally`. Prints statuses and short bodies, never
secrets.

    TEST_DOMAIN=... TEST_API_KEY=... python scripts/probe_timesheet_flags.py
"""

from __future__ import annotations

import json
import os
import sys

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from exceptions import ToolInputError  # noqa: E402
from tools.operations import _shift_time_fields  # noqa: E402

DAY_BEGIN = "2027-05-03 09:00:00"
DAY_END = "2027-05-03 18:00:00"
NIGHT_BEGIN = "2027-05-03 20:00:00"
NIGHT_END = "2027-05-04 08:00:00"


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required for the shift flags probe.")
    return value


def _host(domain: str) -> str:
    if domain.startswith("http"):
        return domain.rstrip("/")
    if "." in domain:
        return f"https://{domain.strip('/')}"
    response = httpx.get(f"https://billing-api.vetmanager.cloud/host/{domain}", timeout=15.0)
    response.raise_for_status()
    url = response.json().get("data", {}).get("url", "")
    if not url:
        raise RuntimeError("Billing host resolver did not return data.url.")
    return (url if url.startswith("http") else f"https://{url}").rstrip("/")


def _show(label: str, response: httpx.Response) -> dict:
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text[:200]}
    print(f"{label}: HTTP {response.status_code} {json.dumps(payload, ensure_ascii=False)[:280]}")
    return payload if isinstance(payload, dict) else {}


def _entity(payload: dict) -> dict:
    entity = payload.get("data", {}).get("timesheet")
    if isinstance(entity, list):
        entity = entity[0] if entity else {}
    return entity or {}


def _shift_payload(doctor_id: int, clinic_id: int, shift_type: int, fields: dict) -> dict:
    return {
        "doctor_id": doctor_id,
        "clinic_id": clinic_id,
        "type": shift_type,
        "shedule_id": 0,
        **fields,
    }


def main() -> int:
    domain = _required_env("TEST_DOMAIN")
    api_key = _required_env("TEST_API_KEY")
    base = _host(domain)
    headers = {"X-REST-API-KEY": api_key, "Accept": "application/json"}
    created: list[int] = []
    failures: list[str] = []

    with httpx.Client(base_url=base, headers=headers, timeout=30.0) as client:
        types = _show("types", client.get("/rest/api/timesheetTypes"))
        rows = types.get("data", {}).get("timesheetTypes", [])
        working = [row for row in rows if row.get("is_working_hours") == 1]
        if not working:
            print("no working-hours type on the stand, stopping")
            return 1
        shift_type = working[0]["id"]

        try:
            all_day_fields = _shift_time_fields(DAY_BEGIN, DAY_END, True, None)
            response = client.post(
                "/rest/api/timesheet",
                json=_shift_payload(1, 1, shift_type, all_day_fields),
            )
            row = _entity(_show("create all_day", response))
            if row.get("id"):
                created.append(int(row["id"]))
            if str(row.get("all_day")) != "1":
                failures.append("an all-day shift came back without the flag")
            if row.get("begin_datetime") != "2027-05-03 00:00:00" or row.get(
                "end_datetime"
            ) != "2027-05-03 23:59:59":
                failures.append("the day boundaries we computed are not what came back")

            night_fields = _shift_time_fields(NIGHT_BEGIN, NIGHT_END, None, True)
            response = client.post(
                "/rest/api/timesheet",
                json=_shift_payload(1, 1, shift_type, night_fields),
            )
            row = _entity(_show("create night", response))
            night_id = int(row["id"]) if row.get("id") else None
            if night_id:
                created.append(night_id)
            if str(row.get("night")) != "1":
                failures.append("a night shift came back without the flag")

            if night_id:
                # The edit that matters: the stand keeps both flags happily,
                # so nothing but our own payload puts the old one out.
                switch = _shift_time_fields(DAY_BEGIN, DAY_END, True, None)
                _show(
                    "switch night row to all_day",
                    client.put(f"/rest/api/timesheet/{night_id}", json=switch),
                )
                after = _entity(_show("read back", client.get(f"/rest/api/timesheet/{night_id}")))
                if str(after.get("night")) != "0":
                    failures.append("turning on all_day left the night flag standing")
                if str(after.get("all_day")) != "1":
                    failures.append("turning on all_day did not take")

            # Refusals happen before the network. Their point is that no row
            # like this reaches the clinic at all.
            for label, args in (
                ("both flags", (NIGHT_BEGIN, NIGHT_END, True, True)),
                ("night inside one day", (DAY_BEGIN, DAY_END, None, True)),
                ("flag without dates", ("", "", None, True)),
                ("end before begin", (DAY_END, DAY_BEGIN, None, None)),
            ):
                try:
                    _shift_time_fields(*args)
                except ToolInputError as error:
                    print(f"refused {label}: {error}")
                else:
                    failures.append(f"{label} was not refused")
        finally:
            for timesheet_id in created:
                _show(f"delete {timesheet_id}", client.delete(f"/rest/api/timesheet/{timesheet_id}"))

    for line in failures:
        print(f"MISMATCH: {line}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
