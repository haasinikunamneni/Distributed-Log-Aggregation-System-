#!/usr/bin/env bash
# Ubuntu only. Runs baseline then priority (3 repeats each) and builds plots.
set -e
cd "$(dirname "$0")/.."
sudo mn -c >/dev/null 2>&1 || true
sudo .venv/bin/python -m experiments.run_experiment --mode baseline --repeat 3
sudo .venv/bin/python -m experiments.run_experiment --mode priority --repeat 3
.venv/bin/python -m experiments.analyze_results
