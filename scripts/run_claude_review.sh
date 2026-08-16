#!/usr/bin/env bash
# Run one Claude structured-review attempt and preserve diagnostic evidence.

set -euo pipefail

script_dir=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

usage() {
    cat <<'EOF'
Usage: scripts/run_claude_review.sh (--range <git-range> | --file <review-file>) --attempt <N/3> [options]

Options:
  --range <git-range>    Git revision/range for a diff review.
  --file <review-file>   File supplied as the object of a non-diff review (for example PRD).
  --prompt-file <path>   Review prompt (default: built-in structured-review prompt).
  --schema-file <path>   JSON schema (default: findings schema).
  --evidence-dir <path>  Evidence root (default: XDG_DATA_HOME or ~/.local/share).
  --repo <path>          Repository used for git diff (default: current directory).
  --model <name>         Claude model (default: opus).
  --timeout <seconds>    CLI timeout (default: 1200).
EOF
}

range=''
review_file=''
attempt=''
prompt_file=''
schema_file=''
data_home=${XDG_DATA_HOME:-"$HOME/.local/share"}
evidence_dir=$data_home/vetmanager-mcp-review-evidence
repo=$PWD
model=opus
timeout_seconds=1200

while (($#)); do
    case $1 in
        --range) range=${2:?missing value for --range}; shift 2 ;;
        --file) review_file=${2:?missing value for --file}; shift 2 ;;
        --attempt) attempt=${2:?missing value for --attempt}; shift 2 ;;
        --prompt-file) prompt_file=${2:?missing value for --prompt-file}; shift 2 ;;
        --schema-file) schema_file=${2:?missing value for --schema-file}; shift 2 ;;
        --evidence-dir) evidence_dir=${2:?missing value for --evidence-dir}; shift 2 ;;
        --repo) repo=${2:?missing value for --repo}; shift 2 ;;
        --model) model=${2:?missing value for --model}; shift 2 ;;
        --timeout) timeout_seconds=${2:?missing value for --timeout}; shift 2 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 64 ;;
    esac
done

if [[ ( -z $range && -z $review_file ) || ( -n $range && -n $review_file ) || ! $attempt =~ ^[1-3]/3$ ]]; then
    printf '%s\n' 'Exactly one of --range or --file and --attempt N/3 are required; N must be 1, 2, or 3.' >&2
    usage >&2
    exit 64
fi

if [[ ! -d $repo ]]; then
    printf 'Repository is not a directory: %s\n' "$repo" >&2
    exit 64
fi
repo=$(realpath -e -- "$repo")
evidence_candidate=$(realpath -ms -- "$evidence_dir")
if [[ $evidence_candidate == "$repo" || $evidence_candidate == "$repo/"* ]]; then
    printf 'Evidence directory must be outside the repository working tree: %s\n' "$evidence_candidate" >&2
    exit 73
fi
if [[ -n $review_file && ! -f $review_file ]]; then
    printf 'Review file is not a readable regular file: %s\n' "$review_file" >&2
    exit 64
fi

tmp_dir=$(mktemp -d)
cleanup() { rm -rf "$tmp_dir"; }
trap cleanup EXIT

if [[ -z $prompt_file ]]; then
    prompt_file=$tmp_dir/default-prompt.txt
    cat > "$prompt_file" <<'EOF'
Review only. Do not edit files. Do not run commands. Finish this review within 600 seconds. Review the supplied material only. Think briefly, then return JSON matching the schema immediately. Findings should include only material correctness/security/regression issues; use an empty findings array if none.
EOF
fi

if [[ -z $schema_file ]]; then
    schema_file=$tmp_dir/default-schema.json
    cat > "$schema_file" <<'EOF'
{"type":"object","properties":{"findings":{"type":"array","items":{"type":"object","properties":{"severity":{"type":"string"},"file":{"type":"string"},"line":{"type":"integer"},"reason":{"type":"string"}},"required":["severity","file","line","reason"],"additionalProperties":false}}},"required":["findings"],"additionalProperties":false}
EOF
fi

if [[ ! -r $prompt_file || ! -r $schema_file ]]; then
    printf '%s\n' 'Prompt and schema files must be readable.' >&2
    exit 64
fi

stdin_file=$tmp_dir/review.stdin
if [[ -n $range ]]; then
    review_kind='git_range'
    review_target=$range
    if ! { cat "$prompt_file"; printf '\n'; git -C "$repo" show --find-renames --find-copies --format=fuller "$range"; } > "$stdin_file"; then
        printf 'Could not create review stdin for range: %s\n' "$range" >&2
        exit 65
    fi
else
    review_kind='file'
    review_target=$review_file
    if ! { cat "$prompt_file"; printf '\n=== REVIEW FILE: %s ===\n' "$review_file"; cat -- "$review_file"; } > "$stdin_file"; then
        printf 'Could not create review stdin for file: %s\n' "$review_file" >&2
        exit 65
    fi
fi

