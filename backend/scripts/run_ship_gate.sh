#!/usr/bin/env bash
# Official Krexion ship gate — must be all-green before version push.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pytest \
  tests/test_v2_*.py \
  tests/test_browser_profile*.py \
  -q --tb=line
