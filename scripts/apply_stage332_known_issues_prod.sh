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

remote=(ssh root@212.193.59.219)
compose='cd /opt/vetmanager-mcp && docker compose --profile production exec -T mcp'

"${remote[@]}" "$compose python scripts/triage_agent_feedback.py show-known-issue-config 45" >"$before_file"
chmod 600 "$before_file"
test -s "$before_file"
printf 'KI-45 before-state: %s\n' "$before_file"

for name in ki45-match-rules ki45-playbook download-401-match-rules download-401-playbook; do
    "${remote[@]}" "$compose sh -c \"cat > /tmp/stage332-$name.json\"" \
        <"$fixture_dir/$name.json"
done

download_issue_id=${STAGE332_401_ISSUE_ID:-}
if [[ -z $download_issue_id ]]; then
    promote_output=$("${remote[@]}" "$compose python scripts/triage_agent_feedback.py promote 80 --title 'Report export file download is unauthorized' --status workaround_available --public-summary 'The report file was created but current Vetmanager credentials cannot download it.' --workaround 'Re-authorize the integration, then download the same report_file_id; do not start a new export.' --related-tool get_report_export_download --match-rules-json /tmp/stage332-download-401-match-rules.json --playbook-json /tmp/stage332-download-401-playbook.json")
    printf '%s\n' "$promote_output"
    download_issue_id=$(printf '%s\n' "$promote_output" | sed -n 's/.*created known_issue #\([0-9][0-9]*\).*/\1/p')
fi
if [[ ! $download_issue_id =~ ^[0-9]+$ ]]; then
    printf '%s\n' 'Could not determine the separate download-401 known issue id.' >&2
    exit 65
fi

"${remote[@]}" "$compose python scripts/triage_agent_feedback.py move-fingerprint 45 $download_issue_id"
"${remote[@]}" "$compose python scripts/triage_agent_feedback.py set-match-rules 45 --match-rules-json /tmp/stage332-ki45-match-rules.json"
"${remote[@]}" "$compose python scripts/triage_agent_feedback.py set-playbook 45 --playbook-json /tmp/stage332-ki45-playbook.json"
"${remote[@]}" "$compose python scripts/triage_agent_feedback.py show-known-issue-config $download_issue_id"
"${remote[@]}" "$compose python scripts/triage_agent_feedback.py match-effectiveness --days 30"
"${remote[@]}" "$compose sh -c \"rm -f /tmp/stage332-ki45-match-rules.json /tmp/stage332-ki45-playbook.json /tmp/stage332-download-401-match-rules.json /tmp/stage332-download-401-playbook.json\""

printf 'Rollback fingerprint command: %s\n' \
    "ssh root@212.193.59.219 '$compose python scripts/triage_agent_feedback.py move-fingerprint $download_issue_id 45'"
