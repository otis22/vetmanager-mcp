from __future__ import annotations

import importlib.util
from pathlib import Path


def load_privacy_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "check_reference_artifact_privacy.py"
    spec = importlib.util.spec_from_file_location("check_reference_artifact_privacy", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stage164_privacy_checker_reports_locations_without_printing_values(tmp_path, capsys):
    module = load_privacy_module()
    synthetic_email = "Stage164Synthetic@example.invalid"
    synthetic_hash = "abcd1234abcd1234abcd1234abcd1234"
    denylist = {
        module.sha256_text(module.normalize_email(synthetic_email)): "synthetic-email",
        module.sha256_text(module.normalize_passwd_hash(synthetic_hash)): "synthetic-passwd",
    }

    artifact = tmp_path / "artifact.json"
    artifact.write_text(
        f'{{"email":"{synthetic_email}","example":"{synthetic_hash}"}}\n',
        encoding="utf-8",
    )

    violations = module.find_violations(
        tmp_path,
        artifacts=(Path("artifact.json"),),
        denylist_sha256=denylist,
    )
    assert [violation.format(tmp_path) for violation in violations] == [
        "artifact.json:1 synthetic-email",
        "artifact.json:1 synthetic-passwd",
    ]

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    for rel_path in module.REFERENCE_ARTIFACTS:
        path = tmp_path / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    assert module.main(tmp_path) == 0
    output = capsys.readouterr()
    assert synthetic_email not in output.out + output.err
    assert synthetic_hash not in output.out + output.err


def test_stage164_privacy_checker_allows_reserved_placeholders():
    module = load_privacy_module()
    text = '{"email":"user@example.com","alt":"generated-user@example.test","passwd":"00000000000000000000000000000000"}'

    assert module.scan_text(Path("artifact.json"), text) == []


def test_stage164_privacy_checker_scans_committed_reference_artifacts():
    module = load_privacy_module()
    repo_root = Path(__file__).resolve().parents[1]

    assert module.find_violations(repo_root) == []


def test_stage164_privacy_checker_requires_scope_files(tmp_path):
    module = load_privacy_module()

    try:
        module.find_violations(tmp_path, artifacts=(Path("missing.json"),))
    except module.MissingReferenceArtifactError as exc:
        assert str(exc) == "missing.json"
    else:
        raise AssertionError("missing reference artifact did not fail the privacy gate")
