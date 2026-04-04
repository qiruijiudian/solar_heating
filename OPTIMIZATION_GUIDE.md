# Solar Heating System Optimization Guide

This document explains how the solar heating system is optimized in this project, what each study step means, and how to interpret the results.

## Project Purpose

The project sizes a solar heating system with thermal storage using hourly input data. It compares three fixed system cases:

- Short-term storage
- Long-term storage with electric boiler
- Long-term storage with heat pump

For each case, the tool evaluates solar collector area and tank size, calculates energy flows hour by hour, and recommends designs based on annualized cost.

## Main Files

- `thermal_storage_core.py`
  Core simulation and optimization logic
- `thermal_storage_gui.py`
  Panel + hvPlot dashboard
- `thermal_storage_sizing.py`
  CLI entry point

## Required Input Data

The default hourly input file is:

- `01 input files/weather and heating load data.xlsx`

Expected columns:

- `time_step`
- `outside_air_temp(℃）`
- `horizontal_solar_rad(Wh/m2)`
- `solar_rad_55deg_surface`
- `heating_load`

Internal assumptions:

- `time_step`: hourly timestamps
- `outside_air_temp(℃）`: `C`
- `horizontal_solar_rad(Wh/m2)`: hourly solar radiation on horizontal plane
- `solar_rad_55deg_surface`: hourly solar radiation on collector plane
- `heating_load`: hourly building heating energy

The collector calculation uses `solar_rad_55deg_surface`.

## Three System Cases

### 1. Short-Term Storage

Used to study day-scale or short multi-day storage.

Solar heating ratio is calculated as:

`(direct solar heating + tank discharge for heating) / heating load`

### 2. Long-Term Storage with Electric Boiler

Used to study seasonal storage with electric auxiliary heating.

Solar heating ratio is calculated as:

`(direct solar heating + tank discharge for heating) / heating load`

### 3. Long-Term Storage with Heat Pump

Used to study seasonal storage where low-temperature tank energy can be upgraded by a heat pump.

Solar heating ratio is calculated as:

`(direct solar heating + tank discharge for heating + low-temperature tank discharge used by heat pump) / heating load`

Important:

- the heat pump electricity is not counted as solar energy
- only the solar-origin source energy from the tank is counted in the solar heating ratio

## Collector Model

The solar collector uses the standard quadratic efficiency form:

`eta = eta0 - a1 * (Tm - Ta) / G - a2 * (Tm - Ta)^2 / G`

Where:

- `eta0`: optical efficiency
- `a1`: first-order heat loss coefficient
- `a2`: second-order heat loss coefficient
- `Tm`: collector fluid temperature estimate
- `Ta`: outdoor air temperature
- `G`: solar irradiance

The GUI includes a collector-type dropdown that fills typical values, but the user can still edit `eta0`, `a1`, and `a2`.

## Tank Model

The storage tank is modeled as a stratified multi-layer water tank.

The model includes:

- charging from solar collector
- direct discharge when tank temperature is high enough
- low-temperature source extraction for heat pump case
- tank thermal loss
- seasonal carry-over for long-term storage up to 3 repeated years

Short-term tanks use a single-year hourly simulation.

Long-term tanks repeat the same year until:

- the tank state converges, or
- the simulation reaches 3 years

## Optimization Workflow in the GUI

The GUI has a left control panel and several main tabs.

### Step A. Analyze the Input Data

Use `Analyze Input Data` first.

This creates the `Input Analysis` tab and shows:

- annual heating load
- heating-season load
- annual tilted solar radiation
- annual horizontal solar radiation
- monthly summary table
- hourly duration curves
- suggested collector-area and tank-size ranges

### How the suggested ranges are calculated

#### Short-Term Recommendation

Short-term recommendation uses only the hours with heating load.

Target solar heating ratio:

- `70%` to `90%`

Suggested collector area is estimated from:

- heating-season heating load
- heating-season tilted solar radiation
- a reference collector efficiency from the current `eta0`, `a1`, `a2`

Suggested tank size is then estimated using:

- `10` to `300 L/m2`

#### Long-Term Recommendation

Long-term recommendation uses the full year.

Target solar heating ratio:

- `95%` to `100%`

Suggested collector area is estimated from:

- annual heating load
- annual tilted solar radiation
- a reference collector efficiency from the current `eta0`, `a1`, `a2`

Suggested tank size is then estimated using:

- `300` to `3000 L/m2`

These suggestions are screening values only. They help choose candidate ranges for the full simulation. They are not the final optimized design.

