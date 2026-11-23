#!/usr/bin/env bash
# Build the dashboard as a static site that the edge brain serves on the Raspberry Pi
# (http://<pi>:8001/), then copy it into the project as dashboard_dist/.
# Run on any machine with Node.js 20+:  bash scripts/build_dashboard_for_pi.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/dashboard/fyp-research-twin"
[ -d node_modules ] || npm ci --no-audit --no-fund
NEXT_OUTPUT=export NEXT_PUBLIC_EDGE_URL=same-origin npx next build
rm -rf "$ROOT/dashboard_dist"
cp -r out "$ROOT/dashboard_dist"
echo "Built $ROOT/dashboard_dist. On the Pi the edge brain serves it at http://<pi-ip>:8001/"
