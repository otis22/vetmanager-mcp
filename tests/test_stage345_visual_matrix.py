"""The visual evidence gate fails on missing states and duplicate pixels."""
from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from scripts.capture_visual_matrix import required_scenes, required_keys, validate_matrix
from scripts import capture_visual_matrix
from scripts import prepare_visual_review


def _manifest(tmp_path: Path) -> list[dict[str, str]]:
    records = []
    for index, key in enumerate(required_keys()):
        path = tmp_path / f"{index}.png"
        path.write_bytes(f"fictional-image-{index}".encode())
        records.append({"key": key, "path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()})
    return records


def test_matrix_accepts_complete_unique_screenshots(tmp_path: Path) -> None:
    validate_matrix(_manifest(tmp_path))


def test_manifest_paths_are_portable_between_container_and_host(tmp_path: Path) -> None:
    records = _manifest(tmp_path)
    for record in records:
        record["path"] = Path(record["path"]).name
    validate_matrix(records, tmp_path)


def test_missing_each_required_state_is_red(tmp_path: Path) -> None:
    records = _manifest(tmp_path)
    for scene in required_scenes():
        broken = [item for item in records if not item["key"].startswith(scene + ":")]
        with pytest.raises(ValueError, match="missing"):
            validate_matrix(broken)


def test_duplicate_pixels_are_red(tmp_path: Path) -> None:
    records = _manifest(tmp_path)
    second = Path(records[1]["path"])
    second.write_bytes(Path(records[0]["path"]).read_bytes())
    records[1]["sha256"] = sha256(second.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="duplicate"):
        validate_matrix(records)


def test_stale_hash_is_red(tmp_path: Path) -> None:
    records = _manifest(tmp_path)
    records[0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash"):
        validate_matrix(records)


def test_new_code_state_without_scene_is_red(monkeypatch: pytest.MonkeyPatch) -> None:
    existing = capture_visual_matrix._code_states()
    monkeypatch.setattr(capture_visual_matrix, "_code_states", lambda: existing | {"new_status"})
    with pytest.raises(ValueError, match="unmapped"):
        required_scenes()


def test_only_implemented_themes_enter_matrix() -> None:
    assert all(":light:" in key for key in required_keys())


def test_review_sheet_covers_each_implemented_theme(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prepare_visual_review, "_themes", lambda scene: ("light", "dark"))
    assert "ready_bearer:dark:phone-first" in prepare_visual_review.scene_image_keys("ready_bearer")


def test_issued_scene_has_the_key_it_just_issued() -> None:
    html = capture_visual_matrix._pages()["issued"]
    assert 'data-activation-state="needs_client_use"' in html
    assert "Bearer-ключи всего</span>\n            <strong>1</strong>" in html


def test_scene_fixture_with_wrong_rendered_state_is_red() -> None:
    pages = capture_visual_matrix._pages()
    capture_visual_matrix.validate_pages(pages)
    broken = {**pages, "ready_oauth": pages["needs_token"]}
    with pytest.raises(ValueError, match="wrong rendered state"):
        capture_visual_matrix.validate_pages(broken)
