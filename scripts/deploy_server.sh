#!/usr/bin/env bash
# The single-slot mutable deploy was retired for stage 385.
set -euo pipefail
printf '%s\n' 'Legacy single-slot deploy is disabled; use the staged Deploy Prod workflow.' >&2
exit 1
