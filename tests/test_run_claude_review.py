"""Regression tests for external-review evidence capture."""

from __future__ import annotations

import json
import base64
import hashlib
from pathlib import Path
import subprocess
import struct
import time
import zlib


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


def _term_ignoring_claude(path: Path) -> None:
    path.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ ${1:-} == --version ]]; then echo 'fake-claude 1.0'; exit 0; fi\n"
        "trap '' TERM\n"
        "while :; do sleep 0.05; done\n",
    )
    path.chmod(0o755)


def _run(
    tmp_path: Path,
    envelope: str,
    exit_code: int = 0,
    evidence_dir: Path | None = None,
    review_file: Path | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
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
    command = [str(SCRIPT), "--repo", str(repo), "--attempt", "2/3"]
    if review_file is None:
        command.extend(["--range", "HEAD"])
    else:
        command.extend(["--file", str(review_file)])
    command.extend(["--prompt-file", str(prompt), "--schema-file", str(schema)])
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
    if review_file is None:
        assert git_args_log.read_text().strip().endswith("show --find-renames --find-copies --format=fuller HEAD")
    else:
        assert not git_args_log.exists()
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
    assert metadata["attempt"] == "2/3"
    assert metadata["review_kind"] == "git_range"
    assert metadata["review_target"] == "HEAD"
    assert metadata["review_range"] == "HEAD"
    assert metadata["repo"]
    assert metadata["evidence_dir"] == str(evidence)
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


def test_prd_file_review_saves_same_evidence_and_metadata(tmp_path: Path) -> None:
    prd = tmp_path / "stage.md"
    prd.write_text("# PRD\n\nContract text.\n")
    completed, evidence = _run(
        tmp_path,
        '{"is_error": false, "result": "{\\"findings\\":[]}"}',
        review_file=prd,
    )

    assert completed.returncode == 0
    metadata = json.loads(next(evidence.rglob("*.metadata.json")).read_text())
    assert metadata["review_kind"] == "file"
    assert metadata["review_target"] == str(prd)
    assert metadata["review_range"] is None
    assert metadata["attempt"] == "2/3"


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


def test_review_attempt_rejects_empty_verdict_with_diagnostic(tmp_path: Path) -> None:
    completed, evidence = _run(tmp_path, '{"is_error": false, "result": ""}')

    assert completed.returncode == 2
    assert "outcome=invalid_verdict" in completed.stderr
    metadata = json.loads(next(evidence.rglob("*.metadata.json")).read_text())
    assert metadata["outcome"] == "invalid_verdict"
    assert metadata["validator_exit"] == 2


def test_review_attempt_kills_cli_that_ignores_term_after_grace(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    prompt = tmp_path / "prompt.txt"
    schema = tmp_path / "schema.json"
    fake_claude = tmp_path / "claude"
    fake_git = tmp_path / "git"
    evidence = tmp_path / "evidence"
    prompt.write_text("Review only.\n")
    schema.write_text('{"type":"object"}\n')
    _term_ignoring_claude(fake_claude)
    _fake_git(fake_git)

    started = time.monotonic()
    completed = subprocess.run(
        [
            str(SCRIPT), "--repo", str(repo), "--range", "HEAD", "--attempt", "1/3",
            "--prompt-file", str(prompt), "--schema-file", str(schema),
            "--evidence-dir", str(evidence), "--timeout", "1", "--kill-grace", "0.1",
        ],
        text=True,
        capture_output=True,
        env={
            "PATH": f"{tmp_path}:/usr/local/bin:/usr/bin:/bin",
            "CLAUDE_BIN": str(fake_claude),
            "GIT_ARGS_LOG": str(tmp_path / "git-args.txt"),
            "XDG_DATA_HOME": str(tmp_path / "data"),
        },
        timeout=5,
    )

    assert time.monotonic() - started < 5
    assert completed.returncode != 0
    assert "outcome=timeout_killed_after_grace" in completed.stderr
    metadata = json.loads(next(evidence.rglob("*.metadata.json")).read_text())
    assert metadata["outcome"] == "timeout_killed_after_grace"
    assert metadata["kill_grace_seconds"] == 0.1


def test_review_attempt_saves_valid_non_object_json_envelopes(tmp_path: Path) -> None:
    for label, envelope in (("array", "[]"), ("null", "null")):
        completed, evidence = _run(tmp_path / label, envelope)

        assert completed.returncode == 2
        metadata_path = next(evidence.rglob("*.metadata.json"))
        metadata = json.loads(metadata_path.read_text())
        assert Path(metadata["envelope_file"]).read_text() == envelope
        assert metadata["cli_exit"] == 0
        assert metadata["validator_exit"] == 2
        assert metadata["subtype"] is None
        assert metadata["stop_reason"] is None
        assert metadata["output_tokens"] is None
        assert metadata["thinking_tokens"] is None
        assert metadata["result_length"] == 0


def test_default_evidence_root_uses_xdg_data_home(tmp_path: Path) -> None:
    completed, evidence = _run(tmp_path, '{"is_error": false, "result": "{\\"findings\\":[]}"}')

    assert completed.returncode == 0
    assert evidence == tmp_path / "data" / "vetmanager-mcp-review-evidence"
    assert oct((tmp_path / "data").stat().st_mode & 0o777) == "0o700"
    assert oct(evidence.stat().st_mode & 0o777) == "0o700"


def test_review_attempt_resolves_symlinked_evidence_parent(tmp_path: Path) -> None:
    real_data = tmp_path / "real-data"
    real_data.mkdir(mode=0o700)
    linked_data = tmp_path / "linked-data"
    linked_data.symlink_to(real_data, target_is_directory=True)
    evidence = linked_data / "vetmanager-mcp-review-evidence"

    completed, _ = _run(
        tmp_path,
        '{"is_error": false, "result": "{\\"findings\\":[]}"}',
        evidence_dir=evidence,
    )

    assert completed.returncode == 0
    resolved_evidence = real_data / "vetmanager-mcp-review-evidence"
    metadata_path = next(resolved_evidence.rglob("*.metadata.json"))
    metadata = json.loads(metadata_path.read_text())
    assert Path(metadata["envelope_file"]).is_relative_to(resolved_evidence)


def test_review_attempt_rejects_evidence_directory_inside_repository(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    prompt = tmp_path / "prompt.txt"
    schema = tmp_path / "schema.json"
    prompt.write_text("Review only.\n")
    schema.write_text('{"type":"object"}\n')

    completed = subprocess.run(
        [
            str(SCRIPT),
            "--repo",
            str(repo),
            "--range",
            "HEAD",
            "--attempt",
            "1/3",
            "--prompt-file",
            str(prompt),
            "--schema-file",
            str(schema),
            "--evidence-dir",
            str(repo / ".review-evidence"),
        ],
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 73
    assert "outside the repository working tree" in completed.stderr
    assert not (repo / ".review-evidence").exists()


def _png(path: Path, width: int = 8, height: int = 8, padding: int = 0) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    data = b"\x89PNG\r\n\x1a\n"
    data += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    data += chunk(b"IDAT", zlib.compress((b"\x00" + b"\x00\xe8\x4c" * min(width, 8)) * min(height, 8)))
    data += chunk(b"IEND", b"")
    path.write_bytes(data + b"x" * padding)
    return path.read_bytes()


def _run_image(tmp_path: Path, images: list[Path], stream: str | None = None) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    review = tmp_path / "review.md"
    review.write_text("Review only.\n")
    fake = tmp_path / "claude"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ ${1:-} == --version ]]; then echo fake-claude; exit 0; fi\n"
        "printf '%s\\n' \"$*\" > \"$ARGV_LOG\"\n"
        "cat > \"$STDIN_LOG\"\n"
        "printf '%s' \"$FAKE_STREAM\"\n"
    )
    fake.chmod(0o755)
    evidence = tmp_path / "data" / "vetmanager-mcp-review-evidence"
    result = {"type": "result", "is_error": False, "result": '{"findings":[]}', "subtype": "success"}
    completed = subprocess.run(
        [str(SCRIPT), "--repo", str(repo), "--file", str(review), "--attempt", "1/3",
         "--evidence-dir", str(evidence), *[arg for image in images for arg in ("--image", str(image))]],
        text=True,
        capture_output=True,
        env={"PATH": f"{tmp_path}:/usr/local/bin:/usr/bin:/bin", "CLAUDE_BIN": str(fake),
             "ARGV_LOG": str(tmp_path / "argv.txt"), "STDIN_LOG": str(tmp_path / "stdin.jsonl"),
             "FAKE_STREAM": stream if stream is not None else json.dumps(result) + "\n",
             "XDG_DATA_HOME": str(tmp_path / "data")},
    )
    return completed, evidence, tmp_path


def test_image_review_sends_pixels_and_records_hashes(tmp_path: Path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    pixels = [_png(first), _png(second)]
    completed, evidence, logs = _run_image(tmp_path, [first, second])

    assert completed.returncode == 0, completed.stderr
    argv = (logs / "argv.txt").read_text()
    assert "--input-format stream-json" in argv
    assert "--output-format stream-json" in argv
    assert "--verbose" in argv
    assert "--tools " in argv
    message = json.loads((logs / "stdin.jsonl").read_text())
    content = message["message"]["content"]
    assert message["type"] == "user"
    assert content[0]["type"] == "text"
    assert [base64.b64decode(item["source"]["data"]) for item in content[1:]] == pixels
    metadata = json.loads(next(evidence.rglob("*.metadata.json")).read_text())
    assert metadata["images"] == [
        {"path": str(path.resolve()), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        for path, raw in zip([first, second], pixels)
    ]
    assert metadata["stdin_lines"] == 1
    assert Path(metadata["stream_file"]).is_file()
    assert json.loads(Path(metadata["envelope_file"]).read_text())["result"] == '{"findings":[]}'


def test_image_review_rejects_invalid_input_before_cli(tmp_path: Path) -> None:
    good = tmp_path / "good.png"
    _png(good)
    wrong = tmp_path / "wrong.png"
    wrong.write_bytes(b"not a png")
    truncated = tmp_path / "truncated.png"
    truncated.write_bytes(good.read_bytes()[:24])
    huge = tmp_path / "huge.png"
    _png(huge, padding=2 * 1024 * 1024)
    wide = tmp_path / "wide.png"
    _png(wide, width=4097)
    for label, images in (("format", [wrong]), ("truncated", [truncated]), ("size", [huge]), ("dimensions", [wide]), ("count", [good] * 5)):
        case = tmp_path / label
        case.mkdir()
        completed, evidence, logs = _run_image(case, images)
        assert completed.returncode == 64, (label, completed.stderr)
        assert not (logs / "argv.txt").exists()
        assert not evidence.exists()


def test_image_review_rejects_missing_or_malformed_result(tmp_path: Path) -> None:
    for label, stream in (("missing", '{"type":"system"}\n'), ("broken", '{broken}\n'),
                          ("multiple", '{"type":"result"}\n{"type":"result"}\n')):
        case = tmp_path / label
        case.mkdir()
        picture = case / "sample.png"
        _png(picture)
        completed, evidence, _ = _run_image(case, [picture], stream)
        assert completed.returncode != 0, label
        metadata = json.loads(next(evidence.rglob("*.metadata.json")).read_text())
        assert metadata["outcome"] == "invalid_verdict"
        assert Path(metadata["envelope_file"]).read_bytes() == b""
        assert Path(metadata["stream_file"]).read_text() == stream
