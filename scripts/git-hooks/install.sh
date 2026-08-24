#!/usr/bin/env bash
# Compatibility entry point for the repository-local Git hook installer.

set -euo pipefail

script_dir=$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec "$script_dir/../install_git_hooks.sh" "$@"
