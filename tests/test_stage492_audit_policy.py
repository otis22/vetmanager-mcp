import json
from datetime import date
import os
from pathlib import Path
import subprocess
import sys
import pytest

from scripts.check_stage492_audit import KNOWN, verify


def write_snapshot(path, workers):
    path.write_text(json.dumps({
        "worker_inventory": [
            {"service": worker["service"], "container_id": chr(97 + index) * 12}
            for index, worker in enumerate(workers)],
        "workers": [{**worker, "container_id": chr(97 + index) * 12}
                    for index, worker in enumerate(workers)]}))


@pytest.mark.parametrize("service,image_id", [
    ("mcpevil", "sha256:" + "a" * 64),
    ("mcp2", "sha256:bad"),
])
def test_scheduled_audit_rejects_malformed_worker_before_scanning(tmp_path, service, image_id):
    expected = (Path(__file__).resolve().parents[1] /
                "requirements/production-installed.txt").read_text()
    snapshot = tmp_path / "snapshot.json"
    write_snapshot(snapshot, [{"service": service,
        "image_id": image_id, "freeze": expected}])
    run = subprocess.run([sys.executable, "scripts/run_stage492_scheduled_audit.py",
                          str(snapshot)], capture_output=True, text=True)
    assert run.returncode == 1
    assert "invalid" in run.stderr


