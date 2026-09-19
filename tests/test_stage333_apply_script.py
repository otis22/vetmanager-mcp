"""Этап 333: supervisor migration supports KI-45 with and without fingerprint."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "apply_stage332_known_issues_prod.sh"
FINGERPRINT = "a" * 64
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
        "title": "Report export file download is unauthorized",
        "related_tool": "get_report_export_download",
        "error_fingerprint_hash": state["report_fingerprint"],
        "match_rules_json": {}, "agent_playbook_json": {},
    }
    state["report_link"] = 81
    print("created known_issue #81 from report #80")
elif " move-fingerprint " in command:
    match = re.search(r'move-fingerprint (\d+) (\d+) --expected-fingerprint ([0-9a-f]+)', command)
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


def _run(tmp_path: Path, before: dict, *, mode: str = "apply", live: dict | None = None):
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
        state_file.write_text(json.dumps({
            "commands": [], "remote_files": {}, "report_fingerprint": FINGERPRINT,
            "report_link": 45, "ki45": live or before, "target": None,
        }), encoding="utf-8")
    env = os.environ.copy()
    env.update({
        "CONFIRM_STAGE332_PROD": "apply-stage-332", "STAGE332_MODE": mode,
        "STAGE332_BEFORE_STATE_FILE": str(before_file),
        "STAGE332_401_ID_FILE": str(tmp_path / "target-id.txt"),
        "XDG_DATA_HOME": str(tmp_path / "data"), "FAKE_SSH_STATE": str(state_file),
        "PATH": f"{fake_bin}:{env['PATH']}",
    })
    result = subprocess.run([str(SCRIPT)], cwd=ROOT, env=env, text=True,
                            capture_output=True, check=False)
    return result, json.loads(state_file.read_text()), before_file.read_bytes()


@pytest.mark.parametrize("source_fingerprint", [None, FINGERPRINT], ids=["absent", "present"])
def test_apply_retry_and_rollback_cover_both_source_states(tmp_path, source_fingerprint):
    before = _before(source_fingerprint)
    original = json.dumps(before).encode()
    applied, state, saved = _run(tmp_path, before)
    assert applied.returncode == 0, applied.stderr
    assert saved == original
    assert state["ki45"]["error_fingerprint_hash"] is None
    assert state["target"]["error_fingerprint_hash"] == FINGERPRINT
    moves = [command for command in state["commands"] if " move-fingerprint " in command]
    assert bool(moves) is (source_fingerprint is not None)
    assert not any("set-related-tool" in command for command in state["commands"])

    retried, state, _ = _run(tmp_path, before)
    assert retried.returncode == 0, retried.stderr
    assert sum(" promote 80 " in command for command in state["commands"]) == 1

    rolled_back, state, _ = _run(tmp_path, before, mode="rollback")
    assert rolled_back.returncode == 0, rolled_back.stderr
    assert state["ki45"] == before
    assert state["report_link"] == 45
    assert state["target"]["status"] == "wontfix"
    expected_target = None if source_fingerprint else FINGERPRINT
    assert state["target"]["error_fingerprint_hash"] == expected_target

    rolled_back_again, state, _ = _run(tmp_path, before, mode="rollback")
    assert rolled_back_again.returncode == 0, rolled_back_again.stderr

    reapplied, state, _ = _run(tmp_path, before)
    assert reapplied.returncode == 0, reapplied.stderr
    assert state["target"]["status"] == "workaround_available"
    assert state["report_link"] == 81


def test_mismatched_source_fails_before_any_write(tmp_path):
    before = _before("b" * 64)
    failed, state, _ = _run(tmp_path, before)
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
