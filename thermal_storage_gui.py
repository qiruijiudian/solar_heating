#!/usr/bin/env python3
"""Panel GUI for solar heating storage sizing."""

from __future__ import annotations

import html
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

TANK_OPERATION_PRESETS = {
    "short_term": {
        "Good": {
            "height_m": 3.0,
            "static_mixing_coeff": 0.010,
            "charge_mixing_coeff": 0.035,
            "discharge_mixing_coeff": 0.035,
        },
        "Average": {
            "height_m": 3.0,
            "static_mixing_coeff": 0.020,
            "charge_mixing_coeff": 0.060,
            "discharge_mixing_coeff": 0.050,
        },
        "Poor": {
            "height_m": 2.2,
            "static_mixing_coeff": 0.040,
            "charge_mixing_coeff": 0.120,
            "discharge_mixing_coeff": 0.100,
        },
    },
    "seasonal": {
        "Good": {
            "height_m": 10.0,
            "static_mixing_coeff": 0.005,
            "charge_mixing_coeff": 0.020,
            "discharge_mixing_coeff": 0.018,
        },
        "Average": {
            "height_m": 8.0,
            "static_mixing_coeff": 0.010,
            "charge_mixing_coeff": 0.045,
            "discharge_mixing_coeff": 0.035,
        },
        "Poor": {
            "height_m": 5.5,
            "static_mixing_coeff": 0.025,
            "charge_mixing_coeff": 0.090,
            "discharge_mixing_coeff": 0.075,
        },
    },
}


def evenly_spaced_values(min_value: float, max_value: float, count: int) -> list[float]:
    if count <= 0:
        raise ValueError("The number of size options must be at least 1.")
    if max_value < min_value:
        raise ValueError("Maximum value must be greater than or equal to minimum value.")
    if count == 1:
        return [round(min_value, 3)]
    return [round(float(value), 3) for value in np.linspace(min_value, max_value, count)]


def engineering_round_up(value: float) -> float:
    value = float(value)
    if value <= 0:
        return 0.0
    exponent = int(np.floor(np.log10(value)))
    scale = 10 ** max(exponent - 2, 0)
    return float(np.ceil(value / scale) * scale)


def rounded_candidate_values(min_value: float, max_value: float, count: int) -> list[float]:
    raw_values = evenly_spaced_values(min_value, max_value, count)
    rounded_values = sorted({engineering_round_up(value) for value in raw_values if value > 0})
    if not rounded_values:
        raise ValueError("No valid rounded candidate values could be generated.")
    return rounded_values


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
    heatmap = hv.QuadMesh(
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
        width=720,
    )
    contour_levels = 8 if min(pivot.shape) >= 2 else 1
    contour_base = hv.operation.contours(heatmap, levels=contour_levels)
    contour_underlay = contour_base.opts(
        color="white",
        line_width=2.6,
        alpha=0.85,
        line_dash="dashed",
    )
    contours = contour_base.opts(
        color="black",
        line_width=1.6,
        alpha=0.9,
        tools=["hover"],
    )
    return heatmap * contour_underlay * contours


