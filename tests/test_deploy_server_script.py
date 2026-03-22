from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "deploy_server.sh"


def test_deploy_server_prepares_writable_data_dir_and_consistent_compose_uid_gid() -> None:
    script_text = SCRIPT_PATH.read_text(encoding="utf-8")

    assert 'mkdir -p data' in script_text
    assert 'prepare_storage_permissions() {' in script_text
    assert 'chown -R ${UID_VAL}:${GID_VAL} /target' in script_text
    assert 'compose() {' in script_text
    assert 'env UID="${UID_VAL}" GID="${GID_VAL}" docker compose "$@"' in script_text
