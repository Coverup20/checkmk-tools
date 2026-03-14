#!/usr/bin/env bash
set -euo pipefail

# Wrapper: this variant is deprecated.
# Use the canonical script:
#   script-tools/full/monitoring_diagnostics/checkmk-tuning-interactive.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$SCRIPT_DIR/checkmk-tuning-interactive.sh" "$@"
