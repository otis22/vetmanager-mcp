"""Recovery restores its own database even when a Docker stop fails midway."""

import subprocess
from types import SimpleNamespace

import pytest

import scripts.test_recovery_supervisor as supervisor


@pytest.mark.parametrize("failure", [None, "stop", "writer-timeout", "restore"])
def test_recovery_restore_and_child_cleanup(tmp_path, monkeypatch, failure):
    hook = tmp_path / "hook"
    hook.mkdir()
    calls = []

    class Child:
        returncode = None

        def __init__(self, *args, **kwargs):
            (hook / "entered").touch()

        def poll(self):
            if (hook / "restored").exists() and self.returncode is None:
                self.returncode = 0
            return self.returncode

        def terminate(self):
            calls.append("terminate-child")
            self.returncode = -15

        def wait(self, timeout):
            return self.returncode

    def run(command, **kwargs):
        if command[0:2] == ["docker", "stop"]:
            calls.append("stop-pg")
            if failure == "stop":
                raise subprocess.CalledProcessError(1, command)
            if failure != "writer-timeout":
                (hook / "write_done").touch()
        else:
            calls.append("restore-pg")
            if failure == "restore":
                raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(supervisor, "owned_container", lambda candidate, project: "exact-pg")
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: "candidate\n")
    monkeypatch.setattr(subprocess, "Popen", Child)
    monkeypatch.setattr(subprocess, "run", run)
    ticks = iter([0, 61])
    monkeypatch.setattr(supervisor, "time", SimpleNamespace(
        sleep=lambda _: None, monotonic=lambda: next(ticks)))
    if failure:
        with pytest.raises((subprocess.CalledProcessError, TimeoutError)):
            supervisor.supervise(["pytest"], ["compose"], "ours", hook, tmp_path / "run.log")
    else:
        assert supervisor.supervise(["pytest"], ["compose"], "ours", hook, tmp_path / "run.log") == 0
    assert calls[:2] == ["stop-pg", "restore-pg"]
    if failure == "restore":
        assert "terminate-child" in calls
        assert not (hook / "restored").exists()
    else:
        assert (hook / "restored").exists()
