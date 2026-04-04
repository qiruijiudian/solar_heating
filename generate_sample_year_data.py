#!/usr/bin/env python3
"""Generate a synthetic annual dataset for testing seasonal solar heating sizing."""
import csv
import math

output_file = "sample_year_data.csv"

# generate 365 daily points representing a simple temperate annual cycle
n_days = 365
rows = []
for d in range(n_days):
    day_angle = 2 * math.pi * d / n_days
    # seasonal outdoor temperature: -10 to 20 degC
    t_out = 5 + 15 * math.sin(day_angle - math.pi/2)
    # solar radiation in kWh/m2/day: low in winter, high in summer
    solar = 1.0 + 4.5 * max(0, math.sin(day_angle - math.pi/2))
    # heating load in kWh/day: high when cold
    load = 45 - 1.5 * t_out
    load = max(0.1, load)
    rows.append((round(t_out, 2), round(solar, 3), round(load, 2)))

with open(output_file, "w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["outside_temp", "solar_rad", "heating_load"])
    writer.writerows(rows)

print(f"Wrote {n_days} rows to {output_file}")
