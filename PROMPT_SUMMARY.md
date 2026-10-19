# Prompt Summary

## Project

This project models and optimizes a solar thermal heating system with water tank storage using hourly weather and heating-load inputs.

It supports:

- short-term storage
- long-term seasonal storage with electric boilers
- long-term seasonal storage with heat pump

The main goal is to size:

- solar collector area in `m2`
- tank volume in `m3`

The default optimization objective is minimum `annualized_total_cost`.

## Main Files

- `thermal_storage_core.py`: core simulation, storage model, optimization, cost logic
- `thermal_storage_gui.py`: Panel dashboard and plotting UI
- `thermal_storage_sizing.py`: CLI entry point
- `OPTIMIZATION_GUIDE.md`: project explanation and workflow notes

## Inputs

Default hourly file:

- `01 input files/weather and heating load data.xlsx`

Saved GUI defaults:

- `design_inputs.xlsx`

Expected hourly columns include aliases of:

- `timestamp`
- `outside_temp`
- `solar_rad`
- `horizontal_solar_rad`
- `heating_load`

Important internal assumptions:

- `solar_rad` is the collector-plane solar radiation used in the collector model
- `horizontal_solar_rad` is optional and used for analysis/reporting
- timestamps default to hourly from `2025-01-01 00:00:00` if not provided
- radiation and load units are normalized to `kWh`-based hourly values

## Core Model Rules

Collector model:

- quadratic efficiency form using `eta0`, `a1`, and `a2`
- collector efficiency is clipped between `0.0` and `0.85`

Tank model:

- stratified multi-layer water tank
- short-term storage runs a single-year simulation
- seasonal storage can repeat the same year up to 3 years until convergence

Heating dispatch order each hour:

1. direct solar collector to load
2. direct tank discharge to load if tank layers are hot enough
3. heat pump upgrade from low-temperature tank energy, only for `water_heat_pump`
4. remaining unmet load served by auxiliary heating

Heat pump source rule:

- the heat pump uses tank energy down to `tank_min_temp`
- for long-term heat-pump studies, this is driven by the GUI input `Large Delta-T Tank Min Temp (C)`

Optimization ranking:

- best design is chosen by `annualized_total_cost`
- tiebreakers favor higher `solar_coverage_pct`, then smaller collector area, then smaller tank size

Cost model:

- annualized capital cost = `(collector_capital + tank_capital) / project_lifetime_years`
- annual auxiliary energy cost = `auxiliary_energy_input_kwh * electricity_price`
- annualized total cost = annualized capital cost + annual auxiliary energy cost

## Current GUI Behavior

The GUI has tabs for:

- Design Inputs
- Input Analysis Results
- Short-Term Storage
- Long-Term Storage With Electric Boilers
- Long-Term Storage With Heat Pump

Important current UI details:

- main dashboard background is white
- hourly weather/load inputs are split into 3 plots:
  - outside temperature
  - heating load
  - solar radiation
- cost heatmap uses green for low cost and red for high cost
- both heatmaps are wider and include contour lines
- Step 2 uses a selectable collector-area dropdown from the candidate list
- Step 3 auto-fills the area from Step 2, but the Step 3 area and tank size remain editable
- Step 3 runs only when the user clicks `Run Step 3 Final Results`
- Step 3 places `Run Step 3 Final Results` and `Export Excel Report` below the inputs
- `Export Excel Report` is a normal button that saves a report into `02 reports/`
- Step 3 summary includes solar collector efficiency
- the visible `Full Design Table` section has been removed from the GUI
- monthly summary tables are set to show all rows without pagination or internal scrolling
- candidate size inputs are grouped into `Short-Term Storage` and `Long-Term Storage`

## Candidate Size Behavior

For `Auto Generate` mode in the GUI:

- candidate collector areas and tank sizes are generated from min/max/count inputs
- generated values are rounded up using engineering-style rounding

For `Upload Excel` mode:

- uploaded collector and tank values are used as provided

## Reports And Outputs

The GUI can export Excel reports after Step 3 final results are available.

Reports are written to:

- `02 reports/`

Excel report sheets currently include:

- `project_inputs`
- `final_summary`
- `step1_results`
- `step2_results`
- `optimization_grid`
- `monthly_summary`
- `hourly_results`
- `input_monthly_data`

Excel report formatting has been improved:

- styled header rows
- frozen top row
- auto filters
- adjusted column widths
- formatted dates and numeric columns
- cleaner borders/alignment and hidden gridlines

Step 3 summary shows metrics such as:

- collector area
- tank volume
- total heating load
- solar collector efficiency
- solar direct heat
- solar heat via heat pump
- usable solar heat
- solar heating delivered
- solar energy use ratio
- solar heating ratio
- auxiliary heating delivered
- auxiliary energy input
- heat pump power input
- annualized total cost
- final tank temperature

## Useful Prompt Context For Future Work

When working on this project, assume:

- the user usually wants direct code changes, not just analysis
- GUI changes should preserve the existing Panel/hvPlot structure
- Step 2 and Step 3 are intentionally decoupled:
  - Step 2 changes update the tank-study plots and auto-fill the Step 3 area
  - Step 3 simulation must not rerun automatically from value edits
- avoid reverting user edits in unrelated files
- use `apply_patch` for file edits
- verify Python syntax after changes with `python3 -m py_compile thermal_storage_gui.py` or relevant files

## Example Reuse Prompt

Use this project context:

This repository is a solar thermal storage sizing tool with a Panel GUI. The main files are `thermal_storage_core.py`, `thermal_storage_gui.py`, and `thermal_storage_sizing.py`. The tool simulates hourly solar collection, stratified water tank storage, auxiliary heating, and optional heat-pump upgrading of low-temperature tank energy. The GUI supports short-term storage, long-term storage with electric boilers, and long-term storage with heat pump. Preserve the current workflow carefully: Step 2 uses a selectable candidate collector area, Step 3 uses editable final area/tank inputs and runs only on button click, Excel export saves polished reports into `02 reports`, and the heatmaps/plot views are part of the main decision flow.
