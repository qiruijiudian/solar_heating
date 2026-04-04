#!/usr/bin/env python3
"""Core calculation utilities for solar heating storage sizing."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

RHO_WATER = 1000.0  # kg/m3
CP_WATER = 4182.0  # J/(kg*K)

TANK_TYPE_DEFAULTS = {
    "short_term": {
        "label": "Short / Mid-Term Storage",
        "ratio_l_per_m2": 200.0,
        "loss_percent_per_day": 1.0,
        "cost_coeff": 1400.0,
        "cost_exponent": 0.78,
    },
    "seasonal": {
        "label": "Long-Term / Seasonal Storage",
        "ratio_l_per_m2": 2000.0,
        "loss_percent_per_day": 0.15,
        "cost_coeff": 900.0,
        "cost_exponent": 0.82,
    },
}

INPUT_COLUMN_ALIASES = {
    "outside_temp": [
        "outside_temp",
        "outside_air_temp",
        "outsideairtemp",
        "outsideairtempc",
    ],
    "solar_rad": [
        "solar_rad",
        "solar_rad_55deg_surface",
        "solarrad55degsurface",
        "solarrad55degsurfacewhm2",
    ],
    "horizontal_solar_rad": [
        "horizontal_solar_rad",
        "horizontalsolarrad",
        "horizontalsolarradwhm2",
    ],
    "heating_load": ["heating_load", "heatingload", "heatingloadw", "heatingloadwh"],
    "timestamp": ["timestamp", "time_step", "timestep"],
}


def parse_numeric_list(value: str) -> list[float]:
    items = []
    for part in value.split(","):
        text = part.strip()
        if text:
            items.append(float(text))
    if not items:
        raise ValueError("Please provide at least one numeric value.")
    return sorted(set(items))


def make_candidate_values(min_value: float, max_value: float, step: float) -> list[float]:
    count = int(round((max_value - min_value) / step))
    return [round(min_value + index * step, 10) for index in range(count + 1)]


def normalize_tank_types(tank_types: list[str] | tuple[str, ...] | None) -> list[str]:
    if not tank_types:
        return ["short_term"]
    normalized = []
    for tank_type in tank_types:
        if tank_type not in TANK_TYPE_DEFAULTS:
            raise ValueError(f"Unsupported tank type: {tank_type}")
        normalized.append(tank_type)
    return normalized


def tank_type_label(tank_type: str) -> str:
    return TANK_TYPE_DEFAULTS[tank_type]["label"]


def tank_type_ratio_m3_per_m2(
    tank_type: str,
    short_term_ratio_l_per_m2: float,
    seasonal_ratio_l_per_m2: float,
) -> float:
    if tank_type == "short_term":
        return short_term_ratio_l_per_m2 / 1000.0
    return seasonal_ratio_l_per_m2 / 1000.0


def tank_loss_percent_per_day(
    tank_type: str,
    short_term_loss_percent_per_day: float,
    seasonal_loss_percent_per_day: float,
) -> float:
    if tank_type == "short_term":
        return short_term_loss_percent_per_day
    return seasonal_loss_percent_per_day


def tank_cost_curve(
    tank_type: str,
    short_term_cost_coeff: float,
    short_term_cost_exponent: float,
    seasonal_cost_coeff: float,
    seasonal_cost_exponent: float,
) -> tuple[float, float]:
    if tank_type == "short_term":
        return short_term_cost_coeff, short_term_cost_exponent
    return seasonal_cost_coeff, seasonal_cost_exponent


def energy_per_m3_kwh(tank_min_temp: float, tank_max_temp: float) -> float:
    delta_t = tank_max_temp - tank_min_temp
    if delta_t <= 0:
        raise ValueError("Tank maximum temperature must be higher than tank minimum temperature.")
    return RHO_WATER * CP_WATER * delta_t / 3.6e6


def first_matching_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    normalized = {normalize_column_name(column): column for column in df.columns}
    for candidate in candidates:
        if candidate in df.columns:
            return candidate
        normalized_candidate = normalize_column_name(candidate)
        if normalized_candidate in normalized:
            return normalized[normalized_candidate]
    return None


def normalize_column_name(name: str) -> str:
    normalized = str(name).strip().lower()
    replacements = {
        "℃": "c",
        "°c": "c",
        "°": "",
        "（": "(",
        "）": ")",
    }
    for source, target in replacements.items():
        normalized = normalized.replace(source, target)
    return "".join(character for character in normalized if character.isalnum())


def load_input(
    filename: str | Path,
    radiation_unit: str = "kwh/m2",
    load_unit: str = "kwh",
    timestep_hours: float = 1.0,
) -> pd.DataFrame:
    file_path = Path(filename)
    suffix = file_path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(file_path)
    else:
        df = pd.read_csv(file_path)
    mapped_columns: dict[str, str] = {}
    for standard_name, aliases in INPUT_COLUMN_ALIASES.items():
        found = first_matching_column(df, aliases)
        if found is not None:
            mapped_columns[standard_name] = found

    required = ["outside_temp", "solar_rad", "heating_load"]
    missing = [column for column in required if column not in mapped_columns]
    if missing:
        raise ValueError(f"Missing required columns in {filename}: {missing}")

    df = df.copy()
    df["outside_temp"] = df[mapped_columns["outside_temp"]].astype(float)
    df["solar_rad"] = df[mapped_columns["solar_rad"]].astype(float)
    df["heating_load"] = df[mapped_columns["heating_load"]].astype(float)
    if "horizontal_solar_rad" in mapped_columns:
        df["horizontal_solar_rad"] = df[mapped_columns["horizontal_solar_rad"]].astype(float)
        horizontal_column_name = normalize_column_name(mapped_columns["horizontal_solar_rad"])
        if radiation_unit.lower() == "w/m2":
            df["horizontal_solar_rad"] = df["horizontal_solar_rad"] * timestep_hours / 1000.0
        elif "whm2" in horizontal_column_name:
            df["horizontal_solar_rad"] = df["horizontal_solar_rad"] / 1000.0

    solar_column_name = normalize_column_name(mapped_columns["solar_rad"])
    if radiation_unit.lower() == "w/m2":
        df["solar_rad"] = df["solar_rad"] * timestep_hours / 1000.0
    elif "whm2" in solar_column_name or (suffix in {".xlsx", ".xls"} and df["solar_rad"].max() > 50.0):
        df["solar_rad"] = df["solar_rad"] / 1000.0
    elif radiation_unit.lower() != "kwh/m2":
        raise ValueError("Unsupported radiation unit, choose kWh/m2 or W/m2.")

    heating_column_name = normalize_column_name(mapped_columns["heating_load"])
    if load_unit.lower() == "w":
        df["heating_load"] = df["heating_load"] * timestep_hours / 1000.0
    elif heating_column_name.endswith("w") or heating_column_name.endswith("wh"):
        df["heating_load"] = df["heating_load"] * timestep_hours / 1000.0
    elif load_unit.lower() != "kwh":
        raise ValueError("Unsupported load unit, choose kWh or W.")

    if "timestamp" in mapped_columns:
        df["timestamp"] = pd.to_datetime(df[mapped_columns["timestamp"]])
    else:
        df["timestamp"] = pd.date_range(
            start="2025-01-01 00:00:00",
            periods=len(df),
            freq=pd.to_timedelta(timestep_hours, unit="h"),
        )

    return df


def collector_output_kwh(
    area_m2: float,
    solar_rad_kwh_m2: float,
    outside_temp_c: float,
    fluid_temp_c: float,
    timestep_hours: float,
    eta0: float,
    a1: float,
    a2: float,
) -> tuple[float, float]:
    if solar_rad_kwh_m2 <= 0 or area_m2 <= 0:
        return 0.0, 0.0

    irradiance_w_m2 = solar_rad_kwh_m2 * 1000.0 / max(timestep_hours, 1e-9)
    delta_t = fluid_temp_c - outside_temp_c
    eta = eta0 - a1 * delta_t / max(irradiance_w_m2, 1e-6) - a2 * delta_t**2 / max(irradiance_w_m2, 1e-6)
    eta = float(np.clip(eta, 0.0, 0.85))
    collected_kwh = area_m2 * solar_rad_kwh_m2 * eta
    return collected_kwh, eta


def temperature_fraction(temp_c: float, tank_min_temp: float, tank_max_temp: float) -> float:
    return float(np.clip((temp_c - tank_min_temp) / max(tank_max_temp - tank_min_temp, 1e-9), 0.0, 1.0))


def storage_energy_from_temp(
    tank_temp_c: float,
    storage_capacity_kwh: float,
    tank_min_temp: float,
    tank_max_temp: float,
) -> float:
    return storage_capacity_kwh * temperature_fraction(tank_temp_c, tank_min_temp, tank_max_temp)


def storage_temp_from_energy(
    storage_energy_kwh: float,
    storage_capacity_kwh: float,
    tank_min_temp: float,
    tank_max_temp: float,
) -> float:
    if storage_capacity_kwh <= 0:
        return tank_min_temp
    fraction = np.clip(storage_energy_kwh / storage_capacity_kwh, 0.0, 1.0)
    return tank_min_temp + fraction * (tank_max_temp - tank_min_temp)


def energy_above_temperature(
    storage_energy_kwh: float,
    storage_capacity_kwh: float,
    tank_min_temp: float,
    tank_max_temp: float,
    threshold_temp_c: float,
) -> float:
    threshold_energy = storage_energy_from_temp(
        tank_temp_c=threshold_temp_c,
        storage_capacity_kwh=storage_capacity_kwh,
        tank_min_temp=tank_min_temp,
        tank_max_temp=tank_max_temp,
    )
    return max(storage_energy_kwh - threshold_energy, 0.0)


def energy_between_temperatures(
    storage_energy_kwh: float,
    storage_capacity_kwh: float,
    tank_min_temp: float,
    tank_max_temp: float,
    low_temp_c: float,
    high_temp_c: float,
) -> float:
    if high_temp_c <= low_temp_c:
        return 0.0
    energy_above_low = energy_above_temperature(
        storage_energy_kwh=storage_energy_kwh,
        storage_capacity_kwh=storage_capacity_kwh,
        tank_min_temp=tank_min_temp,
        tank_max_temp=tank_max_temp,
        threshold_temp_c=low_temp_c,
    )
    energy_above_high = energy_above_temperature(
        storage_energy_kwh=storage_energy_kwh,
        storage_capacity_kwh=storage_capacity_kwh,
        tank_min_temp=tank_min_temp,
        tank_max_temp=tank_max_temp,
        threshold_temp_c=high_temp_c,
    )
    return max(energy_above_low - energy_above_high, 0.0)


def storage_loss_kwh(storage_energy_kwh: float, loss_percent_per_day: float, timestep_hours: float) -> float:
    daily_retention = float(np.clip(1.0 - loss_percent_per_day / 100.0, 0.0, 1.0))
    step_retention = daily_retention ** (timestep_hours / 24.0)
    return storage_energy_kwh * (1.0 - step_retention)


def default_stratification_nodes(tank_type: str) -> int:
    return 8 if tank_type == "short_term" else 12


def create_tank_layers(initial_temp: float, num_nodes: int) -> np.ndarray:
    return np.full(num_nodes, float(initial_temp), dtype=float)


def stabilize_stratification(layer_temps_c: np.ndarray) -> np.ndarray:
    return np.sort(layer_temps_c)[::-1]


def layer_kwh_per_k(tank_volume_m3: float, num_nodes: int) -> float:
    return tank_volume_m3 * RHO_WATER * CP_WATER / 3.6e6 / max(num_nodes, 1)


def tank_energy_from_layers(layer_temps_c: np.ndarray, tank_min_temp: float, kwh_per_k: float) -> float:
    return float(np.maximum(layer_temps_c - tank_min_temp, 0.0).sum() * kwh_per_k)


def tank_summary_temperatures(layer_temps_c: np.ndarray) -> tuple[float, float, float]:
    return float(layer_temps_c.mean()), float(layer_temps_c[0]), float(layer_temps_c[-1])


def charge_tank_layers(
    layer_temps_c: np.ndarray,
    charge_kwh: float,
    source_temp_c: float,
    tank_max_temp: float,
    kwh_per_k: float,
) -> tuple[np.ndarray, float]:
    remaining_kwh = max(charge_kwh, 0.0)
    updated = layer_temps_c.copy()

    for idx in range(len(updated)):
        if remaining_kwh <= 0:
            break
        target_temp = min(tank_max_temp, source_temp_c)
        if target_temp <= updated[idx]:
            continue
        capacity_kwh = (target_temp - updated[idx]) * kwh_per_k
        applied_kwh = min(remaining_kwh, capacity_kwh)
        updated[idx] += applied_kwh / kwh_per_k
        remaining_kwh -= applied_kwh

    return stabilize_stratification(updated), charge_kwh - remaining_kwh


def discharge_tank_above_threshold(
    layer_temps_c: np.ndarray,
    demand_kwh: float,
    threshold_temp_c: float,
    kwh_per_k: float,
) -> tuple[np.ndarray, float]:
    remaining_kwh = max(demand_kwh, 0.0)
    updated = layer_temps_c.copy()
    delivered_kwh = 0.0

    for idx in range(len(updated)):
        if remaining_kwh <= 0:
            break
        available_kwh = max(updated[idx] - threshold_temp_c, 0.0) * kwh_per_k
        used_kwh = min(remaining_kwh, available_kwh)
        updated[idx] -= used_kwh / kwh_per_k
        remaining_kwh -= used_kwh
        delivered_kwh += used_kwh

    return stabilize_stratification(updated), delivered_kwh


def discharge_tank_for_hp_source(
    layer_temps_c: np.ndarray,
    source_energy_needed_kwh: float,
    min_source_temp_c: float,
    max_source_temp_c: float,
    kwh_per_k: float,
) -> tuple[np.ndarray, float]:
    remaining_kwh = max(source_energy_needed_kwh, 0.0)
    updated = layer_temps_c.copy()
    extracted_kwh = 0.0

    for idx in range(len(updated)):
        if remaining_kwh <= 0:
            break
        upper_temp = min(updated[idx], max_source_temp_c)
        lower_temp = min_source_temp_c
        if upper_temp <= lower_temp:
            continue
        available_kwh = (upper_temp - lower_temp) * kwh_per_k
        used_kwh = min(remaining_kwh, available_kwh)
        updated[idx] -= used_kwh / kwh_per_k
        remaining_kwh -= used_kwh
        extracted_kwh += used_kwh

    return stabilize_stratification(updated), extracted_kwh


def apply_tank_losses(
    layer_temps_c: np.ndarray,
    tank_min_temp: float,
    loss_percent_per_day: float,
    timestep_hours: float,
    kwh_per_k: float,
) -> tuple[np.ndarray, float]:
    daily_retention = float(np.clip(1.0 - loss_percent_per_day / 100.0, 0.0, 1.0))
    step_retention = daily_retention ** (timestep_hours / 24.0)
    updated = tank_min_temp + (layer_temps_c - tank_min_temp) * step_retention
    loss_kwh = float(np.maximum(layer_temps_c - updated, 0.0).sum() * kwh_per_k)
    return stabilize_stratification(updated), loss_kwh


def tank_capital_cost(
    tank_volume_m3: float,
    tank_type: str,
    short_term_cost_coeff: float,
    short_term_cost_exponent: float,
    seasonal_cost_coeff: float,
    seasonal_cost_exponent: float,
) -> float:
    coeff, exponent = tank_cost_curve(
        tank_type=tank_type,
        short_term_cost_coeff=short_term_cost_coeff,
        short_term_cost_exponent=short_term_cost_exponent,
        seasonal_cost_coeff=seasonal_cost_coeff,
        seasonal_cost_exponent=seasonal_cost_exponent,
    )
    return coeff * max(tank_volume_m3, 0.0) ** exponent


def _simulate_single_pass(
    weather_load_df: pd.DataFrame,
    collector_area_m2: float,
    tank_layers_c: np.ndarray,
    tank_type: str,
    tank_min_temp: float,
    tank_max_temp: float,
    heating_supply_temp: float,
    heating_delta_t: float,
    solar_collector_delta_t: float,
    tank_thermal_loss_percent_per_day: float,
    auxiliary_system: str,
    auxiliary_efficiency: float,
    timestep_hours: float,
    eta0: float,
    a1: float,
    a2: float,
    kwh_per_k_per_node: float,
    pass_index: int,
) -> tuple[dict[str, float], pd.DataFrame, np.ndarray]:
    heating_return_temp = heating_supply_temp - heating_delta_t
    working_layers = tank_layers_c.copy()
    records: list[dict[str, float]] = []
    totals = {
        "solar_energy_collected_kwh": 0.0,
        "solar_direct_collector_to_load_kwh": 0.0,
        "solar_from_tank_direct_kwh": 0.0,
        "solar_from_tank_via_hp_kwh": 0.0,
        "solar_from_tank_via_hp_source_kwh": 0.0,
        "solar_source_energy_used_kwh": 0.0,
        "solar_energy_for_heating_kwh": 0.0,
        "auxiliary_heating_delivered_kwh": 0.0,
        "auxiliary_energy_input_kwh": 0.0,
        "auxiliary_energy_for_hp_boost_kwh": 0.0,
        "solar_energy_curtailed_kwh": 0.0,
        "tank_charge_kwh": 0.0,
        "tank_discharge_total_kwh": 0.0,
        "tank_loss_kwh": 0.0,
        "heating_load_kwh": float(weather_load_df["heating_load"].sum()),
    }

    for row in weather_load_df.itertuples(index=False):
        tank_temp_start, tank_top_temp_start, tank_bottom_temp_start = tank_summary_temperatures(working_layers)
        storage_energy_start_kwh = tank_energy_from_layers(working_layers, tank_min_temp, kwh_per_k_per_node)
        collector_fluid_temp = max(heating_supply_temp, tank_top_temp_start) + solar_collector_delta_t / 2.0
        solar_collected_kwh, efficiency = collector_output_kwh(
            area_m2=collector_area_m2,
            solar_rad_kwh_m2=row.solar_rad,
            outside_temp_c=row.outside_temp,
            fluid_temp_c=collector_fluid_temp,
            timestep_hours=timestep_hours,
            eta0=eta0,
            a1=a1,
            a2=a2,
        )

        direct_solar_to_load_kwh = min(solar_collected_kwh, row.heating_load)
        remaining_load_kwh = row.heating_load - direct_solar_to_load_kwh

        surplus_solar_kwh = max(solar_collected_kwh - direct_solar_to_load_kwh, 0.0)
        available_storage_kwh = max(
            tank_volume_kwh_capacity_from_layers(working_layers, tank_min_temp, tank_max_temp, kwh_per_k_per_node)
            - storage_energy_start_kwh,
            0.0,
        )
        candidate_charge_kwh = min(surplus_solar_kwh, available_storage_kwh)
        charge_source_temp = min(tank_max_temp, collector_fluid_temp + solar_collector_delta_t / 2.0)
        working_layers, tank_charge_kwh = charge_tank_layers(
            layer_temps_c=working_layers,
            charge_kwh=candidate_charge_kwh,
            source_temp_c=charge_source_temp,
            tank_max_temp=tank_max_temp,
            kwh_per_k=kwh_per_k_per_node,
        )
        solar_curtailed_kwh = surplus_solar_kwh - tank_charge_kwh
        working_layers, solar_from_tank_direct_kwh = discharge_tank_above_threshold(
            layer_temps_c=working_layers,
            demand_kwh=remaining_load_kwh,
            threshold_temp_c=heating_supply_temp,
            kwh_per_k=kwh_per_k_per_node,
        )
        remaining_load_kwh -= solar_from_tank_direct_kwh

        solar_from_tank_via_hp_kwh = 0.0
        solar_from_tank_via_hp_source_kwh = 0.0
        auxiliary_energy_for_hp_boost_kwh = 0.0
        if remaining_load_kwh > 0 and auxiliary_system == "water_heat_pump" and auxiliary_efficiency > 1.0:
            hp_deliverable_factor = auxiliary_efficiency / max(auxiliary_efficiency - 1.0, 1e-6)
            hp_source_needed_kwh = remaining_load_kwh / hp_deliverable_factor
            working_layers, solar_from_tank_via_hp_source_kwh = discharge_tank_for_hp_source(
                layer_temps_c=working_layers,
                source_energy_needed_kwh=hp_source_needed_kwh,
                min_source_temp_c=tank_min_temp,
                max_source_temp_c=min(heating_supply_temp, tank_max_temp),
                kwh_per_k=kwh_per_k_per_node,
            )
            if solar_from_tank_via_hp_source_kwh > 0:
                solar_from_tank_via_hp_kwh = solar_from_tank_via_hp_source_kwh * hp_deliverable_factor
                solar_from_tank_via_hp_kwh = min(remaining_load_kwh, solar_from_tank_via_hp_kwh)
                solar_from_tank_via_hp_source_kwh = solar_from_tank_via_hp_kwh * (1.0 - 1.0 / auxiliary_efficiency)
                auxiliary_energy_for_hp_boost_kwh = solar_from_tank_via_hp_kwh / auxiliary_efficiency
                remaining_load_kwh -= solar_from_tank_via_hp_kwh

        auxiliary_heating_delivered_kwh = max(remaining_load_kwh, 0.0)
        if auxiliary_system == "water_heat_pump" and auxiliary_efficiency > 1.0:
            auxiliary_energy_input_kwh = auxiliary_heating_delivered_kwh / auxiliary_efficiency + auxiliary_energy_for_hp_boost_kwh
        else:
            auxiliary_energy_input_kwh = (
                auxiliary_heating_delivered_kwh / max(auxiliary_efficiency, 1e-6) + auxiliary_energy_for_hp_boost_kwh
            )

        working_layers, tank_loss_step_kwh = apply_tank_losses(
            layer_temps_c=working_layers,
            tank_min_temp=tank_min_temp,
            loss_percent_per_day=tank_thermal_loss_percent_per_day,
            timestep_hours=timestep_hours,
            kwh_per_k=kwh_per_k_per_node,
        )
        tank_temp_end, tank_top_temp_end, tank_bottom_temp_end = tank_summary_temperatures(working_layers)
        storage_energy_kwh = tank_energy_from_layers(working_layers, tank_min_temp, kwh_per_k_per_node)

        solar_heating_delivered_kwh = direct_solar_to_load_kwh + solar_from_tank_direct_kwh + solar_from_tank_via_hp_kwh
        solar_source_energy_used_kwh = (
            direct_solar_to_load_kwh + solar_from_tank_direct_kwh + solar_from_tank_via_hp_source_kwh
        )
        tank_discharge_total_kwh = solar_from_tank_direct_kwh + solar_from_tank_via_hp_source_kwh

        for key, value in {
            "solar_energy_collected_kwh": solar_collected_kwh,
            "solar_direct_collector_to_load_kwh": direct_solar_to_load_kwh,
            "solar_from_tank_direct_kwh": solar_from_tank_direct_kwh,
            "solar_from_tank_via_hp_kwh": solar_from_tank_via_hp_kwh,
            "solar_from_tank_via_hp_source_kwh": solar_from_tank_via_hp_source_kwh,
            "solar_source_energy_used_kwh": solar_source_energy_used_kwh,
            "solar_energy_for_heating_kwh": solar_heating_delivered_kwh,
            "auxiliary_heating_delivered_kwh": auxiliary_heating_delivered_kwh,
            "auxiliary_energy_input_kwh": auxiliary_energy_input_kwh,
            "auxiliary_energy_for_hp_boost_kwh": auxiliary_energy_for_hp_boost_kwh,
            "solar_energy_curtailed_kwh": solar_curtailed_kwh,
            "tank_charge_kwh": tank_charge_kwh,
            "tank_discharge_total_kwh": tank_discharge_total_kwh,
            "tank_loss_kwh": tank_loss_step_kwh,
        }.items():
            totals[key] += value

        timestamp = row.timestamp
        if pass_index > 0:
            timestamp = pd.Timestamp(timestamp) + pd.DateOffset(years=pass_index)

        records.append(
            {
                "timestamp": timestamp,
                "simulation_year_index": pass_index + 1,
                "tank_type": tank_type,
                "tank_type_label": tank_type_label(tank_type),
                "outside_temp_c": row.outside_temp,
                "solar_rad_kwh_m2": row.solar_rad,
                "horizontal_solar_rad_kwh_m2": getattr(row, "horizontal_solar_rad", np.nan),
                "heating_load_kwh": row.heating_load,
                "collector_efficiency": efficiency,
                "solar_energy_collected_kwh": solar_collected_kwh,
                "solar_direct_collector_to_load_kwh": direct_solar_to_load_kwh,
                "solar_from_tank_direct_kwh": solar_from_tank_direct_kwh,
                "solar_from_tank_via_hp_kwh": solar_from_tank_via_hp_kwh,
                "solar_from_tank_via_hp_source_kwh": solar_from_tank_via_hp_source_kwh,
                "solar_heating_total_kwh": solar_heating_delivered_kwh,
                "auxiliary_heating_delivered_kwh": auxiliary_heating_delivered_kwh,
                "auxiliary_energy_input_kwh": auxiliary_energy_input_kwh,
                "auxiliary_energy_for_hp_boost_kwh": auxiliary_energy_for_hp_boost_kwh,
                "tank_temp_start_c": tank_temp_start,
                "tank_temp_end_c": tank_temp_end,
                "tank_top_temp_start_c": tank_top_temp_start,
                "tank_bottom_temp_start_c": tank_bottom_temp_start,
                "tank_top_temp_end_c": tank_top_temp_end,
                "tank_bottom_temp_end_c": tank_bottom_temp_end,
                "tank_stored_energy_kwh": storage_energy_kwh,
                "tank_charge_kwh": tank_charge_kwh,
                "tank_discharge_direct_kwh": solar_from_tank_direct_kwh,
                "tank_discharge_hp_source_kwh": solar_from_tank_via_hp_source_kwh,
                "tank_discharge_total_kwh": tank_discharge_total_kwh,
                "tank_loss_kwh": tank_loss_step_kwh,
                "solar_energy_curtailed_kwh": solar_curtailed_kwh,
            }
        )

    return totals, pd.DataFrame.from_records(records), working_layers


def tank_volume_kwh_capacity_from_layers(
    layer_temps_c: np.ndarray,
    tank_min_temp: float,
    tank_max_temp: float,
    kwh_per_k: float,
) -> float:
    return len(layer_temps_c) * kwh_per_k * (tank_max_temp - tank_min_temp)


def simulate_design(
    weather_load_df: pd.DataFrame,
    collector_area_m2: float,
    tank_volume_m3: float,
    tank_type: str = "short_term",
    tank_min_temp: float = 30.0,
    tank_max_temp: float = 80.0,
    initial_tank_temp: float | None = None,
    heating_supply_temp: float = 45.0,
    heating_delta_t: float = 10.0,
    solar_collector_delta_t: float = 10.0,
    tank_thermal_loss_percent_per_day: float = 1.0,
    auxiliary_system: str = "electric",
    auxiliary_efficiency: float = 0.98,
    timestep_hours: float = 1.0,
    eta0: float = 0.72,
    a1: float = 3.2,
    a2: float = 0.0,
    collector_cost_per_m2: float = 300.0,
    short_term_cost_coeff: float = 1400.0,
    short_term_cost_exponent: float = 0.78,
    seasonal_cost_coeff: float = 900.0,
    seasonal_cost_exponent: float = 0.82,
    electricity_price: float = 0.12,
    project_lifetime_years: float = 20.0,
    seasonal_max_years: int = 3,
    seasonal_convergence_tolerance_kwh: float = 1.0,
) -> tuple[dict[str, float], pd.DataFrame]:
    if tank_type not in TANK_TYPE_DEFAULTS:
        raise ValueError(f"Unsupported tank type: {tank_type}")
    if tank_max_temp <= tank_min_temp:
        raise ValueError("Tank maximum temperature must be higher than tank minimum temperature.")
    if heating_delta_t < 0:
        raise ValueError("Heating system delta T must be non-negative.")
    if project_lifetime_years <= 0:
        raise ValueError("Project lifetime must be greater than zero.")

    initial_temp = tank_min_temp if initial_tank_temp is None else initial_tank_temp
    initial_temp = float(np.clip(initial_temp, tank_min_temp, tank_max_temp))
    heating_return_temp = heating_supply_temp - heating_delta_t

    capacity_kwh = tank_volume_m3 * energy_per_m3_kwh(tank_min_temp, tank_max_temp)
    num_nodes = default_stratification_nodes(tank_type)
    kwh_per_k_per_node = layer_kwh_per_k(tank_volume_m3, num_nodes)
    tank_layers_c = create_tank_layers(initial_temp, num_nodes)
    seasonal_years = min(max(seasonal_max_years, 1), 3)
    if tank_type != "seasonal":
        seasonal_years = 1

    final_totals = None
    final_records = None
    converged = False
    years_used = 1

    for pass_index in range(seasonal_years):
        start_energy_kwh = tank_energy_from_layers(tank_layers_c, tank_min_temp, kwh_per_k_per_node)
        totals, records_df, end_layers = _simulate_single_pass(
            weather_load_df=weather_load_df,
            collector_area_m2=collector_area_m2,
            tank_layers_c=tank_layers_c,
            tank_type=tank_type,
            tank_min_temp=tank_min_temp,
            tank_max_temp=tank_max_temp,
            heating_supply_temp=heating_supply_temp,
            heating_delta_t=heating_delta_t,
            solar_collector_delta_t=solar_collector_delta_t,
            tank_thermal_loss_percent_per_day=tank_thermal_loss_percent_per_day,
            auxiliary_system=auxiliary_system,
            auxiliary_efficiency=auxiliary_efficiency,
            timestep_hours=timestep_hours,
            eta0=eta0,
            a1=a1,
            a2=a2,
            kwh_per_k_per_node=kwh_per_k_per_node,
            pass_index=pass_index,
        )
        end_energy_kwh = tank_energy_from_layers(end_layers, tank_min_temp, kwh_per_k_per_node)
        final_totals = totals
        final_records = records_df
        years_used = pass_index + 1
        tank_layers_c = end_layers

        if tank_type != "seasonal":
            break
        if abs(end_energy_kwh - start_energy_kwh) <= max(seasonal_convergence_tolerance_kwh, 0.005 * capacity_kwh):
            converged = True
            break

    totals = final_totals if final_totals is not None else {}
    records_df = final_records if final_records is not None else pd.DataFrame()

    collector_capital = collector_area_m2 * collector_cost_per_m2
    tank_capital = tank_capital_cost(
        tank_volume_m3=tank_volume_m3,
        tank_type=tank_type,
        short_term_cost_coeff=short_term_cost_coeff,
        short_term_cost_exponent=short_term_cost_exponent,
        seasonal_cost_coeff=seasonal_cost_coeff,
        seasonal_cost_exponent=seasonal_cost_exponent,
    )
    annualized_capital = (collector_capital + tank_capital) / project_lifetime_years
    annual_auxiliary_energy_cost = totals["auxiliary_energy_input_kwh"] * electricity_price
    annualized_total_cost = annualized_capital + annual_auxiliary_energy_cost

    results = {
        "tank_type": tank_type,
        "tank_type_label": tank_type_label(tank_type),
        "collector_area_m2": collector_area_m2,
        "tank_volume_m3": tank_volume_m3,
        "tank_capacity_kwh": capacity_kwh,
        "initial_tank_temp_c": initial_temp,
        "tank_final_temp_c": float(records_df["tank_temp_end_c"].iloc[-1]) if not records_df.empty else initial_temp,
        "heating_return_temp_c": heating_return_temp,
        "seasonal_years_used": years_used,
        "seasonal_converged": converged if tank_type == "seasonal" else True,
        "seasonal_max_years": seasonal_years,
        "collector_cost_per_m2": collector_cost_per_m2,
        "collector_capital_cost": collector_capital,
        "tank_capital_cost": tank_capital,
        "annualized_capital_cost": annualized_capital,
        "annual_auxiliary_energy_cost": annual_auxiliary_energy_cost,
        "annualized_total_cost": annualized_total_cost,
        **totals,
    }
    load_total = results["heating_load_kwh"]
    results["solar_heating_ratio_pct"] = (
        100.0 * results["solar_source_energy_used_kwh"] / load_total if load_total > 0 else 0.0
    )
    results["solar_coverage_pct"] = results["solar_heating_ratio_pct"]
    results["auxiliary_fraction_pct"] = (
        100.0 * results["auxiliary_heating_delivered_kwh"] / load_total if load_total > 0 else 0.0
    )
    return results, records_df


def run_design_grid(
    weather_load_df: pd.DataFrame,
    collector_area_list: list[float],
    tank_size_list: list[float],
    tank_types: list[str] | tuple[str, ...] | None = None,
    tank_min_temp: float = 30.0,
    tank_max_temp: float = 80.0,
    initial_tank_temp: float | None = None,
    heating_supply_temp: float = 45.0,
    heating_delta_t: float = 10.0,
    solar_collector_delta_t: float = 10.0,
    short_term_loss_percent_per_day: float = 1.0,
    seasonal_loss_percent_per_day: float = 0.15,
    auxiliary_system: str = "electric",
    auxiliary_efficiency: float = 0.98,
    timestep_hours: float = 1.0,
    eta0: float = 0.72,
    a1: float = 3.2,
    a2: float = 0.0,
    collector_cost_per_m2: float = 300.0,
    short_term_cost_coeff: float = 1400.0,
    short_term_cost_exponent: float = 0.78,
    seasonal_cost_coeff: float = 900.0,
    seasonal_cost_exponent: float = 0.82,
    electricity_price: float = 0.12,
    project_lifetime_years: float = 20.0,
    progress_callback: Callable[[dict[str, float | str]], None] | None = None,
) -> pd.DataFrame:
    rows = []
    normalized_tank_types = normalize_tank_types(tank_types)
    total = len(normalized_tank_types) * len(collector_area_list) * len(tank_size_list)
    current = 0
    for tank_type in normalized_tank_types:
        current_loss = tank_loss_percent_per_day(
            tank_type=tank_type,
            short_term_loss_percent_per_day=short_term_loss_percent_per_day,
            seasonal_loss_percent_per_day=seasonal_loss_percent_per_day,
        )
        for area in collector_area_list:
            for tank_size in tank_size_list:
                current += 1
                if progress_callback is not None:
                    progress_callback(
                        {
                            "current": current,
                            "total": total,
                            "tank_type": tank_type,
                            "collector_area_m2": area,
                            "tank_volume_m3": tank_size,
                        }
                    )
                summary, _ = simulate_design(
                    weather_load_df=weather_load_df,
                    collector_area_m2=area,
                    tank_volume_m3=tank_size,
                    tank_type=tank_type,
                    tank_min_temp=tank_min_temp,
                    tank_max_temp=tank_max_temp,
                    initial_tank_temp=initial_tank_temp,
                    heating_supply_temp=heating_supply_temp,
                    heating_delta_t=heating_delta_t,
                    solar_collector_delta_t=solar_collector_delta_t,
                    tank_thermal_loss_percent_per_day=current_loss,
                    auxiliary_system=auxiliary_system,
                    auxiliary_efficiency=auxiliary_efficiency,
                    timestep_hours=timestep_hours,
                    eta0=eta0,
                    a1=a1,
                    a2=a2,
                    collector_cost_per_m2=collector_cost_per_m2,
                    short_term_cost_coeff=short_term_cost_coeff,
                    short_term_cost_exponent=short_term_cost_exponent,
                    seasonal_cost_coeff=seasonal_cost_coeff,
                    seasonal_cost_exponent=seasonal_cost_exponent,
                    electricity_price=electricity_price,
                    project_lifetime_years=project_lifetime_years,
                )
                rows.append(summary)
    return pd.DataFrame(rows).sort_values(["tank_type", "collector_area_m2", "tank_volume_m3"]).reset_index(drop=True)


def run_collector_area_study(
    weather_load_df: pd.DataFrame,
    collector_area_list: list[float],
    tank_types: list[str] | tuple[str, ...] | None = None,
    tank_min_temp: float = 30.0,
    tank_max_temp: float = 80.0,
    initial_tank_temp: float | None = None,
    heating_supply_temp: float = 45.0,
    heating_delta_t: float = 10.0,
    solar_collector_delta_t: float = 10.0,
    short_term_loss_percent_per_day: float = 1.0,
    seasonal_loss_percent_per_day: float = 0.15,
    short_term_ratio_l_per_m2: float = 200.0,
    seasonal_ratio_l_per_m2: float = 2000.0,
    auxiliary_system: str = "electric",
    auxiliary_efficiency: float = 0.98,
    timestep_hours: float = 1.0,
    eta0: float = 0.72,
    a1: float = 3.2,
    a2: float = 0.0,
    collector_cost_per_m2: float = 300.0,
    short_term_cost_coeff: float = 1400.0,
    short_term_cost_exponent: float = 0.78,
    seasonal_cost_coeff: float = 900.0,
    seasonal_cost_exponent: float = 0.82,
    electricity_price: float = 0.12,
    project_lifetime_years: float = 20.0,
    progress_callback: Callable[[dict[str, float | str]], None] | None = None,
) -> pd.DataFrame:
    rows = []
    normalized_tank_types = normalize_tank_types(tank_types)
    total = len(normalized_tank_types) * len(collector_area_list)
    current = 0
    for tank_type in normalized_tank_types:
        current_loss = tank_loss_percent_per_day(
            tank_type=tank_type,
            short_term_loss_percent_per_day=short_term_loss_percent_per_day,
            seasonal_loss_percent_per_day=seasonal_loss_percent_per_day,
        )
        ratio_m3_per_m2 = tank_type_ratio_m3_per_m2(
            tank_type=tank_type,
            short_term_ratio_l_per_m2=short_term_ratio_l_per_m2,
            seasonal_ratio_l_per_m2=seasonal_ratio_l_per_m2,
        )
        for area in collector_area_list:
            current += 1
            if progress_callback is not None:
                progress_callback(
                    {
                        "current": current,
                        "total": total,
                        "tank_type": tank_type,
                        "collector_area_m2": area,
                        "tank_volume_m3": area * ratio_m3_per_m2,
                    }
                )
            summary, _ = simulate_design(
                weather_load_df=weather_load_df,
                collector_area_m2=area,
                tank_volume_m3=area * ratio_m3_per_m2,
                tank_type=tank_type,
                tank_min_temp=tank_min_temp,
                tank_max_temp=tank_max_temp,
                initial_tank_temp=initial_tank_temp,
                heating_supply_temp=heating_supply_temp,
                heating_delta_t=heating_delta_t,
                solar_collector_delta_t=solar_collector_delta_t,
                tank_thermal_loss_percent_per_day=current_loss,
                auxiliary_system=auxiliary_system,
                auxiliary_efficiency=auxiliary_efficiency,
                timestep_hours=timestep_hours,
                eta0=eta0,
                a1=a1,
                a2=a2,
                collector_cost_per_m2=collector_cost_per_m2,
                short_term_cost_coeff=short_term_cost_coeff,
                short_term_cost_exponent=short_term_cost_exponent,
                seasonal_cost_coeff=seasonal_cost_coeff,
                seasonal_cost_exponent=seasonal_cost_exponent,
                electricity_price=electricity_price,
                project_lifetime_years=project_lifetime_years,
            )
            summary["study_ratio_l_per_m2"] = ratio_m3_per_m2 * 1000.0
            rows.append(summary)
    return pd.DataFrame(rows).sort_values(["tank_type", "collector_area_m2"]).reset_index(drop=True)


def run_tank_size_study(
    weather_load_df: pd.DataFrame,
    collector_area_m2: float,
    tank_size_list: list[float],
    tank_types: list[str] | tuple[str, ...] | None = None,
    tank_min_temp: float = 30.0,
    tank_max_temp: float = 80.0,
    initial_tank_temp: float | None = None,
    heating_supply_temp: float = 45.0,
    heating_delta_t: float = 10.0,
    solar_collector_delta_t: float = 10.0,
    short_term_loss_percent_per_day: float = 1.0,
    seasonal_loss_percent_per_day: float = 0.15,
    auxiliary_system: str = "electric",
    auxiliary_efficiency: float = 0.98,
    timestep_hours: float = 1.0,
    eta0: float = 0.72,
    a1: float = 3.2,
    a2: float = 0.0,
    collector_cost_per_m2: float = 300.0,
    short_term_cost_coeff: float = 1400.0,
    short_term_cost_exponent: float = 0.78,
    seasonal_cost_coeff: float = 900.0,
    seasonal_cost_exponent: float = 0.82,
    electricity_price: float = 0.12,
    project_lifetime_years: float = 20.0,
    progress_callback: Callable[[dict[str, float | str]], None] | None = None,
) -> pd.DataFrame:
    rows = []
    normalized_tank_types = normalize_tank_types(tank_types)
    total = len(normalized_tank_types) * len(tank_size_list)
    current = 0
    for tank_type in normalized_tank_types:
        current_loss = tank_loss_percent_per_day(
            tank_type=tank_type,
            short_term_loss_percent_per_day=short_term_loss_percent_per_day,
            seasonal_loss_percent_per_day=seasonal_loss_percent_per_day,
        )
        for tank_size in tank_size_list:
            current += 1
            if progress_callback is not None:
                progress_callback(
                    {
                        "current": current,
                        "total": total,
                        "tank_type": tank_type,
                        "collector_area_m2": collector_area_m2,
                        "tank_volume_m3": tank_size,
                    }
                )
            summary, _ = simulate_design(
                weather_load_df=weather_load_df,
                collector_area_m2=collector_area_m2,
                tank_volume_m3=tank_size,
                tank_type=tank_type,
                tank_min_temp=tank_min_temp,
                tank_max_temp=tank_max_temp,
                initial_tank_temp=initial_tank_temp,
                heating_supply_temp=heating_supply_temp,
                heating_delta_t=heating_delta_t,
                solar_collector_delta_t=solar_collector_delta_t,
                tank_thermal_loss_percent_per_day=current_loss,
                auxiliary_system=auxiliary_system,
                auxiliary_efficiency=auxiliary_efficiency,
                timestep_hours=timestep_hours,
                eta0=eta0,
                a1=a1,
                a2=a2,
                collector_cost_per_m2=collector_cost_per_m2,
                short_term_cost_coeff=short_term_cost_coeff,
                short_term_cost_exponent=short_term_cost_exponent,
                seasonal_cost_coeff=seasonal_cost_coeff,
                seasonal_cost_exponent=seasonal_cost_exponent,
                electricity_price=electricity_price,
                project_lifetime_years=project_lifetime_years,
            )
            rows.append(summary)
    return pd.DataFrame(rows).sort_values(["tank_type", "tank_volume_m3"]).reset_index(drop=True)


def best_design(summary_df: pd.DataFrame, objective: str = "cost") -> pd.Series:
    if objective == "cost":
        sort_columns = ["annualized_total_cost", "solar_coverage_pct", "collector_area_m2", "tank_volume_m3"]
        ascending = [True, False, True, True]
    else:
        sort_columns = ["auxiliary_heating_delivered_kwh", "solar_coverage_pct", "collector_area_m2", "tank_volume_m3"]
        ascending = [True, False, True, True]
    return summary_df.sort_values(by=sort_columns, ascending=ascending).iloc[0]
