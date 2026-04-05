#!/usr/bin/env python3
"""Panel GUI for solar heating storage sizing."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import sys

import numpy as np

try:
    import hvplot.pandas  # noqa: F401
    import holoviews as hv
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
    analyze_input_data,
    best_design,
    export_case_report,
    load_input,
    run_collector_area_study,
    run_design_grid,
    run_tank_size_study,
    simulate_design,
)

pn.extension("tabulator")

BUTTON_WIDTH = 260
PLOT_HEIGHT = 450


COLLECTOR_TYPE_PRESETS = {
    "Flat Plate": {"eta0": 0.72, "a1": 3.2, "a2": 0.0},
    "Evacuated Tube": {"eta0": 0.65, "a1": 1.5, "a2": 0.005},
    "Custom": None,
}


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


def heatmap_frame(df: pd.DataFrame, value_column: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["collector_area_m2", "tank_volume_m3", value_column])
    return df[["collector_area_m2", "tank_volume_m3", value_column, "tank_type_label"]].copy()


def build_quadmesh_heatmap(df: pd.DataFrame, value_column: str, title: str, cmap: str):
    if df.empty:
        return None
    pivot = (
        df.pivot_table(
            index="tank_volume_m3",
            columns="collector_area_m2",
            values=value_column,
            aggfunc="mean",
        )
        .sort_index()
        .sort_index(axis=1)
    )
    return hv.QuadMesh(
        (
            pivot.columns.to_numpy(dtype=float),
            pivot.index.to_numpy(dtype=float),
            pivot.to_numpy(dtype=float),
        ),
        kdims=["collector_area_m2", "tank_volume_m3"],
        vdims=[value_column],
    ).opts(
        cmap=cmap,
        colorbar=True,
        title=title,
        xlabel="Collector Area (m2)",
        ylabel="Tank Size (m3)",
        tools=["hover"],
        show_grid=True,
        shared_axes=False,
        height=PLOT_HEIGHT,
    )


def scenario_monthly_summary(hourly_df: pd.DataFrame) -> pd.DataFrame:
    if hourly_df.empty:
        return pd.DataFrame()
    working = hourly_df.copy()
    working["month"] = working["timestamp"].dt.to_period("M").astype(str)

    def productive_efficiency_pct(values: pd.Series, collected: pd.Series) -> float:
        productive = values[collected > 0]
        source = productive if not productive.empty else values
        return 100.0 * float(source.mean()) if len(source) else 0.0

    monthly_df = (
        working.groupby("month", as_index=False)
        .apply(
            lambda group: pd.Series(
                {
                    "total_heating_load_kwh": group["heating_load_kwh"].sum(),
                    "average_heating_load_kwh": group["heating_load_kwh"].mean(),
                    "usable_solar_heat_kwh": group["solar_source_energy_used_kwh"].sum(),
                    "solar_heating_energy_kwh": group["solar_heating_total_kwh"].sum(),
                    "auxiliary_energy_kwh": group["auxiliary_energy_input_kwh"].sum(),
                    "collector_efficiency_pct": productive_efficiency_pct(
                        group["collector_efficiency"], group["solar_energy_collected_kwh"]
                    ),
                    "tank_charge_kwh": group["tank_charge_kwh"].sum(),
                    "tank_loss_kwh": group["tank_loss_kwh"].sum(),
                }
            ),
            include_groups=False,
        )
        .reset_index()
    )
    monthly_df["solar_heat_ratio_pct"] = np.where(
        monthly_df["total_heating_load_kwh"] > 0,
        100.0 * monthly_df["solar_heating_energy_kwh"] / monthly_df["total_heating_load_kwh"],
        0.0,
    )
    annual_row = pd.DataFrame(
        [
            {
                "month": "Annual Summary",
                "total_heating_load_kwh": monthly_df["total_heating_load_kwh"].sum(),
                "average_heating_load_kwh": working["heating_load_kwh"].mean(),
                "usable_solar_heat_kwh": monthly_df["usable_solar_heat_kwh"].sum(),
                "solar_heating_energy_kwh": monthly_df["solar_heating_energy_kwh"].sum(),
                "auxiliary_energy_kwh": monthly_df["auxiliary_energy_kwh"].sum(),
                "collector_efficiency_pct": productive_efficiency_pct(
                    working["collector_efficiency"], working["solar_energy_collected_kwh"]
                ),
                "tank_charge_kwh": monthly_df["tank_charge_kwh"].sum(),
                "tank_loss_kwh": monthly_df["tank_loss_kwh"].sum(),
                "solar_heat_ratio_pct": (
                    100.0 * monthly_df["solar_heating_energy_kwh"].sum() / monthly_df["total_heating_load_kwh"].sum()
                    if monthly_df["total_heating_load_kwh"].sum() > 0
                    else 0.0
                ),
            }
        ]
    )
    return pd.concat([monthly_df, annual_row], ignore_index=True)


def load_design_inputs_from_excel(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        df = pd.read_excel(path)
    except Exception:
        return {}
    if df.empty:
        return {}
    row = df.iloc[0].to_dict()
    return {str(key): value for key, value in row.items() if pd.notna(value)}


def save_design_inputs_to_excel(path: Path, values: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([values]).to_excel(path, index=False)


def plot_container(height: int) -> pn.Column:
    return pn.Column(
        pn.pane.Markdown("Plot will appear after the analysis runs."),
        height=height,
        min_height=height,
        sizing_mode="stretch_width",
        margin=(0, 0, 6, 0),
    )


def set_plot(container: pn.Column, plot=None, empty_message: str = "Plot will appear after the analysis runs.") -> None:
    container.objects = [plot if plot is not None else pn.pane.Markdown(empty_message)]


def build_dashboard():
    input_dir = Path(__file__).resolve().parent / "01 input files"
    input_dir.mkdir(exist_ok=True)
    hourly_input_path = input_dir / "weather and heating load data.xlsx"
    design_inputs_path = Path(__file__).resolve().parent / "design_inputs.xlsx"
    default_inputs = {
        "tank_max_temp": 80.0,
        "small_delta_t_tank_min_temp": 35.0,
        "large_delta_t_tank_min_temp": 8.0,
        "initial_tank_temp": 35.0,
        "heating_supply_temp": 45.0,
        "heating_delta_t": 10.0,
        "solar_collector_delta_t": 10.0,
        "short_term_loss": 1.0,
        "seasonal_loss": 0.15,
        "short_term_ratio": 200.0,
        "seasonal_ratio": 2000.0,
        "collector_cost_per_m2": 300.0,
        "project_lifetime_years": 20.0,
        "electricity_price": 0.12,
        "electric_boiler_efficiency": 0.98,
        "heat_pump_cop": 3.5,
        "short_term_cost_coeff": 1400.0,
        "short_term_cost_exponent": 0.78,
        "seasonal_cost_coeff": 900.0,
        "seasonal_cost_exponent": 0.82,
        "sizing_mode": "Auto Generate",
        "short_collector_min_size": 50.0,
        "short_collector_max_size": 500.0,
        "short_collector_count": 8,
        "short_tank_min_size": 10.0,
        "short_tank_max_size": 600.0,
        "short_tank_count": 8,
        "long_collector_min_size": 200.0,
        "long_collector_max_size": 2000.0,
        "long_collector_count": 8,
        "long_tank_min_size": 100.0,
        "long_tank_max_size": 5000.0,
        "long_tank_count": 8,
        "collector_type": "Flat Plate",
        "eta0": 0.72,
        "a1": 3.2,
        "a2": 0.0,
    }
    default_inputs.update(load_design_inputs_from_excel(design_inputs_path))

    scenario_defs = {
        "short_term": {
            "tab_title": "Short-Term Storage",
            "tank_type": "short_term",
            "auxiliary_system": "electric",
            "efficiency_kind": "boiler",
            "size_group": "short",
            "ratio_value": lambda: short_term_ratio.value,
        },
        "seasonal_boiler": {
            "tab_title": "Long-Term Storage With Electric Boilers",
            "tank_type": "seasonal",
            "auxiliary_system": "boiler",
            "efficiency_kind": "boiler",
            "size_group": "long",
            "ratio_value": lambda: seasonal_ratio.value,
        },
        "seasonal_hp": {
            "tab_title": "Long-Term Storage With Heat Pump",
            "tank_type": "seasonal",
            "auxiliary_system": "water_heat_pump",
            "efficiency_kind": "hp",
            "size_group": "long",
            "ratio_value": lambda: seasonal_ratio.value,
        },
    }

    path_input = pn.widgets.TextInput(
        name="Hourly Input File",
        value=str(Path("01 input files") / "weather and heating load data.xlsx"),
        disabled=True,
    )
    hourly_file = pn.widgets.FileInput(name="Upload Hourly Input File", accept=".csv,.xlsx,.xls")
    update_hourly_button = pn.widgets.Button(name="Update Hourly Input File", button_type="warning", width=BUTTON_WIDTH)
    analyze_button = pn.widgets.Button(name="Analyze Input Data", button_type="default", width=BUTTON_WIDTH)
    run_two_step_button = pn.widgets.Button(name="Run Two-Step Analysis", button_type="primary", width=BUTTON_WIDTH)
    run_cost_button = pn.widgets.Button(name="Run Cost Optimization Analysis", button_type="primary", width=BUTTON_WIDTH)
    run_combined_button = pn.widgets.Button(name="Run Cost + Two-Step Analysis", button_type="success", width=BUTTON_WIDTH)
    overall_status = pn.pane.Markdown("Ready.")
    hourly_upload_status = pn.pane.Markdown("")

    tank_max_temp = pn.widgets.FloatInput(name="Tank Max Temp (C)", value=float(default_inputs["tank_max_temp"]), step=1.0)
    small_delta_t_tank_min_temp = pn.widgets.FloatInput(name="Small Delta-T Tank Min Temp (C)", value=float(default_inputs["small_delta_t_tank_min_temp"]), step=1.0)
    large_delta_t_tank_min_temp = pn.widgets.FloatInput(name="Large Delta-T Tank Min Temp (C)", value=float(default_inputs["large_delta_t_tank_min_temp"]), step=1.0)
    initial_tank_temp = pn.widgets.FloatInput(name="Initial Tank Temp (C)", value=float(default_inputs["initial_tank_temp"]), step=1.0)
    heating_supply_temp = pn.widgets.FloatInput(name="Heating Supply Temp (C)", value=float(default_inputs["heating_supply_temp"]), step=1.0)
    heating_delta_t = pn.widgets.FloatInput(name="Heating System Delta T (C)", value=float(default_inputs["heating_delta_t"]), step=1.0)
    solar_collector_delta_t = pn.widgets.FloatInput(name="Solar Collector Delta T (C)", value=float(default_inputs["solar_collector_delta_t"]), step=1.0)

    short_term_loss = pn.widgets.FloatInput(name="Short-Term Tank Loss (%/day)", value=float(default_inputs["short_term_loss"]), step=0.1)
    seasonal_loss = pn.widgets.FloatInput(name="Seasonal Tank Loss (%/day)", value=float(default_inputs["seasonal_loss"]), step=0.05)
    short_term_ratio = pn.widgets.FloatInput(name="Short-Term Large Tank Ratio (L/m2)", value=float(default_inputs["short_term_ratio"]), step=25.0)
    seasonal_ratio = pn.widgets.FloatInput(name="Seasonal Large Tank Ratio (L/m2)", value=float(default_inputs["seasonal_ratio"]), step=100.0)

    collector_cost_per_m2 = pn.widgets.FloatInput(name="Collector Cost (RMB/m2)", value=float(default_inputs["collector_cost_per_m2"]), step=10.0)
    project_lifetime_years = pn.widgets.FloatInput(name="Project Lifetime (years)", value=float(default_inputs["project_lifetime_years"]), step=1.0)
    electricity_price = pn.widgets.FloatInput(name="Electricity Price (RMB/kWh)", value=float(default_inputs["electricity_price"]), step=0.01)
    electric_boiler_efficiency = pn.widgets.FloatInput(name="Electric Boiler Efficiency", value=float(default_inputs["electric_boiler_efficiency"]), step=0.01)
    heat_pump_cop = pn.widgets.FloatInput(name="Heat Pump COP", value=float(default_inputs["heat_pump_cop"]), step=0.1)
    short_term_cost_coeff = pn.widgets.FloatInput(name="Short-Term Tank Cost Coefficient", value=float(default_inputs["short_term_cost_coeff"]), step=50.0)
    short_term_cost_exponent = pn.widgets.FloatInput(name="Short-Term Tank Cost Exponent", value=float(default_inputs["short_term_cost_exponent"]), step=0.01)
    seasonal_cost_coeff = pn.widgets.FloatInput(name="Seasonal Tank Cost Coefficient", value=float(default_inputs["seasonal_cost_coeff"]), step=50.0)
    seasonal_cost_exponent = pn.widgets.FloatInput(name="Seasonal Tank Cost Exponent", value=float(default_inputs["seasonal_cost_exponent"]), step=0.01)

    sizing_mode = pn.widgets.RadioButtonGroup(
        name="Candidate Sizes",
        options=["Auto Generate", "Upload Excel"],
        value=str(default_inputs["sizing_mode"]),
        button_type="light",
    )
    short_collector_min_size = pn.widgets.FloatInput(name="Short-Term Collector Area Min (m2)", value=float(default_inputs["short_collector_min_size"]), step=10.0)
    short_collector_max_size = pn.widgets.FloatInput(name="Short-Term Collector Area Max (m2)", value=float(default_inputs["short_collector_max_size"]), step=10.0)
    short_collector_count = pn.widgets.IntInput(name="Short-Term Collector Area Count", value=int(default_inputs["short_collector_count"]), step=1, start=1)
    short_tank_min_size = pn.widgets.FloatInput(name="Short-Term Tank Volume Min (m3)", value=float(default_inputs["short_tank_min_size"]), step=5.0)
    short_tank_max_size = pn.widgets.FloatInput(name="Short-Term Tank Volume Max (m3)", value=float(default_inputs["short_tank_max_size"]), step=10.0)
    short_tank_count = pn.widgets.IntInput(name="Short-Term Tank Volume Count", value=int(default_inputs["short_tank_count"]), step=1, start=1)
    long_collector_min_size = pn.widgets.FloatInput(name="Long-Term Collector Area Min (m2)", value=float(default_inputs["long_collector_min_size"]), step=10.0)
    long_collector_max_size = pn.widgets.FloatInput(name="Long-Term Collector Area Max (m2)", value=float(default_inputs["long_collector_max_size"]), step=50.0)
    long_collector_count = pn.widgets.IntInput(name="Long-Term Collector Area Count", value=int(default_inputs["long_collector_count"]), step=1, start=1)
    long_tank_min_size = pn.widgets.FloatInput(name="Long-Term Tank Volume Min (m3)", value=float(default_inputs["long_tank_min_size"]), step=10.0)
    long_tank_max_size = pn.widgets.FloatInput(name="Long-Term Tank Volume Max (m3)", value=float(default_inputs["long_tank_max_size"]), step=50.0)
    long_tank_count = pn.widgets.IntInput(name="Long-Term Tank Volume Count", value=int(default_inputs["long_tank_count"]), step=1, start=1)
    sizing_file = pn.widgets.FileInput(name="Sizing Excel File", accept=".xlsx")
    sizing_help = pn.pane.Markdown(
        "Upload an Excel file with columns like `collector_area_m2` and `tank_volume_m3`.",
        visible=False,
    )

    collector_type = pn.widgets.Select(name="Collector Type", options=list(COLLECTOR_TYPE_PRESETS.keys()), value=str(default_inputs["collector_type"]))
    eta0 = pn.widgets.FloatInput(name="Collector eta0", value=float(default_inputs["eta0"]), step=0.01)
    a1 = pn.widgets.FloatInput(name="Collector a1", value=float(default_inputs["a1"]), step=0.1)
    a2 = pn.widgets.FloatInput(name="Collector a2", value=float(default_inputs["a2"]), step=0.001)

    input_analysis = pn.pane.Markdown("")
    monthly_table = pn.widgets.Tabulator(pagination="remote", page_size=12, sizing_mode="stretch_width", height=260)
    duration_plot = plot_container(PLOT_HEIGHT)

    state = {
        "weather_df": None,
        "input_summary": None,
        "input_monthly_df": None,
        "input_duration_df": None,
        "scenarios": {},
        "is_running": False,
    }

    def scenario_tank_min_temp(definition: dict[str, object]) -> float:
        return large_delta_t_tank_min_temp.value if definition["auxiliary_system"] == "water_heat_pump" else small_delta_t_tank_min_temp.value

    def study_common_kwargs() -> dict[str, float]:
        return {
            "tank_max_temp": tank_max_temp.value,
            "initial_tank_temp": initial_tank_temp.value,
            "heating_supply_temp": heating_supply_temp.value,
            "heating_delta_t": heating_delta_t.value,
            "solar_collector_delta_t": solar_collector_delta_t.value,
            "short_term_loss_percent_per_day": short_term_loss.value,
            "seasonal_loss_percent_per_day": seasonal_loss.value,
            "eta0": eta0.value,
            "a1": a1.value,
            "a2": a2.value,
            "collector_cost_per_m2": collector_cost_per_m2.value,
            "short_term_cost_coeff": short_term_cost_coeff.value,
            "short_term_cost_exponent": short_term_cost_exponent.value,
            "seasonal_cost_coeff": seasonal_cost_coeff.value,
            "seasonal_cost_exponent": seasonal_cost_exponent.value,
            "electricity_price": electricity_price.value,
            "project_lifetime_years": project_lifetime_years.value,
        }

    def simulate_common_kwargs() -> dict[str, float]:
        return {
            "tank_max_temp": tank_max_temp.value,
            "initial_tank_temp": initial_tank_temp.value,
            "heating_supply_temp": heating_supply_temp.value,
            "heating_delta_t": heating_delta_t.value,
            "solar_collector_delta_t": solar_collector_delta_t.value,
            "eta0": eta0.value,
            "a1": a1.value,
            "a2": a2.value,
            "collector_cost_per_m2": collector_cost_per_m2.value,
            "short_term_cost_coeff": short_term_cost_coeff.value,
            "short_term_cost_exponent": short_term_cost_exponent.value,
            "seasonal_cost_coeff": seasonal_cost_coeff.value,
            "seasonal_cost_exponent": seasonal_cost_exponent.value,
            "electricity_price": electricity_price.value,
            "project_lifetime_years": project_lifetime_years.value,
        }

    def scenario_efficiency(definition: dict[str, object]) -> float:
        return electric_boiler_efficiency.value if definition["efficiency_kind"] == "boiler" else heat_pump_cop.value

    def tank_loss_for_type(tank_type: str) -> float:
        return short_term_loss.value if tank_type == "short_term" else seasonal_loss.value

    def scenario_kwargs(definition: dict[str, object]) -> dict[str, float | str]:
        return {
            **study_common_kwargs(),
            "tank_min_temp": scenario_tank_min_temp(definition),
            "auxiliary_system": definition["auxiliary_system"],
            "auxiliary_efficiency": scenario_efficiency(definition),
        }

    def current_size_lists(group: str) -> tuple[list[float], list[float]]:
        if sizing_mode.value == "Upload Excel":
            if not sizing_file.value:
                raise ValueError("Upload an Excel file with tank and collector size lists.")
            return extract_size_lists_from_excel(sizing_file.value)

        if group == "short":
            return (
                evenly_spaced_values(short_collector_min_size.value, short_collector_max_size.value, short_collector_count.value),
                evenly_spaced_values(short_tank_min_size.value, short_tank_max_size.value, short_tank_count.value),
            )
        return (
            evenly_spaced_values(long_collector_min_size.value, long_collector_max_size.value, long_collector_count.value),
            evenly_spaced_values(long_tank_min_size.value, long_tank_max_size.value, long_tank_count.value),
        )

    def update_hourly_file(_event=None) -> None:
        try:
            if not hourly_file.value:
                raise ValueError("Choose an input file to update the hourly input file.")
            hourly_input_path.write_bytes(hourly_file.value)
            hourly_upload_status.object = f"Hourly input file updated: `{Path('01 input files') / 'weather and heating load data.xlsx'}`"
        except Exception as exc:
            hourly_upload_status.object = f"Hourly file update failed: `{exc}`"

    def current_design_inputs() -> dict[str, object]:
        return {
            "tank_max_temp": tank_max_temp.value,
            "small_delta_t_tank_min_temp": small_delta_t_tank_min_temp.value,
            "large_delta_t_tank_min_temp": large_delta_t_tank_min_temp.value,
            "initial_tank_temp": initial_tank_temp.value,
            "heating_supply_temp": heating_supply_temp.value,
            "heating_delta_t": heating_delta_t.value,
            "solar_collector_delta_t": solar_collector_delta_t.value,
            "short_term_loss": short_term_loss.value,
            "seasonal_loss": seasonal_loss.value,
            "short_term_ratio": short_term_ratio.value,
            "seasonal_ratio": seasonal_ratio.value,
            "collector_cost_per_m2": collector_cost_per_m2.value,
            "project_lifetime_years": project_lifetime_years.value,
            "electricity_price": electricity_price.value,
            "electric_boiler_efficiency": electric_boiler_efficiency.value,
            "heat_pump_cop": heat_pump_cop.value,
            "short_term_cost_coeff": short_term_cost_coeff.value,
            "short_term_cost_exponent": short_term_cost_exponent.value,
            "seasonal_cost_coeff": seasonal_cost_coeff.value,
            "seasonal_cost_exponent": seasonal_cost_exponent.value,
            "sizing_mode": sizing_mode.value,
            "short_collector_min_size": short_collector_min_size.value,
            "short_collector_max_size": short_collector_max_size.value,
            "short_collector_count": short_collector_count.value,
            "short_tank_min_size": short_tank_min_size.value,
            "short_tank_max_size": short_tank_max_size.value,
            "short_tank_count": short_tank_count.value,
            "long_collector_min_size": long_collector_min_size.value,
            "long_collector_max_size": long_collector_max_size.value,
            "long_collector_count": long_collector_count.value,
            "long_tank_min_size": long_tank_min_size.value,
            "long_tank_max_size": long_tank_max_size.value,
            "long_tank_count": long_tank_count.value,
            "collector_type": collector_type.value,
            "eta0": eta0.value,
            "a1": a1.value,
            "a2": a2.value,
        }

    def persist_design_inputs() -> None:
        save_design_inputs_to_excel(design_inputs_path, current_design_inputs())

    def set_running_state(is_running: bool) -> None:
        state["is_running"] = is_running
        update_hourly_button.disabled = is_running
        analyze_button.disabled = is_running
        run_two_step_button.disabled = is_running
        run_cost_button.disabled = is_running
        run_combined_button.disabled = is_running
        for scenario_state in state["scenarios"].values():
            scenario_state["run_final_button"].disabled = is_running
            scenario_state["export_button"].disabled = is_running or scenario_state["selected_summary"] is None

    def update_sizing_mode(*_events) -> None:
        auto_visible = sizing_mode.value == "Auto Generate"
        for widget in [
            short_collector_min_size,
            short_collector_max_size,
            short_collector_count,
            short_tank_min_size,
            short_tank_max_size,
            short_tank_count,
            long_collector_min_size,
            long_collector_max_size,
            long_collector_count,
            long_tank_min_size,
            long_tank_max_size,
            long_tank_count,
        ]:
            widget.visible = auto_visible
        sizing_file.visible = not auto_visible
        sizing_help.visible = not auto_visible

    def apply_collector_preset(*_events) -> None:
        preset = COLLECTOR_TYPE_PRESETS.get(collector_type.value)
        if preset is None:
            return
        eta0.value = preset["eta0"]
        a1.value = preset["a1"]
        a2.value = preset["a2"]

    def analyze_inputs(_event=None) -> None:
        try:
            persist_design_inputs()
            weather_df = load_input(filename=hourly_input_path)
            summary, monthly_df, duration_df = analyze_input_data(
                weather_load_df=weather_df,
                heating_supply_temp=heating_supply_temp.value,
                solar_collector_delta_t=solar_collector_delta_t.value,
                eta0=eta0.value,
                a1=a1.value,
                a2=a2.value,
            )
            state["weather_df"] = weather_df
            state["input_summary"] = summary
            state["input_monthly_df"] = monthly_df
            state["input_duration_df"] = duration_df

            input_analysis.object = (
                "### Input Analysis Results\n"
                f"- Annual heating load: `{summary['annual_heating_load_kwh']:.1f} kWh`\n"
                f"- Heating-season load: `{summary['heating_season_load_kwh']:.1f} kWh`\n"
                f"- Annual tilted solar radiation: `{summary['annual_tilted_solar_kwh_m2']:.1f} kWh/m2`\n"
                f"- Annual horizontal solar radiation: `{summary['annual_horizontal_solar_kwh_m2']:.1f} kWh/m2`\n"
                f"- Reference collector efficiency: `{summary['reference_collector_efficiency']:.3f}`\n"
                f"- Short-term suggested collector range: `{summary['short_term_collector_min_m2']:.1f}` to `{summary['short_term_collector_max_m2']:.1f} m2`\n"
                f"- Short-term suggested tank range: `{summary['short_term_tank_min_m3']:.1f}` to `{summary['short_term_tank_max_m3']:.1f} m3`\n"
                f"- Long-term suggested collector range: `{summary['seasonal_collector_min_m2']:.1f}` to `{summary['seasonal_collector_max_m2']:.1f} m2`\n"
                f"- Long-term suggested tank range: `{summary['seasonal_tank_min_m3']:.1f}` to `{summary['seasonal_tank_max_m3']:.1f} m3`"
            )
            monthly_table.value = monthly_df.round(3)
            duration_plot_df = duration_df.rename(
                columns={
                    "heating_load_duration_kwh": "Load",
                    "tilted_solar_duration_kwh_m2": "Surface Solar",
                    "horizontal_solar_duration_kwh_m2": "Horizontal Solar",
                }
            )
            set_plot(duration_plot, duration_plot_df.hvplot.line(
                x="hour_rank",
                y=["Load", "Surface Solar", "Horizontal Solar"],
                title="Hourly Duration Curves",
                xlabel="Sorted Hour Rank",
                ylabel="Value",
                legend="top",
                height=PLOT_HEIGHT,
                grid=True,
                shared_axes=False,
            ))
            overall_status.object = "Input analysis completed."
        except Exception as exc:
            input_analysis.object = f"### Input Analysis Error\n`{exc}`"
            overall_status.object = f"### Error\n`{exc}`"

    def make_scenario_state(tab_title: str) -> dict[str, object]:
        selected_area = pn.widgets.Select(name="Selected Collector Area (m2)", options=[])
        selected_tank = pn.widgets.Select(name="Selected Tank Size (m3)", options=[])
        run_final_button = pn.widgets.Button(name="Run Step 3 Final Results", button_type="success", width=BUTTON_WIDTH)
        export_button = pn.widgets.FileDownload(
            name="Export Recommended Excel Report",
            button_type="light",
            callback=None,
            filename="report.xlsx",
            width=BUTTON_WIDTH,
        )
        scenario_state = {
            "status": pn.pane.Markdown("Run the study to populate this tab."),
            "metrics": pn.pane.Markdown(""),
            "export_status": pn.pane.Markdown(""),
            "selected_area": selected_area,
            "selected_tank": selected_tank,
            "run_final_button": run_final_button,
            "export_button": export_button,
            "best_table": pn.widgets.Tabulator(pagination="remote", page_size=5, sizing_mode="stretch_width", height=140),
            "monthly_table": pn.widgets.Tabulator(pagination="remote", page_size=13, sizing_mode="stretch_width", height=320),
            "summary_table": pn.widgets.Tabulator(pagination="remote", page_size=12, sizing_mode="stretch_width", height=280),
            "collector_plot": plot_container(PLOT_HEIGHT),
            "collector_eff_plot": plot_container(PLOT_HEIGHT),
            "tank_plot": plot_container(PLOT_HEIGHT),
            "tank_eff_plot": plot_container(PLOT_HEIGHT),
            "cost_heatmap": plot_container(PLOT_HEIGHT),
            "ratio_heatmap": plot_container(PLOT_HEIGHT),
            "tank_temp_plot": plot_container(PLOT_HEIGHT),
            "heating_plot": plot_container(PLOT_HEIGHT),
            "tank_flow_plot": plot_container(PLOT_HEIGHT),
            "weather_plot": plot_container(PLOT_HEIGHT),
            "design_grid_df": None,
            "collector_df": None,
            "tank_df": None,
            "selected_summary": None,
            "selected_hourly_df": None,
            "tank_values": [],
            "layout": None,
        }
        scenario_state["layout"] = pn.Column(
            scenario_state["status"],
            pn.pane.Markdown("### Optimized Results"),
            scenario_state["best_table"],
            pn.pane.Markdown("### Heatmaps"),
            pn.Row(scenario_state["cost_heatmap"], scenario_state["ratio_heatmap"], sizing_mode="stretch_width", margin=(0, 0, 6, 0)),
            pn.pane.Markdown("### Step 1: Collector Area"),
            pn.Row(scenario_state["collector_plot"], scenario_state["collector_eff_plot"], sizing_mode="stretch_width", margin=(0, 0, 6, 0)),
            pn.pane.Markdown("### Step 2: Tank Volume At Selected Collector Area"),
            pn.Row(selected_area, sizing_mode="stretch_width", margin=(0, 0, 6, 0)),
            pn.Row(scenario_state["tank_plot"], scenario_state["tank_eff_plot"], sizing_mode="stretch_width", margin=(0, 0, 6, 0)),
            pn.pane.Markdown("### Step 3: Final Selected Design"),
            pn.Row(selected_area, selected_tank, run_final_button, export_button, sizing_mode="stretch_width", margin=(0, 0, 6, 0)),
            scenario_state["export_status"],
            pn.pane.Markdown("### Step 3 Results"),
            scenario_state["metrics"],
            pn.Row(scenario_state["tank_temp_plot"], sizing_mode="stretch_width", margin=(0, 0, 6, 0)),
            pn.Row(scenario_state["heating_plot"], sizing_mode="stretch_width", margin=(0, 0, 6, 0)),
            pn.Row(scenario_state["tank_flow_plot"], sizing_mode="stretch_width", margin=(0, 0, 6, 0)),
            pn.Row(scenario_state["weather_plot"], sizing_mode="stretch_width", margin=(0, 0, 6, 0)),
            pn.pane.Markdown("### Monthly Summary"),
            scenario_state["monthly_table"],
            pn.pane.Markdown("### Full Design Table"),
            scenario_state["summary_table"],
            sizing_mode="stretch_width",
        )
        return scenario_state

    for scenario_key, definition in scenario_defs.items():
        state["scenarios"][scenario_key] = make_scenario_state(definition["tab_title"])

    def update_scenario_tank_study(scenario_key: str) -> None:
        weather_df = state["weather_df"]
        scenario_state = state["scenarios"][scenario_key]
        definition = scenario_defs[scenario_key]
        if weather_df is None or scenario_state["selected_area"].value is None or not scenario_state["tank_values"]:
            return

        tank_df = run_tank_size_study(
            weather_load_df=weather_df,
            collector_area_m2=float(scenario_state["selected_area"].value),
            tank_size_list=scenario_state["tank_values"],
            tank_types=[definition["tank_type"]],
            progress_callback=lambda info, title=definition["tab_title"]: overall_status.__setattr__(
                "object",
                progress_text(
                    "Step 2 tank analysis",
                    int(info["current"]),
                    int(info["total"]),
                    title,
                    float(info["collector_area_m2"]),
                    float(info["tank_volume_m3"]),
                ),
            ),
            **scenario_kwargs(definition),
        )
        scenario_state["tank_df"] = tank_df
        set_plot(scenario_state["tank_plot"], tank_df.hvplot.line(
            x="tank_volume_m3",
            y="solar_coverage_pct",
            ylabel="Solar Heat Ratio (%)",
            xlabel="Tank Size (m3)",
            title=f"Solar Heat Ratio vs Tank Size at {float(scenario_state['selected_area'].value):.1f} m2",
            legend=False,
            height=PLOT_HEIGHT,
            grid=True,
            shared_axes=False,
        ))
        set_plot(scenario_state["tank_eff_plot"], tank_df.hvplot.line(
            x="tank_volume_m3",
            y="collector_efficiency_pct",
            ylabel="Collector Efficiency (%)",
            xlabel="Tank Size (m3)",
            title=f"Collector Efficiency vs Tank Size at {float(scenario_state['selected_area'].value):.1f} m2",
            legend=False,
            height=PLOT_HEIGHT,
            grid=True,
            shared_axes=False,
        ))
        scenario_state["selected_tank"].options = sorted(tank_df["tank_volume_m3"].unique().tolist())
        if scenario_state["selected_tank"].value not in scenario_state["selected_tank"].options:
            scenario_state["selected_tank"].value = float(best_design(tank_df, objective="cost")["tank_volume_m3"])

    def update_scenario_final_view(scenario_key: str, *_events) -> None:
        weather_df = state["weather_df"]
        scenario_state = state["scenarios"][scenario_key]
        definition = scenario_defs[scenario_key]
        if weather_df is None or scenario_state["selected_area"].value is None or scenario_state["selected_tank"].value is None:
            return

        summary, hourly_df = simulate_design(
            weather_load_df=weather_df,
            collector_area_m2=float(scenario_state["selected_area"].value),
            tank_volume_m3=float(scenario_state["selected_tank"].value),
            tank_type=definition["tank_type"],
            tank_min_temp=scenario_tank_min_temp(definition),
            tank_thermal_loss_percent_per_day=tank_loss_for_type(definition["tank_type"]),
            auxiliary_system=definition["auxiliary_system"],
            auxiliary_efficiency=scenario_efficiency(definition),
            **simulate_common_kwargs(),
        )
        scenario_state["selected_summary"] = summary
        scenario_state["selected_hourly_df"] = hourly_df

        supply_overlay = hourly_df.assign(
            Supply=heating_supply_temp.value,
            Return=heating_supply_temp.value - heating_delta_t.value,
        ).hvplot.line(
            x="timestamp",
            y=["Supply", "Return"],
            line_dash=["dashed", "dotted"],
            color=["firebrick", "gray"],
            legend="top",
            height=PLOT_HEIGHT,
            grid=True,
            shared_axes=False,
        )
        tank_temp_df = hourly_df.rename(
            columns={
                "tank_top_temp_end_c": "Top",
                "tank_temp_end_c": "Mean",
                "tank_bottom_temp_end_c": "Bottom",
            }
        )
        set_plot(scenario_state["tank_temp_plot"], tank_temp_df.hvplot.line(
            x="timestamp",
            y=["Top", "Mean", "Bottom"],
            ylabel="Temperature (C)",
            title="Stratified Tank Temperature",
            legend="top",
            height=PLOT_HEIGHT,
            grid=True,
            shared_axes=False,
        ) * supply_overlay)
        heating_plot_df = hourly_df.rename(
            columns={
                "heating_load_kwh": "Load",
                "solar_direct_collector_to_load_kwh": "Collector",
                "solar_from_tank_direct_kwh": "Tank Direct",
                "solar_from_tank_via_hp_kwh": "Tank via HP",
                "auxiliary_heating_delivered_kwh": "Auxiliary",
            }
        )
        set_plot(scenario_state["heating_plot"], heating_plot_df.hvplot.line(
            x="timestamp",
            y=["Load", "Collector", "Tank Direct", "Tank via HP", "Auxiliary"],
            ylabel="Heating Energy (kWh)",
            title="Heating Load and Sources",
            legend="top",
            height=PLOT_HEIGHT,
            grid=True,
            shared_axes=False,
        ))
        tank_flow_df = hourly_df.assign(
            Charge=hourly_df["tank_charge_kwh"],
            Discharge=-hourly_df["tank_discharge_total_kwh"],
            Loss=-hourly_df["tank_loss_kwh"],
        )
        set_plot(scenario_state["tank_flow_plot"], tank_flow_df.hvplot.line(
            x="timestamp",
            y=["Charge", "Discharge", "Loss"],
            ylabel="Tank Energy Flow (kWh)",
            title="Tank Charging, Discharging, and Loss",
            legend="top",
            height=PLOT_HEIGHT,
            grid=True,
            shared_axes=False,
        ))
        weather_plot_df = weather_df.rename(
            columns={
                "outside_temp": "Outside",
                "heating_load": "Load",
                "solar_rad": "Solar",
            }
        )
        set_plot(scenario_state["weather_plot"], weather_plot_df.hvplot.line(
            x="timestamp",
            y=["Outside", "Load", "Solar"],
            title="Hourly Weather and Load Inputs",
            legend="top",
            height=PLOT_HEIGHT,
            grid=True,
            shared_axes=False,
        ))
        scenario_state["monthly_table"].value = scenario_monthly_summary(hourly_df).round(3)
        solar_direct_heat_kwh = summary["solar_direct_collector_to_load_kwh"] + summary["solar_from_tank_direct_kwh"]
        solar_energy_use_ratio_pct = (
            100.0 * summary["solar_energy_for_heating_kwh"] / summary["heating_load_kwh"]
            if summary["heating_load_kwh"] > 0
            else 0.0
        )
        scenario_state["metrics"].object = (
            "### Final Selected Result\n"
            "#### Selected Size\n"
            f"- Collector area: `{summary['collector_area_m2']:.1f} m2`\n"
            f"- Tank volume: `{summary['tank_volume_m3']:.1f} m3`\n"
            "\n"
            "#### Energy Performance\n"
            f"- Total heating load: `{summary['heating_load_kwh']:.1f} kWh`\n"
            f"- Solar direct heat energy: `{solar_direct_heat_kwh:.1f} kWh`\n"
            f"- Solar energy by using heat pump: `{summary['solar_from_tank_via_hp_kwh']:.1f} kWh`\n"
            f"- Usable solar heat energy: `{summary['solar_source_energy_used_kwh']:.1f} kWh`\n"
            f"- Solar heating delivered: `{summary['solar_energy_for_heating_kwh']:.1f} kWh`\n"
            f"- Solar-Assisted Heating Fraction: `{solar_energy_use_ratio_pct:.2f}%`\n"
            f"- Solar Source Fraction: `{summary['solar_coverage_pct']:.2f}%`\n"
            f"- Auxiliary heating delivered: `{summary['auxiliary_heating_delivered_kwh']:.1f} kWh`\n"
            "\n"
            "#### Cost And Operation\n"
            f"- Auxiliary energy input: `{summary['auxiliary_energy_input_kwh']:.1f} kWh`\n"
            f"- Heat pump power input: `{summary['auxiliary_energy_for_hp_boost_kwh']:.1f} kWh`\n"
            f"- Annualized total cost: `RMB {summary['annualized_total_cost']:.2f}`\n"
            f"- Tank final temperature: `{summary['tank_final_temp_c']:.1f} C`"
        )

    def export_scenario_report(scenario_key: str) -> BytesIO:
        scenario_state = state["scenarios"][scenario_key]
        if scenario_state["selected_summary"] is None or scenario_state["selected_hourly_df"] is None:
            raise ValueError("Run Step 3 Final Results before exporting the Excel report.")
        reports_dir = Path(__file__).resolve().parent / "02 reports"
        filename = f"{scenario_key}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        output_path = reports_dir / filename
        export_case_report(
            output_path=output_path,
            optimized_df=scenario_state["design_grid_df"],
            step1_df=scenario_state["collector_df"],
            step2_df=scenario_state["tank_df"],
            final_summary=scenario_state["selected_summary"],
            final_hourly_df=scenario_state["selected_hourly_df"],
            project_inputs={
                **current_design_inputs(),
                "scenario_key": scenario_key,
                "scenario_title": scenario_defs[scenario_key]["tab_title"],
                "hourly_input_file": str(Path("01 input files") / "weather and heating load data.xlsx"),
                "selected_collector_area_m2": scenario_state["selected_summary"]["collector_area_m2"],
                "selected_tank_volume_m3": scenario_state["selected_summary"]["tank_volume_m3"],
                "report_generated_at": pd.Timestamp.now().isoformat(),
            },
            monthly_summary_df=scenario_monthly_summary(scenario_state["selected_hourly_df"]),
            input_monthly_df=state["input_monthly_df"],
        )
        scenario_state["export_status"].object = f"Report exported to `{Path('02 reports') / filename}`"
        scenario_state["export_button"].filename = filename
        file_bytes = BytesIO(output_path.read_bytes())
        file_bytes.seek(0)
        return file_bytes

    def progress_text(
        stage: str,
        current: int,
        total: int,
        scenario_title: str,
        collector_area_m2: float | None = None,
        tank_volume_m3: float | None = None,
    ) -> str:
        percent = 100.0 if total <= 0 else 100.0 * current / total
        lines = [
            "### Running",
            f"- Scenario: `{scenario_title}`",
            f"- Process: `{stage}`",
            f"- Progress: `{percent:.1f}%` ({current}/{total})",
        ]
        if collector_area_m2 is not None:
            lines.append(f"- Current collector area: `{collector_area_m2:.1f} m2`")
        if tank_volume_m3 is not None:
            lines.append(f"- Current tank volume: `{tank_volume_m3:.1f} m3`")
        return "\n".join(lines)

    def run_scenario_study(scenario_key: str, mode: str) -> None:
        weather_df = state["weather_df"]
        scenario_state = state["scenarios"][scenario_key]
        definition = scenario_defs[scenario_key]
        if weather_df is None:
            raise ValueError("Run input analysis first.")

        area_values, tank_values = current_size_lists(definition["size_group"])
        design_grid_df = scenario_state["design_grid_df"]
        collector_df = scenario_state["collector_df"]

        if mode in {"cost", "combined"}:
            design_grid_df = run_design_grid(
                weather_load_df=weather_df,
                collector_area_list=area_values,
                tank_size_list=tank_values,
                tank_types=[definition["tank_type"]],
                progress_callback=lambda info, title=definition["tab_title"]: overall_status.__setattr__(
                    "object",
                    progress_text(
                        "Cost optimization",
                        int(info["current"]),
                        int(info["total"]),
                        title,
                        float(info["collector_area_m2"]),
                        float(info["tank_volume_m3"]),
                    ),
                ),
                **scenario_kwargs(definition),
            )
            scenario_state["design_grid_df"] = design_grid_df

        if mode in {"two_step", "combined"}:
            collector_df = run_collector_area_study(
                weather_load_df=weather_df,
                collector_area_list=area_values,
                tank_types=[definition["tank_type"]],
                short_term_ratio_l_per_m2=definition["ratio_value"](),
                seasonal_ratio_l_per_m2=definition["ratio_value"](),
                progress_callback=lambda info, title=definition["tab_title"]: overall_status.__setattr__(
                    "object",
                    progress_text(
                        "Step 1 collector analysis",
                        int(info["current"]),
                        int(info["total"]),
                        title,
                        float(info["collector_area_m2"]),
                        float(info["tank_volume_m3"]),
                    ),
                ),
                **scenario_kwargs(definition),
            )
            scenario_state["collector_df"] = collector_df

        scenario_state["tank_values"] = tank_values

        if design_grid_df is not None and not design_grid_df.empty:
            scenario_state["best_table"].value = design_grid_df.nsmallest(5, "annualized_total_cost").round(3)
            scenario_state["summary_table"].value = design_grid_df.round(3)
            best_case = best_design(design_grid_df, objective="cost")
            scenario_state["selected_area"].options = area_values
            scenario_state["selected_area"].value = float(best_case["collector_area_m2"])
            scenario_state["selected_tank"].options = sorted(design_grid_df["tank_volume_m3"].unique().tolist())
            scenario_state["selected_tank"].value = float(best_case["tank_volume_m3"])
            scenario_state["status"].object = (
                f"### {definition['tab_title']}\n"
                f"- Best collector area: `{best_case['collector_area_m2']:.1f} m2`\n"
                f"- Best tank size: `{best_case['tank_volume_m3']:.1f} m3`\n"
                f"- Solar Source Fraction: `{best_case['solar_coverage_pct']:.2f}%`\n"
                f"- Annualized total cost: `RMB {best_case['annualized_total_cost']:.2f}`"
            )
            set_plot(scenario_state["cost_heatmap"], build_quadmesh_heatmap(
                heatmap_frame(design_grid_df, "annualized_total_cost"),
                value_column="annualized_total_cost",
                title="Cost Heatmap",
                cmap="Viridis",
            ))
            set_plot(scenario_state["ratio_heatmap"], build_quadmesh_heatmap(
                heatmap_frame(design_grid_df, "solar_coverage_pct"),
                value_column="solar_coverage_pct",
                title="Solar Heating Ratio Heatmap",
                cmap="Plasma",
            ))

        if collector_df is not None and not collector_df.empty:
            set_plot(scenario_state["collector_plot"], collector_df.hvplot.line(
                x="collector_area_m2",
                y="solar_coverage_pct",
                ylabel="Solar Heat Ratio (%)",
                xlabel="Collector Area (m2)",
                title="Solar Heat Ratio vs Collector Area",
                legend=False,
                height=PLOT_HEIGHT,
                grid=True,
                shared_axes=False,
            ))
            set_plot(scenario_state["collector_eff_plot"], collector_df.hvplot.line(
                x="collector_area_m2",
                y="collector_efficiency_pct",
                ylabel="Collector Efficiency (%)",
                xlabel="Collector Area (m2)",
                title="Collector Efficiency vs Collector Area",
                legend=False,
                height=PLOT_HEIGHT,
                grid=True,
                shared_axes=False,
            ))
            if mode == "two_step":
                area_best = best_design(collector_df, objective="cost")
                scenario_state["selected_area"].options = area_values
                scenario_state["selected_area"].value = float(area_best["collector_area_m2"])
                scenario_state["best_table"].value = collector_df.nsmallest(5, "annualized_total_cost").round(3)
                scenario_state["summary_table"].value = collector_df.round(3)

        if mode in {"two_step", "combined"}:
            update_scenario_tank_study(scenario_key)
            if scenario_state["tank_df"] is not None and not scenario_state["tank_df"].empty:
                scenario_state["best_table"].value = scenario_state["tank_df"].nsmallest(5, "annualized_total_cost").round(3)
                if mode == "two_step":
                    scenario_state["summary_table"].value = scenario_state["tank_df"].round(3)

        update_scenario_final_view(scenario_key)

    def run_analysis(mode: str) -> None:
        try:
            set_running_state(True)
            persist_design_inputs()
            if tank_max_temp.value <= small_delta_t_tank_min_temp.value:
                raise ValueError("Tank maximum temperature must be greater than the small delta-T tank minimum temperature.")
            if tank_max_temp.value <= large_delta_t_tank_min_temp.value:
                raise ValueError("Tank maximum temperature must be greater than the large delta-T tank minimum temperature.")
            if not (min(small_delta_t_tank_min_temp.value, large_delta_t_tank_min_temp.value) <= initial_tank_temp.value <= tank_max_temp.value):
                raise ValueError("Initial tank temperature must be between the tank minimum temperatures and the tank maximum temperature.")
            if heating_supply_temp.value > tank_max_temp.value:
                raise ValueError("Heating supply temperature should not exceed the tank maximum temperature.")
            if project_lifetime_years.value <= 0:
                raise ValueError("Project lifetime must be greater than zero.")
            if state["weather_df"] is None:
                analyze_inputs()
            for scenario_key in scenario_defs:
                run_scenario_study(scenario_key, mode=mode)
            mode_label = {
                "two_step": "Two-step analysis",
                "cost": "Cost optimization analysis",
                "combined": "Cost + two-step analysis",
            }[mode]
            overall_status.object = f"{mode_label} completed: `100%`"
        except Exception as exc:
            overall_status.object = f"### Error\n`{exc}`"
        finally:
            set_running_state(False)

    for scenario_key, scenario_state in state["scenarios"].items():
        scenario_state["selected_area"].param.watch(lambda _event, key=scenario_key: update_scenario_tank_study(key), "value")
        scenario_state["selected_tank"].param.watch(lambda _event, key=scenario_key: update_scenario_final_view(key), "value")
        scenario_state["run_final_button"].on_click(lambda _event, key=scenario_key: update_scenario_final_view(key))
        scenario_state["export_button"].callback = lambda key=scenario_key: export_scenario_report(key)

    update_hourly_button.on_click(update_hourly_file)
    analyze_button.on_click(analyze_inputs)
    run_two_step_button.on_click(lambda _event: run_analysis("two_step"))
    run_cost_button.on_click(lambda _event: run_analysis("cost"))
    run_combined_button.on_click(lambda _event: run_analysis("combined"))
    sizing_mode.param.watch(update_sizing_mode, "value")
    collector_type.param.watch(apply_collector_preset, "value")
    update_sizing_mode()
    apply_collector_preset()

    sidebar_controls = pn.Column(
        pn.pane.Markdown("## Study Control"),
        path_input,
        hourly_file,
        update_hourly_button,
        hourly_upload_status,
        analyze_button,
        run_two_step_button,
        run_cost_button,
        run_combined_button,
        overall_status,
        width=390,
    )

    design_inputs_tab = pn.Column(
        pn.pane.Markdown("## Design Inputs"),
        pn.pane.Markdown("### Tank Temperature"),
        pn.Row(
            tank_max_temp,
            small_delta_t_tank_min_temp,
            large_delta_t_tank_min_temp,
            initial_tank_temp,
            heating_supply_temp,
        ),
        pn.Row(heating_delta_t, solar_collector_delta_t),
        pn.pane.Markdown("### Stratified Storage Settings"),
        pn.Row(short_term_loss, seasonal_loss, short_term_ratio, seasonal_ratio),
        pn.pane.Markdown("### Auxiliary Systems"),
        pn.Row(electric_boiler_efficiency, heat_pump_cop, electricity_price),
        pn.pane.Markdown("### Cost Inputs"),
        pn.Row(collector_cost_per_m2, project_lifetime_years),
        pn.Row(short_term_cost_coeff, short_term_cost_exponent),
        pn.Row(seasonal_cost_coeff, seasonal_cost_exponent),
        pn.pane.Markdown("### Candidate Size Inputs"),
        sizing_mode,
        pn.pane.Markdown("#### Short-Term Storage"),
        pn.Row(short_collector_min_size, short_collector_max_size, short_collector_count),
        pn.Row(short_tank_min_size, short_tank_max_size, short_tank_count),
        pn.pane.Markdown("#### Long-Term Storage"),
        pn.Row(long_collector_min_size, long_collector_max_size, long_collector_count),
        pn.Row(long_tank_min_size, long_tank_max_size, long_tank_count),
        sizing_file,
        sizing_help,
        pn.pane.Markdown("### Collector Model"),
        pn.Row(collector_type, eta0, a1, a2),
        sizing_mode="stretch_width",
    )

    input_results_tab = pn.Column(
        pn.pane.Markdown("## Input Analysis Results"),
        input_analysis,
        duration_plot,
        monthly_table,
        sizing_mode="stretch_width",
    )

    tabs = pn.Tabs(
        ("Design Inputs", design_inputs_tab),
        ("Input Analysis Results", input_results_tab),
        ("Short-Term Storage", state["scenarios"]["short_term"]["layout"]),
        ("Long-Term Storage With Electric Boilers", state["scenarios"]["seasonal_boiler"]["layout"]),
        ("Long-Term Storage With Heat Pump", state["scenarios"]["seasonal_hp"]["layout"]),
        dynamic=True,
    )

    return pn.template.FastListTemplate(
        title="Solar Thermal Storage Design Study",
        sidebar=[sidebar_controls],
        main=[
            pn.Column(
                tabs,
                sizing_mode="stretch_width",
                styles={
                    "background": "white",
                    "padding": "16px",
                    "border-radius": "8px",
                },
            )
        ],
    )


def main() -> None:
    pn.serve(build_dashboard(), show=True)


if __name__.startswith("bokeh"):
    build_dashboard().servable()


if __name__ == "__main__":
    main()