started_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
started_ns=$(date +%s%N)
attempt_label=${attempt//\//-of-}
safe_target=$(printf '%s' "$review_kind-$review_target" | tr '/.' '__' | tr -cd '[:alnum:]_-' | cut -c1-80)
evidence_parent=$(dirname -- "$evidence_dir")
if [[ -e $evidence_parent && ! -d $evidence_parent ]]; then
    printf 'Evidence parent path must be a directory: %s\n' "$evidence_parent" >&2
    exit 73
fi
# mkdir -p -m affects only the leaf; umask makes every new parent private.
if [[ ! -d $evidence_parent ]] && ! (umask 077; mkdir -p "$evidence_parent"); then
    printf 'Could not create evidence parent directory: %s\n' "$evidence_parent" >&2
    exit 73
fi
if ! evidence_parent=$(realpath -e -- "$evidence_parent"); then
    printf 'Could not resolve evidence parent directory: %s\n' "$(dirname -- "$evidence_dir")" >&2
    exit 73
fi
evidence_dir=$evidence_parent/$(basename -- "$evidence_dir")
if [[ $evidence_dir == "$repo" || $evidence_dir == "$repo/"* ]]; then
    printf 'Evidence directory must be outside the repository working tree: %s\n' "$evidence_dir" >&2
    exit 73
fi
if [[ -L $evidence_dir || ( -e $evidence_dir && ! -d $evidence_dir ) ]]; then
    printf 'Evidence path must be a real directory: %s\n' "$evidence_dir" >&2
    exit 73
fi
if [[ ! -e $evidence_dir ]] && ! mkdir -m 700 "$evidence_dir"; then
    printf 'Could not create evidence directory: %s\n' "$evidence_dir" >&2
    exit 73
fi
if [[ $(stat -c %u "$evidence_dir") != "$EUID" ]]; then
    printf 'Evidence directory is not owned by the current user: %s\n' "$evidence_dir" >&2
    exit 73
fi
chmod 700 "$evidence_dir"
evidence_path=$(mktemp -d "$evidence_dir/${started_at//[:]/}-${safe_target}-attempt-${attempt_label}.XXXXXX")
prefix="$evidence_path/claude-review-attempt-${attempt_label}"
envelope_file="$prefix.envelope.json"
stderr_file="$prefix.stderr.txt"
prompt_copy="$prefix.prompt.txt"
schema_copy="$prefix.schema.json"
metadata_file="$prefix.metadata.json"

cp "$prompt_file" "$prompt_copy"
cp "$schema_file" "$schema_copy"

claude_bin=${CLAUDE_BIN:-claude}
cli_version=$($claude_bin --version 2>&1 || true)
schema=$(cat "$schema_file")

set +e
timeout "$timeout_seconds" "$claude_bin" -p --model "$model" --strict-mcp-config \
    --mcp-config '{"mcpServers":{}}' --tools '' --output-format json \
    --json-schema "$schema" < "$stdin_file" > "$envelope_file" 2> "$stderr_file"
cli_exit=$?
set -e

validator_exit=''
verdict_file=''
validator_stderr_file=''
if ((cli_exit == 0)); then
    verdict_file="$prefix.verdict.json"
    validator_stderr_file="$prefix.validator.stderr.txt"
    set +e
    "$script_dir/validate_review_result.py" < "$envelope_file" > "$verdict_file" 2> "$validator_stderr_file"
    validator_exit=$?
    set -e
fi

finished_ns=$(date +%s%N)
duration_ms=$(( (finished_ns - started_ns) / 1000000 ))
stdin_bytes=$(wc -c < "$stdin_file")
stdin_lines=$(wc -l < "$stdin_file")

python3 - "$metadata_file" "$envelope_file" "$prompt_copy" "$schema_copy" "$stderr_file" \
    "$started_at" "$duration_ms" "$review_kind" "$review_target" "$attempt" "$repo" "$evidence_dir" \
    "$stdin_bytes" "$stdin_lines" "$cli_version" "$cli_exit" "$model" "$timeout_seconds" \
    "$validator_exit" "$verdict_file" "$validator_stderr_file" <<'PY'
import json
import pathlib
import sys

(
    metadata_path, envelope_path, prompt_path, schema_path, stderr_path,
    started_at, duration_ms, review_kind, review_target, attempt, repo, evidence_dir,
    stdin_bytes, stdin_lines, cli_version, cli_exit, model, timeout_seconds,
    validator_exit, verdict_file, validator_stderr_file,
) = sys.argv[1:]

raw = pathlib.Path(envelope_path).read_bytes()
try:
    envelope = json.loads(raw)
except Exception:
    envelope = {}
if not isinstance(envelope, dict):
    envelope = {}
usage = envelope.get("usage") if isinstance(envelope.get("usage"), dict) else {}
details = usage.get("output_tokens_details") if isinstance(usage.get("output_tokens_details"), dict) else {}
result = envelope.get("result")
metadata = {
    "started_at": started_at,
    "duration_ms": int(duration_ms),
    "review_kind": review_kind,
    "review_target": review_target,
    "review_range": review_target if review_kind == "git_range" else None,
    "attempt": attempt,
    "repo": repo,
    "evidence_dir": evidence_dir,
    "stdin_bytes": int(stdin_bytes),
    "stdin_lines": int(stdin_lines),
    "cli_version": cli_version,
    "cli_exit": int(cli_exit),
    "model": model,
    "timeout_seconds": int(timeout_seconds),
    "validator_exit": int(validator_exit) if validator_exit else None,
    "verdict_file": verdict_file or None,
    "validator_stderr_file": validator_stderr_file or None,
    "envelope_file": envelope_path,
    "prompt_file": prompt_path,
    "schema_file": schema_path,
    "stderr_file": stderr_path,
    "is_error": envelope.get("is_error"),
    "subtype": envelope.get("subtype"),
    "stop_reason": envelope.get("stop_reason"),
    "num_turns": envelope.get("num_turns"),
    "output_tokens": usage.get("output_tokens"),
    "thinking_tokens": details.get("thinking_tokens"),
    "result_length": len(result) if isinstance(result, str) else 0,
}
pathlib.Path(metadata_path).write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
print(
    "review evidence: {envelope}; subtype={subtype}; stop_reason={stop_reason}; "
    "output_tokens={output_tokens}; thinking_tokens={thinking_tokens}; "
    "len(result)={result_length}".format(envelope=envelope_path, **metadata)
)
PY

if ((cli_exit != 0)); then
    exit "$cli_exit"
fi
exit "$validator_exit"
