#!/usr/bin/env bash
# Launch RoastMaster in development mode on Mac
set -euo pipefail

cd "$(dirname "$0")/.."

echo "=== ROASTMASTER DEV MODE ==="
echo "Starting with simulated hardware..."
echo ""

uv run python -m roastmaster "$@"
