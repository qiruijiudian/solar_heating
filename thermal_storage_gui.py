#!/usr/bin/env python3
"""Panel GUI for solar heating storage sizing."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sys

import numpy as np

try:
    import hvplot.pandas  # noqa: F401
    import panel as pn
    import pandas as pd
except ModuleNotFoundError as exc:
    missing = exc.name or "panel/hvplot"
    raise SystemExit(
        "Missing GUI dependency: "
        f"{missing}\n"
        "Install the GUI packages into the active environment with:\n"
        f"  {sys.executable} -m pip install panel hvplot holoviews bokeh openpyxl"
    ) from exc

from thermal_storage_core import (
    TANK_TYPE_DEFAULTS,
    best_design,
    load_input,
    run_collector_area_study,
    run_design_grid,
    run_tank_size_study,
    simulate_design,
)

pn.extension("tabulator")


def evenly_spaced_values(min_value: float, max_value: float, count: int) -> list[float]:
    if count <= 0:
        raise ValueError("The number of size options must be at least 1.")
    if max_value < min_value:
        raise ValueError("Maximum value must be greater than or equal to minimum value.")
    if count == 1:
        return [round(min_value, 3)]
    return [round(float(value), 3) for value in np.linspace(min_value, max_value, count)]


def extract_size_lists_from_excel(file_bytes: bytes) -> tuple[list[float], list[float]]:
    df = pd.read_excel(BytesIO(file_bytes))
    normalized = {column.strip().lower(): column for column in df.columns}

    tank_column = None
    for name in ["tank_volume_m3", "tank_size_m3", "tank_size", "tank_m3"]:
        if name in normalized:
            tank_column = normalized[name]
            break

    collector_column = None
    for name in ["collector_area_m2", "solar_collector_area_m2", "collector_area", "solar_area_m2"]:
        if name in normalized:
            collector_column = normalized[name]
            break

    if tank_column is None or collector_column is None:
        raise ValueError(
            "Excel file must contain columns for tank sizes and collector areas, "
            "for example `tank_volume_m3` and `collector_area_m2`."
        )

    tank_values = sorted(set(pd.to_numeric(df[tank_column], errors="coerce").dropna().astype(float).tolist()))
    collector_values = sorted(set(pd.to_numeric(df[collector_column], errors="coerce").dropna().astype(float).tolist()))

    if not tank_values or not collector_values:
        raise ValueError("Excel file did not contain any valid tank or collector size values.")

    return collector_values, tank_values


def selected_tank_types(study_mode: str) -> list[str]:
    if study_mode == "Short-Term Only":
        return ["short_term"]
    if study_mode == "Seasonal Only":
        return ["seasonal"]
    return ["short_term", "seasonal"]


def tank_type_options(tank_types: list[str]) -> dict[str, str]:
    return {TANK_TYPE_DEFAULTS[tank_type]["label"]: tank_type for tank_type in tank_types}


def best_by_type(df: pd.DataFrame, objective: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()
    rows = [best_design(group, objective=objective) for _, group in df.groupby("tank_type", sort=False)]
    return pd.DataFrame(rows).reset_index(drop=True)


def build_dashboard():
    input_dir = Path(__file__).resolve().parent / "01 input files"
    input_dir.mkdir(exist_ok=True)
    hourly_input_path = input_dir / "sample_year_data.csv"

    path_input = pn.widgets.TextInput(
        name="Hourly CSV File",
        value=str(Path("01 input files") / "sample_year_data.csv"),
        disabled=True,
    )
    hourly_file = pn.widgets.FileInput(name="Upload Hourly CSV", accept=".csv")
    update_hourly_button = pn.widgets.Button(name="Update Hourly Input File", button_type="warning")
    hourly_upload_status = pn.pane.Markdown("")

    study_mode = pn.widgets.RadioButtonGroup(
        name="Storage Study",
        options=["Short-Term Only", "Seasonal Only", "Compare Both"],
        value="Compare Both",
        button_type="success",
    )
    optimization_mode = pn.widgets.RadioButtonGroup(
        name="Optimization Mode",
        options=["Cost Optimization", "Two-Step Study"],
        value="Cost Optimization",
        button_type="primary",
    )
    auxiliary_system = pn.widgets.Select(
        name="Auxiliary System",
        options={
            "Electric Heater": "electric",
            "Boiler": "boiler",
            "Water Heat Pump": "water_heat_pump",
        },
        value="water_heat_pump",
    )
    auxiliary_efficiency = pn.widgets.FloatInput(name="Auxiliary Efficiency / COP", value=3.5, step=0.1)
    electricity_price = pn.widgets.FloatInput(name="Electricity / Energy Price ($/kWh)", value=0.12, step=0.01)

    tank_max_temp = pn.widgets.FloatInput(name="Tank Max Temp (C)", value=80.0, step=1.0)
    tank_min_temp = pn.widgets.FloatInput(name="Tank Min Temp (C)", value=30.0, step=1.0)
    initial_tank_temp = pn.widgets.FloatInput(name="Initial Tank Temp (C)", value=35.0, step=1.0)
    heating_supply_temp = pn.widgets.FloatInput(name="Heating Supply Temp (C)", value=45.0, step=1.0)
    heating_delta_t = pn.widgets.FloatInput(name="Heating System Delta T (C)", value=10.0, step=1.0)
    solar_collector_delta_t = pn.widgets.FloatInput(name="Solar Collector Delta T (C)", value=10.0, step=1.0)

    short_term_loss = pn.widgets.FloatInput(name="Short-Term Tank Loss (%/day)", value=1.0, step=0.1)
    seasonal_loss = pn.widgets.FloatInput(name="Seasonal Tank Loss (%/day)", value=0.15, step=0.05)
    short_term_ratio = pn.widgets.FloatInput(name="Short-Term Large Tank Ratio (L/m2)", value=200.0, step=25.0)
    seasonal_ratio = pn.widgets.FloatInput(name="Seasonal Large Tank Ratio (L/m2)", value=2000.0, step=100.0)

    collector_cost_per_m2 = pn.widgets.FloatInput(name="Collector Cost ($/m2)", value=300.0, step=10.0)
    project_lifetime_years = pn.widgets.FloatInput(name="Project Lifetime (years)", value=20.0, step=1.0)
    short_term_cost_coeff = pn.widgets.FloatInput(name="Short-Term Tank Cost Coefficient", value=1400.0, step=50.0)
    short_term_cost_exponent = pn.widgets.FloatInput(name="Short-Term Tank Cost Exponent", value=0.78, step=0.01)
    seasonal_cost_coeff = pn.widgets.FloatInput(name="Seasonal Tank Cost Coefficient", value=900.0, step=50.0)
    seasonal_cost_exponent = pn.widgets.FloatInput(name="Seasonal Tank Cost Exponent", value=0.82, step=0.01)

    sizing_mode = pn.widgets.RadioButtonGroup(
        name="Candidate Sizes",
        options=["Auto Generate", "Upload Excel"],
        value="Auto Generate",
        button_type="light",
    )
    collector_min_size = pn.widgets.FloatInput(name="Collector Min Area (m2)", value=50.0, step=10.0)
    collector_max_size = pn.widgets.FloatInput(name="Collector Max Area (m2)", value=500.0, step=10.0)
    collector_count = pn.widgets.IntInput(name="Collector Area Count", value=8, step=1, start=1)
    tank_min_size = pn.widgets.FloatInput(name="Tank Min Size (m3)", value=10.0, step=5.0)
    tank_max_size = pn.widgets.FloatInput(name="Tank Max Size (m3)", value=600.0, step=10.0)
    tank_count = pn.widgets.IntInput(name="Tank Size Count", value=8, step=1, start=1)
    sizing_file = pn.widgets.FileInput(name="Sizing Excel File", accept=".xlsx")
    sizing_help = pn.pane.Markdown(
        "Upload an Excel file with columns like `collector_area_m2` and `tank_volume_m3`.",
        visible=False,
    )

    eta0 = pn.widgets.FloatInput(name="Collector eta0", value=0.72, step=0.01)
    a1 = pn.widgets.FloatInput(name="Collector a1", value=3.2, step=0.1)

    run_button = pn.widgets.Button(name="Run Study", button_type="primary")
    selected_detail_type = pn.widgets.Select(name="Detail Storage Type", options={})
    selected_area = pn.widgets.Select(name="Selected Collector Area (m2)", options=[])
    selected_tank = pn.widgets.Select(name="Selected Tank Size (m3)", options=[])

    status = pn.pane.Markdown("Ready.")
    metrics = pn.pane.Markdown("")
    best_table = pn.widgets.Tabulator(pagination="remote", page_size=5, sizing_mode="stretch_width", height=180)
    summary_table = pn.widgets.Tabulator(pagination="remote", page_size=12, sizing_mode="stretch_width", height=320)
    collector_study_plot = pn.pane.HoloViews(height=320, sizing_mode="stretch_width")
    tank_study_plot = pn.pane.HoloViews(height=320, sizing_mode="stretch_width")
    tank_temp_plot = pn.pane.HoloViews(height=320, sizing_mode="stretch_width")
    heating_plot = pn.pane.HoloViews(height=340, sizing_mode="stretch_width")
    tank_flow_plot = pn.pane.HoloViews(height=320, sizing_mode="stretch_width")
    weather_plot = pn.pane.HoloViews(height=280, sizing_mode="stretch_width")

    state = {
        "weather_df": None,
        "design_grid_df": None,
        "collector_study_df": None,
        "tank_study_df": None,
        "tank_types": [],
        "area_values": [],
        "tank_values": [],
    }

    def update_hourly_file(_event=None) -> None:
        try:
            if not hourly_file.value:
                raise ValueError("Choose a CSV file to update the hourly input file.")
            hourly_input_path.write_bytes(hourly_file.value)
            hourly_upload_status.object = (
                "Hourly input file updated: "
                f"`{Path('01 input files') / 'sample_year_data.csv'}`"
            )
        except Exception as exc:
            hourly_upload_status.object = f"Hourly file update failed: `{exc}`"

    def current_size_lists() -> tuple[list[float], list[float]]:
        if sizing_mode.value == "Upload Excel":
            if not sizing_file.value:
                raise ValueError("Upload an Excel file with tank and collector size lists.")
            return extract_size_lists_from_excel(sizing_file.value)

        collector_values = evenly_spaced_values(
            min_value=collector_min_size.value,
            max_value=collector_max_size.value,
            count=collector_count.value,
        )
        tank_values = evenly_spaced_values(
            min_value=tank_min_size.value,
            max_value=tank_max_size.value,
            count=tank_count.value,
        )
        return collector_values, tank_values

    def study_kwargs() -> dict[str, float | str]:
        return {
            "tank_min_temp": tank_min_temp.value,
            "tank_max_temp": tank_max_temp.value,
            "initial_tank_temp": initial_tank_temp.value,
            "heating_supply_temp": heating_supply_temp.value,
            "heating_delta_t": heating_delta_t.value,
            "solar_collector_delta_t": solar_collector_delta_t.value,
            "short_term_loss_percent_per_day": short_term_loss.value,
            "seasonal_loss_percent_per_day": seasonal_loss.value,
            "auxiliary_system": auxiliary_system.value,
            "auxiliary_efficiency": auxiliary_efficiency.value,
            "eta0": eta0.value,
            "a1": a1.value,
            "collector_cost_per_m2": collector_cost_per_m2.value,
            "short_term_cost_coeff": short_term_cost_coeff.value,
            "short_term_cost_exponent": short_term_cost_exponent.value,
            "seasonal_cost_coeff": seasonal_cost_coeff.value,
            "seasonal_cost_exponent": seasonal_cost_exponent.value,
            "electricity_price": electricity_price.value,
            "project_lifetime_years": project_lifetime_years.value,
        }

    def detail_kwargs() -> dict[str, float | str]:
        return {
            "tank_min_temp": tank_min_temp.value,
            "tank_max_temp": tank_max_temp.value,
            "initial_tank_temp": initial_tank_temp.value,
            "heating_supply_temp": heating_supply_temp.value,
            "heating_delta_t": heating_delta_t.value,
            "solar_collector_delta_t": solar_collector_delta_t.value,
            "auxiliary_system": auxiliary_system.value,
            "auxiliary_efficiency": auxiliary_efficiency.value,
            "eta0": eta0.value,
            "a1": a1.value,
            "collector_cost_per_m2": collector_cost_per_m2.value,
            "short_term_cost_coeff": short_term_cost_coeff.value,
            "short_term_cost_exponent": short_term_cost_exponent.value,
            "seasonal_cost_coeff": seasonal_cost_coeff.value,
            "seasonal_cost_exponent": seasonal_cost_exponent.value,
            "electricity_price": electricity_price.value,
            "project_lifetime_years": project_lifetime_years.value,
        }

    def update_sizing_mode(*_events) -> None:
        auto_visible = sizing_mode.value == "Auto Generate"
        collector_min_size.visible = auto_visible
        collector_max_size.visible = auto_visible
        collector_count.visible = auto_visible
        tank_min_size.visible = auto_visible
        tank_max_size.visible = auto_visible
        tank_count.visible = auto_visible
        sizing_file.visible = not auto_visible
        sizing_help.visible = not auto_visible

    def current_objective() -> str:
        return "cost" if optimization_mode.value == "Cost Optimization" else "auxiliary"

    def update_best_and_status() -> None:
        design_grid_df = state["design_grid_df"]
        collector_df = state["collector_study_df"]
        tank_df = state["tank_study_df"]
        if design_grid_df is None or collector_df is None:
            return

        if optimization_mode.value == "Cost Optimization":
            per_type = best_by_type(design_grid_df, objective="cost")
            overall = best_design(design_grid_df, objective="cost")
            best_table.value = per_type.round(3)
            status.object = (
                "### Cost Optimization\n"
                f"- Overall best design: `{overall['tank_type_label']}` with "
                f"`{overall['collector_area_m2']:.1f} m2` collector and "
                f"`{overall['tank_volume_m3']:.1f} m3` tank\n"
                f"- Annualized total cost: `${overall['annualized_total_cost']:.2f}`\n"
                f"- Solar coverage: `{overall['solar_coverage_pct']:.2f}%`"
            )
        else:
            per_type = best_by_type(tank_df, objective="cost") if tank_df is not None and not tank_df.empty else pd.DataFrame()
            best_table.value = per_type.round(3)
            selected_area_value = float(selected_area.value) if selected_area.value is not None else 0.0
            if per_type.empty:
                status.object = (
                    "### Two-Step Study\n"
                    "Step 1 completed. Select a collector area to calculate the tank-size study."
                )
            else:
                lines = [
                    "### Two-Step Study",
                    f"- Step 1 uses large-tank ratios of `{short_term_ratio.value:.0f} L/m2` for short-term and "
                    f"`{seasonal_ratio.value:.0f} L/m2` for seasonal storage.",
                    f"- Selected collector area for Step 2: `{selected_area_value:.1f} m2`",
                ]
                for row in per_type.itertuples(index=False):
                    lines.append(
                        f"- Recommended {row.tank_type_label}: `{row.tank_volume_m3:.1f} m3` tank, "
                        f"`{row.solar_coverage_pct:.2f}%` solar coverage, "
                        f"`$ {row.annualized_total_cost:.2f}` annualized total cost".replace("$ ", "$")
                    )
                status.object = "\n".join(lines)

    def update_collector_plot() -> None:
        collector_df = state["collector_study_df"]
        if collector_df is None or collector_df.empty:
            return
        collector_study_plot.object = collector_df.hvplot.line(
            x="collector_area_m2",
            y="solar_coverage_pct",
            by="tank_type_label",
            ylabel="Solar Coverage (%)",
            xlabel="Collector Area (m2)",
            title="Solar Coverage vs Collector Area with Large Tank Ratios",
            legend="top_left",
        )

    def update_tank_study() -> None:
        weather_df = state["weather_df"]
        tank_types = state["tank_types"]
        tank_values = state["tank_values"]
        if weather_df is None or not tank_types or not tank_values or selected_area.value is None:
            return

        tank_df = run_tank_size_study(
            weather_load_df=weather_df,
            collector_area_m2=float(selected_area.value),
            tank_size_list=tank_values,
            tank_types=tank_types,
            **study_kwargs(),
        )
        state["tank_study_df"] = tank_df
        tank_study_plot.object = tank_df.hvplot.line(
            x="tank_volume_m3",
            y="solar_coverage_pct",
            by="tank_type_label",
            ylabel="Solar Coverage (%)",
            xlabel="Tank Size (m3)",
            title=f"Solar Coverage vs Tank Size at {float(selected_area.value):.1f} m2 Collector Area",
            legend="top_left",
        )

        if selected_detail_type.value not in tank_types:
            selected_detail_type.value = tank_types[0]

        detail_df = tank_df[tank_df["tank_type"] == selected_detail_type.value]
        if detail_df.empty:
            selected_tank.options = tank_values
            selected_tank.value = tank_values[0]
        else:
            selected_tank.options = sorted(detail_df["tank_volume_m3"].unique().tolist())
            if selected_tank.value not in selected_tank.options:
                recommended = best_design(detail_df, objective="cost")
                selected_tank.value = float(recommended["tank_volume_m3"])

        if optimization_mode.value == "Two-Step Study":
            summary_table.value = tank_df.round(3)

        update_best_and_status()
        update_hourly_view()

    def update_hourly_view(*_events) -> None:
        weather_df = state["weather_df"]
        if weather_df is None or selected_detail_type.value is None or selected_area.value is None or selected_tank.value is None:
            return

        loss_value = short_term_loss.value if selected_detail_type.value == "short_term" else seasonal_loss.value
        summary, hourly_df = simulate_design(
            weather_load_df=weather_df,
            collector_area_m2=float(selected_area.value),
            tank_volume_m3=float(selected_tank.value),
            tank_type=selected_detail_type.value,
            tank_thermal_loss_percent_per_day=loss_value,
            **detail_kwargs(),
        )

        supply_overlay = hourly_df.assign(
            supply_temp_c=heating_supply_temp.value,
            return_temp_c=heating_supply_temp.value - heating_delta_t.value,
        ).hvplot.line(
            x="timestamp",
            y=["supply_temp_c", "return_temp_c"],
            line_dash=["dashed", "dotted"],
            color=["firebrick", "gray"],
        )
        tank_temp_plot.object = hourly_df.hvplot.line(
            x="timestamp",
            y=["tank_temp_start_c", "tank_temp_end_c"],
            ylabel="Temperature (C)",
            title="Tank Temperature Time Series",
            legend="top_left",
        ) * supply_overlay

        heating_plot.object = hourly_df.hvplot.line(
            x="timestamp",
            y=[
                "heating_load_kwh",
                "solar_direct_collector_to_load_kwh",
                "solar_from_tank_direct_kwh",
                "solar_from_tank_via_hp_kwh",
                "auxiliary_heating_delivered_kwh",
            ],
            ylabel="Heating Energy (kWh)",
            title="Heating Load, Solar Heating, and Auxiliary Heating",
            legend="top_left",
        )

        tank_flow_df = hourly_df.assign(
            tank_charge_plot=hourly_df["tank_charge_kwh"],
            tank_discharge_plot=-hourly_df["tank_discharge_total_kwh"],
            tank_loss_plot=-hourly_df["tank_loss_kwh"],
        )
        tank_flow_plot.object = tank_flow_df.hvplot.line(
            x="timestamp",
            y=["tank_charge_plot", "tank_discharge_plot", "tank_loss_plot"],
            ylabel="Tank Energy Flow (kWh)",
            title="Tank Charging, Discharging, and Thermal Loss",
            legend="top_left",
        )

        weather_plot.object = weather_df.hvplot.line(
            x="timestamp",
            y=["outside_temp", "heating_load", "solar_rad"],
            title="Hourly Weather and Load Inputs",
            legend="top_left",
        )

        metrics.object = (
            "### Selected Design Detail\n"
            f"- Storage type: `{summary['tank_type_label']}`\n"
            f"- Collector area: `{summary['collector_area_m2']:.1f} m2`\n"
            f"- Tank size: `{summary['tank_volume_m3']:.1f} m3`\n"
            f"- Initial tank temperature: `{summary['initial_tank_temp_c']:.1f} C`\n"
            f"- Final tank temperature: `{summary['tank_final_temp_c']:.1f} C`\n"
            f"- Solar coverage: `{summary['solar_coverage_pct']:.2f}%`\n"
            f"- Direct solar to load: `{summary['solar_direct_collector_to_load_kwh']:.1f} kWh`\n"
            f"- Tank discharge above supply temp: `{summary['solar_from_tank_direct_kwh']:.1f} kWh`\n"
            f"- Tank discharge with heat pump boost: `{summary['solar_from_tank_via_hp_kwh']:.1f} kWh`\n"
            f"- Heat pump boost electricity: `{summary['auxiliary_energy_for_hp_boost_kwh']:.1f} kWh`\n"
            f"- Auxiliary heating delivered: `{summary['auxiliary_heating_delivered_kwh']:.1f} kWh`\n"
            f"- Tank thermal loss: `{summary['tank_loss_kwh']:.1f} kWh`\n"
            f"- Annualized total cost: `${summary['annualized_total_cost']:.2f}`"
        )

    def run_study(_event=None) -> None:
        try:
            if tank_max_temp.value <= tank_min_temp.value:
                raise ValueError("Tank maximum temperature must be greater than tank minimum temperature.")
            if not (tank_min_temp.value <= initial_tank_temp.value <= tank_max_temp.value):
                raise ValueError("Initial tank temperature must be between tank minimum and maximum temperature.")
            if heating_supply_temp.value > tank_max_temp.value:
                raise ValueError("Heating supply temperature should not exceed the tank maximum temperature.")
            if project_lifetime_years.value <= 0:
                raise ValueError("Project lifetime must be greater than zero.")

            weather_df = load_input(filename=hourly_input_path)
            area_values, tank_values = current_size_lists()
            tank_types = selected_tank_types(study_mode.value)

            design_grid_df = run_design_grid(
                weather_load_df=weather_df,
                collector_area_list=area_values,
                tank_size_list=tank_values,
                tank_types=tank_types,
                **study_kwargs(),
            )
            collector_df = run_collector_area_study(
                weather_load_df=weather_df,
                collector_area_list=area_values,
                tank_types=tank_types,
                short_term_ratio_l_per_m2=short_term_ratio.value,
                seasonal_ratio_l_per_m2=seasonal_ratio.value,
                **study_kwargs(),
            )

            state["weather_df"] = weather_df
            state["design_grid_df"] = design_grid_df
            state["collector_study_df"] = collector_df
            state["tank_types"] = tank_types
            state["area_values"] = area_values
            state["tank_values"] = tank_values

            selected_detail_type.options = tank_type_options(tank_types)
            if selected_detail_type.value not in tank_types:
                if optimization_mode.value == "Cost Optimization":
                    overall_best = best_design(design_grid_df, objective="cost")
                    selected_detail_type.value = overall_best["tank_type"]
                else:
                    selected_detail_type.value = tank_types[0]

            selected_area.options = area_values
            if optimization_mode.value == "Cost Optimization":
                overall_best = best_design(design_grid_df, objective="cost")
                selected_area.value = float(overall_best["collector_area_m2"])
            elif selected_area.value not in area_values:
                area_best = best_design(collector_df, objective="cost")
                selected_area.value = float(area_best["collector_area_m2"])

            update_collector_plot()

            if optimization_mode.value == "Cost Optimization":
                summary_table.value = design_grid_df.round(3)

            update_tank_study()
        except Exception as exc:
            status.object = f"### Error\n`{exc}`"

    update_hourly_button.on_click(update_hourly_file)
    run_button.on_click(run_study)
    selected_area.param.watch(update_tank_study, "value")
    selected_tank.param.watch(update_hourly_view, "value")
    selected_detail_type.param.watch(update_tank_study, "value")
    sizing_mode.param.watch(update_sizing_mode, "value")
    update_sizing_mode()

    sidebar_controls = pn.Column(
        pn.pane.Markdown("## Study Control"),
        pn.pane.Markdown("### Input File"),
        path_input,
        hourly_file,
        update_hourly_button,
        hourly_upload_status,
        pn.pane.Markdown("### Actions"),
        run_button,
        status,
        width=390,
    )

    top_inputs = pn.Column(
        pn.pane.Markdown("### Study Scope"),
        pn.Row(study_mode, optimization_mode),
        pn.pane.Markdown("### Tank Temperature"),
        pn.Row(tank_max_temp, tank_min_temp, initial_tank_temp, heating_supply_temp),
        pn.Row(heating_delta_t, solar_collector_delta_t),
        pn.pane.Markdown("### Storage Type Settings"),
        pn.Row(short_term_loss, seasonal_loss, short_term_ratio, seasonal_ratio),
        pn.pane.Markdown("### Auxiliary Input"),
        pn.Row(auxiliary_system, auxiliary_efficiency, electricity_price),
        pn.pane.Markdown("### Cost Input"),
        pn.Row(
            collector_cost_per_m2,
            project_lifetime_years,
            short_term_cost_coeff,
            short_term_cost_exponent,
        ),
        pn.Row(seasonal_cost_coeff, seasonal_cost_exponent),
        pn.pane.Markdown("### Candidate Size Input"),
        pn.Row(sizing_mode),
        pn.Row(collector_min_size, collector_max_size, collector_count, sizing_file),
        pn.Row(tank_min_size, tank_max_size, tank_count),
        sizing_help,
        pn.pane.Markdown("### Collector Model"),
        pn.Row(eta0, a1),
        sizing_mode="stretch_width",
    )

    detail_controls = pn.Row(selected_detail_type, selected_area, selected_tank)
    dashboard = pn.template.FastListTemplate(
        title="Solar Thermal Storage Design Study",
        sidebar=[sidebar_controls],
        main=[
            pn.pane.Markdown("## Design Inputs"),
            top_inputs,
            pn.Row(metrics),
            pn.pane.Markdown("## Design Recommendations"),
            pn.Row(best_table),
            pn.pane.Markdown("## Study Outputs"),
            pn.Row(collector_study_plot, tank_study_plot),
            pn.pane.Markdown("## Selected Design Time Series"),
            detail_controls,
            pn.Row(tank_temp_plot),
            pn.Row(heating_plot),
            pn.Row(tank_flow_plot),
            pn.Row(weather_plot),
            pn.pane.Markdown("## Design Table"),
            pn.Row(summary_table),
        ],
    )

    run_study()
    return dashboard


def main() -> None:
    pn.serve(build_dashboard(), show=True)


if __name__.startswith("bokeh"):
    build_dashboard().servable()


if __name__ == "__main__":
    main()
