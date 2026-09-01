"""Stage 276 — the report export goes through MCP instead of past it.

Stage 275 wrote down an honest leftover: the CSV/XLSX export was downloaded
straight from Vetmanager, past all three layers. A live probe on devtr6 on
01.09.2026 showed the leftover was worse than written — the locator is an
absolute address on a public CDN that serves the file to anyone, with no
authorization header at all.

Now the server downloads the export itself, cleans it with the same layers as
report rows, and hands the agent a link of its own: an unguessable path, three
days of life, and a check that the access it was issued to is still alive.
"""

from __future__ import annotations

from pathlib import Path
import json
import logging
import os

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

import report_export
from privacy_utils import REPORT_EXPORT_ROUTE_TEMPLATE
import tool_descriptions
import tools
from depersonalization import REDACTED_NAME, REDACTED_PHONE
from server import mcp
from tests.runtime_factories import patch_runtime_credentials
from token_scopes import SCOPE_ANALYTICS_READ, SCOPE_REPORT_AI_WRITE
from tool_access_registry import TOOL_REQUIRED_SCOPES


DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"
CDN = "https://308427.selcdn.example/vetmanager-public-user-files/testclinic/9/report.csv"


def billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def report_file_mock(**fields):
    payload = {"success": True, "data": {"report": {"csv_file": CDN, **fields}}}
    return respx.get(f"{BASE}/rest/api/report/reportFile").mock(
        return_value=httpx.Response(200, json=payload)
    )


def cdn_mock(body: bytes, *, content_type: str = "text/csv", status: int = 200):
    return respx.get(CDN).mock(
        return_value=httpx.Response(status, content=body, headers={"content-type": content_type})
    )


def runtime(*, depersonalized: bool = True, token_id: int = 11):
    return patch_runtime_credentials(
        DOMAIN,
        API_KEY,
        bearer_token="mock-token",
        bearer_token_id=token_id,
        connection_id=1,
        scopes=(SCOPE_ANALYTICS_READ, SCOPE_REPORT_AI_WRITE),
        is_depersonalized=depersonalized,
    )


@pytest.fixture(autouse=True)
def export_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Every test writes into its own directory and signs with its own secret."""
    root = tmp_path / "report-exports"
    monkeypatch.setenv("REPORT_EXPORT_DIR", str(root))
    monkeypatch.setenv("WEB_SESSION_SECRET", "stage-276-test-secret")
    monkeypatch.setenv("SITE_BASE_URL", "https://mcp.example")
    report_export.reset_link_key_cache()
    return root


def _structured(result) -> dict:
    return result.structured_content


# ── The locator tool is gone ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_locator_tool_is_gone_for_good():
    """Stage 276.4. Vetmanager's own address must not reach the agent again."""
    names = {tool.name for tool in await mcp.list_tools()}

    assert "get_report_export_file" not in names
    assert "get_report_export_file" not in TOOL_REQUIRED_SCOPES
    assert "get_report_export_file" not in tool_descriptions.SPECIAL_TOOL_DESCRIPTIONS
    assert "get_report_export_file" not in tools.REPORT_TOOLS
    assert "get_report_export_download" in names
    assert TOOL_REQUIRED_SCOPES["get_report_export_download"] == (SCOPE_ANALYTICS_READ,)


# ── The link ─────────────────────────────────────────────────────────────────


def test_a_link_segment_is_thirty_two_hex_characters():
    owner = report_export.owner_segment(domain=DOMAIN, subject_type="service_bearer", subject_id=11)

    assert len(owner) == 32
    assert set(owner) <= set("0123456789abcdef")


def test_different_subjects_of_one_clinic_get_different_directories():
    first = report_export.owner_segment(domain=DOMAIN, subject_type="service_bearer", subject_id=11)
    second = report_export.owner_segment(domain=DOMAIN, subject_type="service_bearer", subject_id=12)
    other_kind = report_export.owner_segment(domain=DOMAIN, subject_type="oauth", subject_id=11)

    assert len({first, second, other_kind}) == 3


def test_the_pieces_cannot_be_shifted_between_each_other():
    """Length prefixes: `a:b` + `c` must not sign the same bytes as `a` + `b:c`."""
    first = report_export.owner_segment(domain="clinic:one", subject_type="service_bearer", subject_id=11)
    second = report_export.owner_segment(domain="clinic", subject_type="one:bearer", subject_id=11)

    assert first != second


def test_the_path_cannot_be_computed_without_the_server_secret(monkeypatch):
    before = report_export.owner_segment(domain=DOMAIN, subject_type="service_bearer", subject_id=11)
    monkeypatch.setenv("WEB_SESSION_SECRET", "a-different-secret")
    report_export.reset_link_key_cache()

    assert report_export.owner_segment(domain=DOMAIN, subject_type="service_bearer", subject_id=11) != before


