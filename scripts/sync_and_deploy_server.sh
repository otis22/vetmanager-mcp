#!/usr/bin/env bash
# The live-checkout rsync deploy was retired for stage 385.
set -euo pipefail
printf '%s\n' 'Legacy live-checkout sync is disabled; use the staged Deploy Prod workflow.' >&2
exit 1
