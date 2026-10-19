#!/usr/bin/env python3
"""Study load-growth impact on system cost and backup reliance."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from thermal_storage_core import load_input, simulate_design


SCENARIO_DEFAULTS = {
    "short_term": {
        "tank_type": "short_term",
        "tank_min_temp": 35.0,
        "auxiliary_system": "electric",
        "auxiliary_efficiency": 0.98,
        "backup_auxiliary_efficiency": 0.98,
    },
    "seasonal_boiler": {
        "tank_type": "seasonal",
        "tank_min_temp": 35.0,
        "auxiliary_system": "electric",
        "auxiliary_efficiency": 0.98,
        "backup_auxiliary_efficiency": 0.98,
    },
    "seasonal_hp": {
        "tank_type": "seasonal",
        "tank_min_temp": 8.0,
        "auxiliary_system": "water_heat_pump",
        "auxiliary_efficiency": 3.5,
        "backup_auxiliary_efficiency": 0.98,
    },
}


def parse_numeric_list(value: str) -> list[float]:
    values = []
    for part in value.split(","):
        text = part.strip()
        if text:
            values.append(float(text))
    if not values:
        raise ValueError("Provide at least one numeric value.")
    return values


def scale_heating_load(weather_df: pd.DataFrame, multiplier: float) -> pd.DataFrame:
    scaled = weather_df.copy()
    scaled["heating_load"] = scaled["heating_load"] * multiplier
    return scaled


def reliability_metrics(hourly_df: pd.DataFrame) -> dict[str, float]:
    if hourly_df.empty:
        return {
            "heating_hours": 0.0,
            "solar_only_hours": 0.0,
            "solar_only_hour_pct": 0.0,
            "hours_with_aux": 0.0,
            "days_with_aux": 0.0,
            "peak_hourly_aux_kwh": 0.0,
            "peak_daily_aux_kwh": 0.0,
        }

    heating_mask = hourly_df["heating_load_kwh"] > 0
    aux_mask = hourly_df["auxiliary_energy_input_kwh"] > 1e-9
    direct_aux_mask = hourly_df["auxiliary_heating_delivered_kwh"] > 1e-9
    solar_only_mask = heating_mask & ~aux_mask
    daily_aux = (
        hourly_df.assign(date=hourly_df["timestamp"].dt.date)
        .groupby("date", as_index=False)
        .agg(
            auxiliary_energy_input_kwh=("auxiliary_energy_input_kwh", "sum"),
            auxiliary_heating_delivered_kwh=("auxiliary_heating_delivered_kwh", "sum"),
        )
    )

    heating_hours = int(heating_mask.sum())
    solar_only_hours = int(solar_only_mask.sum())
    return {
        "heating_hours": float(heating_hours),
        "solar_only_hours": float(solar_only_hours),
        "solar_only_hour_pct": 100.0 * solar_only_hours / heating_hours if heating_hours else 0.0,
        "hours_with_aux": float(aux_mask.sum()),
        "hours_with_direct_aux": float(direct_aux_mask.sum()),
        "days_with_aux": float((daily_aux["auxiliary_energy_input_kwh"] > 0.1).sum()),
        "peak_hourly_aux_kwh": float(hourly_df["auxiliary_energy_input_kwh"].max()),
        "peak_daily_aux_kwh": float(daily_aux["auxiliary_energy_input_kwh"].max()),
    }


def run_load_sensitivity(
    weather_df: pd.DataFrame,
    load_multipliers: list[float],
    collector_area_m2: float,
    tank_volume_m3: float,
    scenario: str,
    tank_max_temp: float,
    initial_tank_temp: float,
    heating_supply_temp: float,
    heating_delta_t: float,
    solar_collector_delta_t: float,
    collector_flow_lph_per_m2: float,
    collector_delta_t_min_c: float,
    collector_delta_t_max_c: float,
    collector_cost_per_m2: float,
    electricity_price: float,
    project_lifetime_years: float,
) -> pd.DataFrame:
    defaults = SCENARIO_DEFAULTS[scenario]
    rows: list[dict[str, float | str]] = []
    for multiplier in load_multipliers:
        scaled_weather = scale_heating_load(weather_df, multiplier)
        summary, hourly_df = simulate_design(
            scaled_weather,
            collector_area_m2=collector_area_m2,
            tank_volume_m3=tank_volume_m3,
            tank_type=str(defaults["tank_type"]),
            tank_min_temp=float(defaults["tank_min_temp"]),
            tank_max_temp=tank_max_temp,
            initial_tank_temp=initial_tank_temp,
            heating_supply_temp=heating_supply_temp,
            heating_delta_t=heating_delta_t,
            solar_collector_delta_t=solar_collector_delta_t,
            collector_flow_lph_per_m2=collector_flow_lph_per_m2,
            collector_delta_t_min_c=collector_delta_t_min_c,
            collector_delta_t_max_c=collector_delta_t_max_c,
            auxiliary_system=str(defaults["auxiliary_system"]),
            auxiliary_efficiency=float(defaults["auxiliary_efficiency"]),
            backup_auxiliary_efficiency=float(defaults["backup_auxiliary_efficiency"]),
            collector_cost_per_m2=collector_cost_per_m2,
            electricity_price=electricity_price,
            project_lifetime_years=project_lifetime_years,
            return_hourly=True,
        )
        row: dict[str, float | str] = {
            "scenario": scenario,
            "load_multiplier": multiplier,
            "collector_area_m2": collector_area_m2,
            "tank_volume_m3": tank_volume_m3,
            "annual_heating_load_kwh": float(summary["heating_load_kwh"]),
            "solar_heating_ratio_pct": float(summary["solar_heating_ratio_pct"]),
            "auxiliary_fraction_pct": float(summary["auxiliary_fraction_pct"]),
            "annualized_total_cost": float(summary["annualized_total_cost"]),
            "annualized_capital_cost": float(summary["annualized_capital_cost"]),
            "annual_auxiliary_energy_cost": float(summary["annual_auxiliary_energy_cost"]),
            "auxiliary_energy_input_kwh": float(summary["auxiliary_energy_input_kwh"]),
            "auxiliary_heating_delivered_kwh": float(summary["auxiliary_heating_delivered_kwh"]),
            "solar_energy_curtailed_kwh": float(summary["solar_energy_curtailed_kwh"]),
            "tank_loss_kwh": float(summary["tank_loss_kwh"]),
        }
        row.update(reliability_metrics(hourly_df))
        rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Study cost and reliability impact of higher heating loads.")
    parser.add_argument(
        "input_file",
        nargs="?",
        default="01 input files/weather and heating load data.xlsx",
        help="Input CSV or Excel file with hourly weather and heating-load data",
    )
    parser.add_argument(
        "--scenario",
        default="seasonal_hp",
        choices=sorted(SCENARIO_DEFAULTS),
        help="System configuration preset to test",
    )
    parser.add_argument("--collector-area", type=float, required=True, help="Collector area in m2")
    parser.add_argument("--tank-volume", type=float, required=True, help="Tank volume in m3")
    parser.add_argument(
        "--load-multipliers",
        default="1.0,1.1,1.2,1.3",
        help="Comma-separated heating-load multipliers to test, e.g. 1.0,1.15,1.3",
    )
    parser.add_argument("--radiation-unit", default="kwh/m2", choices=["kwh/m2", "w/m2"])
    parser.add_argument("--load-unit", default="kwh", choices=["kwh", "w"])
    parser.add_argument("--timestep-hours", type=float, default=1.0)
    parser.add_argument("--tank-max-temp", type=float, default=80.0)
    parser.add_argument("--initial-tank-temp", type=float, default=35.0)
    parser.add_argument("--heating-supply-temp", type=float, default=45.0)
    parser.add_argument("--heating-delta-t", type=float, default=10.0)
    parser.add_argument("--solar-collector-delta-t", type=float, default=10.0)
    parser.add_argument("--collector-flow-lph-per-m2", type=float, default=20.0)
    parser.add_argument("--collector-delta-t-min-c", type=float, default=2.0)
    parser.add_argument("--collector-delta-t-max-c", type=float, default=15.0)
    parser.add_argument("--collector-cost-per-m2", type=float, default=800.0)
    parser.add_argument("--electricity-price", type=float, default=0.12)
    parser.add_argument("--project-lifetime-years", type=float, default=25.0)
    parser.add_argument("--output-csv", default="", help="Optional CSV file for the study table")
    args = parser.parse_args()

    weather_df = load_input(
        filename=args.input_file,
        radiation_unit=args.radiation_unit,
        load_unit=args.load_unit,
        timestep_hours=args.timestep_hours,
    )
    load_multipliers = parse_numeric_list(args.load_multipliers)
    results_df = run_load_sensitivity(
        weather_df=weather_df,
        load_multipliers=load_multipliers,
        collector_area_m2=args.collector_area,
        tank_volume_m3=args.tank_volume,
        scenario=args.scenario,
        tank_max_temp=args.tank_max_temp,
        initial_tank_temp=args.initial_tank_temp,
        heating_supply_temp=args.heating_supply_temp,
        heating_delta_t=args.heating_delta_t,
        solar_collector_delta_t=args.solar_collector_delta_t,
        collector_flow_lph_per_m2=args.collector_flow_lph_per_m2,
        collector_delta_t_min_c=args.collector_delta_t_min_c,
        collector_delta_t_max_c=args.collector_delta_t_max_c,
        collector_cost_per_m2=args.collector_cost_per_m2,
        electricity_price=args.electricity_price,
        project_lifetime_years=args.project_lifetime_years,
    )

    if args.output_csv:
        output_path = Path(args.output_csv)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        results_df.to_csv(output_path, index=False)
        print(f"Saved study table to: {output_path}")

    display_columns = [
        "scenario",
        "load_multiplier",
        "annual_heating_load_kwh",
        "solar_heating_ratio_pct",
        "annualized_total_cost",
        "annual_auxiliary_energy_cost",
        "auxiliary_energy_input_kwh",
        "hours_with_aux",
        "days_with_aux",
        "peak_daily_aux_kwh",
        "solar_only_hour_pct",
    ]
    print(results_df[display_columns].to_string(index=False, float_format=lambda value: f"{value:.3f}"))


if __name__ == "__main__":
    main()