def test_the_same_report_exported_twice_does_not_overwrite_the_first_link():
    first = report_export.new_export_filename(report_file_id=7)
    second = report_export.new_export_filename(report_file_id=7)

    assert first != second


# ── Cleaning the file ────────────────────────────────────────────────────────


def _build(raw: bytes, *, delimiter: str = ",", depersonalize: bool = True):
    return report_export.build_export_csv(raw, delimiter=delimiter, depersonalize=depersonalize)


def test_a_named_column_is_recognised_by_its_header():
    text, rows, columns = _build("Владелец,Приёмов\nИванов Пётр Сергеевич,3\n".encode())

    assert rows == 1
    assert columns == 2
    assert REDACTED_NAME in text
    assert "Иванов" not in text


def test_a_column_nobody_expected_is_cleaned_by_its_values():
    text, _, _ = _build("Колонка 1,Колонка 2\n+7 918 414-01-11,Стрижка\n".encode())

    assert REDACTED_PHONE in text
    assert "414-01-11" not in text


def test_a_date_a_microchip_and_a_barcode_survive():
    raw = "Дата,Чип,Штрихкод\n2026-08-31 10:11,643094100123456,4600000000001\n".encode()

    text, _, _ = _build(raw)

    assert "2026-08-31 10:11" in text
    assert "643094100123456" in text
    assert "4600000000001" in text


def test_without_depersonalization_the_cells_are_left_alone():
    text, _, _ = _build("Владелец\nИванов Пётр Сергеевич\n".encode(), depersonalize=False)

    assert "Иванов Пётр Сергеевич" in text


def test_every_file_is_written_the_way_excel_opens_it():
    text, _, _ = _build("a,b\n1,2\n".encode(), depersonalize=False)

    assert text.startswith("﻿")
    assert "a;b\r\n" in text


@pytest.mark.parametrize(
    "cell",
    [
        "=1+1",
        "+1",
        "@SUM(A1)",
        "\t=1+1",
        "   =1+1",
        "-cmd|'/c calc'!A0",
        # A control or format character hides the `=` from a naive check and
        # Excel looks straight past it.
        "\x1b=1+1",
        "\u200b=1+1",
        "\x00=1+1",
    ],
)
def test_a_cell_that_excel_would_execute_is_escaped(cell):
    text, _, _ = _build(f"Колонка\n{cell}\n".encode(), depersonalize=False)

    body = text.splitlines()[1]
    assert body.lstrip('"').startswith("'")


@pytest.mark.parametrize("cell", ["-1234", "-1.23", "-1,23", "1234"])
def test_a_negative_number_is_not_escaped(cell):
    text, _, _ = _build(f"Колонка\n{cell}\n".encode(), depersonalize=False)

    assert "'" not in text


def test_an_empty_file_is_refused_rather_than_served_as_a_report():
    with pytest.raises(report_export.ReportExportError):
        _build(b"")


def test_a_header_without_rows_is_a_report_with_no_rows():
    text, rows, columns = _build("Владелец,Приёмов\n".encode())

    assert rows == 0
    assert columns == 2
    assert text


def test_repeated_column_names_are_handled_by_position():
    text, rows, columns = _build("Телефон,Телефон\n+7 918 414-01-11,+7 918 414-01-12\n".encode())

    assert columns == 2
    assert text.count(REDACTED_PHONE) == 2


def test_a_row_longer_than_the_header_is_still_cleaned():
    text, _, _ = _build("Колонка\nСтрижка,+7 918 414-01-11\n".encode())

    assert REDACTED_PHONE in text
    assert "414-01-11" not in text


def test_a_file_in_the_other_encoding_is_read_rather_than_refused():
    text, _, _ = _build("Владелец\nИванов Пётр Сергеевич\n".encode("cp1251"))

    assert REDACTED_NAME in text


# ── Storing and serving ──────────────────────────────────────────────────────


def _store(root: Path, *, subject_id: int = 11, text: str = "﻿a;b\r\n"):
    owner = report_export.owner_segment(domain=DOMAIN, subject_type="service_bearer", subject_id=subject_id)
    filename = report_export.new_export_filename(report_file_id=5)
    url_path = report_export.store_export(
        csv_text=text,
        owner=owner,
        filename=filename,
        subject_type="service_bearer",
        subject_id=subject_id,
        download_name="report-5.csv",
    )
    return owner, report_export.file_segment(owner, filename), url_path


def test_a_stored_file_is_readable_only_by_the_service(export_root: Path):
    owner, name, url_path = _store(export_root)

    csv_path = export_root / owner / f"{name}.csv"
    assert csv_path.exists()
    assert url_path == f"/report-export/{owner}/{name}.csv"
    assert oct(csv_path.stat().st_mode)[-3:] == "600"
    assert oct((export_root / owner).stat().st_mode)[-3:] == "700"


