"""Three containers may share a log volume and all have PID 1."""

import logging
import os
import threading
from datetime import datetime, timezone

import structured_logging
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


def test_size_budget_prunes_oldest_same_day_file_across_slots(tmp_path, monkeypatch):
    handler = PersistentRotatingFileHandler(str(tmp_path))
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    older = tmp_path / f"runtime-{day}-z-old-001.log"
    newer = tmp_path / f"runtime-{day}-a-new-001.log"
    older.write_text("old!", encoding="utf-8")
    newer.write_text("new!", encoding="utf-8")
    os.utime(older, ns=(1, 1))
    os.utime(newer, ns=(2, 2))
    monkeypatch.setattr(structured_logging, "PERSISTENT_LOG_MAX_TOTAL_BYTES", 4)
    handler._prune()
    assert not older.exists() and newer.exists()


def test_other_slot_cannot_write_while_shared_prune_is_active(tmp_path):
    first = PersistentRotatingFileHandler(str(tmp_path))
    second = PersistentRotatingFileHandler(str(tmp_path))
    entered = threading.Event()
    release = threading.Event()
    second_done = threading.Event()

    def paused_prune():
        entered.set()
        assert release.wait(2)

    first._prune = paused_prune
    record = lambda value: logging.makeLogRecord({"msg": value, "args": ()})
    first_thread = threading.Thread(target=lambda: first.emit(record("first")))
    second_thread = threading.Thread(
        target=lambda: (second.emit(record("second")), second_done.set()))
    first_thread.start()
    try:
        assert entered.wait(2)
        second_thread.start()
        assert not second_done.wait(.1)
    finally:
        release.set()
        first_thread.join(2)
        second_thread.join(2)
    assert second_done.is_set()
