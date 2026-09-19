#!/usr/bin/env bash
# Supervisor-only production application for Stage 332. Do not run from agents.

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
expected_fingerprint=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["error_fingerprint_hash"] or "")' "$before_file")
if [[ ! $expected_fingerprint =~ ^[[:xdigit:]]{64}$ ]]; then
    printf '%s\n' 'KI-45 before-state has no usable fingerprint; refusing migration.' >&2
    exit 65
fi

download_issue_id=${STAGE332_401_ISSUE_ID:-}
if [[ -z $download_issue_id && -s $id_file ]]; then
    download_issue_id=$(<"$id_file")
fi

if [[ $mode == rollback ]]; then
    if [[ ! $download_issue_id =~ ^[0-9]+$ ]]; then
        printf '%s\n' 'Rollback requires STAGE332_401_ISSUE_ID or the saved id file.' >&2
        exit 65
    fi
    "${remote[@]}" "$compose sh -c \"cat > /tmp/stage332-ki45-before.json\"" <"$before_file"
    "${remote[@]}" "$compose python scripts/triage_agent_feedback.py move-fingerprint $download_issue_id 45 --expected-fingerprint $expected_fingerprint"
    "${remote[@]}" "$compose python scripts/triage_agent_feedback.py restore-known-issue-config 45 --config-json /tmp/stage332-ki45-before.json"
    "${remote[@]}" "$compose python scripts/triage_agent_feedback.py mark $download_issue_id wontfix"
    "${remote[@]}" "$compose python scripts/triage_agent_feedback.py link 45 80"
    "${remote[@]}" "$compose python scripts/triage_agent_feedback.py show-known-issue-config 45"
    "${remote[@]}" "$compose python scripts/triage_agent_feedback.py match-effectiveness --days 30"
    "${remote[@]}" "$compose sh -c \"rm -f /tmp/stage332-ki45-before.json\""
    printf '%s\n' 'Stage 332 known-issue configuration rolled back.'
    exit 0
fi

for name in ki45-match-rules ki45-playbook download-401-match-rules download-401-playbook; do
    "${remote[@]}" "$compose sh -c \"cat > /tmp/stage332-$name.json\"" \
        <"$fixture_dir/$name.json"
done

if [[ -z $download_issue_id ]]; then
    promote_output=$("${remote[@]}" "$compose python scripts/triage_agent_feedback.py promote 80 --title 'Report export file download is unauthorized' --status workaround_available --public-summary 'The report file was created but current Vetmanager credentials cannot download it.' --workaround 'Re-authorize the integration, then download the same report_file_id; do not start a new export.' --related-tool get_report_export_download --match-rules-json /tmp/stage332-download-401-match-rules.json --playbook-json /tmp/stage332-download-401-playbook.json")
    printf '%s\n' "$promote_output"
    download_issue_id=$(printf '%s\n' "$promote_output" | sed -n 's/.*created known_issue #\([0-9][0-9]*\).*/\1/p')
fi
if [[ ! $download_issue_id =~ ^[0-9]+$ ]]; then
    printf '%s\n' 'Could not determine the separate download-401 known issue id.' >&2
    exit 65
fi
if [[ ! -s $id_file ]]; then
    (umask 077; printf '%s\n' "$download_issue_id" >"$id_file")
fi

"${remote[@]}" "$compose python scripts/triage_agent_feedback.py set-match-rules 45 --match-rules-json /tmp/stage332-ki45-match-rules.json"
"${remote[@]}" "$compose python scripts/triage_agent_feedback.py set-playbook 45 --playbook-json /tmp/stage332-ki45-playbook.json"
"${remote[@]}" "$compose python scripts/triage_agent_feedback.py move-fingerprint 45 $download_issue_id --expected-fingerprint $expected_fingerprint"
"${remote[@]}" "$compose python scripts/triage_agent_feedback.py show-known-issue-config $download_issue_id"
"${remote[@]}" "$compose python scripts/triage_agent_feedback.py match-effectiveness --days 30"
"${remote[@]}" "$compose sh -c \"rm -f /tmp/stage332-ki45-match-rules.json /tmp/stage332-ki45-playbook.json /tmp/stage332-download-401-match-rules.json /tmp/stage332-download-401-playbook.json\""

printf 'Rollback command: %s\n' \
    "CONFIRM_STAGE332_PROD=apply-stage-332 STAGE332_MODE=rollback STAGE332_401_ISSUE_ID=$download_issue_id scripts/apply_stage332_known_issues_prod.sh"
