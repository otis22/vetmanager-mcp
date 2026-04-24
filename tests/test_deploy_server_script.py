from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "deploy_server.sh"


def test_deploy_server_has_compose_helper_and_postgres_support() -> None:
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'compose() {' in script_text
    assert 'docker compose' in script_text
    assert 'pg_isready' in script_text
    assert 'compose run -T --rm mcp alembic upgrade head </dev/null' in script_text
    assert 'pre-deploy' in script_text
    assert 'compose up -d --force-recreate --no-build mcp' in script_text
    assert 'post_deploy_smoke_checks.sh' in script_text
