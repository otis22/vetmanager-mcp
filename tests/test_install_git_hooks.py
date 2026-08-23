"""Regression coverage for generated local Git hooks."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "install_git_hooks.sh"


def test_installer_backs_up_existing_pre_push_and_generates_detached_packaging_guard(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    scripts_dir = repo / "scripts"
    hooks_dir = repo / ".git" / "hooks"
    scripts_dir.mkdir(parents=True)
    hooks_dir.mkdir(parents=True)
    shutil.copy2(SCRIPT, scripts_dir / SCRIPT.name)
    existing_hook = hooks_dir / "pre-push"
    existing_hook.write_text("#!/usr/bin/env bash\necho existing\n", encoding="utf-8")

    completed = subprocess.run(
        ["bash", str(scripts_dir / SCRIPT.name)],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    )

    backups = list(hooks_dir.glob("pre-push.bak.*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "#!/usr/bin/env bash\necho existing\n"
    generated_hook = existing_hook.read_text(encoding="utf-8")
    assert "docker compose --profile test run --rm -T test pytest -q tests/test_packaging_metadata.py < /dev/null" in generated_hook
    assert "Backed up existing pre-push hook" in completed.stdout
