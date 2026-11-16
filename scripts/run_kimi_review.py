#!/usr/bin/env python3
"""Run one tool-free Kimi K3 review and preserve fail-closed evidence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

MODEL = "kimi-code/k3"
ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "scripts/kimi_review_agent.md"
VALIDATOR = ROOT / "scripts/validate_review_result.py"
DEFAULT_PROMPT = ("Review only. Do not edit files. Do not run commands. "
                  "Use only the supplied material. Find material correctness, security, "
                  "privacy, regression and acceptance issues. Return exactly one JSON object "
                  "with findings: [{severity, file, line, reason}] or {\"findings\":[]}. "
                  "Severity must be critical, high or medium. No markdown.\n")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, text=True,
                          capture_output=True).stdout


def _object(args: argparse.Namespace, repo: Path) -> tuple[str, str, str]:
    if args.file:
        path = Path(args.file).resolve(strict=True)
        return "file", str(path), path.read_text(encoding="utf-8")
    if args.range:
        return "git_range", args.range, _git(repo, "show", "--find-renames", "--format=fuller", args.range)
    diff = _git(repo, "diff", "--no-ext-diff", "HEAD")
    for name in filter(None, _git(repo, "ls-files", "-z", "--others", "--exclude-standard").split("\0")):
        path = repo / name
        if (path.is_symlink() or not path.is_file() or
                not path.resolve().is_relative_to(repo) or path.stat().st_size > 100_000):
            raise ValueError(f"untracked review file cannot be included: {name}")
        diff += f"\n=== UNTRACKED FILE: {name} ===\n" + path.read_text(encoding="utf-8")
    return "working_diff", _git(repo, "rev-parse", "HEAD").strip(), diff


def _parse_stream(raw: str) -> str:
    messages = []
    for line in raw.splitlines():
        event = json.loads(line)
        if not isinstance(event, dict) or event.get("tool_calls"):
            raise ValueError("tool call or malformed event")
        if event.get("role") == "meta":
            if event.get("type") not in {"system.version", "session.resume_hint", "turn.step.retrying"}:
                raise ValueError("unexpected meta event")
            continue
        if event.get("role") != "assistant" or event.get("type") is not None:
            raise ValueError("unexpected stream event")
        if event.get("role") == "assistant":
            content = event.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty assistant content")
            messages.append(content.strip())
    if len(messages) != 1:
        raise ValueError("expected exactly one assistant verdict")
    return messages[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    objects = parser.add_mutually_exclusive_group(required=True)
    objects.add_argument("--file")
    objects.add_argument("--range")
    objects.add_argument("--working-diff", action="store_true")
    parser.add_argument("--attempt", choices=("1/3", "2/3", "3/3"), required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--evidence-dir", type=Path, default=Path.home() / ".local/share/vetmanager-mcp-review-evidence")
    parser.add_argument("--prompt-file", type=Path)
    parser.add_argument("--context-file", type=Path, action="append", default=[])
    parser.add_argument("--timeout", type=int, default=1200)
    args = parser.parse_args()
    repo = args.repo.resolve(strict=True)
    evidence_root = args.evidence_dir.resolve()
    if evidence_root == repo or repo in evidence_root.parents:
        parser.error("evidence must be outside repository")
    kimi_home = os.environ.get("KIMI_CODE_HOME")
    if not kimi_home or not Path(kimi_home).is_dir():
        parser.error("KIMI_CODE_HOME must point to an existing isolated writable directory")
    isolated_home = Path(kimi_home).resolve()
    if (isolated_home == repo or repo in isolated_home.parents or
            isolated_home == evidence_root or evidence_root in isolated_home.parents or
            isolated_home in repo.parents or isolated_home in evidence_root.parents):
        parser.error("KIMI_CODE_HOME must be isolated from checkout and evidence")
    if args.timeout < 1:
        parser.error("timeout must be positive")
    kind, target, material = _object(args, repo)
    for context in args.context_file:
        path = context.resolve(strict=True)
        if not path.is_file() or path.stat().st_size > 100_000:
            parser.error("context file must be a regular file of at most 100 KiB")
        material += f"\n=== CONTEXT FILE: {path} ===\n" + path.read_text(encoding="utf-8")
    if not material.strip():
        parser.error("review object is empty")
    prompt = args.prompt_file.read_text(encoding="utf-8") if args.prompt_file else DEFAULT_PROMPT
    prompt += f"\nOBJECT: {kind} {target}\n=== MATERIAL ===\n{material}\n"
    evidence_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(evidence_root, 0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    evidence = evidence_root / f"kimi-{kind}-{stamp}-{uuid.uuid4().hex[:8]}-attempt-{args.attempt.replace('/', '-of-')}"
    evidence.mkdir(mode=0o700)
    prefix = evidence / "kimi-review"
    prompt_file = prefix.with_suffix(".prompt.txt")
    stream_file = prefix.with_suffix(".stream.jsonl")
    stderr_file = prefix.with_suffix(".stderr.txt")
    verdict_file = prefix.with_suffix(".verdict.json")
    metadata_file = prefix.with_suffix(".metadata.json")
    prompt_file.write_text(prompt, encoding="utf-8")
    empty_skills = evidence / "empty-skills"
    empty_skills.mkdir(mode=0o700)
    binary = os.environ.get("KIMI_BIN", "kimi")
    start = time.time()
    try:
        version = subprocess.run([binary, "--version"], capture_output=True, text=True,
                                 timeout=min(args.timeout, 10)).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        version = "unavailable"
    command = [binary, "-m", MODEL, "--agent-file", str(AGENT), "--skills-dir", str(empty_skills),
               "-p", prompt, "--output-format", "stream-json"]
    try:
        run = subprocess.run(command, cwd=repo, capture_output=True, text=True, timeout=args.timeout)
        cli_exit, stdout, stderr = run.returncode, run.stdout, run.stderr
    except OSError as exc:
        cli_exit, stdout, stderr = 127, "", f"CLI launch failed: {type(exc).__name__} (errno={exc.errno})\n"
    except subprocess.TimeoutExpired as exc:
        cli_exit = 124
        stdout = (exc.stdout or b"").decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = (exc.stderr or b"").decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        stderr += "\nCLI timeout\n"
    stream_file.write_text(stdout, encoding="utf-8")
    stderr_file.write_text(stderr, encoding="utf-8")
    result = ""
    validator_exit = None
    outcome = "cli_error" if cli_exit else "invalid_stream"
    if cli_exit == 0:
        try:
            result = _parse_stream(stdout)
        except (ValueError, json.JSONDecodeError):
            pass
        else:
            valid = subprocess.run([str(VALIDATOR), "--plain"], input=result,
                                   text=True, capture_output=True)
            validator_exit = valid.returncode
            if valid.returncode == 0:
                verdict_file.write_text(valid.stdout, encoding="utf-8")
                outcome = "valid_verdict"
            else:
                (prefix.with_suffix(".validator.stderr.txt")).write_text(valid.stderr, encoding="utf-8")
                outcome = "invalid_verdict"
    try:
        reviewed_sha = _git(repo, "rev-parse", "HEAD").strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        reviewed_sha = None
    metadata = {"started_at": datetime.fromtimestamp(start, timezone.utc).isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(), "model": MODEL,
                "cli_version": version, "cli_exit": cli_exit, "validator_exit": validator_exit,
                "outcome": outcome, "attempt": args.attempt, "review_kind": kind,
                "review_target": target, "reviewed_sha": reviewed_sha,
                "context_files": [str(path.resolve()) for path in args.context_file],
                "prompt_file": str(prompt_file), "stream_file": str(stream_file),
                "stderr_file": str(stderr_file), "verdict_file": str(verdict_file) if outcome == "valid_verdict" else None,
                "result_length": len(result), "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                "agent_file": str(AGENT), "agent_sha256": hashlib.sha256(AGENT.read_bytes()).hexdigest(),
                "tool_calls_allowed": False}
    metadata_file.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"review evidence: {metadata_file}; outcome={outcome}; cli_exit={cli_exit}; validator_exit={validator_exit}; len(result)={len(result)}")
    return 0 if outcome == "valid_verdict" else (cli_exit or validator_exit or 2)


if __name__ == "__main__":
    sys.exit(main())
