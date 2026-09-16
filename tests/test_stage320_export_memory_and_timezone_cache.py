"""Stage 320.2/320.3 — bounded export copies and bounded timezone cache."""

from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

import report_export
import tools.report_ai as report_ai


def _store_streamed(root: Path, raw: bytes, *, delimiter=",", depersonalize=True):
    owner = report_export.owner_segment(
        domain="clinic", subject_type="service_bearer", subject_id=7
    )
    filename = report_export.new_export_filename(report_file_id=5)
    url, rows, columns = report_export.store_export_stream(
        raw=io.BytesIO(raw),
        delimiter=delimiter,
        depersonalize=depersonalize,
        owner=owner,
        filename=filename,
        subject_type="service_bearer",
        subject_id=7,
        download_name="report-5.csv",
    )
    name = report_export.file_segment(owner, filename)
    return url, root / owner / f"{name}.csv", rows, columns


@pytest.fixture
def export_root(tmp_path, monkeypatch):
    root = tmp_path / "exports"
    monkeypatch.setenv("REPORT_EXPORT_DIR", str(root))
    monkeypatch.setenv("WEB_SESSION_SECRET", "stage-320-memory-test-secret")
    report_export.reset_link_key_cache()
    return root


@pytest.mark.parametrize(
    "raw,delimiter,depersonalize",
    [
        ("Владелец,Сумма\nИванов Пётр Сергеевич,-12.5\n".encode(), ",", True),
        ("Название;Формула\nАнализ крови общий; =2+2\n".encode(), ";", False),
        ("Владелец\nИванов Пётр Сергеевич\n".encode("cp1251"), ",", True),
    ],
)
def test_streamed_storage_is_byte_identical_to_existing_csv_contract(
    export_root, raw, delimiter, depersonalize
):
    expected, expected_rows, expected_columns = report_export.build_export_csv(
        raw, delimiter=delimiter, depersonalize=depersonalize
    )

    _url, path, rows, columns = _store_streamed(
        export_root, raw, delimiter=delimiter, depersonalize=depersonalize
    )

    assert path.read_bytes() == expected.encode("utf-8")
    assert (rows, columns) == (expected_rows, expected_columns)


def test_late_utf8_failure_restarts_cp1251_without_mixing_partial_output(export_root):
    raw = b"Column\n" + b"ascii-row\n" * 20_000 + "Привет\n".encode("cp1251")

    _url, path, rows, columns = _store_streamed(
        export_root, raw, depersonalize=False
    )

    body = path.read_text(encoding="utf-8-sig")
    assert body.count("ascii-row") == 20_000
    assert path.read_bytes().endswith("Привет\r\n".encode())
    assert (rows, columns) == (20_001, 1)


def test_failed_parse_publishes_nothing_and_removes_temporary_file(export_root):
    with pytest.raises(report_export.ReportExportError):
        _store_streamed(export_root, b"Column\nvalue\n\x98", depersonalize=False)

    assert list(export_root.rglob("*.csv")) == []
    assert list(export_root.rglob("*.json")) == []
    assert list(export_root.rglob("*.tmp")) == []


def test_regular_sweep_removes_stale_streaming_temporaries(export_root):
    directory = export_root / ("a" * 32)
    directory.mkdir(parents=True)
    temporary = directory / ".partial.csv.deadbeef.tmp"
    temporary.write_bytes(b"partial")
    os.utime(temporary, (0, 0))

    removed = report_export.sweep_expired(now=report_export.REPORT_EXPORT_TTL_SECONDS + 1)

    assert removed == 1
    assert not temporary.exists()


def test_production_export_path_no_longer_builds_or_reads_a_full_csv_copy():
    tool_source = Path("tools/report_ai.py").read_text(encoding="utf-8")
    route_source = Path("web_routes_export.py").read_text(encoding="utf-8")

    assert "report_export.store_export_stream" in tool_source
    assert "report_export.build_export_csv" not in tool_source
    assert ".read_bytes" not in route_source
    assert "StreamingResponse" in route_source


class _ClinicClient:
    calls = 0
    zones = ["UTC", "Europe/Moscow"]

    async def get(self, _path):
        index = min(self.calls, len(self.zones) - 1)
        self.calls += 1
        return {"data": {"clinics": {"time_zone": self.zones[index]}}}


@pytest.mark.asyncio
async def test_timezone_cache_has_absolute_ttl_and_refreshes_without_cleanup(monkeypatch):
    report_ai._reset_report_ai_queue_observations()
    client = _ClinicClient()
    client.calls = 0
    now = [0.0]
    monkeypatch.setattr(report_ai, "VetmanagerClient", lambda: client)
    monkeypatch.setattr(report_ai, "_monotonic_seconds", lambda: now[0])
    monkeypatch.setattr(report_ai, "_unix_seconds", lambda: 1_800_000_000.0)
    monkeypatch.setattr(
        report_ai, "_report_ai_queue_observation_key", lambda job: (1, 1, int(job["id"]))
    )
    job = {"clinic_id": 7, "created_at": "2026-01-01 00:00:00"}

    first = await report_ai._upstream_job_age_seconds(job)
    now[0] = report_ai.REPORT_AI_QUEUE_OBSERVATION_TTL_SECONDS * 0.6
    second = await report_ai._upstream_job_age_seconds(job)
    now[0] = report_ai.REPORT_AI_QUEUE_OBSERVATION_TTL_SECONDS * 1.2
    third = await report_ai._upstream_job_age_seconds(job)

    assert first == second
    assert third != second
    assert client.calls == 2


def test_timezone_cache_participates_in_shared_ttl_and_size_cleanup(monkeypatch):
    report_ai._reset_report_ai_queue_observations()
    monkeypatch.setattr(report_ai, "REPORT_AI_QUEUE_OBSERVATION_MAX_ENTRIES", 2)
    ttl = report_ai.REPORT_AI_QUEUE_OBSERVATION_TTL_SECONDS
    report_ai._REPORT_AI_CLINIC_TIMEZONES[(1, 1, 1)] = ("UTC", 0.0)
    report_ai._REPORT_AI_CLINIC_TIMEZONES[(1, 1, 2)] = ("UTC", ttl)
    report_ai._REPORT_AI_CLINIC_TIMEZONES[(1, 1, 3)] = ("UTC", ttl)

    report_ai._cleanup_report_ai_queue_observations(ttl + 1.0)

    assert list(report_ai._REPORT_AI_CLINIC_TIMEZONES) == [(1, 1, 2), (1, 1, 3)]
