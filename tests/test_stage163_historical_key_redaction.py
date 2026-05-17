from __future__ import annotations

import importlib.util
from pathlib import Path


def load_checker_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "check_no_historical_api_key_literal.py"
    spec = importlib.util.spec_from_file_location("check_no_historical_api_key_literal", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stage163_checker_reports_synthetic_token_location_without_printing_value(
    tmp_path,
    capsys,
    monkeypatch,
):
    module = load_checker_module()
    synthetic_token = "stage163_synthetic_api_key_1234567890"
    target_sha256 = module.token_digest(synthetic_token)

    notes_path = tmp_path / "notes.md"
    notes_path.write_text(f"key={synthetic_token}\n", encoding="utf-8")
    monkeypatch.setattr(module, "candidate_files", lambda repo_root: [notes_path])

    assert module.find_matching_locations(tmp_path, target_sha256) == ["notes.md:1"]

    assert module.main(tmp_path, target_sha256) == 1
    output = capsys.readouterr()
    assert synthetic_token not in output.out + output.err
    assert "notes.md:1" in output.err


def test_stage163_checker_ignores_nonmatching_token_like_values(tmp_path, monkeypatch):
    module = load_checker_module()
    synthetic_token = "stage163_synthetic_api_key_1234567890"
    target_sha256 = module.token_digest(synthetic_token)

    notes_path = tmp_path / "notes.md"
    notes_path.write_text(
        "other=stage163_synthetic_api_key_0987654321\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "candidate_files", lambda repo_root: [notes_path])

    assert module.find_matching_locations(tmp_path, target_sha256) == []