def scenario_monthly_summary(hourly_df: pd.DataFrame) -> pd.DataFrame:
    if hourly_df.empty:
        return pd.DataFrame()
    working = hourly_df.copy()
    working["month"] = working["timestamp"].dt.to_period("M").astype(str)
    monthly_df = (
        working.groupby("month", as_index=False)
        .agg(
            total_heating_load_kwh=("heating_load_kwh", "sum"),
            average_heating_load_kwh=("heating_load_kwh", "mean"),
            usable_solar_heat_kwh=("solar_source_energy_used_kwh", "sum"),
            solar_heating_energy_kwh=("solar_heating_total_kwh", "sum"),
            auxiliary_energy_kwh=("auxiliary_energy_input_kwh", "sum"),
            collector_efficiency_pct=("collector_efficiency", lambda values: 100.0 * values.mean()),
            tank_charge_kwh=("tank_charge_kwh", "sum"),
            tank_loss_kwh=("tank_loss_kwh", "sum"),
        )
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
                "collector_efficiency_pct": 100.0 * working["collector_efficiency"].mean(),
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


def line_plot_ylim(df: pd.DataFrame, columns: str | list[str]) -> tuple[float, float | None]:
    series_columns = [columns] if isinstance(columns, str) else list(columns)
    numeric_values = pd.to_numeric(df[series_columns].to_numpy().ravel(), errors="coerce")
    finite_values = numeric_values[np.isfinite(numeric_values)]
    if finite_values.size == 0:
        return (0.0, None)
    min_value = float(finite_values.min())
    if min_value >= 0:
        return (0.0, None)
    max_value = float(finite_values.max())
    value_range = max_value - min_value
    pad = max(0.05 * value_range, 0.02 * abs(min_value), 1e-6)
    return (min_value - pad, None)


def table_height_for_rows(row_count: int, min_height: int = 120, max_height: int = 1400) -> int:
    header_height = 38
    row_height = 30
    footer_padding = 12
    estimated = header_height + max(row_count, 1) * row_height + footer_padding
    return max(min_height, min(estimated, max_height))


def make_data_table(default_rows: int = 5, min_height: int = 120, max_height: int = 1400) -> pn.widgets.Tabulator:
    return pn.widgets.Tabulator(
        pagination=None,
        sizing_mode="stretch_width",
        height=table_height_for_rows(default_rows, min_height=min_height, max_height=max_height),
    )


def set_table_data(
    table: pn.widgets.Tabulator,
    df: pd.DataFrame,
    *,
    min_height: int = 120,
    max_height: int = 1400,
) -> None:
    table.value = df
    table.height = table_height_for_rows(len(df.index), min_height=min_height, max_height=max_height)


def static_table_pane(df: pd.DataFrame | None, *, height: int = 320) -> pn.viewable.Viewable:
    if df is None or df.empty:
        return pn.pane.HTML("<div style='color:#111 !important;font-size:14px;background:#fff !important;'>No data available.</div>")
    html_df = df.copy()
    html = html_df.to_html(index=False, border=0, classes=["static-report-table"], justify="left")
    return pn.pane.HTML(
        f"""
        <div style="overflow-x:auto; max-height:{height}px; background:#ffffff !important; color:#111111 !important;">
            {html}
        </div>
        """,
        sizing_mode="stretch_width",
    )


def static_markdown_pane(text: str) -> pn.pane.HTML:
    lines = str(text).splitlines()
    html_parts: list[str] = []
    in_list = False
    for raw_line in lines:
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            continue
        if stripped.startswith("### "):
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(f"<h3>{html.escape(stripped[4:])}</h3>")
            continue
        if stripped.startswith("#### "):
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            html_parts.append(f"<h4>{html.escape(stripped[5:])}</h4>")
            continue
        if stripped.startswith("- "):
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            html_parts.append(f"<li>{html.escape(stripped[2:])}</li>")
            continue
        if in_list:
            html_parts.append("</ul>")
            in_list = False
        html_parts.append(f"<p>{html.escape(stripped)}</p>")
    if in_list:
        html_parts.append("</ul>")
    return pn.pane.HTML(
        (
            "<div class='static-report-text' "
            "style='color:#111111 !important; background:#ffffff !important; "
            "font-family:Arial,sans-serif !important; line-height:1.45 !important;'>"
            f"{''.join(html_parts)}</div>"
        ),
        sizing_mode="stretch_width",
    )


def first_object(container: pn.Column):
    return container.objects[0] if container.objects else pn.pane.Markdown("No content available.")


def safe_project_folder_name(value: str) -> str:
    cleaned = "".join(character if character.isalnum() or character in {" ", "-", "_"} else "_" for character in str(value).strip())
    cleaned = " ".join(cleaned.split())
    return cleaned or "project"


def build_dashboard():
    input_dir = Path(__file__).resolve().parent / "01 input files"
    input_dir.mkdir(exist_ok=True)
    hourly_input_path = input_dir / "weather and heating load data.xlsx"
    design_inputs_path = Path(__file__).resolve().parent / "design_inputs.xlsx"
    default_inputs = {
        "project_name": Path(__file__).resolve().parent.name,
        "tank_max_temp": 80.0,
        "small_delta_t_tank_min_temp": 35.0,
        "large_delta_t_tank_min_temp": 8.0,
        "initial_tank_temp": 35.0,
        "heating_supply_temp": 45.0,
        "heating_delta_t": 10.0,
        "solar_collector_delta_t": 10.0,
        "direct_solar_delivery_margin_c": 2.0,
        "short_term_loss": 1.0,
        "seasonal_loss": 0.15,
        "short_term_ratio": 200.0,
        "seasonal_ratio": 2000.0,
        "short_term_tank_height_m": 2.4,
        "seasonal_tank_height_m": 7.5,
        "short_term_static_mixing_coeff": 0.020,
        "seasonal_static_mixing_coeff": 0.010,
        "short_term_charge_mixing_coeff": 0.080,
        "seasonal_charge_mixing_coeff": 0.045,
        "short_term_discharge_mixing_coeff": 0.060,
        "seasonal_discharge_mixing_coeff": 0.035,
        "short_term_preset": "Average",
        "seasonal_preset": "Average",
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

    project_name = pn.widgets.TextInput(
        name="Project Name",
        value=str(default_inputs["project_name"]),
    )
    path_input = pn.widgets.TextInput(
        name="Hourly Input File",
        value=str(Path("01 input files") / "weather and heating load data.xlsx"),
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
    direct_solar_delivery_margin_c = pn.widgets.FloatInput(name="Direct Solar Delivery Margin (C)", value=float(default_inputs["direct_solar_delivery_margin_c"]), step=0.5)

    short_term_loss = pn.widgets.FloatInput(name="Short-Term Tank Loss (%/day)", value=float(default_inputs["short_term_loss"]), step=0.1)
    seasonal_loss = pn.widgets.FloatInput(name="Seasonal Tank Loss (%/day)", value=float(default_inputs["seasonal_loss"]), step=0.05)
    short_term_ratio = pn.widgets.FloatInput(name="Short-Term Large Tank Ratio (L/m2)", value=float(default_inputs["short_term_ratio"]), step=25.0)
    seasonal_ratio = pn.widgets.FloatInput(name="Seasonal Large Tank Ratio (L/m2)", value=float(default_inputs["seasonal_ratio"]), step=100.0)
    short_term_preset = pn.widgets.Select(name="Short-Term Thermal Stratification Model", options=list(TANK_OPERATION_PRESETS["short_term"].keys()), value=str(default_inputs["short_term_preset"]))
    seasonal_preset = pn.widgets.Select(name="Long-Term Thermal Stratification Model", options=list(TANK_OPERATION_PRESETS["seasonal"].keys()), value=str(default_inputs["seasonal_preset"]))
    short_term_tank_height_m = pn.widgets.FloatInput(name="Short-Term Tank Height (m)", value=float(default_inputs["short_term_tank_height_m"]), step=0.1)
    seasonal_tank_height_m = pn.widgets.FloatInput(name="Long-Term Tank Height (m)", value=float(default_inputs["seasonal_tank_height_m"]), step=0.1)
    short_term_static_mixing_coeff = pn.widgets.FloatInput(name="Short-Term Passive Mixing", value=float(default_inputs["short_term_static_mixing_coeff"]), step=0.005)
    seasonal_static_mixing_coeff = pn.widgets.FloatInput(name="Long-Term Passive Mixing", value=float(default_inputs["seasonal_static_mixing_coeff"]), step=0.005)
    short_term_charge_mixing_coeff = pn.widgets.FloatInput(name="Short-Term Charge Mixing", value=float(default_inputs["short_term_charge_mixing_coeff"]), step=0.005)
    seasonal_charge_mixing_coeff = pn.widgets.FloatInput(name="Long-Term Charge Mixing", value=float(default_inputs["seasonal_charge_mixing_coeff"]), step=0.005)
    short_term_discharge_mixing_coeff = pn.widgets.FloatInput(name="Short-Term Draw Mixing", value=float(default_inputs["short_term_discharge_mixing_coeff"]), step=0.005)
    seasonal_discharge_mixing_coeff = pn.widgets.FloatInput(name="Long-Term Draw Mixing", value=float(default_inputs["seasonal_discharge_mixing_coeff"]), step=0.005)

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
    short_collector_min_size = pn.widgets.FloatInput(name="Short Collector Min (m2)", value=float(default_inputs["short_collector_min_size"]), step=10.0)
    short_collector_max_size = pn.widgets.FloatInput(name="Short Collector Max (m2)", value=float(default_inputs["short_collector_max_size"]), step=10.0)
    short_collector_count = pn.widgets.IntInput(name="Short Collector Count", value=int(default_inputs["short_collector_count"]), step=1, start=1)
    short_tank_min_size = pn.widgets.FloatInput(name="Short Tank Min (m3)", value=float(default_inputs["short_tank_min_size"]), step=5.0)
    short_tank_max_size = pn.widgets.FloatInput(name="Short Tank Max (m3)", value=float(default_inputs["short_tank_max_size"]), step=10.0)
    short_tank_count = pn.widgets.IntInput(name="Short Tank Count", value=int(default_inputs["short_tank_count"]), step=1, start=1)
    long_collector_min_size = pn.widgets.FloatInput(name="Long Collector Min (m2)", value=float(default_inputs["long_collector_min_size"]), step=10.0)
    long_collector_max_size = pn.widgets.FloatInput(name="Long Collector Max (m2)", value=float(default_inputs["long_collector_max_size"]), step=50.0)
    long_collector_count = pn.widgets.IntInput(name="Long Collector Count", value=int(default_inputs["long_collector_count"]), step=1, start=1)
    long_tank_min_size = pn.widgets.FloatInput(name="Long Tank Min (m3)", value=float(default_inputs["long_tank_min_size"]), step=10.0)
    long_tank_max_size = pn.widgets.FloatInput(name="Long Tank Max (m3)", value=float(default_inputs["long_tank_max_size"]), step=50.0)
    long_tank_count = pn.widgets.IntInput(name="Long Tank Count", value=int(default_inputs["long_tank_count"]), step=1, start=1)
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
    monthly_table = make_data_table(default_rows=12, min_height=260, max_height=900)
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
            "direct_solar_delivery_margin_c": direct_solar_delivery_margin_c.value,
            "short_term_loss_percent_per_day": short_term_loss.value,
            "seasonal_loss_percent_per_day": seasonal_loss.value,
            "short_term_tank_height_m": short_term_tank_height_m.value,
            "seasonal_tank_height_m": seasonal_tank_height_m.value,
            "short_term_static_mixing_coeff": short_term_static_mixing_coeff.value,
            "seasonal_static_mixing_coeff": seasonal_static_mixing_coeff.value,
            "short_term_charge_mixing_coeff": short_term_charge_mixing_coeff.value,
            "seasonal_charge_mixing_coeff": seasonal_charge_mixing_coeff.value,
            "short_term_discharge_mixing_coeff": short_term_discharge_mixing_coeff.value,
            "seasonal_discharge_mixing_coeff": seasonal_discharge_mixing_coeff.value,
            "eta0": eta0.value,
            "a1": a1.value,
            "a2": a2.value,
            "collector_cost_per_m2": collector_cost_per_m2.value,
            "short_term_cost_coeff": short_term_cost_coeff.value,
            "short_term_cost_exponent": short_term_cost_exponent.value,
            "seasonal_cost_coeff": seasonal_cost_coeff.value,
            "seasonal_cost_exponent": seasonal_cost_exponent.value,
            "electricity_price": electricity_price.value,
            "backup_auxiliary_efficiency": electric_boiler_efficiency.value,
            "project_lifetime_years": project_lifetime_years.value,
        }

    def simulate_common_kwargs() -> dict[str, float]:
        return {
            "tank_max_temp": tank_max_temp.value,
            "initial_tank_temp": initial_tank_temp.value,
            "heating_supply_temp": heating_supply_temp.value,
            "heating_delta_t": heating_delta_t.value,
            "solar_collector_delta_t": solar_collector_delta_t.value,
            "direct_solar_delivery_margin_c": direct_solar_delivery_margin_c.value,
            "short_term_tank_height_m": short_term_tank_height_m.value,
            "seasonal_tank_height_m": seasonal_tank_height_m.value,
            "short_term_static_mixing_coeff": short_term_static_mixing_coeff.value,
            "seasonal_static_mixing_coeff": seasonal_static_mixing_coeff.value,
            "short_term_charge_mixing_coeff": short_term_charge_mixing_coeff.value,
            "seasonal_charge_mixing_coeff": seasonal_charge_mixing_coeff.value,
            "short_term_discharge_mixing_coeff": short_term_discharge_mixing_coeff.value,
            "seasonal_discharge_mixing_coeff": seasonal_discharge_mixing_coeff.value,
            "eta0": eta0.value,
            "a1": a1.value,
            "a2": a2.value,
            "collector_cost_per_m2": collector_cost_per_m2.value,
            "short_term_cost_coeff": short_term_cost_coeff.value,
            "short_term_cost_exponent": short_term_cost_exponent.value,
            "seasonal_cost_coeff": seasonal_cost_coeff.value,
            "seasonal_cost_exponent": seasonal_cost_exponent.value,
            "electricity_price": electricity_price.value,
            "backup_auxiliary_efficiency": electric_boiler_efficiency.value,
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
                rounded_candidate_values(short_collector_min_size.value, short_collector_max_size.value, short_collector_count.value),
                rounded_candidate_values(short_tank_min_size.value, short_tank_max_size.value, short_tank_count.value),
            )
        return (
            rounded_candidate_values(long_collector_min_size.value, long_collector_max_size.value, long_collector_count.value),
            rounded_candidate_values(long_tank_min_size.value, long_tank_max_size.value, long_tank_count.value),
        )

    def selected_hourly_input_path() -> Path:
        raw_path = str(path_input.value).strip()
        if not raw_path:
            return hourly_input_path
        chosen_path = Path(raw_path).expanduser()
        if not chosen_path.is_absolute():
            chosen_path = Path(__file__).resolve().parent / chosen_path
        return chosen_path

    def project_reports_dir() -> Path:
        return Path(__file__).resolve().parent / "02 reports" / safe_project_folder_name(project_name.value)

    def display_hourly_input_path(path: Path | None = None) -> str:
        chosen_path = selected_hourly_input_path() if path is None else path
        try:
            chosen_path = chosen_path.relative_to(Path(__file__).resolve().parent)
        except ValueError:
            pass
        return str(chosen_path)

    def update_hourly_file(_event=None) -> None:
        try:
            if not hourly_file.value:
                raise ValueError("Choose an input file to update the hourly input file.")
            target_path = selected_hourly_input_path()
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_bytes(hourly_file.value)
            hourly_upload_status.object = f"Hourly input file updated: `{display_hourly_input_path(target_path)}`"
        except Exception as exc:
            hourly_upload_status.object = f"Hourly file update failed: `{exc}`"

    def current_design_inputs() -> dict[str, object]:
        return {
            "project_name": project_name.value,
            "tank_max_temp": tank_max_temp.value,
            "small_delta_t_tank_min_temp": small_delta_t_tank_min_temp.value,
            "large_delta_t_tank_min_temp": large_delta_t_tank_min_temp.value,
            "initial_tank_temp": initial_tank_temp.value,
            "heating_supply_temp": heating_supply_temp.value,
            "heating_delta_t": heating_delta_t.value,
            "solar_collector_delta_t": solar_collector_delta_t.value,
            "direct_solar_delivery_margin_c": direct_solar_delivery_margin_c.value,
            "short_term_loss": short_term_loss.value,
            "seasonal_loss": seasonal_loss.value,
            "short_term_ratio": short_term_ratio.value,
            "seasonal_ratio": seasonal_ratio.value,
            "short_term_preset": short_term_preset.value,
            "seasonal_preset": seasonal_preset.value,
            "short_term_tank_height_m": short_term_tank_height_m.value,
            "seasonal_tank_height_m": seasonal_tank_height_m.value,
            "short_term_static_mixing_coeff": short_term_static_mixing_coeff.value,
            "seasonal_static_mixing_coeff": seasonal_static_mixing_coeff.value,
            "short_term_charge_mixing_coeff": short_term_charge_mixing_coeff.value,
            "seasonal_charge_mixing_coeff": seasonal_charge_mixing_coeff.value,
            "short_term_discharge_mixing_coeff": short_term_discharge_mixing_coeff.value,
            "seasonal_discharge_mixing_coeff": seasonal_discharge_mixing_coeff.value,
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
            scenario_state["html_button"].disabled = is_running or scenario_state["selected_summary"] is None

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

    def apply_tank_operation_preset(tank_type: str) -> None:
        preset_name = short_term_preset.value if tank_type == "short_term" else seasonal_preset.value
        preset = TANK_OPERATION_PRESETS[tank_type].get(str(preset_name))
        if preset is None:
            return
        if tank_type == "short_term":
            short_term_tank_height_m.value = preset["height_m"]
            short_term_static_mixing_coeff.value = preset["static_mixing_coeff"]
            short_term_charge_mixing_coeff.value = preset["charge_mixing_coeff"]
            short_term_discharge_mixing_coeff.value = preset["discharge_mixing_coeff"]
            return
        seasonal_tank_height_m.value = preset["height_m"]
        seasonal_static_mixing_coeff.value = preset["static_mixing_coeff"]
        seasonal_charge_mixing_coeff.value = preset["charge_mixing_coeff"]
        seasonal_discharge_mixing_coeff.value = preset["discharge_mixing_coeff"]

    def analyze_inputs(_event=None) -> None:
        try:
            persist_design_inputs()
            weather_df = load_input(filename=selected_hourly_input_path())
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
                f"- Average heating load: `{summary['average_heating_load_kwh']:.1f} kWh`\n"
                f"- Heating-season load: `{summary['heating_season_load_kwh']:.1f} kWh`\n"
                f"- Annual tilted solar radiation: `{summary['annual_tilted_solar_kwh_m2']:.1f} kWh/m2`\n"
                f"- Annual horizontal solar radiation: `{summary['annual_horizontal_solar_kwh_m2']:.1f} kWh/m2`\n"
                f"- Reference collector efficiency: `{summary['reference_collector_efficiency']:.3f}`\n"
                f"- Short-term suggested collector range: `{summary['short_term_collector_min_m2']:.1f}` to `{summary['short_term_collector_max_m2']:.1f} m2`\n"
                f"- Short-term suggested tank range: `{summary['short_term_tank_min_m3']:.1f}` to `{summary['short_term_tank_max_m3']:.1f} m3`\n"
                f"- Long-term suggested collector range: `{summary['seasonal_collector_min_m2']:.1f}` to `{summary['seasonal_collector_max_m2']:.1f} m2`\n"
                f"- Long-term suggested tank range: `{summary['seasonal_tank_min_m3']:.1f}` to `{summary['seasonal_tank_max_m3']:.1f} m3`"
            )
            set_table_data(monthly_table, monthly_df.round(3), min_height=260, max_height=900)
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
                ylim=line_plot_ylim(duration_plot_df, ["Load", "Surface Solar", "Horizontal Solar"]),
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
        final_area = pn.widgets.FloatInput(name="Selected Collector Area (m2)", value=0.0, step=1.0)
        final_tank = pn.widgets.FloatInput(name="Selected Tank Size (m3)", value=0.0, step=1.0)
        run_final_button = pn.widgets.Button(name="Run Step 3 Final Results", button_type="success", width=BUTTON_WIDTH)
        export_button = pn.widgets.Button(
            name="Export Excel Report",
            button_type="light",
            width=BUTTON_WIDTH,
        )
        html_button = pn.widgets.Button(
            name="Save HTML Report",
            button_type="light",
            width=BUTTON_WIDTH,
        )
        scenario_state = {
            "status": pn.pane.Markdown("Run the study to populate this tab."),
            "metrics": pn.pane.Markdown(""),
            "export_status": pn.pane.Markdown(""),
            "selected_area": selected_area,
            "final_area": final_area,
            "final_tank": final_tank,
            "run_final_button": run_final_button,
            "export_button": export_button,
            "html_button": html_button,
            "best_table": make_data_table(default_rows=5, min_height=140, max_height=320),
            "monthly_table": make_data_table(default_rows=13, min_height=320, max_height=900),
            "summary_table": make_data_table(default_rows=12, min_height=280, max_height=1400),
            "collector_plot": plot_container(PLOT_HEIGHT),
            "collector_eff_plot": plot_container(PLOT_HEIGHT),
            "tank_plot": plot_container(PLOT_HEIGHT),
            "tank_eff_plot": plot_container(PLOT_HEIGHT),
            "cost_heatmap": plot_container(PLOT_HEIGHT),
            "ratio_heatmap": plot_container(PLOT_HEIGHT),
            "tank_temp_plot": plot_container(PLOT_HEIGHT),
            "heating_plot": plot_container(PLOT_HEIGHT),
            "tank_flow_plot": plot_container(PLOT_HEIGHT),
            "weather_temp_plot": plot_container(PLOT_HEIGHT),
            "weather_load_plot": plot_container(PLOT_HEIGHT),
            "weather_solar_plot": plot_container(PLOT_HEIGHT),
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
            pn.Row(final_area, final_tank, sizing_mode="stretch_width", margin=(0, 0, 6, 0)),
            pn.Row(run_final_button, export_button, html_button, sizing_mode="stretch_width", margin=(0, 0, 6, 0)),
            scenario_state["export_status"],
            pn.pane.Markdown("### Step 3 Results"),
            scenario_state["metrics"],
            pn.Row(scenario_state["tank_temp_plot"], sizing_mode="stretch_width", margin=(0, 0, 6, 0)),
            pn.Row(scenario_state["heating_plot"], sizing_mode="stretch_width", margin=(0, 0, 6, 0)),
            pn.Row(scenario_state["tank_flow_plot"], sizing_mode="stretch_width", margin=(0, 0, 6, 0)),
            pn.Column(
                scenario_state["weather_temp_plot"],
                scenario_state["weather_load_plot"],
                scenario_state["weather_solar_plot"],
                sizing_mode="stretch_width",
                margin=(0, 0, 6, 0),
            ),
            pn.pane.Markdown("### Monthly Summary"),
            scenario_state["monthly_table"],
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

        scenario_state["final_area"].value = float(scenario_state["selected_area"].value)

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
            ylim=line_plot_ylim(tank_df, "solar_coverage_pct"),
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
            ylim=line_plot_ylim(tank_df, "collector_efficiency_pct"),
            legend=False,
            height=PLOT_HEIGHT,
            grid=True,
            shared_axes=False,
        ))
        if scenario_state["final_tank"].value is None or scenario_state["final_tank"].value <= 0:
            scenario_state["final_tank"].value = float(best_design(tank_df, objective="cost")["tank_volume_m3"])

    def update_scenario_final_view(scenario_key: str, *_events) -> None:
        weather_df = state["weather_df"]
        scenario_state = state["scenarios"][scenario_key]
        definition = scenario_defs[scenario_key]
        if weather_df is None or scenario_state["final_area"].value is None or scenario_state["final_tank"].value is None:
            return

        summary, hourly_df = simulate_design(
            weather_load_df=weather_df,
            collector_area_m2=float(scenario_state["final_area"].value),
            tank_volume_m3=float(scenario_state["final_tank"].value),
            tank_type=definition["tank_type"],
            tank_min_temp=scenario_tank_min_temp(definition),
            tank_thermal_loss_percent_per_day=tank_loss_for_type(definition["tank_type"]),
            auxiliary_system=definition["auxiliary_system"],
            auxiliary_efficiency=scenario_efficiency(definition),
            **simulate_common_kwargs(),
        )
        scenario_state["selected_summary"] = summary
        scenario_state["selected_hourly_df"] = hourly_df

        heating_window_mask = (
            hourly_df[
                [
                    "heating_load_kwh",
                    "solar_direct_collector_to_load_kwh",
                    "solar_from_tank_direct_kwh",
                    "solar_from_tank_via_hp_kwh",
                    "auxiliary_heating_delivered_kwh",
                ]
            ]
            .abs()
            .sum(axis=1)
            > 0
        )
        if heating_window_mask.any():
            plot_start = hourly_df.loc[heating_window_mask, "timestamp"].min()
            plot_end = hourly_df.loc[heating_window_mask, "timestamp"].max()
            plot_hourly_df = hourly_df[
                (hourly_df["timestamp"] >= plot_start) & (hourly_df["timestamp"] <= plot_end)
            ].copy()
        else:
            plot_hourly_df = hourly_df.copy()

        supply_overlay = plot_hourly_df.assign(
            Supply=heating_supply_temp.value,
            Return=heating_supply_temp.value - heating_delta_t.value,
        ).hvplot.line(
            x="timestamp",
            y=["Supply", "Return"],
            line_dash=["dashed", "dotted"],
            color=["firebrick", "gray"],
            ylim=line_plot_ylim(
                plot_hourly_df.assign(
                    Supply=heating_supply_temp.value,
                    Return=heating_supply_temp.value - heating_delta_t.value,
                ),
                ["Supply", "Return"],
            ),
            legend="top",
            height=PLOT_HEIGHT,
            grid=True,
            shared_axes=False,
        )
        tank_temp_df = plot_hourly_df.rename(
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
            ylim=line_plot_ylim(
                tank_temp_df.assign(
                    Supply=heating_supply_temp.value,
                    Return=heating_supply_temp.value - heating_delta_t.value,
                ),
                ["Top", "Mean", "Bottom", "Supply", "Return"],
            ),
            legend="top",
            height=PLOT_HEIGHT,
            grid=True,
            shared_axes=False,
        ) * supply_overlay)
        heating_plot_df = plot_hourly_df.rename(
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
            ylim=line_plot_ylim(heating_plot_df, ["Load", "Collector", "Tank Direct", "Tank via HP", "Auxiliary"]),
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
            ylim=line_plot_ylim(tank_flow_df, ["Charge", "Discharge", "Loss"]),
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
        set_plot(scenario_state["weather_temp_plot"], weather_plot_df.hvplot.line(
            x="timestamp",
            y="Outside",
            ylabel="Temperature (C)",
            title="Hourly Outside Temperature",
            ylim=line_plot_ylim(weather_plot_df, "Outside"),
            legend=False,
            height=PLOT_HEIGHT,
            grid=True,
            shared_axes=False,
        ))
        set_plot(scenario_state["weather_load_plot"], weather_plot_df.hvplot.line(
            x="timestamp",
            y="Load",
            ylabel="Heating Load (kWh)",
            title="Hourly Heating Load",
            ylim=line_plot_ylim(weather_plot_df, "Load"),
            legend=False,
            height=PLOT_HEIGHT,
            grid=True,
            shared_axes=False,
        ))
        set_plot(scenario_state["weather_solar_plot"], weather_plot_df.hvplot.line(
            x="timestamp",
            y="Solar",
            ylabel="Solar Radiation",
            title="Hourly Solar Radiation",
            ylim=line_plot_ylim(weather_plot_df, "Solar"),
            legend=False,
            height=PLOT_HEIGHT,
            grid=True,
            shared_axes=False,
        ))
        set_table_data(scenario_state["monthly_table"], scenario_monthly_summary(hourly_df).round(3), min_height=320, max_height=900)
        solar_direct_heat_kwh = summary["solar_direct_collector_to_load_kwh"] + summary["solar_from_tank_direct_kwh"]
        solar_energy_use_ratio_pct = (
            100.0 * summary["solar_energy_for_heating_kwh"] / summary["heating_load_kwh"]
            if summary["heating_load_kwh"] > 0
            else 0.0
        )
        heat_loss_pct = (
            100.0 * summary["tank_loss_kwh"] / summary["solar_energy_collected_kwh"]
            if summary["solar_energy_collected_kwh"] > 0
            else 0.0
        )
        scenario_state["metrics"].object = (
            "### Final Selected Result\n"
            "#### Selected Size\n"
            f"- Collector area: `{summary['collector_area_m2']:.1f} m2`\n"
            f"- Tank volume: `{summary['tank_volume_m3']:.1f} m3`\n"
            f"- Tank height: `{summary['tank_height_m']:.2f} m`\n"
            f"- Tank diameter: `{summary['tank_diameter_m']:.2f} m`\n"
            f"- Height/diameter ratio: `{summary['tank_height_to_diameter_ratio']:.2f}`\n"
            f"- Stratification efficiency: `{summary['stratification_efficiency']:.2f}`\n"
            "\n"
            "#### Energy Performance\n"
            f"- Total heating load: `{summary['heating_load_kwh']:.1f} kWh`\n"
            f"- Solar collector efficiency: `{summary['collector_efficiency_pct']:.2f}%`\n"
            f"- Solar direct heat energy: `{solar_direct_heat_kwh:.1f} kWh`\n"
            f"- Solar energy by using heat pump: `{summary['solar_from_tank_via_hp_kwh']:.1f} kWh`\n"
            f"- Usable solar heat energy: `{summary['solar_source_energy_used_kwh']:.1f} kWh`\n"
            f"- Solar heating delivered: `{summary['solar_energy_for_heating_kwh']:.1f} kWh`\n"
            f"- Solar energy use ratio: `{solar_energy_use_ratio_pct:.2f}%`\n"
            f"- Solar heating ratio: `{summary['solar_coverage_pct']:.2f}%`\n"
            f"- Auxiliary heating delivered: `{summary['auxiliary_heating_delivered_kwh']:.1f} kWh`\n"
            "\n"
            "#### Cost And Operation\n"
            f"- Auxiliary energy input: `{summary['auxiliary_energy_input_kwh']:.1f} kWh`\n"
            f"- Annual energy cost: `RMB {summary['annual_auxiliary_energy_cost']:.2f}`\n"
            f"- Heat loss percentage: `{heat_loss_pct:.2f}%`\n"
            f"- Heat pump power input: `{summary['auxiliary_energy_for_hp_boost_kwh']:.1f} kWh`\n"
            f"- Annualized total cost: `RMB {summary['annualized_total_cost']:.2f}`\n"
            f"- Tank final temperature: `{summary['tank_final_temp_c']:.1f} C`"
        )

    def export_scenario_report(scenario_key: str) -> None:
        scenario_state = state["scenarios"][scenario_key]
        if scenario_state["selected_summary"] is None or scenario_state["selected_hourly_df"] is None:
            raise ValueError("Run Step 3 Final Results before exporting the Excel report.")
        reports_dir = project_reports_dir()
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
                "hourly_input_file": display_hourly_input_path(),
                "report_generated_at": pd.Timestamp.now().isoformat(),
            },
            input_monthly_df=state["input_monthly_df"],
        )
        scenario_state["export_status"].object = (
            f"Report exported to `{Path('02 reports') / safe_project_folder_name(project_name.value) / filename}`"
        )

    def on_export_click(scenario_key: str) -> None:
        scenario_state = state["scenarios"][scenario_key]
        try:
            export_scenario_report(scenario_key)
        except Exception as exc:
            scenario_state["export_status"].object = f"Export failed: `{exc}`"

    def build_static_scenario_report(scenario_key: str) -> pn.Column:
        scenario_state = state["scenarios"][scenario_key]
        return pn.Column(
            pn.pane.HTML(
                """
                <style>
                html, body {
                    color: #111111 !important;
                    background: #ffffff !important;
                }
                .static-report-text, .static-report-text * {
                    color: #111111 !important;
                    background: #ffffff !important;
                    font-family: Arial, sans-serif !important;
                    line-height: 1.45 !important;
                }
                .static-report-text h1, .static-report-text h2, .static-report-text h3, .static-report-text h4 {
                    color: #111111 !important; margin: 12px 0 8px 0;
                }
                .static-report-text p, .static-report-text li { color: #111111 !important; font-size: 14px; }
                .static-report-table {
                    width: 100%;
                    border-collapse: collapse;
                    background: #ffffff !important;
                    color: #111111 !important;
                    font-family: Arial, sans-serif !important;
                    font-size: 13px !important;
                }
                .static-report-table th {
                    background: #e8f1fb !important;
                    color: #111111 !important;
                    border: 1px solid #d1d5db !important;
                    padding: 8px !important;
                    text-align: left !important;
                    position: sticky;
                    top: 0;
                }
                .static-report-table td {
                    border: 1px solid #e5e7eb !important;
                    padding: 7px 8px !important;
                    vertical-align: top !important;
                    color: #111111 !important;
                    background: #ffffff !important;
                }
                .static-report-table tr:nth-child(even) td { background: #f9fafb !important; }
                </style>
                """
            ),
            static_markdown_pane(f"# {scenario_defs[scenario_key]['tab_title']}"),
            static_markdown_pane(str(scenario_state["status"].object)),
            static_markdown_pane("## Optimized Results"),
            static_table_pane(scenario_state["best_table"].value, height=220),
            static_markdown_pane("## Heatmaps"),
            pn.Row(first_object(scenario_state["cost_heatmap"]), first_object(scenario_state["ratio_heatmap"]), sizing_mode="stretch_width"),
            static_markdown_pane("## Step 1: Collector Area"),
            pn.Row(first_object(scenario_state["collector_plot"]), first_object(scenario_state["collector_eff_plot"]), sizing_mode="stretch_width"),
            static_markdown_pane("## Step 2: Tank Volume At Selected Collector Area"),
            pn.Row(
                static_markdown_pane(f"Selected Collector Area: `{scenario_state['selected_area'].value}` m2"),
                sizing_mode="stretch_width",
            ),
            pn.Row(first_object(scenario_state["tank_plot"]), first_object(scenario_state["tank_eff_plot"]), sizing_mode="stretch_width"),
            static_markdown_pane("## Step 3: Final Selected Design"),
            pn.Row(
                static_markdown_pane(f"Selected Collector Area: `{scenario_state['final_area'].value}` m2"),
                static_markdown_pane(f"Selected Tank Size: `{scenario_state['final_tank'].value}` m3"),
                sizing_mode="stretch_width",
            ),
            static_markdown_pane(str(scenario_state["metrics"].object)),
            pn.Row(first_object(scenario_state["tank_temp_plot"]), sizing_mode="stretch_width"),
            pn.Row(first_object(scenario_state["heating_plot"]), sizing_mode="stretch_width"),
            pn.Row(first_object(scenario_state["tank_flow_plot"]), sizing_mode="stretch_width"),
            pn.Column(
                first_object(scenario_state["weather_temp_plot"]),
                first_object(scenario_state["weather_load_plot"]),
                first_object(scenario_state["weather_solar_plot"]),
                sizing_mode="stretch_width",
            ),
            static_markdown_pane("## Monthly Summary"),
            static_table_pane(scenario_state["monthly_table"].value, height=420),
            styles={"background": "white", "padding": "16px"},
            sizing_mode="stretch_width",
        )

    def save_scenario_html(scenario_key: str) -> None:
        scenario_state = state["scenarios"][scenario_key]
        if scenario_state["selected_summary"] is None:
            raise ValueError("Run Step 3 Final Results before saving the HTML report.")
        reports_dir = project_reports_dir()
        reports_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{scenario_key}_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.html"
        output_path = reports_dir / filename
        build_static_scenario_report(scenario_key).save(
            output_path,
            title=f"{scenario_defs[scenario_key]['tab_title']} Report",
            resources="inline",
        )
        scenario_state["export_status"].object = (
            f"HTML report saved to `{Path('02 reports') / safe_project_folder_name(project_name.value) / filename}`"
        )

    def on_html_click(scenario_key: str) -> None:
        scenario_state = state["scenarios"][scenario_key]
        try:
            save_scenario_html(scenario_key)
        except Exception as exc:
            scenario_state["export_status"].object = f"HTML save failed: `{exc}`"

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
            set_table_data(scenario_state["best_table"], design_grid_df.nsmallest(5, "annualized_total_cost").round(3), min_height=140, max_height=320)
            set_table_data(scenario_state["summary_table"], design_grid_df.round(3), min_height=280, max_height=1400)
            best_case = best_design(design_grid_df, objective="cost")
            initial_cost = float(best_case["collector_capital_cost"]) + float(best_case["tank_capital_cost"])
            solar_collected = float(best_case["solar_energy_collected_kwh"])
            heat_loss_pct = 100.0 * float(best_case["tank_loss_kwh"]) / solar_collected if solar_collected > 0 else 0.0
            scenario_state["selected_area"].options = area_values
            scenario_state["selected_area"].value = float(best_case["collector_area_m2"])
            scenario_state["final_area"].value = float(best_case["collector_area_m2"])
            scenario_state["final_tank"].value = float(best_case["tank_volume_m3"])
            scenario_state["status"].object = (
                f"### {definition['tab_title']}\n"
                f"- Best collector area: `{best_case['collector_area_m2']:.1f} m2`\n"
                f"- Best tank size: `{best_case['tank_volume_m3']:.1f} m3`\n"
                f"- Solar heating ratio: `{best_case['solar_coverage_pct']:.2f}%`\n"
                f"- Annual energy cost: `RMB {best_case['annual_auxiliary_energy_cost']:.2f}`\n"
                f"- Heat loss percentage: `{heat_loss_pct:.2f}%`\n"
                f"- Initial cost: `RMB {initial_cost:.2f}`\n"
                f"- Annualized total cost: `RMB {best_case['annualized_total_cost']:.2f}`"
            )
            set_plot(scenario_state["cost_heatmap"], build_quadmesh_heatmap(
                heatmap_frame(design_grid_df, "annualized_total_cost"),
                value_column="annualized_total_cost",
                title="Cost Heatmap",
                cmap="RdYlGn_r",
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
                ylim=line_plot_ylim(collector_df, "solar_coverage_pct"),
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
                ylim=line_plot_ylim(collector_df, "collector_efficiency_pct"),
                legend=False,
                height=PLOT_HEIGHT,
                grid=True,
                shared_axes=False,
            ))
            if mode == "two_step":
                area_best = best_design(collector_df, objective="cost")
                scenario_state["selected_area"].options = area_values
                scenario_state["selected_area"].value = float(area_best["collector_area_m2"])
                scenario_state["final_area"].value = float(area_best["collector_area_m2"])
                set_table_data(scenario_state["best_table"], collector_df.nsmallest(5, "annualized_total_cost").round(3), min_height=140, max_height=320)
                set_table_data(scenario_state["summary_table"], collector_df.round(3), min_height=280, max_height=1400)

        if mode in {"two_step", "combined"}:
            update_scenario_tank_study(scenario_key)
            if scenario_state["tank_df"] is not None and not scenario_state["tank_df"].empty:
                set_table_data(scenario_state["best_table"], scenario_state["tank_df"].nsmallest(5, "annualized_total_cost").round(3), min_height=140, max_height=320)
                if mode == "two_step":
                    set_table_data(scenario_state["summary_table"], scenario_state["tank_df"].round(3), min_height=280, max_height=1400)

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
            for label, value in {
                "Short-term tank height": short_term_tank_height_m.value,
                "Long-term tank height": seasonal_tank_height_m.value,
            }.items():
                if value <= 0:
                    raise ValueError(f"{label} must be greater than zero.")
            for label, value in {
                "Short-term passive mixing": short_term_static_mixing_coeff.value,
                "Long-term passive mixing": seasonal_static_mixing_coeff.value,
                "Short-term charge mixing": short_term_charge_mixing_coeff.value,
                "Long-term charge mixing": seasonal_charge_mixing_coeff.value,
                "Short-term draw mixing": short_term_discharge_mixing_coeff.value,
                "Long-term draw mixing": seasonal_discharge_mixing_coeff.value,
            }.items():
                if not 0.0 <= value <= 0.45:
                    raise ValueError(f"{label} must be between 0.0 and 0.45.")
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
        scenario_state["run_final_button"].on_click(lambda _event, key=scenario_key: update_scenario_final_view(key))
        scenario_state["export_button"].on_click(lambda _event, key=scenario_key: on_export_click(key))
        scenario_state["html_button"].on_click(lambda _event, key=scenario_key: on_html_click(key))

    update_hourly_button.on_click(update_hourly_file)
    analyze_button.on_click(analyze_inputs)
    run_two_step_button.on_click(lambda _event: run_analysis("two_step"))
    run_cost_button.on_click(lambda _event: run_analysis("cost"))
    run_combined_button.on_click(lambda _event: run_analysis("combined"))
    sizing_mode.param.watch(update_sizing_mode, "value")
    collector_type.param.watch(apply_collector_preset, "value")
    short_term_preset.param.watch(lambda _event: apply_tank_operation_preset("short_term"), "value")
    seasonal_preset.param.watch(lambda _event: apply_tank_operation_preset("seasonal"), "value")
    update_sizing_mode()
    apply_collector_preset()
    apply_tank_operation_preset("short_term")
    apply_tank_operation_preset("seasonal")

    sidebar_controls = pn.Column(
        pn.pane.Markdown("## Project"),
        project_name,
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
        pn.Row(heating_delta_t, solar_collector_delta_t, direct_solar_delivery_margin_c),
        pn.pane.Markdown("### Stratified Storage Settings"),
        pn.Row(
            pn.Column(
                pn.pane.Markdown("#### Short-Term Tank"),
                short_term_loss,
                short_term_ratio,
                short_term_preset,
                short_term_tank_height_m,
                short_term_static_mixing_coeff,
                short_term_charge_mixing_coeff,
                short_term_discharge_mixing_coeff,
                width=360,
                sizing_mode="fixed",
            ),
            pn.Column(
                pn.pane.Markdown("#### Long-Term Tank"),
                seasonal_loss,
                seasonal_ratio,
                seasonal_preset,
                seasonal_tank_height_m,
                seasonal_static_mixing_coeff,
                seasonal_charge_mixing_coeff,
                seasonal_discharge_mixing_coeff,
                width=360,
                sizing_mode="fixed",
            ),
            sizing_mode="fixed",
            margin=(0, 0, 0, 0),
            styles={"gap": "32px", "align-items": "flex-start"},
        ),
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
