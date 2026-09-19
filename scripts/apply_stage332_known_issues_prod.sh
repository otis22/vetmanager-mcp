#!/usr/bin/env bash
# Supervisor-only production application for Stage 332. Do not run from agents.
# Run only after Deploy Prod of this commit succeeds.

set -euo pipefail

if [[ ${CONFIRM_STAGE332_PROD:-} != apply-stage-332 ]]; then
    printf '%s\n' 'Refusing production change. Set CONFIRM_STAGE332_PROD=apply-stage-332.' >&2
    exit 64
fi

repo_dir=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
fixture_dir=$repo_dir/artifacts/known-issues/stage-332
data_root=${XDG_DATA_HOME:-${HOME:?HOME is required}/.local/share}
evidence_dir=$data_root/vetmanager-mcp-review-evidence/stage-332
(umask 077; mkdir -p "$evidence_dir")
chmod 700 "$evidence_dir"
before_file=${STAGE332_BEFORE_STATE_FILE:-$evidence_dir/ki45-before.json}
id_file=${STAGE332_401_ID_FILE:-$evidence_dir/download-401-known-issue-id.txt}
mode=${STAGE332_MODE:-apply}

remote=(ssh root@212.193.59.219)
compose='cd /opt/vetmanager-mcp && docker compose --profile production exec -T mcp'

if [[ $mode != apply && $mode != rollback ]]; then
    printf '%s\n' 'STAGE332_MODE must be apply or rollback.' >&2
    exit 64
fi

if [[ $mode == rollback && ! -s $before_file ]]; then
    printf '%s\n' 'Rollback before-state is missing; refusing to guess production state.' >&2
    exit 65
fi
if [[ $mode == apply && ! -s $before_file ]]; then
    before_tmp=$(mktemp "$evidence_dir/ki45-before.XXXXXX")
    "${remote[@]}" "$compose python scripts/triage_agent_feedback.py show-known-issue-config 45" >"$before_tmp"
    test -s "$before_tmp"
    chmod 600 "$before_tmp"
    mv -n "$before_tmp" "$before_file"
    if [[ -e $before_tmp ]]; then
        rm -f "$before_tmp"
    fi
