"""The first cutover must stage code aside and pin a bind-free old image."""

from pathlib import Path

import pytest
import yaml

from scripts import stage385_release


def test_release_sync_never_deletes_the_live_checkout(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(stage385_release, "_run", lambda args: commands.append(args))
    monkeypatch.setattr(stage385_release, "_verified_checkout_sha", lambda checkout: "a" * 40)
    stage385_release.stage_remote_release(
        Path("/checkout"), "test@host", "/opt/vetmanager-mcp", "a" * 40)
    rsync = next(args for args in commands if args[0] == "rsync")
    assert "--delete" not in rsync
    assert rsync[-1] == "test@host:/opt/vetmanager-mcp/releases/" + "a" * 40 + "/"
    assert rsync[-1] != "test@host:/opt/vetmanager-mcp/"
    assert "--exclude=.env" in rsync
    assert any(args[0] == "ssh" and "mkdir -m 700" in args[-1] for args in commands)


def test_release_rejects_dirty_or_mislabeled_checkout(tmp_path, monkeypatch):
    head = "b" * 40
    status = ""
    monkeypatch.setattr(stage385_release, "_git_output",
                        lambda checkout, *args: head if args[0] == "rev-parse" else status)
    monkeypatch.setattr(stage385_release, "_run", lambda args: pytest.fail("remote command started"))
    with pytest.raises(ValueError, match="SHA"):
        stage385_release.stage_remote_release(tmp_path, "test@host", "/opt/vetmanager-mcp", "a" * 40)
    status = " M probe.txt"
    with pytest.raises(ValueError, match="clean"):
        stage385_release.stage_remote_release(tmp_path, "test@host", "/opt/vetmanager-mcp", head)


def test_rollback_manifest_has_one_pinned_slot_and_no_source_bind(tmp_path):
    source = yaml.safe_load((Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text())
    source["services"]["mcp"]["volumes"].append(".:/app")
    source["services"]["mcp"]["volumes"].append("./tools:/app/tools:ro")
    image_id = "sha256:" + "a" * 64
    manifest = stage385_release.make_rollback_manifest(source, image_id, "stage385probe")
    services = manifest["services"]
    assert "mcp" in services and "mcp2" not in services and "mcp3" not in services
    assert services["mcp"]["image"] == image_id
    assert "build" not in services["mcp"]
    assert all(not str(volume).endswith(":/app") for volume in services["mcp"]["volumes"])
    assert "./tools:/app/tools:ro" not in services["mcp"]["volumes"]
    assert "mcp-data:/app/data" in services["mcp"]["volumes"]
    assert "MCP_WORKER_SLOTS=1" in services["mcp"]["environment"]
    assert manifest["name"] == "stage385probe"
    assert manifest["volumes"]["mcp-data"] == {
        "external": True, "name": "stage385probe_mcp-data"}
    output = tmp_path / "rollback.yml"
    stage385_release.write_rollback_manifest(output, manifest)
    with pytest.raises(FileExistsError):
        stage385_release.write_rollback_manifest(output, manifest)
