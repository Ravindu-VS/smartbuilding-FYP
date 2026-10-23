#!/usr/bin/env bash
# Full automated test suite (from the repository root).  Add "-m 'not slow'" for a quick run.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pytest "$@"
