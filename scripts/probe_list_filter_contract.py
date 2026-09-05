#!/usr/bin/env python3
"""Opt-in read-only probe for scalar list filter/sort field names.

Requires TEST_DOMAIN and TEST_API_KEY. Output deliberately contains only an
entity name, a field name and an HTTP status; values and credentials never
leave process memory or reach stdout.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from auth.context import VetmanagerAuthContext, VETMANAGER_AUTH_MODE_DOMAIN_API_KEY
from host_resolver import resolve_vetmanager_host


ENTITIES = {
    "cassaclose": "/rest/api/cassaclose",
    "payment": "/rest/api/payment",
    "invoice": "/rest/api/invoice",
    "closingOfInvoices": "/rest/api/closingOfInvoices", "cassa": "/rest/api/cassa",
    "admission": "/rest/api/admission", "client": "/rest/api/client",
    "hospital": "/rest/api/hospital", "hospitalBlock": "/rest/api/HospitalBlock",
    "pet": "/rest/api/pet", "user": "/rest/api/user", "clinics": "/rest/api/clinics",
    "timesheet": "/rest/api/timesheet", "properties": "/rest/api/properties",
    "breed": "/rest/api/breed", "petType": "/rest/api/petType", "city": "/rest/api/city",
    "cityType": "/rest/api/cityType", "street": "/rest/api/street", "unit": "/rest/api/unit",
    "role": "/rest/api/role", "userPosition": "/rest/api/userPosition",
    "goodSaleParam": "/rest/api/goodSaleParam", "good": "/rest/api/good",
    # Этап 235.7: сущности, у которых контракт фильтров не подтверждён — раньше
    # проба на них не ходила. Из одиннадцати инструментов пункта сюда попали
    # семь: остальные четыре (`get_medical_cards`, `get_diagnoses`,
    # `get_anonymous_clients`, `get_message_reports`) ходят не в обычный
    # list-эндпоинт, а в особые пути вида `/rest/api/MedicalCards/AllDiagnoses`
    # и `/rest/api/user/anonymousList`, где общий контракт `filter`/`sort`
    # неприменим — для них вопрос поставлен неверно, а не остался без ответа.
    "comboManualName": "/rest/api/ComboManualName",
    "comboManualItem": "/rest/api/ComboManualItem",
    "goodGroup": "/rest/api/GoodGroup",
    "partyAccount": "/rest/api/PartyAccount",
    "partyAccountDoc": "/rest/api/PartyAccountDoc",
    "storeDocument": "/rest/api/StoreDocument",
    "suppliers": "/rest/api/Suppliers",
}
PROBE_VALUE = 0
REQUEST_GAP_SECONDS = 0.1


def _scalar_fields(row: dict[str, Any]) -> list[str]:
    return sorted(
        field for field, value in row.items()
        if value is None or isinstance(value, (bool, int, float, str))
    )


def _rows(payload: Any, entity: str) -> list[dict[str, Any]]:
    """Строки списка, как бы Ветменеджер ни назвал ключ.

    Этап 235.7: раньше ключ искался точным совпадением с именем сущности, и на
    любом расхождении регистра или числа (`goodGroup` против `GoodGroup`,
    `clients` против `client`) проба печатала `NO_ROWS`. «Записей нет» и «ключ
    называется иначе» выглядели одинаково, а вывод из них делался разный.
    """
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        return data if isinstance(data, list) else []
    rows = data.get(entity)
    if not isinstance(rows, list):
        # Ключ не совпал — берём единственный список в ответе, если он один.
        lists = [value for value in data.values() if isinstance(value, list)]
        rows = lists[0] if len(lists) == 1 else None
    return rows if isinstance(rows, list) else []


async def _probe_entity(
    client: httpx.AsyncClient, base_url: str, entity: str, path: str, mode: str
) -> None:
    response = await client.get(f"{base_url}{path}", params={"limit": 1, "offset": 0})
    if response.status_code != 200:
        print(f"{entity} LIST {response.status_code}")
        return
    rows = _rows(response.json(), entity)
    if not rows or not isinstance(rows[0], dict):
        print(f"{entity} NO_ROWS")
        return
    for field in _scalar_fields(rows[0]):
        response = await client.get(
            f"{base_url}{path}",
            params={
                "limit": 1,
                "offset": 0,
                mode: json.dumps(
                    [{"property": field, "direction": "ASC"}]
                    if mode == "sort" else
                    [{"property": field, "operator": "=", "value": PROBE_VALUE}],
                    separators=(",", ":"),
                ),
            },
        )
        print(f"{entity} {field} {response.status_code}")
        await asyncio.sleep(REQUEST_GAP_SECONDS)


async def main() -> None:
    domain = os.environ.get("TEST_DOMAIN", "")
    api_key = os.environ.get("TEST_API_KEY", "")
    if not domain or not api_key:
        raise SystemExit("TEST_DOMAIN and TEST_API_KEY are required")
    if domain != "devtr6":
        raise SystemExit("This probe is restricted to TEST_DOMAIN=devtr6")
    mode = os.environ.get("PROBE_LIST_CONTRACT_MODE", "filter")
    if mode not in {"filter", "sort"}:
        raise SystemExit("PROBE_LIST_CONTRACT_MODE must be filter or sort")
    base_url = await resolve_vetmanager_host(domain)
    auth = VetmanagerAuthContext(
        auth_mode=VETMANAGER_AUTH_MODE_DOMAIN_API_KEY,
        domain=domain,
        credential=api_key,
    )
    async with httpx.AsyncClient(headers=auth.build_headers(), timeout=30.0) as client:
        for entity, path in ENTITIES.items():
            await _probe_entity(client, base_url, entity, path, mode)


if __name__ == "__main__":
    asyncio.run(main())
