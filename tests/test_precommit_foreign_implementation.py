"""Regression coverage for the stage 232 staged-addition Git hook."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "scripts" / "git-hooks" / "pre-commit"

_CODE_MARKERS = (
    ":" + ":model()",
    "C" + "HttpException",
    "N" + "Database::",
    "json_decode(" + "$this",
    "array_merge(" + "$",
    "-" + ">doRest",
)


def _stub_git(bin_dir: Path, staged: dict[str, str | None]) -> Path:
    """Provide the two diff forms the hook needs; the test image has no Git."""
    bin_dir.mkdir(parents=True)
    contents_dir = bin_dir / "contents"
    contents_dir.mkdir()
    for path, content in staged.items():
        if content is not None:
            target = contents_dir / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    script = bin_dir / "git"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json\n"
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "staged = json.loads(os.environ['FAKE_STAGED'])\n"
        "if args == ['rev-parse', '--show-toplevel']:\n"
        "    print(os.environ['FAKE_REPO'])\n"
        "elif (args[:2] == ['diff', '--cached'] or args[:3] == ['--literal-pathspecs', 'diff', '--cached']) and '--name-only' in args:\n"
        "    if '-z' in args:\n"
        "        sys.stdout.buffer.write(b''.join(name.encode() + b'\\0' for name in staged))\n"
        "    else:\n"
        "        names = [name for name in staged if name.startswith('tools/') and name.endswith('.py') or name == 'prompts.py']\n"
        "        sys.stdout.write('\\n'.join(names))\n"
        "elif args[:2] == ['diff', '--cached'] or args[:3] == ['--literal-pathspecs', 'diff', '--cached']:\n"
        "    name = args[-1]\n"
        "    content = staged[name]\n"
        "    if content is None:\n"
        "        context = os.environ['FAKE_CONTEXT_MARKER']\n"
        "        sys.stdout.write(f'diff --git a/x b/x\\n@@ -1 +1 @@\\n {context}\\n')\n"
        "    else:\n"
        "        lines = Path(os.environ['FAKE_CONTENTS'], name).read_bytes().splitlines(keepends=True)\n"
        "        sys.stdout.buffer.write(b'diff --git a/x b/x\\n@@ -0,0 +1 @@\\n')\n"
        "        sys.stdout.buffer.write(b''.join(b'+' + line for line in lines))\n"
        "else:\n"
        "    raise SystemExit(f'unexpected git arguments: {args!r}')\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return contents_dir


def _run(
    tmp_path: Path,
    staged: dict[str, str | None],
    *,
    context_marker: str = "context only",
    lint_exit: int = 0,
    **extra_env: str,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    contents_dir = _stub_git(bin_dir, staged)
    lint_script = tmp_path / "scripts" / "lint_api_contracts.py"
    lint_script.parent.mkdir(exist_ok=True)
    lint_script.write_text(
        "import os\n"
        "print('stub lint finding')\n"
        "raise SystemExit(int(os.environ['FAKE_LINT_EXIT']))\n",
        encoding="utf-8",
    )
    env = dict(
        os.environ,
        PATH=f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        FAKE_REPO=str(tmp_path),
        FAKE_STAGED=json.dumps(staged),
        FAKE_CONTENTS=str(contents_dir),
        FAKE_CONTEXT_MARKER=context_marker,
        FAKE_LINT_EXIT=str(lint_exit),
        **extra_env,
    )
    return subprocess.run(
        ["bash", str(HOOK)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )


@pytest.mark.parametrize("marker", _CODE_MARKERS)
def test_added_php_implementation_marker_blocks_commit(tmp_path: Path, marker: str) -> None:
    result = _run(tmp_path, {"new.php": f"$value = {marker};\n"})
    assert result.returncode == 1
    assert "new.php adds prohibited implementation marker" in result.stderr
    assert marker not in result.stderr


def test_added_level_two_class_name_is_allowed(tmp_path: Path) -> None:
    class_name = "Legacy" + "Controller::method"
    result = _run(tmp_path, {"notes.md": f"Source: {class_name}\n"})
    assert result.returncode == 0


def test_added_observable_api_error_quote_is_allowed(tmp_path: Path) -> None:
    error_quote = "Ent" + "ity\\MedicalCard\\Diagnoses::$diagnoses"
    result = _run(tmp_path, {"notes.md": f"API error: {error_quote}\n"})
    assert result.returncode == 0


def test_existing_marker_outside_added_lines_is_ignored(tmp_path: Path) -> None:
    result = _run(tmp_path, {"Roadmap.md": None}, context_marker=_CODE_MARKERS[0])
    assert result.returncode == 0


def test_file_name_with_space_is_checked(tmp_path: Path) -> None:
    result = _run(tmp_path, {"new notes.php": _CODE_MARKERS[0] + "\n"})
    assert result.returncode == 1
    assert "new notes.php" in result.stderr


def test_api_contract_lint_remains_blocking_for_staged_tool_code(tmp_path: Path) -> None:
    result = _run(tmp_path, {"tools/new.py": "payload = {}\n"}, lint_exit=1)
    assert result.returncode == 1
    assert "lint_api_contracts.py found high/blocker findings" in result.stderr


@pytest.mark.parametrize(
    "marker",
    (
        ":" + ":model ( )",
        "N" + "Database ::",
        "json_decode" + " ( $this",
        "array_merge" + " ( $",
        "-" + " > doRest",
    ),
)
def test_added_php_marker_with_whitespace_blocks_commit(tmp_path: Path, marker: str) -> None:
    result = _run(tmp_path, {"new.php": marker + "\n"})
    assert result.returncode == 1


def test_bypass_applies_to_exactly_one_file(tmp_path: Path) -> None:
    staged = {
        "allowed.php": _CODE_MARKERS[0] + "\n",
        "other.php": _CODE_MARKERS[1] + "\n",
    }
    result = _run(tmp_path, staged, ALLOW_FOREIGN_IMPLEMENTATION_FILE="allowed.php")
    assert result.returncode == 1
    assert "other.php" in result.stderr

    only_allowed = _run(
        tmp_path / "only_allowed",
        {"allowed.php": _CODE_MARKERS[0] + "\n"},
        ALLOW_FOREIGN_IMPLEMENTATION_FILE="allowed.php",
    )
    assert only_allowed.returncode == 0


def test_blocked_commit_leaves_no_temporary_files(tmp_path: Path) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    result = _run(
        tmp_path,
        {"new.php": _CODE_MARKERS[0] + "\n"},
        TMPDIR=str(scratch),
    )
    assert result.returncode == 1
    assert list(scratch.iterdir()) == []
