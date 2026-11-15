"""Stage 465 guards for the addressable diagnostic command."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import run_scoped_diagnostic as diagnostic


def test_diagnostic_rejects_broad_scope(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="single owning file or node"):
        diagnostic.build_command("tests/", tmp_path)


def test_diagnostic_preserves_pytest_failure(monkeypatch, tmp_path: Path) -> None:
    for name in diagnostic._CREDENTIAL_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(diagnostic.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=1, stdout="", stderr="",
    ))
    assert diagnostic.run("tests/test_warning_policy.py::test_default_suite_warning_policy_requires_zero_warnings", tmp_path) == 1


def test_diagnostic_rejects_real_scope_and_credentials(monkeypatch, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="offline nodes only"):
        diagnostic.build_command("tests/test_stage436_live.py", tmp_path)
    monkeypatch.setenv("TEST_API_KEY", "stage465-canary")
    with pytest.raises(ValueError, match="without test credentials") as error:
        diagnostic.build_command("tests/test_warning_policy.py", tmp_path)
    assert "stage465-canary" not in str(error.value)


def test_diagnostic_redacts_canary_and_url_from_evidence(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STAGE465_SYNTHETIC_TOKEN", "stage465-canary-secret")
    for name in diagnostic._CREDENTIAL_ENV:
        monkeypatch.delenv(name, raising=False)
    leaked = ("token=stage465-canary-secret https://example.invalid/path?q=private "
              "Authorization: Bearer independently-generated-canary "
              "Bearer standalone-canary access_token=assignment-canary "
              "{'Authorization': 'Bearer quoted-canary'}")
    monkeypatch.setattr(diagnostic.subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=1, stdout=leaked, stderr=leaked,
    ))
    assert diagnostic.run("tests/test_warning_policy.py", tmp_path) == 1
    output = (tmp_path / "stdout.txt").read_text() + (tmp_path / "stderr.txt").read_text()
    assert "stage465-canary-secret" not in output
    assert "example.invalid" not in output
    assert "independently-generated-canary" not in output
    for secret in ("standalone-canary", "assignment-canary", "quoted-canary"):
        assert secret not in output