def test_the_companion_names_the_subject_the_link_was_issued_to(export_root: Path):
    owner, name, _ = _store(export_root)

    meta = json.loads((export_root / owner / f"{name}.json").read_text())
    assert meta["subject_type"] == "service_bearer"
    assert meta["subject_id"] == 11
    assert meta["owner"] == owner
    assert meta["download_name"] == "report-5.csv"


def test_the_right_path_resolves(export_root: Path):
    owner, name, _ = _store(export_root)

    stored = report_export.resolve_export(owner, name)

    assert stored is not None
    assert stored.download_name == "report-5.csv"


@pytest.mark.parametrize(
    "owner_value, name_value",
    [
        ("0" * 32, "{name}"),
        ("{owner}", "0" * 32),
        ("{owner}", "../../etc/passwd"),
        ("..", "{name}"),
        ("{owner}", "NOTHEX" + "0" * 26),
        ("{owner}", "0" * 31),
    ],
)
def test_a_wrong_path_resolves_to_nothing(export_root: Path, owner_value, name_value):
    owner, name, _ = _store(export_root)

    assert report_export.resolve_export(
        owner_value.format(owner=owner), name_value.format(name=name)
    ) is None


def test_a_file_past_its_three_days_is_neither_served_nor_kept(export_root: Path):
    owner, name, _ = _store(export_root)
    csv_path = export_root / owner / f"{name}.csv"
    old = csv_path.stat().st_mtime - report_export.REPORT_EXPORT_TTL_SECONDS - 60
    os.utime(csv_path, (old, old))

    assert report_export.resolve_export(owner, name) is None
    assert not csv_path.exists()
    assert not (export_root / owner / f"{name}.json").exists()


def test_a_file_without_its_companion_is_not_served(export_root: Path):
    owner, name, _ = _store(export_root)
    (export_root / owner / f"{name}.json").unlink()

    assert report_export.resolve_export(owner, name) is None
    assert not (export_root / owner / f"{name}.csv").exists()


def test_a_companion_pointing_at_another_owner_is_not_served(export_root: Path):
    owner, name, _ = _store(export_root)
    meta_path = export_root / owner / f"{name}.json"
    meta = json.loads(meta_path.read_text())
    meta["owner"] = "f" * 32
    meta_path.write_text(json.dumps(meta))

    assert report_export.resolve_export(owner, name) is None


def test_sweeping_removes_what_expired_and_keeps_what_did_not(export_root: Path):
    stale_owner, stale_name, _ = _store(export_root, subject_id=11)
    fresh_owner, fresh_name, _ = _store(export_root, subject_id=12)
    stale = export_root / stale_owner / f"{stale_name}.csv"
    old = stale.stat().st_mtime - report_export.REPORT_EXPORT_TTL_SECONDS - 60
    os.utime(stale, (old, old))
    os.utime(export_root / stale_owner / f"{stale_name}.json", (old, old))

    removed = report_export.sweep_expired()

    assert removed == 1
    assert not stale.exists()
    assert not (export_root / stale_owner).exists()
    assert (export_root / fresh_owner / f"{fresh_name}.csv").exists()


# ── The tool ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_the_tool_answers_with_our_link_and_no_foreign_address(export_root: Path):
    billing_mock()
    report_file_mock(xlsx_file="https://308427.selcdn.example/x.xlsx")
    cdn_mock("Владелец,Приёмов\nИванов Пётр Сергеевич,3\n".encode())

    headers_patch, runtime_patch = runtime()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_report_export_download", {"report_file_id": 5})

    payload = _structured(result)
    assert payload["download_url"].startswith("https://mcp.example/report-export/")
    assert payload["rows"] == 1
    assert payload["columns"] == 2
    assert payload["depersonalized"] is True
    assert "selcdn" not in json.dumps(payload)
    assert "vetmanager" not in json.dumps(payload).lower()


@pytest.mark.asyncio
@respx.mock
async def test_the_downloaded_file_is_the_cleaned_one(export_root: Path):
    billing_mock()
    report_file_mock()
    cdn_mock("Владелец,Приёмов\nИванов Пётр Сергеевич,3\n".encode())

    headers_patch, runtime_patch = runtime()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_report_export_download", {"report_file_id": 5})

    written = list(export_root.rglob("*.csv"))
    assert len(written) == 1
    body = written[0].read_text(encoding="utf-8-sig")
    assert REDACTED_NAME in body
    assert "Иванов" not in body


