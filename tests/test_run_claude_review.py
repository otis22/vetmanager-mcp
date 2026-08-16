"""Regression tests for external-review evidence capture."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess


SCRIPT = Path("scripts/run_claude_review.sh")


def test_default_prompt_retains_thinking_constraint() -> None:
    assert "Think briefly, then return JSON matching the schema immediately." in SCRIPT.read_text()


def _fake_git(path: Path) -> None:
    path.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' \"$*\" > \"$GIT_ARGS_LOG\"\n"
        "printf '%s\\n' 'commit deadbeef' 'diff --git a/file.txt b/file.txt' '+after'\n",
    )
    path.chmod(0o755)


def _fake_claude(path: Path, exit_code: int) -> None:
    path.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ ${1:-} == --version ]]; then echo 'fake-claude 1.0'; exit 0; fi\n"
        "printf '%s' \"$FAKE_ENVELOPE\"\n"
        "printf 'fake stderr' >&2\n"
        f"exit {exit_code}\n",
    )
    path.chmod(0o755)


def _run(
    tmp_path: Path,
    envelope: str,
    exit_code: int = 0,
    evidence_dir: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    prompt = tmp_path / "prompt.txt"
    schema = tmp_path / "schema.json"
    fake_claude = tmp_path / "claude"
    fake_git = tmp_path / "git"
    git_args_log = tmp_path / "git-args.txt"
    evidence = evidence_dir or tmp_path / "data" / "vetmanager-mcp-review-evidence"
    prompt.write_text("Review only. Think briefly, then return JSON matching the schema immediately.\n")
    schema.write_text('{"type":"object"}\n')
    _fake_claude(fake_claude, exit_code)
    _fake_git(fake_git)
    command = [
        str(SCRIPT), "--repo", str(repo), "--range", "HEAD", "--attempt", "2/3",
        "--prompt-file", str(prompt), "--schema-file", str(schema),
    ]
    if evidence_dir is not None:
        command.extend(["--evidence-dir", str(evidence)])
    completed = subprocess.run(
        command,
        text=True,
        capture_output=True,
        env={
            "PATH": f"{tmp_path}:/usr/local/bin:/usr/bin:/bin",
            "CLAUDE_BIN": str(fake_claude),
            "FAKE_ENVELOPE": envelope,
            "GIT_ARGS_LOG": str(git_args_log),
            "XDG_DATA_HOME": str(tmp_path / "data"),
        },
    )
    assert git_args_log.read_text().strip().endswith("show --find-renames --find-copies --format=fuller HEAD")
    return completed, evidence


def test_review_attempt_saves_complete_success_evidence(tmp_path: Path) -> None:
    envelope = '{\n  "is_error": false, "subtype": "success", "stop_reason": "tool_use", "num_turns": 2, "result": "{\\"findings\\":[]}", "usage": {"output_tokens": 274, "output_tokens_details": {"thinking_tokens": 61}}\n}\n'
    completed, evidence = _run(tmp_path, envelope)

    assert completed.returncode == 0
    metadata_path = next(evidence.rglob("*.metadata.json"))
    metadata = json.loads(metadata_path.read_text())
    envelope_path = Path(metadata["envelope_file"])
    assert envelope_path.read_text() == envelope
    assert Path(metadata["prompt_file"]).read_text().startswith("Review only.")
    assert Path(metadata["schema_file"]).read_text() == '{"type":"object"}\n'
    assert Path(metadata["stderr_file"]).read_text() == "fake stderr"
    assert "attempt-2-of-3" in envelope_path.name
    assert metadata["review_range"] == "HEAD"
    assert metadata["stdin_bytes"] > 0
    assert metadata["stdin_lines"] > 1
    assert metadata["cli_version"] == "fake-claude 1.0"
    assert metadata["duration_ms"] >= 0
    assert metadata["validator_exit"] == 0
    assert json.loads(Path(metadata["verdict_file"]).read_text()) == {"findings": []}
    assert metadata["subtype"] == "success"
    assert metadata["stop_reason"] == "tool_use"
    assert metadata["output_tokens"] == 274
    assert metadata["thinking_tokens"] == 61
    assert metadata["result_length"] == 15


def test_review_attempt_saves_empty_failed_stdout_and_metadata(tmp_path: Path) -> None:
    completed, evidence = _run(tmp_path, "", exit_code=7)

    assert completed.returncode == 7
    metadata_path = next(evidence.rglob("*.metadata.json"))
    metadata = json.loads(metadata_path.read_text())
    assert Path(metadata["envelope_file"]).read_bytes() == b""
    assert metadata["cli_exit"] == 7
    assert metadata["validator_exit"] is None
    assert metadata["subtype"] is None
    assert metadata["stop_reason"] is None
    assert metadata["output_tokens"] is None
    assert metadata["thinking_tokens"] is None
    assert metadata["result_length"] == 0


def test_default_evidence_root_uses_xdg_data_home(tmp_path: Path) -> None:
    completed, evidence = _run(tmp_path, '{"is_error": false, "result": "{\\"findings\\":[]}"}')

    assert completed.returncode == 0
    assert evidence == tmp_path / "data" / "vetmanager-mcp-review-evidence"
    assert oct(evidence.stat().st_mode & 0o777) == "0o700"