fi
printf 'KI-45 before-state: %s\n' "$before_file"
if ! expected_fingerprint=$(python3 -c '
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
if not isinstance(data, dict) or data.get("id") != 45 or "error_fingerprint_hash" not in data:
    raise SystemExit(1)
value = data["error_fingerprint_hash"]
if value is not None and (not isinstance(value, str) or len(value) != 64):
    raise SystemExit(1)
print(value or "")
' "$before_file" 2>/dev/null); then
    printf '%s\n' 'KI-45 before-state is invalid; refusing migration.' >&2
    exit 65
fi
has_source_fingerprint=false
if [[ -n $expected_fingerprint ]]; then
    if [[ ! $expected_fingerprint =~ ^[[:xdigit:]]{64}$ ]]; then
        printf '%s\n' 'KI-45 before-state fingerprint is invalid; refusing migration.' >&2
        exit 65
    fi
    has_source_fingerprint=true
fi

download_issue_id=${STAGE332_401_ISSUE_ID:-}
if [[ -z $download_issue_id && -s $id_file ]]; then
    download_issue_id=$(<"$id_file")
fi
if [[ -n $download_issue_id && ! $download_issue_id =~ ^[0-9]+$ ]]; then
    printf '%s\n' 'Saved download-401 known issue id is invalid.' >&2
    exit 65
fi

load_report_state() {
    local report_config parsed
    report_config=$("${remote[@]}" "$compose python scripts/triage_agent_feedback.py show-feedback-fingerprint 80")
    parsed=$(python3 -c '
import json, re, sys
data = json.load(sys.stdin)
value = data.get("error_fingerprint_hash")
known_issue_id = data.get("known_issue_id")
if (data.get("id") != 80
        or not isinstance(value, str)
        or re.fullmatch(r"[0-9A-Fa-f]{64}", value) is None
        or not isinstance(known_issue_id, int)
        or known_issue_id <= 0):
    raise SystemExit(1)
print(f"{value}|{known_issue_id}")
' <<<"$report_config" 2>/dev/null) || return 1
    report_fingerprint=${parsed%%|*}
    report_known_issue_id=${parsed#*|}
}

if ! load_report_state; then
    printf '%s\n' 'Report #80 has no usable fingerprint; refusing migration.' >&2
    exit 65
fi
if $has_source_fingerprint && [[ $expected_fingerprint != "$report_fingerprint" ]]; then
    printf '%s\n' 'KI-45 fingerprint does not match report #80; refusing migration.' >&2
    exit 65
fi
if [[ -z $download_issue_id && $report_known_issue_id != 45 ]]; then
    printf '%s\n' 'Report #80 is not linked to KI-45 before promotion; refusing migration.' >&2
    exit 65
fi
if [[ -n $download_issue_id && $report_known_issue_id != 45 && $report_known_issue_id != "$download_issue_id" ]]; then
    printf '%s\n' 'Report #80 is linked to an unexpected known issue; refusing migration.' >&2
    exit 65
fi

validate_initial_ki45() {
    local live_config=$1
    python3 -c '
import json, sys
saved = json.load(open(sys.argv[1], encoding="utf-8"))
live = json.loads(sys.argv[2])
fields = ("id", "status", "title", "related_tool", "error_fingerprint_hash", "match_rules_json", "agent_playbook_json")
if any(field not in saved or field not in live or saved[field] != live[field] for field in fields):
    raise SystemExit(1)
' "$before_file" "$live_config"
}

validate_issue_pair() {
    local source_config=$1
    local target_config=$2
    python3 -c '
import json, sys
source, target = json.loads(sys.argv[1]), json.loads(sys.argv[2])
target_id, expected, has_source = int(sys.argv[3]), sys.argv[4], sys.argv[5] == "true"
if source.get("id") != 45:
    raise SystemExit(1)
if (target.get("id") != target_id
        or target.get("title") != "Report export file download is unauthorized"
        or target.get("related_tool") != "get_report_export_download"):
    raise SystemExit(1)
pair = (source.get("error_fingerprint_hash"), target.get("error_fingerprint_hash"))
allowed = {(expected, expected), (expected, None), (None, expected)} if has_source else {(None, expected)}
if pair not in allowed:
    raise SystemExit(1)
' "$source_config" "$target_config" "$download_issue_id" "$report_fingerprint" "$has_source_fingerprint"
}

if [[ $mode == rollback ]]; then
    if [[ ! $download_issue_id =~ ^[0-9]+$ ]]; then
        printf '%s\n' 'Rollback requires STAGE332_401_ISSUE_ID or the saved id file.' >&2
        exit 65
    fi
    source_config=$("${remote[@]}" "$compose python scripts/triage_agent_feedback.py show-known-issue-config 45")
    target_config=$("${remote[@]}" "$compose python scripts/triage_agent_feedback.py show-known-issue-config $download_issue_id")
    if ! validate_issue_pair "$source_config" "$target_config"; then
        printf '%s\n' 'Known-issue fingerprint state is unexpected; refusing rollback.' >&2
        exit 65
    fi
    "${remote[@]}" "$compose sh -c \"cat > /tmp/stage332-ki45-before.json\"" <"$before_file"
    if $has_source_fingerprint; then
        "${remote[@]}" "$compose python scripts/triage_agent_feedback.py move-fingerprint $download_issue_id 45 --expected-fingerprint $expected_fingerprint"
    else
        printf '%s\n' 'KI-45 had no source fingerprint; rollback move skipped.'
    fi
    "${remote[@]}" "$compose python scripts/triage_agent_feedback.py restore-known-issue-config 45 --config-json /tmp/stage332-ki45-before.json"
    "${remote[@]}" "$compose python scripts/triage_agent_feedback.py mark $download_issue_id wontfix"
    "${remote[@]}" "$compose python scripts/triage_agent_feedback.py link 45 80"
    "${remote[@]}" "$compose python scripts/triage_agent_feedback.py show-known-issue-config 45"
    "${remote[@]}" "$compose python scripts/triage_agent_feedback.py match-effectiveness --days 30"
    "${remote[@]}" "$compose sh -c \"rm -f /tmp/stage332-ki45-before.json\""
    printf '%s\n' 'Stage 332 known-issue configuration rolled back.'
    exit 0
fi

promoted_this_run=false
if [[ -z $download_issue_id ]]; then
    live_ki45=$("${remote[@]}" "$compose python scripts/triage_agent_feedback.py show-known-issue-config 45")
    if ! validate_initial_ki45 "$live_ki45"; then
        printf '%s\n' 'Live KI-45 differs from the saved before-state; refusing migration.' >&2
        exit 65
    fi
fi

for name in ki45-match-rules ki45-playbook download-401-match-rules download-401-playbook; do
    "${remote[@]}" "$compose sh -c \"cat > /tmp/stage332-$name.json\"" \
        <"$fixture_dir/$name.json"
done

"${remote[@]}" "$compose python scripts/triage_agent_feedback.py validate-known-issue-config --match-rules-json /tmp/stage332-ki45-match-rules.json --playbook-json /tmp/stage332-ki45-playbook.json"
"${remote[@]}" "$compose python scripts/triage_agent_feedback.py validate-known-issue-config --match-rules-json /tmp/stage332-download-401-match-rules.json --playbook-json /tmp/stage332-download-401-playbook.json"

if [[ -z $download_issue_id ]]; then
    promote_output=$("${remote[@]}" "$compose python scripts/triage_agent_feedback.py promote 80 --title 'Report export file download is unauthorized' --status workaround_available --public-summary 'The report file was created but current Vetmanager credentials cannot download it.' --workaround 'Re-authorize the integration, then download the same report_file_id; do not start a new export.' --related-tool get_report_export_download --match-rules-json /tmp/stage332-download-401-match-rules.json --playbook-json /tmp/stage332-download-401-playbook.json")
    printf '%s\n' "$promote_output"
    download_issue_id=$(printf '%s\n' "$promote_output" | sed -n 's/.*created known_issue #\([0-9][0-9]*\).*/\1/p')
    promoted_this_run=true
fi
if [[ ! $download_issue_id =~ ^[0-9]+$ ]]; then
    printf '%s\n' 'Could not determine the separate download-401 known issue id.' >&2
    exit 65
fi
if [[ ! -s $id_file ]]; then
    (umask 077; printf '%s\n' "$download_issue_id" >"$id_file")
fi
if $promoted_this_run; then
    if ! load_report_state || [[ $report_known_issue_id != "$download_issue_id" ]]; then
        printf '%s\n' 'Report #80 was not linked to the promoted known issue; refusing migration.' >&2
        exit 65
    fi
fi

source_config=$("${remote[@]}" "$compose python scripts/triage_agent_feedback.py show-known-issue-config 45")
target_config=$("${remote[@]}" "$compose python scripts/triage_agent_feedback.py show-known-issue-config $download_issue_id")
if ! validate_issue_pair "$source_config" "$target_config"; then
    printf '%s\n' 'Known-issue fingerprint state is unexpected; refusing migration.' >&2
    exit 65
fi

if $has_source_fingerprint; then
    "${remote[@]}" "$compose python scripts/triage_agent_feedback.py move-fingerprint 45 $download_issue_id --expected-fingerprint $expected_fingerprint"
else
    printf '%s\n' 'KI-45 has no source fingerprint; forward move skipped.'
fi
"${remote[@]}" "$compose python scripts/triage_agent_feedback.py set-match-rules 45 --match-rules-json /tmp/stage332-ki45-match-rules.json"
"${remote[@]}" "$compose python scripts/triage_agent_feedback.py set-playbook 45 --playbook-json /tmp/stage332-ki45-playbook.json"
"${remote[@]}" "$compose python scripts/triage_agent_feedback.py mark $download_issue_id workaround_available"
"${remote[@]}" "$compose python scripts/triage_agent_feedback.py link $download_issue_id 80"
"${remote[@]}" "$compose python scripts/triage_agent_feedback.py show-known-issue-config $download_issue_id"
"${remote[@]}" "$compose python scripts/triage_agent_feedback.py match-effectiveness --days 30"
"${remote[@]}" "$compose sh -c \"rm -f /tmp/stage332-ki45-match-rules.json /tmp/stage332-ki45-playbook.json /tmp/stage332-download-401-match-rules.json /tmp/stage332-download-401-playbook.json\""

printf 'Rollback command: %s\n' \
    "CONFIRM_STAGE332_PROD=apply-stage-332 STAGE332_MODE=rollback STAGE332_401_ISSUE_ID=$download_issue_id scripts/apply_stage332_known_issues_prod.sh"