@pytest.mark.asyncio
@respx.mock
async def test_the_api_key_is_not_sent_to_the_cdn(export_root: Path):
    billing_mock()
    report_file_mock()
    route = cdn_mock("a,b\n1,2\n".encode())

    headers_patch, runtime_patch = runtime()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_report_export_download", {"report_file_id": 5})

    sent = route.calls.last.request.headers
    assert "x-rest-api-key" not in sent
    assert "authorization" not in sent


@pytest.mark.asyncio
@respx.mock
async def test_a_file_over_the_limit_is_refused_and_nothing_is_stored(
    export_root: Path, monkeypatch
):
    monkeypatch.setattr(report_export, "REPORT_EXPORT_MAX_BYTES", 16)
    billing_mock()
    report_file_mock()
    cdn_mock(b"a,b\n" + b"1,2\n" * 40)

    headers_patch, runtime_patch = runtime()
    with headers_patch, runtime_patch, pytest.raises(ToolError) as excinfo:
        await mcp.call_tool("get_report_export_download", {"report_file_id": 5})

    assert "selcdn" not in str(excinfo.value)
    assert list(export_root.rglob("*.csv")) == []


@pytest.mark.asyncio
@respx.mock
async def test_a_body_with_no_type_at_all_is_not_served_as_a_report(export_root: Path):
    """An error page with its label torn off is still an error page."""
    billing_mock()
    report_file_mock()
    respx.get(CDN).mock(return_value=httpx.Response(200, content=b"<html>nope</html>"))

    headers_patch, runtime_patch = runtime()
    with headers_patch, runtime_patch, pytest.raises(ToolError):
        await mcp.call_tool("get_report_export_download", {"report_file_id": 5})

    assert list(export_root.rglob("*.csv")) == []


@pytest.mark.asyncio
@respx.mock
async def test_an_error_page_from_the_cdn_is_not_served_as_a_report(export_root: Path):
    billing_mock()
    report_file_mock()
    cdn_mock(b"<html>gateway timeout</html>", content_type="text/html")

    headers_patch, runtime_patch = runtime()
    with headers_patch, runtime_patch, pytest.raises(ToolError) as excinfo:
        await mcp.call_tool("get_report_export_download", {"report_file_id": 5})

    assert "selcdn" not in str(excinfo.value)
    assert list(export_root.rglob("*.csv")) == []


@pytest.mark.asyncio
@respx.mock
async def test_a_redirect_away_from_the_locator_is_not_followed(export_root: Path):
    billing_mock()
    report_file_mock()
    respx.get(CDN).mock(
        return_value=httpx.Response(302, headers={"location": "https://elsewhere.example/x.csv"})
    )

    headers_patch, runtime_patch = runtime()
    with headers_patch, runtime_patch, pytest.raises(ToolError):
        await mcp.call_tool("get_report_export_download", {"report_file_id": 5})

    assert list(export_root.rglob("*.csv")) == []


@pytest.mark.asyncio
@respx.mock
async def test_a_build_still_running_says_so_without_naming_the_locator(export_root: Path):
    billing_mock()
    respx.get(f"{BASE}/rest/api/report/reportFile").mock(
        return_value=httpx.Response(
            401, json={"success": False, "error": True, "message": "Error: build in progress."}
        )
    )

    headers_patch, runtime_patch = runtime()
    with headers_patch, runtime_patch, pytest.raises(ToolError) as excinfo:
        await mcp.call_tool("get_report_export_download", {"report_file_id": 5})

    message = str(excinfo.value)
    assert "get_report_export_download" in message
    assert "selcdn" not in message


# ── The route ────────────────────────────────────────────────────────────────


def test_the_privacy_note_no_longer_sends_people_around_the_layers():
    from web_html import REPORT_PRIVACY_NOTE

    assert "мимо этих слоёв" not in REPORT_PRIVACY_NOTE
    assert "выгрузк" in REPORT_PRIVACY_NOTE.lower()


def test_the_access_log_line_does_not_carry_the_key_to_the_file():
    """A signed path in a persistent log file is the file handed out."""
    from structured_logging import ReportExportPathFilter

    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1", "GET", f"/report-export/{'a' * 32}/{'b' * 32}.csv", "1.1", 200),
        None,
    )

    assert ReportExportPathFilter().filter(record) is True
    assert record.args[2] == REPORT_EXPORT_ROUTE_TEMPLATE


def test_sentry_does_not_keep_the_key_to_the_file_either():
    from error_tracking import _sanitize_event

    event = {
        "request": {"url": f"https://mcp.example/report-export/{'a' * 32}/{'b' * 32}.csv"},
        "logger": "vetmanager.runtime",
    }

    scrubbed = _sanitize_event(event, {})

    assert "a" * 32 not in scrubbed["request"]["url"]
    assert scrubbed["request"]["url"].endswith(REPORT_EXPORT_ROUTE_TEMPLATE)
