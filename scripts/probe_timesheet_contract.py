"""Opt-in real API probe for the Vetmanager work schedule (timesheet).

Stage 310 rests on claims read out of Vetmanager's own source: creating a
shift requires `type`, the model also requires `shedule_id`, an empty update
is refused with 406, and `PUT`/`DELETE` on a shift exist at all. Mocks encode
those beliefs; only a real call checks them.

Requires TEST_DOMAIN and TEST_API_KEY. Writes to the stand and removes what it
created: the delete runs in `finally`. Prints statuses and short bodies, never
secrets.

    TEST_DOMAIN=... TEST_API_KEY=... python scripts/probe_timesheet_contract.py
"""

from __future__ import annotations

import json
import os
import sys

import httpx

PROBE_BEGIN = "2027-03-01 09:00:00"
PROBE_END = "2027-03-01 18:00:00"


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required for the timesheet probe.")
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
    print(f"{label}: HTTP {response.status_code} {json.dumps(payload, ensure_ascii=False)[:300]}")
    return payload if isinstance(payload, dict) else {}


def main() -> int:
    domain = _required_env("TEST_DOMAIN")
    api_key = _required_env("TEST_API_KEY")
    base = _host(domain)
    headers = {"X-REST-API-KEY": api_key, "Accept": "application/json"}
    created_id = None
    failures: list[str] = []

    with httpx.Client(base_url=base, headers=headers, timeout=30.0) as client:
        types = _show("types", client.get("/rest/api/timesheetTypes"))
        rows = types.get("data", {}).get("timesheetTypes", [])
        working = [row for row in rows if row.get("is_working_hours") == 1]
        if not working:
            print("no working-hours type on the stand, stopping")
            return 1
        shift_type = working[0]["id"]
        print(f"-> working-hours type id: {shift_type}")

        try:
            without_type = client.post(
                "/rest/api/timesheet",
                json={
                    "doctor_id": 1,
                    "begin_datetime": PROBE_BEGIN,
                    "end_datetime": PROBE_END,
                    "clinic_id": 1,
                },
            )
            _show("create without type", without_type)
            if without_type.status_code < 400:
                failures.append("a shift without `type` was accepted — the whole premise is wrong")

            created = client.post(
                "/rest/api/timesheet",
                json={
                    "doctor_id": 1,
                    "begin_datetime": PROBE_BEGIN,
                    "end_datetime": PROBE_END,
                    "clinic_id": 1,
                    "type": shift_type,
                    "shedule_id": 0,
                    "title": "stage310 probe",
                },
            )
            payload = _show("create", created)
            if created.status_code >= 400:
                failures.append("create with `type` and `shedule_id: 0` was refused")
            else:
                entity = payload.get("data", {}).get("timesheet")
                if isinstance(entity, list):
                    entity = entity[0] if entity else {}
                created_id = (entity or {}).get("id")
                print(f"-> created id: {created_id}")

            if created_id:
                _show(
                    "update",
                    client.put(
                        f"/rest/api/timesheet/{created_id}",
                        json={"end_datetime": "2027-03-01 20:00:00"},
                    ),
                )
                empty = client.put(f"/rest/api/timesheet/{created_id}", json={})
                _show("update with empty body", empty)
                if empty.status_code < 400:
                    failures.append("an empty update was accepted — 406 claim is wrong")
        finally:
            if created_id:
                deleted = client.delete(f"/rest/api/timesheet/{created_id}")
                _show("delete", deleted)
                if deleted.status_code >= 400:
                    failures.append("DELETE on a shift is not available")
                gone = client.get(f"/rest/api/timesheet/{created_id}")
                _show("read after delete", gone)

    for line in failures:
        print(f"MISMATCH: {line}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
