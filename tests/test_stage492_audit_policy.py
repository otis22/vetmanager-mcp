import json
from datetime import date
import pytest

from scripts.check_stage492_audit import KNOWN, verify


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
