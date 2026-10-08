#!/usr/bin/env bash
# Runs the whole pipeline end to end: generate -> clean -> analyze -> build -> test
set -euo pipefail
cd "$(dirname "$0")"
PY="${PYTHON:-python3}"

echo "== 1/5 Generate sample data"
"$PY" src/generate_sample_data.py
echo "== 2/5 Clean"
"$PY" src/clean.py
echo "== 3/5 Analyze"
"$PY" src/analyze.py
echo "== 4/5 Build dashboard"
"$PY" src/build_dashboard.py
echo "== 5/5 Tests"
"$PY" -m pytest -q

echo
echo "Done. Open dashboard/index.html in a browser."
