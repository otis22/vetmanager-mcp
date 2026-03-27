from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "deploy_server.sh"


def test_deploy_server_has_compose_helper_and_postgres_support() -> None:
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'compose() {' in script_text
    assert 'docker compose' in script_text
    assert 'pg_isready' in script_text
    assert 'alembic upgrade head' in script_text
    assert 'pre-deploy' in script_text
