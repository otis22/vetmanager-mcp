from pathlib import Path
import stat
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "deploy_server.sh"
SYNC_SCRIPT_PATH = REPO_ROOT / "scripts" / "sync_and_deploy_server.sh"
ENV_WRITER_PATH = REPO_ROOT / "scripts" / "update_env_secret.py"


def test_retired_deploy_scripts_fail_before_any_mutation() -> None:
    for path in (SCRIPT_PATH, SYNC_SCRIPT_PATH):
        script_text = path.read_text(encoding="utf-8")
        commands = "\n".join(line for line in script_text.splitlines() if not line.startswith("#"))
        assert "docker" not in commands and "rsync" not in commands
        result = subprocess.run(["bash", str(path)], capture_output=True, text=True)
        assert result.returncode == 1
        assert "disabled" in result.stderr


def _source_env_value(env_path: Path) -> str:
    result = subprocess.run(
        [
            "bash",
            "-c",
            'set -a; source "$1"; printf "%s" "${FEEDBACK_FINGERPRINT_PEPPER}"',
            "_",
            str(env_path),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout


def test_update_env_secret_round_trips_shell_sensitive_values(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    secret_path = tmp_path / "secret"
    original_mode = 0o640
    env_path.write_text("LOG_LEVEL=INFO\nFEEDBACK_FINGERPRINT_PEPPER=old\n", encoding="utf-8")
    env_path.chmod(original_mode)
    secret = " lead&|\\/'\"#$=trail "
    secret_path.write_text(secret, encoding="utf-8")

    subprocess.run(
        [sys.executable, str(ENV_WRITER_PATH), str(env_path), "FEEDBACK_FINGERPRINT_PEPPER", str(secret_path)],
        check=True,
    )

    assert _source_env_value(env_path) == secret
    assert stat.S_IMODE(env_path.stat().st_mode) == original_mode
    assert env_path.read_text(encoding="utf-8").count("FEEDBACK_FINGERPRINT_PEPPER=") == 1


def test_update_env_secret_writes_safe_values_without_shell_quote_nesting(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    secret_path = tmp_path / "secret"
    secret = "74b2e742784867a33865d2a6ee5801eafc7c1039d12a080d1d4fa08f2efb98fc"
    env_path.write_text(
        "LOG_LEVEL=INFO\n"
        f"FEEDBACK_FINGERPRINT_PEPPER='{secret}'\n",
        encoding="utf-8",
    )
    secret_path.write_text(secret, encoding="utf-8")

    for _ in range(2):
        subprocess.run(
            [
                sys.executable,
                str(ENV_WRITER_PATH),
                str(env_path),
                "FEEDBACK_FINGERPRINT_PEPPER",
                str(secret_path),
            ],
            check=True,
        )

    text = env_path.read_text(encoding="utf-8")
    assert f"FEEDBACK_FINGERPRINT_PEPPER={secret}\n" in text
    assert "'\"'\"'" not in text
    assert _source_env_value(env_path) == secret


def test_update_env_secret_rejects_newlines_and_preserves_existing_env(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    secret_path = tmp_path / "secret"
    original_text = "LOG_LEVEL=INFO\nFEEDBACK_FINGERPRINT_PEPPER=old\n"
    env_path.write_text(original_text, encoding="utf-8")
    secret_path.write_text("bad\nsecret", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(ENV_WRITER_PATH), str(env_path), "FEEDBACK_FINGERPRINT_PEPPER", str(secret_path)],
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "Secret value must not contain newline" in result.stderr
    assert env_path.read_text(encoding="utf-8") == original_text


def test_update_env_secret_creates_new_env_as_owner_only(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    secret_path = tmp_path / "secret"
    secret_path.write_text("secret-value", encoding="utf-8")

    subprocess.run(
        [sys.executable, str(ENV_WRITER_PATH), str(env_path), "FEEDBACK_FINGERPRINT_PEPPER", str(secret_path)],
        check=True,
    )

    assert _source_env_value(env_path) == "secret-value"
    assert stat.S_IMODE(env_path.stat().st_mode) == 0o600
