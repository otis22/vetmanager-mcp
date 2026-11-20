"""Kimi strong-review gate must save evidence and fail closed on tool use."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from argparse import Namespace
import pytest

SCRIPT = Path("scripts/run_kimi_review.py")


def test_review_agent_cannot_use_tools_or_subagents() -> None:
    agent = Path("scripts/kimi_review_agent.md").read_text()
    runner = SCRIPT.read_text()
    assert "tools: []" in agent and "subagents: []" in agent
    assert '"--agent-file", str(AGENT)' in runner
    assert '"--output-format", "stream-json"' in runner


def _run(tmp_path: Path, stream: str, *, prompt_file: Path | None = None) -> tuple[subprocess.CompletedProcess[str], Path]:
    fake = tmp_path / "kimi"
    fake.write_text("#!/usr/bin/env python3\nimport os,sys\n"
                    "print('2.5.3') if '--version' in sys.argv else print(os.environ['FAKE_STREAM'], end='')\n")
    fake.chmod(0o755)
    source = tmp_path / "source.md"
    source.write_text("# Example PRD\n")
    evidence = tmp_path / "evidence"
    (tmp_path / "kimi-home").mkdir()
    env = dict(os.environ, KIMI_BIN=str(fake), KIMI_CODE_HOME=str(tmp_path / "kimi-home"), FAKE_STREAM=stream)
    command = [str(SCRIPT), "--file", str(source), "--attempt", "1/3",
               "--evidence-dir", str(evidence)]
    if prompt_file:
        command.extend(["--prompt-file", str(prompt_file)])
    done = subprocess.run(command, text=True, capture_output=True, env=env)
    return done, evidence


def test_custom_prompt_keeps_required_verdict_schema(tmp_path: Path) -> None:
    prompt_file = tmp_path / "custom-prompt.txt"
    prompt_file.write_text("Review only. Check the requested change.\n")
    stream = json.dumps({"role": "assistant", "content": '{"findings":[]}'}) + "\n"
    done, evidence = _run(tmp_path, stream, prompt_file=prompt_file)
    assert done.returncode == 0, done.stderr
    prompt = next(evidence.rglob("*.prompt.txt")).read_text()
    assert prompt_file.read_text() in prompt
    assert "findings: [{severity, file, line, reason}]" in prompt
    assert "critical, high or medium" in prompt
    assert "No markdown." in prompt


def test_valid_kimi_verdict_saves_stream_and_metadata(tmp_path: Path) -> None:
    stream = '\n'.join([json.dumps({"role": "meta", "type": "system.version", "version": "2.5.3"}),
                        json.dumps({"role": "assistant", "content": '{"findings":[]}'})]) + '\n'
    done, evidence = _run(tmp_path, stream)
    assert done.returncode == 0, done.stderr
    prompt = next(evidence.rglob("*.prompt.txt")).read_text()
    assert prompt.count("findings: [{severity, file, line, reason}]") == 1
    assert "critical, high or medium" in prompt
    assert "No markdown." in prompt
    metadata = json.loads(next(evidence.rglob("*.metadata.json")).read_text())
    assert metadata["model"] == "kimi-code/k3"
    assert metadata["validator_exit"] == 0
    assert metadata["result_length"] == 15
    assert Path(metadata["stream_file"]).read_text() == stream
    assert json.loads(Path(metadata["verdict_file"]).read_text()) == {"findings": []}


def test_kimi_tool_call_is_not_a_valid_verdict(tmp_path: Path) -> None:
    stream = json.dumps({"role": "assistant", "content": '{"findings":[]}',
                         "tool_calls": [{"name": "Bash", "arguments": {"command": "touch x"}}]}) + '\n'
    done, evidence = _run(tmp_path, stream)
    assert done.returncode != 0
    metadata = json.loads(next(evidence.rglob("*.metadata.json")).read_text())
    assert metadata["outcome"] == "invalid_stream"
    assert metadata["validator_exit"] is None


def test_kimi_unknown_tool_event_shape_fails_closed(tmp_path: Path) -> None:
    stream = (json.dumps({"role": "meta", "type": "tool_call", "name": "Bash"}) + "\n"
              + json.dumps({"role": "assistant", "content": '{"findings":[]}'}) + "\n")
    done, evidence = _run(tmp_path, stream)
    assert done.returncode != 0
    assert json.loads(next(evidence.rglob("*.metadata.json")).read_text())["outcome"] == "invalid_stream"


def test_transport_retry_event_does_not_hide_valid_verdict(tmp_path: Path) -> None:
    stream = (json.dumps({"role": "meta", "type": "turn.step.retrying", "failed_attempt": 1,
                          "next_attempt": 2, "error_name": "upstream_unavailable"}) + "\n"
              + json.dumps({"role": "assistant", "content": '{"findings":[]}'}) + "\n")
    done, evidence = _run(tmp_path, stream)
    assert done.returncode == 0, done.stderr
    assert json.loads(next(evidence.rglob("*.verdict.json")).read_text()) == {"findings": []}


def test_kimi_empty_stream_fails_closed(tmp_path: Path) -> None:
    done, evidence = _run(tmp_path, "")
    assert done.returncode != 0
    assert json.loads(next(evidence.rglob("*.metadata.json")).read_text())["outcome"] == "invalid_stream"


def test_working_diff_rejects_omitted_large_untracked_file(monkeypatch, tmp_path: Path) -> None:
    from scripts import run_kimi_review as runner
    (tmp_path / "large.txt").write_text("x" * 100_001)
    monkeypatch.setattr(runner, "_git", lambda repo, *args: "large.txt\0" if "ls-files" in args else "diff")
    with pytest.raises(ValueError, match="cannot be included"):
        runner._object(Namespace(file=None, range=None), tmp_path)


def test_working_diff_includes_non_ascii_untracked_name(monkeypatch, tmp_path: Path) -> None:
    from scripts import run_kimi_review as runner
    (tmp_path / "этап-464.md").write_text("# review material\n")
    def git(repo, *args):
        if "ls-files" in args:
            return "этап-464.md\0" if "-z" in args else '"этап-464.md"\n'
        return "reviewed-sha" if "rev-parse" in args else "diff"
    monkeypatch.setattr(runner, "_git", git)
    kind, _, material = runner._object(Namespace(file=None, range=None), tmp_path)
    assert kind == "working_diff"
    assert "этап-464.md" in material
    assert "# review material" in material


def test_working_diff_rejects_untracked_symlink(monkeypatch, tmp_path: Path) -> None:
    from scripts import run_kimi_review as runner
    outside = tmp_path.parent / "outside-review-material"
    outside.write_text("outside checkout")
    (tmp_path / "linked.md").symlink_to(outside)
    monkeypatch.setattr(runner, "_git", lambda repo, *args: "linked.md\0" if "ls-files" in args else "diff")
    with pytest.raises(ValueError, match="cannot be included"):
        runner._object(Namespace(file=None, range=None), tmp_path)


def test_review_rejects_kimi_home_inside_checkout(tmp_path: Path) -> None:
    source = tmp_path / "source.md"
    source.write_text("# review\n")
    env = dict(os.environ, KIMI_CODE_HOME=str(Path.cwd()))
    done = subprocess.run([str(SCRIPT), "--file", str(source), "--attempt", "1/3",
                           "--evidence-dir", str(tmp_path / "evidence")],
                          text=True, capture_output=True, env=env)
    assert done.returncode != 0
    assert "isolated from checkout" in done.stderr
