#!/usr/bin/env bash
# Full run: tests, E1, E2 (main + gamma), statistics and figures.
# Output: results_new/ (the published results in results/ are not overwritten).
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PYTHON:-python3}
PROCS=${PROCS:-8}
[ -d .venv ] || "$PY" -m venv .venv
. .venv/bin/activate
pip install -q -r requirements.txt
python -m pytest -q tests
mkdir -p results_new
python -m resched_lab.experiments e1 --gammas 0.2,0.5,0.8 --out results_new/e1.csv
python -m resched_lab.experiments e2 --levels low,medium,high --gammas 0.5 --reps 201-240 \
       --policies all --procs "$PROCS" --workers 2 --out results_new/e2_main.csv
python -m resched_lab.experiments e2 --levels medium --gammas 0.2,0.8 --reps 201-240 \
       --policies all --procs "$PROCS" --workers 2 --out results_new/e2_gamma.csv
python -m resched_lab.analysis results_new/e2_main.csv results_new/e2_gamma.csv --out results_new/analysis > results_new/analysis.txt
python -m resched_lab.figures results_new/e2_main.csv results_new/e2_gamma.csv --out results_new/figures
echo "Done: results_new/"