### Step B. Run the Full Study

Use `Run Study`.

For each of the three cases, the tool performs:

1. Full cost optimization grid
2. Step 1 study: solar heating ratio vs collector area
3. Step 2 study: solar heating ratio vs tank size at a selected collector area

### Step C. Review the Result Tab for Each Case

Each case tab shows:

- cost optimization result table
- cost heatmap
- solar heating ratio heatmap
- solar heating ratio vs collector area
- solar heating ratio vs tank size
- final decision calculation section
- time-series plots
- full design table

### Step D. Run the Final Decision Case

After reviewing Step 1 and Step 2:

1. choose a collector area
2. choose a tank size
3. click `Run Step 3 Final Results`

This runs the final hourly simulation for the selected design and updates:

- tank temperature plot
- heating source plot
- tank charge/discharge plot
- summary metrics

## What the Tool Optimizes

The optimization objective is annualized total cost.

For each candidate design:

- `collector area`
- `tank size`

the tool calculates:

- collector capital cost
- tank capital cost
- annualized capital cost
- auxiliary energy input
- annual auxiliary energy cost
- annualized total cost

The best design is the one with the lowest:

- `annualized_total_cost`

Tie-breaking then favors:

- higher solar heating ratio
- smaller collector area
- smaller tank size

## Key Output Definitions

### Solar Energy Collected

Useful heat from the collector after collector efficiency losses.

### Solar Direct Collector to Load

Solar heat used immediately to meet heating demand in the same hour.

### Solar from Tank Direct

Tank discharge used directly when tank temperature is high enough for the heating supply temperature.

### Solar from Tank via Heat Pump

Delivered heating after heat-pump upgrade.

Important:

- this value includes heat-pump electricity effect
- it is useful for system energy balance
- it is not used directly for the solar heating ratio

### Solar Source Energy Used

This is the solar-origin heat actually used for heating:

- direct solar to load
- direct tank discharge
- low-temperature tank source energy used by the heat pump

This is the basis for:

- `solar_heating_ratio_pct`

### Solar Heating Ratio

The current project metric for solar fraction:

`solar_source_energy_used_kwh / heating_load_kwh`

reported as a percentage.

### Auxiliary Heating Delivered

Heating still supplied by electric boiler or other auxiliary system after solar and tank contributions.

### Auxiliary Energy Input

Actual electricity or fuel-equivalent energy used by the auxiliary system.

## Reading the Main Plots

### Cost Heatmap

- X-axis: collector area
- Y-axis: tank size
- color: annualized total cost
- contour lines: equal-cost lines

Use this plot to identify low-cost design regions.

### Solar Heating Ratio Heatmap

- X-axis: collector area
- Y-axis: tank size
- color: solar heating ratio
- contour lines: equal-ratio lines

Use this plot to see how solar contribution changes with sizing.

### Solar Heating Ratio vs Collector Area

This is a screening plot for Step 1.

It shows whether increasing collector area still gives meaningful gain.

### Solar Heating Ratio vs Tank Size

This is Step 2.

It shows how much storage size still improves solar contribution at a fixed collector area.

### Tank Temperature Plot

Shows:

- top tank temperature
- mean tank temperature
- bottom tank temperature
- heating supply / return reference lines

### Heating Load and Sources Plot

Shows hourly:

- heating load
- direct solar heating
- tank direct discharge
- tank heat-pump-assisted contribution
- auxiliary heating

### Tank Charging and Discharging Plot

Shows hourly:

- tank charging
- tank discharging
- tank loss

## Exported Excel Report

The Excel export includes separate files for each case.

Each workbook includes:

- Step 1 results
- Step 2 results
- final selected result
- optimized result
- hourly data
- monthly data
- annual summary

## Recommended Practical Workflow

1. Check the hourly input file
2. Run `Analyze Input Data`
3. Use the suggested ranges to set candidate collector and tank ranges
4. Run `Run Study`
5. Review cost heatmap and solar heating ratio heatmap
6. Use Step 1 to choose a collector area
7. Use Step 2 to choose a tank size
8. Run `Step 3 Final Results`
9. Export the Excel report

## Current Model Limits

This is a useful design-study model, but it is still simplified.

Main limits:

- lumped collector hydraulics
- no detailed pump power model
- no stratified pipe/port geometry
- simplified cost model
- repeated-year seasonal approximation

The tool is best used for:

- early-stage sizing
- option comparison
- sensitivity study

rather than final detailed engineering design.
