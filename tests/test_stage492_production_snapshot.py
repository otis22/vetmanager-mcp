from scripts import production_python_snapshot as subject


def test_snapshot_requires_every_compose_worker(monkeypatch):
    calls = []
    def fake(*args):
        calls.append(args)
        if args[-2:] == ("config", "--services"):
            return "mcp\nmcp2\npostgres\n"
        if args[-2:] == ("-q", "mcp"):
            return "a" * 12
        if args[-2:] == ("-q", "mcp2"):
            return ""
        if args[:2] == ("docker", "inspect"):
            return "sha256:" + "b" * 64
        if args[:2] == ("docker", "exec"):
            return "pip==26.2.0"
        return ""
    monkeypatch.setattr(subject, "run", fake)
    try:
        subject.snapshot()
    except ValueError as exc:
        assert "mcp2" in str(exc)
    else:
        raise AssertionError("missing worker must fail")
    assert ("docker", "compose", "--profile", "production", "ps", "-q", "mcp2") in calls
