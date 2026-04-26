from pathlib import Path
import stat
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "deploy_server.sh"
SYNC_SCRIPT_PATH = REPO_ROOT / "scripts" / "sync_and_deploy_server.sh"
ENV_WRITER_PATH = REPO_ROOT / "scripts" / "update_env_secret.py"


def test_deploy_server_has_compose_helper_and_postgres_support() -> None:
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'compose() {' in script_text
    assert 'docker compose' in script_text
    assert 'pg_isready' in script_text
    assert 'compose run -T --rm mcp alembic upgrade head </dev/null' in script_text
    assert 'pre-deploy' in script_text
    assert 'compose up -d --force-recreate --no-build mcp' in script_text
    assert 'post_deploy_smoke_checks.sh' in script_text


def test_deploy_server_feedback_pepper_not_passed_via_argv_or_sed() -> None:
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert "FEEDBACK_FINGERPRINT_PEPPER_ARG" not in script_text
    assert "DEPLOY_FEEDBACK_FINGERPRINT_PEPPER" not in script_text
    assert "sed -i" not in script_text
    assert "update_env_secret.py" in script_text
    assert "mktemp" in script_text
    assert "cleanup_upload_pepper" in script_text
    assert "__FEEDBACK_PEPPER_FILE__=" in script_text
    assert "bash -c" in script_text
    assert "bash -lc" not in script_text
    assert "trap cleanup_remote_pepper EXIT INT TERM" in script_text
    assert "printenv FEEDBACK_FINGERPRINT_PEPPER" not in script_text
    assert 'echo "$FEEDBACK_FINGERPRINT_PEPPER"' not in script_text
    assert "set -x" not in script_text
    assert "bash -x" not in script_text
    assert script_text.index("git pull --ff-only") < script_text.index("python3 scripts/update_env_secret.py")


def test_sync_deploy_forwards_feedback_pepper_contract() -> None:
    script_text = SYNC_SCRIPT_PATH.read_text(encoding="utf-8")

    assert "FEEDBACK_FINGERPRINT_PEPPER is required" in script_text
    assert 'FEEDBACK_FINGERPRINT_PEPPER="${FEEDBACK_FINGERPRINT_PEPPER}"' in script_text


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