def test_scheduled_audit_scans_actual_freeze_before_blocking_drift(tmp_path):
    snapshot = tmp_path / "snapshot.json"
    write_snapshot(snapshot, [{"service": "mcp",
        "image_id": "sha256:" + "a" * 64, "freeze": "cryptography==46.0.7\n"}])
    marker = tmp_path / "scanner-ran"
    scanner = tmp_path / "pip-audit"
    scanner.write_text(f"#!{sys.executable}\n"
        "import json, pathlib, sys\n"
        f"pathlib.Path({str(marker)!r}).write_text('yes')\n"
        "pathlib.Path(sys.argv[sys.argv.index('--output') + 1]).write_text(json.dumps("
        "{'dependencies': [{'name': 'cryptography', 'version': '46.0.7', "
        "'vulns': [{'id': item} for item in "
        "['PYSEC-2026-3552', 'PYSEC-2026-3553', 'PYSEC-2026-3554', "
        "'GHSA-537c-gmf6-5ccf']]}]}))\n"
        "sys.exit(1)\n")
    scanner.chmod(0o700)
    run = subprocess.run([sys.executable, "scripts/run_stage492_scheduled_audit.py",
                          str(snapshot)], capture_output=True, text=True,
                         env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"]})
    assert run.returncode == 1
    assert marker.exists(), "actual production freeze must be scanned before drift blocks"
    assert "running production packages differ" in run.stderr


def test_scheduled_audit_rejects_requirement_directive_before_scanner(tmp_path):
    snapshot = tmp_path / "snapshot.json"
    write_snapshot(snapshot, [{"service": "mcp",
        "image_id": "sha256:" + "a" * 64,
        "freeze": "cryptography @ https://example.invalid/other.whl\n"}])
    marker = tmp_path / "scanner-ran"
    scanner = tmp_path / "pip-audit"
    scanner.write_text(f"#!{sys.executable}\n"
                       f"from pathlib import Path; Path({str(marker)!r}).write_text('yes')\n")
    scanner.chmod(0o700)
    run = subprocess.run([sys.executable, "scripts/run_stage492_scheduled_audit.py",
                          str(snapshot)], capture_output=True, text=True,
                         env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"]})
    assert run.returncode == 1
    assert not marker.exists()
    assert "invalid pip freeze entry" in run.stderr


def test_scheduled_audit_scans_every_worker_before_reporting_drift(tmp_path):
    freeze = "cryptography==46.0.7\n"
    snapshot = tmp_path / "snapshot.json"
    write_snapshot(snapshot, [
        {"service": name, "image_id": "sha256:" + "a" * 64, "freeze": freeze}
        for name in ("mcp", "mcp2")])
    marker = tmp_path / "scanner-calls"
    scanner = tmp_path / "pip-audit"
    scanner.write_text(f"#!{sys.executable}\n"
        "import json, pathlib, sys\n"
        f"marker=pathlib.Path({str(marker)!r})\n"
        "with marker.open('a') as out: out.write('scan\\n')\n"
        "pathlib.Path(sys.argv[sys.argv.index('--output') + 1]).write_text(json.dumps("
        "{'dependencies': [{'name': 'cryptography', 'version': '46.0.7', "
        "'vulns': [{'id': item} for item in "
        "['PYSEC-2026-3552', 'PYSEC-2026-3553', 'PYSEC-2026-3554', "
        "'GHSA-537c-gmf6-5ccf']]}]}))\n"
        "sys.exit(1)\n")
    scanner.chmod(0o700)
    run = subprocess.run([sys.executable, "scripts/run_stage492_scheduled_audit.py",
                          str(snapshot)], capture_output=True, text=True,
                         env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"]})
    assert run.returncode == 1
    assert marker.read_text().splitlines() == ["scan", "scan"]
    assert "running production packages differ" in run.stderr


def test_scheduled_audit_skips_invalid_freeze_but_scans_later_worker(tmp_path):
    snapshot = tmp_path / "snapshot.json"
    write_snapshot(snapshot, [
        {"service": "mcp", "image_id": "sha256:" + "a" * 64,
         "freeze": "bad @ https://example.invalid/x.whl\n"},
        {"service": "mcp2", "image_id": "sha256:" + "a" * 64,
         "freeze": "cryptography==46.0.7\n"}])
    marker = tmp_path / "scanner-ran"
    scanner = tmp_path / "pip-audit"
    scanner.write_text(f"#!{sys.executable}\n"
        "import json, pathlib, sys\n"
        f"pathlib.Path({str(marker)!r}).write_text('yes')\n"
        "pathlib.Path(sys.argv[sys.argv.index('--output') + 1]).write_text(json.dumps("
        "{'dependencies': [{'name': 'cryptography', 'version': '46.0.7', "
        "'vulns': [{'id': item} for item in "
        "['PYSEC-2026-3552', 'PYSEC-2026-3553', 'PYSEC-2026-3554', "
        "'GHSA-537c-gmf6-5ccf']]}]}))\n"
        "sys.exit(1)\n")
    scanner.chmod(0o700)
    run = subprocess.run([sys.executable, "scripts/run_stage492_scheduled_audit.py",
                          str(snapshot)], capture_output=True, text=True,
                         env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"]})
    assert run.returncode == 1
    assert marker.exists()
    assert "invalid pip freeze entry" in run.stderr


def test_scheduled_audit_attempts_every_worker_after_scanner_launch_error(
        tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    from scripts import run_stage492_scheduled_audit as scheduled

    snapshot = tmp_path / "snapshot.json"
    write_snapshot(snapshot, [
        {"service": name, "image_id": "sha256:" + "a" * 64,
         "freeze": "cryptography==46.0.7\n"}
        for name in ("mcp", "mcp2")])
    calls = []

    def unavailable(*args, **kwargs):
        calls.append(args)
        raise OSError("scanner unavailable")

    monkeypatch.setattr(scheduled.subprocess, "run", unavailable)
    with pytest.raises(ValueError, match="scanner"):
        scheduled.main(snapshot)
    assert len(calls) == 2


def test_scheduled_audit_rejects_truncated_worker_list_against_inventory(
        tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    from scripts import run_stage492_scheduled_audit as scheduled
    from types import SimpleNamespace

    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({
        "worker_inventory": [
            {"service": "mcp", "container_id": "a" * 12},
            {"service": "mcp2", "container_id": "b" * 12}],
        "workers": [{"service": "mcp", "container_id": "a" * 12,
                     "image_id": "sha256:" + "c" * 64,
                     "freeze": (root / "requirements/production-installed.txt").read_text()}]}))

    def fake_scan(command, **kwargs):
        Path(command[command.index("--output") + 1]).write_text("{}")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(scheduled.subprocess, "run", fake_scan)
    monkeypatch.setattr(scheduled, "verify", lambda *_: None)
    with pytest.raises(ValueError, match="incomplete worker inventory"):
        scheduled.main(snapshot)


def test_scheduled_audit_rejects_worker_container_id_mismatch_before_scan(
        tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    from scripts import run_stage492_scheduled_audit as scheduled

    snapshot = tmp_path / "snapshot.json"
    snapshot.write_text(json.dumps({
        "worker_inventory": [{"service": "mcp", "container_id": "a" * 12}],
        "workers": [{"service": "mcp", "container_id": "b" * 12,
                     "image_id": "sha256:" + "c" * 64,
                     "freeze": (root / "requirements/production-installed.txt").read_text()}]}))
    calls = []
    monkeypatch.setattr(scheduled.subprocess, "run", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(ValueError, match="container ID differs"):
        scheduled.main(snapshot)
    assert not calls


def test_scheduled_audit_rejects_unexpected_released_image_id(
        tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    from scripts import run_stage492_scheduled_audit as scheduled
    from types import SimpleNamespace

    snapshot = tmp_path / "snapshot.json"
    write_snapshot(snapshot, [
        {"service": name, "image_id": "sha256:" + "a" * 64,
         "freeze": (root / "requirements/production-installed.txt").read_text()}
        for name in ("mcp", "mcp2")])
    monkeypatch.setenv("PROD_AUDIT_EXPECTED_IMAGE_ID", "sha256:" + "b" * 64)
    scans = []

    def fake_scan(command, **kwargs):
        scans.append(command)
        Path(command[command.index("--output") + 1]).write_text("{}")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(scheduled.subprocess, "run", fake_scan)
    monkeypatch.setattr(scheduled, "verify", lambda *_: None)
    with pytest.raises(ValueError, match="released image ID"):
        scheduled.main(snapshot)
    assert len(scans) == 2, "all actual workers must still be scanned"


@pytest.mark.parametrize("released_image,accepted", [
    ("", False),
    ("sha256:bad", False),
    ("sha256:" + "a" * 64, True),
])
def test_scheduled_audit_requires_exact_released_image_id(
        tmp_path, monkeypatch, released_image, accepted):
    root = Path(__file__).resolve().parents[1]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    from scripts import run_stage492_scheduled_audit as scheduled
    from types import SimpleNamespace

    snapshot = tmp_path / "snapshot.json"
    write_snapshot(snapshot, [{"service": "mcp", "image_id": "sha256:" + "a" * 64,
                               "freeze": (root / "requirements/production-installed.txt").read_text()}])
    monkeypatch.setenv("PROD_AUDIT_EXPECTED_IMAGE_ID", released_image)

    def fake_scan(command, **kwargs):
        Path(command[command.index("--output") + 1]).write_text("{}")
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(scheduled.subprocess, "run", fake_scan)
    monkeypatch.setattr(scheduled, "verify", lambda *_: None)
    if accepted:
        scheduled.main(snapshot)
    else:
        with pytest.raises(ValueError, match="released image ID"):
            scheduled.main(snapshot)


def test_audit_policy_rejects_new_finding_and_inventory_drift(tmp_path):
    freeze = tmp_path / "freeze.txt"
    report = tmp_path / "audit.json"
    freeze.write_text("cryptography==46.0.7\npip==26.2.0\n")
    def check(vulns, packages=("cryptography", "pip")):
        report.write_text(json.dumps({"dependencies": [
            {"name": name, "version": "46.0.7" if name == "cryptography" else "26.2.0",
             "vulns": vulns if name == "cryptography" else []}
            for name in packages]}))
        try:
            verify(freeze, report, today=date(2026, 11, 22))
            return 0
        except (ValueError, json.JSONDecodeError):
            return 1
    known = [{"id": item} for item in (
        "PYSEC-2026-3552", "PYSEC-2026-3553", "PYSEC-2026-3554", "GHSA-537c-gmf6-5ccf")]
    assert check(known) == 0
    assert check(known + [{"id": "CVE-NEW"}]) != 0
    assert check(known, ("cryptography",)) != 0
    report.write_text("{}")
    with pytest.raises(ValueError):
        verify(freeze, report, today=date(2026, 11, 22))


def test_known_finding_policy_expires_at_boundary(tmp_path):
    freeze = tmp_path / "freeze.txt"
    report = tmp_path / "audit.json"
    freeze.write_text("cryptography==46.0.7\n")
    report.write_text(json.dumps({"dependencies": [{"name": "cryptography", "version": "46.0.7",
        "vulns": [{"id": item[2]} for item in sorted(KNOWN)]}]}))
    try:
        verify(freeze, report, today=date(2026, 12, 22))
    except ValueError as exc:
        assert "expired" in str(exc)
    else:
        raise AssertionError("expired policy must fail")
