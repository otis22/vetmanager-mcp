import json
import subprocess

from scripts import production_python_snapshot as subject


def test_snapshot_does_not_resolve_orphan_worker_by_service_name(monkeypatch):
    rows = [{"Service": name, "ID": letter * 12, "State": "running"}
            for name, letter in (("mcp", "a"), ("mcp2", "b"), ("mcp3", "c"))]

    def fake(*args):
        if args[-2:] == ("config", "--services"):
            return "mcp"
        if args[-3:] == ("ps", "--all", "--services") or args[-4:] == (
                "ps", "--filter", "status=running", "--services"):
            return "mcp\nmcp2\nmcp3"
        if args[-2:] == ("--format", "json"):
            return "\n".join(json.dumps(row) for row in rows)
        if args[-2:] == ("-q", "mcp2"):
            raise subprocess.CalledProcessError(1, args)
        if args[-2:] == ("-q", "mcp") or args[-2:] == ("-q", "mcp3"):
            return "a" * 12
        if args[:2] == ("docker", "inspect"):
            return "sha256:" + args[-1][0] * 64
        if args[:2] == ("docker", "exec"):
            return "pip==26.2.0"
        raise AssertionError(args)

    monkeypatch.setattr(subject, "run", fake)
    assert [worker["service"] for worker in subject.snapshot()["workers"]] == [
        "mcp", "mcp2", "mcp3"]


def test_snapshot_discovers_all_running_workers_when_config_is_incomplete(monkeypatch):
    calls = []

    def fake(*args):
        calls.append(args)
        if args[-2:] == ("config", "--services"):
            return "mcp\n"
        if args[-2:] == ("--format", "json"):
            return "\n".join(json.dumps({"Service": name, "ID": letter * 12,
                                         "State": "running"})
                             for name, letter in (("mcp", "a"), ("mcp2", "b"),
                                                  ("mcp3", "c"), ("postgres", "d")))
        if args[:2] == ("docker", "inspect"):
            return "sha256:" + args[-1][0] * 64
        if args[:2] == ("docker", "exec"):
            return "pip==" + str(ord(args[2][0]) - ord("a") + 1)
        raise AssertionError(args)

    monkeypatch.setattr(subject, "run", fake)
    result = subject.snapshot()
    workers = result["workers"]
    assert result["worker_inventory"] == [
        {"service": name, "container_id": letter * 12}
        for name, letter in (("mcp", "a"), ("mcp2", "b"), ("mcp3", "c"))]
    assert [worker["service"] for worker in workers] == ["mcp", "mcp2", "mcp3"]
    assert [worker["freeze"] for worker in workers] == ["pip==1\n", "pip==2\n", "pip==3\n"]
    assert [worker["image_id"] for worker in workers] == [
        "sha256:" + letter * 64 for letter in "abc"]
    assert [worker["container_id"] for worker in workers] == [letter * 12 for letter in "abc"]
    assert not any(args[-2:] == ("config", "--services") for args in calls)
    assert not any(args[-2:] == ("-q", "mcp2") for args in calls)


def test_snapshot_requires_every_compose_worker(monkeypatch):
    calls = []
    def fake(*args):
        calls.append(args)
        if args[-2:] == ("--format", "json"):
            names = ("mcp", "mcp2") if "--all" in args else ("mcp",)
            return "\n".join(json.dumps({"Service": name, "ID": letter * 12,
                                         "State": "running"})
                             for name, letter in zip(names, "ab"))
        raise AssertionError(args)
    monkeypatch.setattr(subject, "run", fake)
    try:
        subject.snapshot()
    except ValueError as exc:
        assert "mcp2" in str(exc)
    else:
        raise AssertionError("missing worker must fail")
    assert any(args[-2:] == ("--format", "json") and "--all" in args for args in calls)


def test_snapshot_rejects_stopped_or_duplicate_worker(monkeypatch):
    def fake(*args):
        if args[-2:] == ("--format", "json"):
            names = ("mcp", "mcp2") if "--all" in args else ("mcp",)
            return "\n".join(json.dumps({"Service": name, "ID": letter * 12,
                                         "State": "running"})
                             for name, letter in zip(names, "ab"))
        raise AssertionError(args)

    monkeypatch.setattr(subject, "run", fake)
    try:
        subject.snapshot()
    except ValueError as exc:
        assert "running" in str(exc)
    else:
        raise AssertionError("stopped worker must fail")

    monkeypatch.setattr(subject, "run", lambda *args: "\n".join(
        json.dumps({"Service": "mcp", "ID": letter * 12, "State": "running"})
        for letter in "ab"))
    try:
        subject.snapshot()
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate worker must fail")
