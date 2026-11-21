"""Bounded, fail-closed exact title snapshot for Report AI depersonalization."""

from __future__ import annotations

import asyncio

from vetmanager_client import VetmanagerClient


CATALOGS = ("good", "goodTag", "goodGroup", "unit", "comboManualName")
PAGE_SIZE = 100
MAX_PAGES_PER_CATALOG = 101
MAX_TOTAL_GETS = 505
SNAPSHOT_TIMEOUT_SECONDS = 15


async def load_report_catalog_titles() -> frozenset[str]:
    """Return only five approved title fields, or no exemptions on any failure.

    Response records and all their other fields are discarded immediately. No
    report cell or catalog payload is put in a query parameter or log entry.
    """
    try:
        async with asyncio.timeout(SNAPSHOT_TIMEOUT_SECONDS):
            titles: set[str] = set()
            gets = 0
            client = VetmanagerClient()
            for catalog in CATALOGS:
                total = None
                offset = 0
                for _ in range(MAX_PAGES_PER_CATALOG):
                    if gets >= MAX_TOTAL_GETS:
                        return frozenset()
                    gets += 1
                    payload = await client.get(
                        f"/rest/api/{catalog}",
                        params={"limit": PAGE_SIZE, "offset": offset},
                        fresh=True, cache=False, retry=False,
                    )
                    data = payload.get("data") if isinstance(payload, dict) else None
                    rows = data.get(catalog) if isinstance(data, dict) else None
                    count = data.get("totalCount") if isinstance(data, dict) else None
                    if (not isinstance(payload, dict) or payload.get("success") is not True
                            or not isinstance(rows, list)
                            or isinstance(count, bool) or not isinstance(count, int)
                            or count < 0 or (total is not None and count != total)):
                        return frozenset()
                    total = count
                    expected = min(PAGE_SIZE, max(0, total - offset))
                    if len(rows) != expected:
                        return frozenset()
                    for row in rows:
                        if not isinstance(row, dict):
                            return frozenset()
                        title = row.get("title")
                        if not isinstance(title, str):
                            return frozenset()
                        titles.add(title)
                    offset += len(rows)
                    if offset == total:
                        break
                else:
                    return frozenset()
            return frozenset(titles)
    except Exception:
        return frozenset()
