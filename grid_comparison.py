# -*- coding: utf-8 -*-
"""综合网格对比：不同集热面积 x 水池容积（复刻 20:51 报告的运行条件）"""
import sys, time
import pandas as pd
from thermal_storage_core import load_input, run_design_grid, near_optimal_designs

INPUT = "01 input files/weather and heating load data.xlsx"

areas = [20300.0, 24000.0, 27900.0, 32000.0]
vols = [10000.0, 14200.0, 18400.0, 22200.0, 26300.0, 30400.0, 34300.0]

df = load_input(INPUT)

def progress(info):
    if "current" in info and "total" in info:
        print(f"[{info['current']:.0f}/{info['total']:.0f}]", flush=True)

t0 = time.time()
grid = run_design_grid(
    df,
    collector_area_list=areas,
    tank_size_list=vols,
    tank_types=["seasonal"],
    tank_min_temp=35.0,
    tank_max_temp=80.0,
    initial_tank_temp=35.0,
    heating_supply_temp=45.0,
    heating_delta_t=10.0,
    solar_collector_delta_t=20.0,
    collector_flow_lph_per_m2=25.0,
    collector_delta_t_min_c=2.0,
    collector_delta_t_max_c=20.0,
    direct_solar_delivery_margin_c=1.0,
    short_term_loss_percent_per_day=5.0,
    seasonal_loss_percent_per_day=0.1,
    auxiliary_system="boiler",
    auxiliary_efficiency=0.98,
    backup_auxiliary_efficiency=0.98,
    eta0=0.65,
    a1=1.5,
    a2=0.005,
    collector_soiling_factor=0.95,
    collector_cost_per_m2=1650.0,
    seasonal_tank_height_m=10.0,
    seasonal_static_mixing_coeff=0.005,
    seasonal_charge_mixing_coeff=0.02,
    seasonal_discharge_mixing_coeff=0.018,
    electricity_price=0.49,
    project_lifetime_years=20.0,
    progress_callback=progress,
)
print(f"grid done in {time.time()-t0:.0f}s, {len(grid)} rows", flush=True)

cols = ["collector_area_m2", "tank_volume_m3", "solar_coverage_pct",
        "annualized_total_cost", "solar_energy_curtailed_kwh",
        "tank_capital_cost", "collector_capital_cost", "annual_auxiliary_energy_cost"]
grid = grid[cols].copy()
grid.to_excel("02 reports/测试clzk/grid_comparison.xlsx", index=False)

print("\n===== 全部工况按年化总成本排序 =====")
print(grid.sort_values("annualized_total_cost").to_string(index=False, float_format=lambda v: f"{v:,.1f}"))

piv_cost = grid.pivot(index="tank_volume_m3", columns="collector_area_m2", values="annualized_total_cost")
piv_cov = grid.pivot(index="tank_volume_m3", columns="collector_area_m2", values="solar_coverage_pct")
print("\n===== 年化总成本矩阵（行=水池容积, 列=集热面积） =====")
print(piv_cost.to_string(float_format=lambda v: f"{v:,.0f}"))
print("\n===== 太阳能保证率矩阵 (%) =====")
print(piv_cov.to_string(float_format=lambda v: f"{v:.1f}"))

near = near_optimal_designs(grid, objective="cost", cost_tolerance_pct=5.0, min_solar_coverage_pct=60.0)
print("\n===== 本网格内的近优集合（成本<=最小值x1.05 且 保证率>=60%） =====")
print(near[cols].sort_values("annualized_total_cost").to_string(index=False, float_format=lambda v: f"{v:,.1f}"))
print("\nsaved: 02 reports/测试clzk/grid_comparison.xlsx")
