"""Three containers may share a log volume and all have PID 1."""

import logging
from datetime import datetime, timezone

from structured_logging import PersistentRotatingFileHandler


def test_handlers_on_one_volume_use_distinct_files_and_ignore_stale_probe(tmp_path, monkeypatch):
    monkeypatch.setattr("structured_logging.os.getpid", lambda: 1)
    (tmp_path / ".write-probe-1").write_text("stale")
    first = PersistentRotatingFileHandler(str(tmp_path))
    second = PersistentRotatingFileHandler(str(tmp_path))
    assert first._path_for_record("slot-a") != second._path_for_record("slot-b")
    for handler, message in ((first, "slot-a"), (second, "slot-b")):
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.emit(logging.makeLogRecord({"msg": message, "args": ()}))
    paths = list(tmp_path.glob("runtime-*.log"))
    assert len(paths) == 2
    assert {path.read_text().strip() for path in paths} == {"slot-a", "slot-b"}


def test_rotation_does_not_reuse_an_existing_number_after_pruning(tmp_path):
    handler = PersistentRotatingFileHandler(str(tmp_path))
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    existing = tmp_path / f"runtime-{day}-{handler._file_tag}-002.log"
    existing.write_text("previous\n")
    assert handler._next_path().name.endswith("-003.log")
