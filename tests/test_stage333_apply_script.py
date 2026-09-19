"""Этап 333: supervisor migration supports KI-45 with and without fingerprint."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess

import pytest

import agent_feedback_service as feedback


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "apply_stage332_known_issues_prod.sh"
FINGERPRINT = "hmac-sha256:" + "a" * 64
LEGACY_FINGERPRINT = "c" * 64
REAL_BEFORE_STATE = {
    "id": 45,
    "status": "workaround_available",
    "title": "[seed:report-export-not-available] Report cannot be exported over REST",
    "related_tool": None,
    "error_fingerprint_hash": None,
    "match_rules_json": {
        "version": 1,
        "all": [{"field": "normalized_error_text", "op": "contains_any",
                 "value": ["getting report export file failed", "not rest-exportable"]}],
    },
    "agent_playbook_json": {
        "version": 1,
        "summary": "Vetmanager did not produce the export file for this report.",
        "steps": [
            "Check the export state with get_report_ai_job before asking for the file again.",
            "If the report is not REST-exportable, build the same data through a Report AI job instead.",
        ],
        "do_not_do": ["Do not poll the download endpoint in a loop — the file is not being prepared."],
        "recommended_tool_sequence": ["get_report_ai_job", "create_report_ai_job"],
        "safe_to_retry": False,
    },
}

FAKE_SSH = r'''#!/usr/bin/env python3
import json, os, re, sys
from pathlib import Path

state_path = Path(os.environ["FAKE_SSH_STATE"])
state = json.loads(state_path.read_text())
command = sys.argv[-1]
state["commands"].append(command)

def save(): state_path.write_text(json.dumps(state, sort_keys=True))
def fail(message):
    save(); print(message, file=sys.stderr); raise SystemExit(65)

upload = re.search(r'cat > (/tmp/[^" ]+)', command)
if upload:
    state["remote_files"][upload.group(1)] = sys.stdin.read()
elif "validate-known-issue-config" in command:
    print("known issue config valid")
elif "show-feedback-fingerprint 80" in command:
    print(json.dumps({"id": 80, "known_issue_id": state["report_link"],
                      "error_fingerprint_hash": state["report_fingerprint"]}))
elif "show-known-issue-config" in command:
    issue_id = int(re.search(r'show-known-issue-config (\d+)', command).group(1))
    issue = state["ki45"] if issue_id == 45 else state.get("target")
    if issue is None or issue["id"] != issue_id: fail(f"Known issue not found: {issue_id}")
    print(json.dumps(issue, sort_keys=True))
elif " promote 80 " in command:
    if state.get("target") is not None: fail("duplicate promote")
    state["target"] = {
        "id": 81, "status": "workaround_available",
        "title": state.get("promote_target_title", "Report export file download is unauthorized"),
        "related_tool": "get_report_export_download",
        "error_fingerprint_hash": state["report_fingerprint"],
        "match_rules_json": json.loads(state["remote_files"]["/tmp/stage332-download-401-match-rules.json"]),
        "agent_playbook_json": json.loads(state["remote_files"]["/tmp/stage332-download-401-playbook.json"]),
    }
    state["report_link"] = 81
    print("created known_issue #81 from report #80")
    if state.pop("fail_after_promote", False):
        save(); raise SystemExit(75)
elif " move-fingerprint " in command:
    match = re.search(r'move-fingerprint (\d+) (\d+) --expected-fingerprint ((?:hmac-sha256:)?[0-9A-Fa-f]{64})', command)
    source_id, target_id, expected = int(match.group(1)), int(match.group(2)), match.group(3)
    source = state["ki45"] if source_id == 45 else state["target"]
    target = state["ki45"] if target_id == 45 else state["target"]
    fingerprint = source["error_fingerprint_hash"]
    if not fingerprint:
        if target["error_fingerprint_hash"] == expected: print("fingerprint already moved")
        else: fail("source has no expected fingerprint")
    elif fingerprint != expected: fail("source fingerprint mismatch")
    elif target["error_fingerprint_hash"] not in (None, fingerprint): fail("different fingerprints")
    else:
        target["error_fingerprint_hash"] = fingerprint
        source["error_fingerprint_hash"] = None
        print("fingerprint moved")
elif " set-match-rules 45 " in command:
    state["ki45"]["match_rules_json"] = json.loads(state["remote_files"]["/tmp/stage332-ki45-match-rules.json"])
elif " set-playbook 45 " in command:
    state["ki45"]["agent_playbook_json"] = json.loads(state["remote_files"]["/tmp/stage332-ki45-playbook.json"])
elif "restore-known-issue-config 45" in command:
    state["ki45"] = json.loads(state["remote_files"]["/tmp/stage332-ki45-before.json"])
elif " mark " in command:
    match = re.search(r' mark (\d+) (\w+)', command)
    issue_id, status = int(match.group(1)), match.group(2)
    (state["ki45"] if issue_id == 45 else state["target"])["status"] = status
elif " link " in command:
    state["report_link"] = int(re.search(r' link (\d+) 80', command).group(1))
elif "match-effectiveness" in command:
    print("match effectiveness ok")
elif "rm -f" in command:
    pass
else:
    fail("unexpected command: " + command)
save()
'''


def _before(fingerprint: str | None) -> dict:
    value = json.loads(json.dumps(REAL_BEFORE_STATE))
    value["error_fingerprint_hash"] = fingerprint
    return value


def _run(
    tmp_path: Path,
    before: dict,
    *,
    mode: str = "apply",
    live: dict | None = None,
    report_link: int = 45,
    issue_id: int | None = None,
    promote_target_title: str | None = None,
    report_fingerprint: str | None = FINGERPRINT,
    fail_after_promote: bool = False,
):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir(exist_ok=True)
    fake_ssh = fake_bin / "ssh"
    fake_ssh.write_text(FAKE_SSH, encoding="utf-8")
    fake_ssh.chmod(0o755)
    before_file = tmp_path / "ki45-before.json"
    if not before_file.exists():
        before_file.write_text(json.dumps(before), encoding="utf-8")
    state_file = tmp_path / "state.json"
    if not state_file.exists():
        initial_state = {
            "commands": [], "remote_files": {}, "report_fingerprint": report_fingerprint,
            "report_link": report_link, "ki45": live or before, "target": None,
            "fail_after_promote": fail_after_promote,
        }
        if promote_target_title is not None:
            initial_state["promote_target_title"] = promote_target_title
        state_file.write_text(json.dumps(initial_state), encoding="utf-8")
    env = os.environ.copy()
    env.update({
        "CONFIRM_STAGE332_PROD": "apply-stage-332", "STAGE332_MODE": mode,
        "STAGE332_BEFORE_STATE_FILE": str(before_file),
        "STAGE332_401_ID_FILE": str(tmp_path / "target-id.txt"),
        "STAGE332_401_STATE_FILE": str(tmp_path / "migration-state.txt"),
        "XDG_DATA_HOME": str(tmp_path / "data"), "FAKE_SSH_STATE": str(state_file),
        "PATH": f"{fake_bin}:{env['PATH']}",
    })
    if issue_id is not None:
        env["STAGE332_401_ISSUE_ID"] = str(issue_id)
    result = subprocess.run([str(SCRIPT)], cwd=ROOT, env=env, text=True,
                            capture_output=True, check=False)
    return result, json.loads(state_file.read_text()), before_file.read_bytes()


@pytest.mark.parametrize(
    ("source_fingerprint", "report_fingerprint"),
    [(None, None), (FINGERPRINT, FINGERPRINT), (None, FINGERPRINT)],
    ids=["both-absent", "both-present", "report-only"],
)
def test_apply_retry_and_rollback_cover_consistent_source_states(
    tmp_path, source_fingerprint, report_fingerprint,
):
    before = _before(source_fingerprint)
    original = json.dumps(before).encode()
    applied, state, saved = _run(
        tmp_path, before, report_fingerprint=report_fingerprint,
    )
    assert applied.returncode == 0, applied.stderr
    assert saved == original
    assert state["ki45"]["error_fingerprint_hash"] is None
    assert state["target"]["error_fingerprint_hash"] == report_fingerprint
    assert state["target"]["status"] == "workaround_available"
    assert state["target"]["related_tool"] == "get_report_export_download"
    assert state["target"]["match_rules_json"]["version"] == 1
    assert state["target"]["agent_playbook_json"]["version"] == 1
    moves = [command for command in state["commands"] if " move-fingerprint " in command]
    assert bool(moves) is (source_fingerprint is not None)
    assert not any("set-related-tool" in command for command in state["commands"])

    retried, state, _ = _run(
        tmp_path, before, report_fingerprint=report_fingerprint,
    )
    assert retried.returncode == 0, retried.stderr
    assert sum(" promote 80 " in command for command in state["commands"]) == 1

    rolled_back, state, _ = _run(
        tmp_path, before, mode="rollback", report_fingerprint=report_fingerprint,
    )
    assert rolled_back.returncode == 0, rolled_back.stderr
    assert state["ki45"] == before
    assert state["report_link"] == 45
    assert state["target"]["status"] == "wontfix"
    expected_rollback_target = None if source_fingerprint is not None else report_fingerprint
    assert state["target"]["error_fingerprint_hash"] == expected_rollback_target

    rolled_back_again, state, _ = _run(
        tmp_path, before, mode="rollback", report_fingerprint=report_fingerprint,
    )
    assert rolled_back_again.returncode == 0, rolled_back_again.stderr

    reapplied, state, _ = _run(
        tmp_path, before, report_fingerprint=report_fingerprint,
    )
    assert reapplied.returncode == 0, reapplied.stderr
    assert state["target"]["status"] == "workaround_available"
    assert state["report_link"] == 81


@pytest.mark.parametrize(
    ("source_fingerprint", "report_fingerprint"),
    [("hmac-sha256:" + "b" * 64, FINGERPRINT), (FINGERPRINT, None)],
    ids=["different", "source-only"],
)
def test_inconsistent_fingerprints_fail_before_any_write(
    tmp_path, source_fingerprint, report_fingerprint,
):
    before = _before(source_fingerprint)
    failed, state, _ = _run(
        tmp_path, before, report_fingerprint=report_fingerprint,
    )
    assert failed.returncode != 0
    writes = (" promote 80 ", " move-fingerprint ", " set-match-rules ",
              " set-playbook ", " mark ", " link ")
    assert not any(any(marker in command for marker in writes) for command in state["commands"])
    assert state["ki45"] == before
    assert state["target"] is None


def test_first_apply_rejects_live_ki45_drift(tmp_path):
    before = _before(None)
    live = dict(before, status="acknowledged")
    failed, state, _ = _run(tmp_path, before, live=live)
    assert failed.returncode != 0
    assert state["target"] is None
    assert state["ki45"] == live


def test_first_apply_rejects_report_linked_to_an_unexpected_issue(tmp_path):
    before = _before(None)
    failed, state, _ = _run(
        tmp_path, before, report_link=999, report_fingerprint=None,
    )
    assert failed.returncode != 0
    assert "migration state is missing" in failed.stderr
    assert "STAGE332_401_ISSUE_ID" not in failed.stderr
    assert state["target"] is None
    assert state["ki45"] == before


def test_invalid_override_id_is_not_persisted(tmp_path):
    before = _before(None)
    failed, state, _ = _run(tmp_path, before, issue_id=45)
    assert failed.returncode != 0
    assert not (tmp_path / "target-id.txt").exists()
    assert state["commands"] == []


def test_post_promote_identity_failure_is_recoverable_without_duplicate(tmp_path):
    before = _before(None)
    failed, state, _ = _run(
        tmp_path, before, promote_target_title="unexpected target",
        report_fingerprint=None,
    )
    assert failed.returncode != 0
    assert (tmp_path / "target-id.txt").read_text().strip() == "81"
    assert sum(" promote 80 " in command for command in state["commands"]) == 1

    retried, state, _ = _run(tmp_path, before, report_fingerprint=None)
    assert retried.returncode != 0
    assert "state is unexpected" in retried.stderr
    assert sum(" promote 80 " in command for command in state["commands"]) == 1


@pytest.mark.parametrize("report_fingerprint", [None, FINGERPRINT], ids=["null-null", "report-only"])
def test_source_null_recovers_crash_after_promote_without_duplicate(
    tmp_path, report_fingerprint,
):
    before = _before(None)
    interrupted, state, _ = _run(
        tmp_path, before, report_fingerprint=report_fingerprint, fail_after_promote=True,
    )
    assert interrupted.returncode != 0
    assert state["report_link"] == 81
    assert not (tmp_path / "target-id.txt").exists()

    retried, state, _ = _run(tmp_path, before, report_fingerprint=report_fingerprint)
    assert retried.returncode == 0, retried.stderr
    assert (tmp_path / "target-id.txt").read_text().strip() == "81"
    assert (tmp_path / "migration-state.txt").read_text().strip() == (
        "stage334-null-null-v1:target:81"
    )
    assert sum(" promote 80 " in command for command in state["commands"]) == 1


def test_null_null_crash_can_rollback_then_reapply_without_duplicate(tmp_path):
    before = _before(None)
    interrupted, state, _ = _run(
        tmp_path, before, report_fingerprint=None, fail_after_promote=True,
    )
    assert interrupted.returncode != 0
    assert state["report_link"] == 81

    rolled_back, state, _ = _run(
        tmp_path, before, mode="rollback", report_fingerprint=None,
    )
    assert rolled_back.returncode == 0, rolled_back.stderr
    assert (tmp_path / "target-id.txt").read_text().strip() == "81"
    assert (tmp_path / "migration-state.txt").read_text().strip() == (
        "stage334-null-null-v1:target:81"
    )

    reapplied, state, _ = _run(tmp_path, before, report_fingerprint=None)
    assert reapplied.returncode == 0, reapplied.stderr
    assert state["report_link"] == 81
    assert sum(" promote 80 " in command for command in state["commands"]) == 1


def test_null_null_prepared_marker_before_promote_is_safe_to_retry(tmp_path):
    before = _before(None)
    (tmp_path / "migration-state.txt").write_text(
        "stage334-null-null-v1:prepared\n", encoding="utf-8",
    )
    applied, state, _ = _run(tmp_path, before, report_fingerprint=None)
    assert applied.returncode == 0, applied.stderr
    assert state["report_link"] == 81
    assert sum(" promote 80 " in command for command in state["commands"]) == 1


def test_null_null_active_target_without_report_link_fails_closed(tmp_path):
    before = _before(None)
    applied, state, _ = _run(tmp_path, before, report_fingerprint=None)
    assert applied.returncode == 0, applied.stderr
    state["report_link"] = 45
    (tmp_path / "state.json").write_text(json.dumps(state), encoding="utf-8")

    failed, state, _ = _run(tmp_path, before, report_fingerprint=None)
    assert failed.returncode != 0
    assert "state is unexpected" in failed.stderr
    assert state["report_link"] == 45


def test_null_null_invalid_migration_marker_fails_before_remote_access(tmp_path):
    before = _before(None)
    (tmp_path / "migration-state.txt").write_text("unknown\n", encoding="utf-8")
    failed, state, _ = _run(tmp_path, before, report_fingerprint=None)
    assert failed.returncode != 0
    assert "migration state is invalid" in failed.stderr
    assert state["commands"] == [
        "cd /opt/vetmanager-mcp && docker compose --profile production exec -T mcp "
        "python scripts/triage_agent_feedback.py show-feedback-fingerprint 80"
    ]


def test_migration_script_takes_an_exclusive_local_lock():
    script = SCRIPT.read_text(encoding="utf-8")
    assert "flock -n 9" in script
    assert "download-401-migration.lock" in script


def _script_fingerprint_regex() -> str:
    script = SCRIPT.read_text(encoding="utf-8")
    assignments = re.findall(r"^fingerprint_regex='([^']+)'$", script, re.MULTILINE)
    assert len(assignments) == 1
    assert script.count('"$fingerprint_regex"') == 2
    assert script.count("=~ $fingerprint_regex") == 1
    assert "[[:xdigit:]]{64}" not in script
    assert 'r"[0-9A-Fa-f]{64}"' not in script
    return assignments[0]


def test_service_fingerprint_passes_the_scripts_single_regex_and_bash_path(
    tmp_path, monkeypatch,
):
    monkeypatch.setenv("FEEDBACK_FINGERPRINT_PEPPER", "stage335-test-pepper")
    incident = feedback.build_incident_from_exception(
        "get_report_export_download",
        RuntimeError("Getting report export file failed HTTP 401."),
    )
    fingerprint = feedback.build_error_fingerprint_hash(incident)

    assert fingerprint is not None
    assert re.fullmatch(_script_fingerprint_regex(), fingerprint)
    applied, state, _ = _run(
        tmp_path, _before(fingerprint), report_fingerprint=fingerprint,
    )
    assert applied.returncode == 0, applied.stderr
    assert state["target"]["error_fingerprint_hash"] == fingerprint


def test_legacy_bare_fingerprint_remains_supported(tmp_path):
    applied, state, _ = _run(
        tmp_path, _before(LEGACY_FINGERPRINT),
        report_fingerprint=LEGACY_FINGERPRINT,
    )
    assert applied.returncode == 0, applied.stderr
    assert state["target"]["error_fingerprint_hash"] == LEGACY_FINGERPRINT


def test_report_only_retry_rejects_target_fingerprint_drift_before_write(tmp_path):
    before = _before(None)
    applied, state, _ = _run(tmp_path, before, report_fingerprint=FINGERPRINT)
    assert applied.returncode == 0, applied.stderr
    state["target"]["error_fingerprint_hash"] = "hmac-sha256:" + "b" * 64
    commands_before = len(state["commands"])
    (tmp_path / "state.json").write_text(json.dumps(state), encoding="utf-8")

    failed, state, _ = _run(tmp_path, before, report_fingerprint=FINGERPRINT)
    assert failed.returncode != 0
    assert "state is unexpected" in failed.stderr
    writes = (" move-fingerprint ", " set-match-rules ", " set-playbook ", " mark ", " link ")
    assert not any(
        any(marker in command for marker in writes)
        for command in state["commands"][commands_before:]
    )


@pytest.mark.parametrize(
    "fingerprint",
    ["sha256:" + "a" * 64, "hmac-sha256:" + "g" * 64, "hmac-sha256:" + "a" * 63],
)
def test_malformed_source_fingerprint_fails_before_remote_access(tmp_path, fingerprint):
    failed, state, _ = _run(
        tmp_path, _before(fingerprint), report_fingerprint=fingerprint,
    )
    assert failed.returncode != 0
    assert state["commands"] == []


def test_rollback_rejects_before_state_missing_a_nullable_field(tmp_path):
    before = _before(None)
    applied, state, _ = _run(tmp_path, before, report_fingerprint=None)
    assert applied.returncode == 0, applied.stderr
    malformed = dict(before)
    malformed.pop("related_tool")
    (tmp_path / "ki45-before.json").write_text(json.dumps(malformed), encoding="utf-8")
    commands_before = len(state["commands"])

    failed, state, _ = _run(
        tmp_path, malformed, mode="rollback", report_fingerprint=None,
    )
    assert failed.returncode != 0
    assert "before-state is invalid" in failed.stderr
    assert not any(
        "restore-known-issue-config" in command
        for command in state["commands"][commands_before:]
    )
