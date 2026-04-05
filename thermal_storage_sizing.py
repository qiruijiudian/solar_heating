#!/usr/bin/env python3
"""CLI entrypoint for solar heating storage sizing calculations."""

from __future__ import annotations

import argparse

from thermal_storage_core import (
    best_design,
    load_input,
    make_candidate_values,
    parse_numeric_list,
    run_design_grid,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Solar heating tank sizing tool")
    parser.add_argument(
        "input_file",
        nargs="?",
        default="01 input files/weather and heating load data.xlsx",
        help="Input CSV or Excel file with hourly weather and heating-load data",
    )
    parser.add_argument("--tank-types", nargs="+", default=["short_term"], choices=["short_term", "seasonal"])
    parser.add_argument("--radiation-unit", default="kwh/m2", choices=["kwh/m2", "w/m2"])
    parser.add_argument("--load-unit", default="kwh", choices=["kwh", "w"])
    parser.add_argument("--timestep-hours", type=float, default=1.0)
    parser.add_argument("--tank-max-temp", type=float, default=80.0)
    parser.add_argument("--tank-min-temp", type=float, default=30.0)
    parser.add_argument("--initial-tank-temp", type=float, default=35.0)
    parser.add_argument("--heating-supply-temp", type=float, default=45.0)
    parser.add_argument("--heating-delta-t", type=float, default=10.0)
    parser.add_argument("--solar-collector-delta-t", type=float, default=10.0)
    parser.add_argument("--short-term-loss", type=float, default=1.0)
    parser.add_argument("--seasonal-loss", type=float, default=0.15)
    parser.add_argument("--auxiliary-system", default="water_heat_pump", choices=["electric", "boiler", "water_heat_pump"])
    parser.add_argument("--auxiliary-efficiency", type=float, default=3.5)
    parser.add_argument("--collector-cost-per-m2", type=float, default=300.0)
    parser.add_argument("--electricity-price", type=float, default=0.12)
    parser.add_argument("--project-lifetime-years", type=float, default=20.0)
    parser.add_argument("--eta0", type=float, default=0.72)
    parser.add_argument("--a1", type=float, default=3.2)
    parser.add_argument("--a2", type=float, default=0.0)
    parser.add_argument("--area-list", default="")
    parser.add_argument("--tank-size-list", default="")
    parser.add_argument("--area-min", type=float, default=50.0)
    parser.add_argument("--area-max", type=float, default=250.0)
    parser.add_argument("--area-step", type=float, default=50.0)
    parser.add_argument("--tank-min", type=float, default=20.0)
    parser.add_argument("--tank-max", type=float, default=200.0)
    parser.add_argument("--tank-step", type=float, default=30.0)
    parser.add_argument("--show-all", action="store_true", help="Print every design case")
    args = parser.parse_args()

    weather_df = load_input(
        filename=args.input_file,
        radiation_unit=args.radiation_unit,
        load_unit=args.load_unit,
        timestep_hours=args.timestep_hours,
    )
    area_values = parse_numeric_list(args.area_list) if args.area_list else make_candidate_values(args.area_min, args.area_max, args.area_step)
    tank_values = (
        parse_numeric_list(args.tank_size_list)
        if args.tank_size_list
        else make_candidate_values(args.tank_min, args.tank_max, args.tank_step)
    )

    summary_df = run_design_grid(
        weather_load_df=weather_df,
        collector_area_list=area_values,
        tank_size_list=tank_values,
        tank_types=args.tank_types,
        tank_min_temp=args.tank_min_temp,
        tank_max_temp=args.tank_max_temp,
        initial_tank_temp=args.initial_tank_temp,
        heating_supply_temp=args.heating_supply_temp,
        heating_delta_t=args.heating_delta_t,
        solar_collector_delta_t=args.solar_collector_delta_t,
        short_term_loss_percent_per_day=args.short_term_loss,
        seasonal_loss_percent_per_day=args.seasonal_loss,
        auxiliary_system=args.auxiliary_system,
        auxiliary_efficiency=args.auxiliary_efficiency,
        timestep_hours=args.timestep_hours,
        eta0=args.eta0,
        a1=args.a1,
        a2=args.a2,
        collector_cost_per_m2=args.collector_cost_per_m2,
        electricity_price=args.electricity_price,
        project_lifetime_years=args.project_lifetime_years,
    )

    if args.show_all:
        print(summary_df.to_string(index=False, float_format=lambda value: f"{value:.3f}"))
        return

    best = best_design(summary_df, objective="cost")
    print("Best design based on minimum annualized total cost:")
    print(f"  Tank type: {best['tank_type_label']}")
    print(f"  Collector area: {best['collector_area_m2']:.2f} m2")
    print(f"  Tank size: {best['tank_volume_m3']:.2f} m3")
    print(f"  Tank capacity: {best['tank_capacity_kwh']:.2f} kWh")
    print(f"  Solar energy collected: {best['solar_energy_collected_kwh']:.2f} kWh")
    print(f"  Solar energy for heating: {best['solar_energy_for_heating_kwh']:.2f} kWh")
    print(f"  Auxiliary heating delivered: {best['auxiliary_heating_delivered_kwh']:.2f} kWh")
    print(f"  Auxiliary energy input: {best['auxiliary_energy_input_kwh']:.2f} kWh")
    print(f"  Solar heating ratio: {best['solar_heating_ratio_pct']:.2f}%")
    print(f"  Annualized total cost: RMB {best['annualized_total_cost']:.2f}")
    print(f"  Final tank temperature: {best['tank_final_temp_c']:.2f} C")


if __name__ == "__main__":
    main()
