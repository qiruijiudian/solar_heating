#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PYTHON="$SCRIPT_DIR/.venv/bin/python"
DEFAULT_INPUT="01 input files/weather and heating load data（mula1）.xlsx"
DEFAULT_SCENARIO="seasonal_hp"
DEFAULT_AREA="1800"
DEFAULT_TANK="400"
DEFAULT_LOADS="1.0,1.1,1.2,1.3"

if [[ ! -x "$VENV_PYTHON" ]]; then
  echo "Missing virtualenv Python: $VENV_PYTHON"
  echo "Create the environment first, then run this launcher again."
  read -r "?Press Enter to close..."
  exit 1
fi

cd "$SCRIPT_DIR"

echo "Fixed-Design Load Reliability Study"
echo "Press Enter to accept each default."
echo

read -r "?Input file [$DEFAULT_INPUT]: " INPUT_FILE
INPUT_FILE="${INPUT_FILE:-$DEFAULT_INPUT}"

read -r "?Scenario [$DEFAULT_SCENARIO] (short_term / seasonal_boiler / seasonal_hp): " SCENARIO
SCENARIO="${SCENARIO:-$DEFAULT_SCENARIO}"

read -r "?Collector area m2 [$DEFAULT_AREA]: " AREA
AREA="${AREA:-$DEFAULT_AREA}"

read -r "?Tank volume m3 [$DEFAULT_TANK]: " TANK
TANK="${TANK:-$DEFAULT_TANK}"

read -r "?Load multipliers [$DEFAULT_LOADS]: " LOADS
LOADS="${LOADS:-$DEFAULT_LOADS}"

echo
"$VENV_PYTHON" heating_load_sensitivity.py "$INPUT_FILE" \
  --scenario "$SCENARIO" \
  --collector-area "$AREA" \
  --tank-volume "$TANK" \
  --load-multipliers "$LOADS"

echo
read -r "?Study finished. Press Enter to close..."
