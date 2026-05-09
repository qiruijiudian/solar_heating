# Solar Heating Model Description

This document explains the current calculation model used in:

- `thermal_storage_core.py`
- `thermal_storage_gui.py`
- `thermal_storage_sizing.py`

It is written to describe the code as it currently behaves.

## 1. Model Scope

The tool compares three system concepts:

1. `short_term`
2. `seasonal_boiler`
3. `seasonal_hp`

In practical terms:

- `short_term` = short-term storage with direct heating and electric auxiliary
- `seasonal_boiler` = long-term storage with direct heating and boiler/electric backup
- `seasonal_hp` = long-term storage with direct heating plus a water-source heat pump that can upgrade lower-temperature tank energy

The model is an hourly simulation with simplified collector, storage, control, and cost logic. It is intended for comparative design studies rather than final detailed engineering.

## 2. Input Data Model

The simulation uses hourly data:

- `timestamp`
- `solar_rad`
- `outside_temp`
- `heating_load`

The code converts the input into hourly `kWh` values where needed and runs the plant logic one timestep at a time.

## 3. Solar Collector Model

The collector useful heat is calculated with a standard efficiency equation:

```text
eta = eta0 - a1 * (Tm - Ta) / G - a2 * (Tm - Ta)^2 / G
Qsolar = Area * SolarRadiation * eta
```

Where:

- `eta0` = optical efficiency
- `a1`, `a2` = heat loss coefficients
- `Tm` = mean collector fluid temperature
- `Ta` = outdoor temperature
- `G` = irradiance

The result is limited to:

- minimum efficiency `0`
- maximum efficiency `0.85`

Then a soiling discount is applied:

```text
eta_effective = eta * collector_soiling_factor
```

Examples:

- `1.00` = clean collector
- `0.95` = 5% output discount
- `0.90` = 10% output discount

## 4. Collector Inlet Temperature Logic

The current collector inlet strategy is:

### Short-Term Storage

- collector inlet temperature = `average tank temperature`
- direct collector-to-load heating is allowed when collector outlet temperature reaches heating supply temperature
- otherwise useful collected solar heat goes to the tank first

### Long-Term Storage

- if `heating_load > 0`: collector inlet temperature = `max(bottom tank temperature, heating return temperature)`
- if `heating_load = 0`: collector inlet temperature = `bottom tank temperature`

In code logic, this means:

```text
if tank_type == short_term:
    collector_inlet = tank_mean_temp
elif heating_load > 0:
    collector_inlet = max(tank_bottom_temp, heating_supply_temp - heating_delta_t)
else:
    collector_inlet = tank_bottom_temp
```

Then the inlet is clipped so it cannot fall below `tank_min_temp`.

Then:

```text
collector outlet temperature = inlet temperature + actual_collector_delta_t
collector mean fluid temperature = (inlet + outlet) / 2
```

The current model no longer assumes a fixed collector `deltaT`.

Instead it calculates a dynamic collector temperature rise from:

```text
Q = m_dot * Cp * deltaT
deltaT = Q / (m_dot * Cp)
```

Where:

- `Q` = useful collector power
- `m_dot` = collector loop mass flow rate
- `Cp` = water heat capacity

The code uses:

- `Nominal Solar Collector Delta T` as the initial guess
- `Collector Flow (L/h/m2)` to convert area into loop flow
- `Collector Delta T Min`
- `Collector Delta T Max`

It then iterates a few times:

1. guess `deltaT`
2. calculate collector mean temperature
3. calculate useful solar heat
4. update `deltaT` from `Q = mCpΔT`
5. clip the result to the configured minimum and maximum

This mean temperature is then used in the collector efficiency equation.

Practical interpretation:

- short-term tank: collector uses the average tank temperature and can serve heating directly when collector outlet temperature is hot enough
- long-term tank during active heating: collector uses the higher of bottom-tank temperature and heating return temperature
- long-term tank during storage-only charging: collector sees the colder bottom of the tank

This is one of the most important control assumptions in the current model because it directly affects collector efficiency and how much solar heat can still be stored.

## 5. Direct Solar Heating Logic

Direct solar heating is allowed only when:

1. the collector is enabled
2. useful collected solar heat is positive
3. `collector outlet temperature >= heating supply temperature + direct solar delivery margin`
4. `heating_load > 0`

If direct mode is enabled:

```text
direct_solar_to_load = min(solar_collected, heating_load)
```

If direct mode is not enabled:

- direct solar to load = `0`
- collected solar is treated as available for tank charging

Current practical meaning:

- `short_term`: direct collector heat goes to the load first when hot enough, and tank discharge is tracked separately
- `seasonal_boiler`: direct solar first, then surplus to tank
- `seasonal_hp`: direct solar first, then surplus to tank

## 6. Surplus Solar Logic

After direct solar heating:

```text
surplus_solar = max(solar_collected - direct_solar_to_load, 0)
```

The model then tries to charge the tank with this surplus.

Any remaining solar that cannot be stored becomes:

```text
solar_energy_curtailed_kwh
```

## 7. Stratified Tank Model

The tank is modeled as a stratified node tank:

- short-term tank: `8` temperature nodes
- long-term tank: `12` temperature nodes

For each timestep, the code tracks:

- average tank temperature
- top tank temperature
- bottom tank temperature
- stored tank energy

### What Top, Mean, and Bottom Mean

The node temperatures are always kept in descending order:

```text
top node >= middle nodes >= bottom node
```

So:

- `top tank temperature` = hottest node
- `mean tank temperature` = arithmetic average of all nodes
- `bottom tank temperature` = coldest node

### Tank Geometry

Tank geometry is derived from:

- `tank volume`
- `tank height`

From this the model calculates:

- tank diameter
- `H/D` ratio
- stratification efficiency

### Ideal Stratification

If:

- passive mixing = `0`
- charge mixing = `0`
- discharge mixing = `0`

then the model treats the tank as ideal and forces:

```text
stratification_efficiency = 1.0
```

## 8. Tank Charging Model

The tank charges from solar surplus.

Charging energy is applied to the tank layers up to:

```text
source_temp = collector outlet temperature
```

The charging routine heats layers only if they are below the source temperature.

So if a top layer is already hotter than the collector source temperature, that layer will not be further heated.

## 8A. How Each Layer Temperature Is Calculated

The model does not calculate one single tank temperature first and then split it later. Instead, it updates every node directly.

At the start of each timestep:

1. read the current node temperatures
2. calculate:
   - top temperature
   - mean temperature
   - bottom temperature
3. determine solar collection and control mode
4. update the tank layers in this order:
   - charging
   - direct discharge
   - heat-pump source discharge if applicable
   - heat loss
   - passive mixing
5. sort the nodes again from hot to cold

### Layer Energy Scale

Each node has a temperature-to-energy conversion factor:

```text
kWh per K per node = tank_volume * rho_water * cp_water / 3.6e6 / number_of_nodes
```

So every `1 C` change in a node corresponds to a fixed `kWh` value for that tank.

### Charging Step

For each node, from top to bottom:

```text
target_temp = min(tank_max_temp, source_temp)
capacity_kwh = (target_temp - node_temp) * kWh_per_K_per_node
applied_kwh = min(remaining_charge_kwh, capacity_kwh)
new_node_temp = old_node_temp + applied_kwh / kWh_per_K_per_node
```

Important behavior:

- if a node is already hotter than the collector source temperature, it is skipped
- the model moves through the nodes until the charging energy is used up
- after charging, the nodes are re-sorted hot to cold

### Direct Discharge Step

All scenarios now use a withdraw-to-return direct-discharge model with bottom reinjection.

The rule is:

- a layer can directly serve heating only if `layer_temp > heating_supply_temp`
- the useful heat from that layer is based on cooling it toward `heating_return_temp`
- the cooled return water is reinjected into the bottom layer

The simplified node model does:

```text
available_useful_kwh = (layer_temp - return_temp) * kWh_per_K_per_node
used_kwh = min(remaining_load_kwh, available_useful_kwh)
circulation_fraction = used_kwh / available_useful_kwh
bottom_new = bottom_old + circulation_fraction * (return_temp - bottom_old)
top_energy_removed = used_kwh + bottom_energy_change
top_new = top_old - top_energy_removed / kWh_per_K_per_node
```

This is an approximate but energy-consistent way to represent:

- hot water withdrawal from the top
- heat delivery to the load
- cooler return water reinjection into the bottom of the tank

So for all direct-heating cases, the tank can effectively be cooled toward return temperature, not just supply temperature.

## 9A. Storage Quality Diagnostics

The model now also tracks average stored-energy quality over the simulation:

- energy above supply temperature
- energy between return and supply temperature
- energy below return temperature

These are reported both as:

- average `kWh`
- percentage of average stored tank energy

They are useful for comparing small and large tanks consistently:

- a tank with more energy above supply is strong for direct heating
- a tank with more energy between return and supply is strong for partial direct-heating credit
- a tank with more energy below return is mainly low-grade storage

### Heat Pump Source Discharge Step

For `seasonal_hp`, the tank can also provide lower-grade source energy.

For each node:

```text
upper_temp = min(node_temp, max_source_temp)
lower_temp = min_source_temp
available_kwh = (upper_temp - lower_temp) * kWh_per_K_per_node
used_kwh = min(remaining_hp_source_need_kwh, available_kwh)
new_node_temp = old_node_temp - used_kwh / kWh_per_K_per_node
```

This allows the HP model to extract heat from tank layers even when those layers are below heating supply temperature.

### Heat Loss Step

Loss is applied to every node relative to `tank_min_temp`:

```text
new_node_temp = tank_min_temp + (old_node_temp - tank_min_temp) * step_retention
```

So hotter nodes lose more absolute temperature than colder nodes.

### Mixing Step

Mixing is modeled as a diffusion-like exchange with neighboring nodes.

For a middle node:

```text
new_T[i] = old_T[i] + coeff * (old_T[i-1] - 2*old_T[i] + old_T[i+1])
```

For the top and bottom nodes, the model mixes them toward their single neighbor.

Then all nodes are sorted again from hottest to coldest.

### Why Tank Temperature Can Drop Quickly

The top or mean tank temperature can fall quickly when:

- the hot upper layers are discharged to meet load
- the remaining energy is stored at lower temperature layers
- heat loss is applied every timestep
- direct tank heating only counts energy above supply temperature

So a tank can still contain a large amount of energy while its top or mean temperature falls rapidly.

## 9. Tank Discharge Model

### Direct Heating from Tank

For all scenarios, a layer must be at or above the heating supply temperature to begin direct delivery to the load:

```text
threshold = heating_supply_temp
```

Once a layer is eligible, the direct-heating model can cool that circulated water toward return temperature because the return water is reinjected to the tank bottom.

So heat below the supply temperature is not counted as directly usable in the direct-heating model.

### Heat Pump Source Use

In the `seasonal_hp` scenario, the tank can also supply lower-grade heat to the heat pump.

The HP source can draw from tank energy between:

- `tank_min_temp`
- `min(heating_supply_temp, tank_max_temp)`

This is why the HP scenario can use storage heat that is too cold for direct heating.

## 10. Tank Mixing Model

The model includes three non-ideal mixing coefficients:

- `Passive Mixing`
- `Charge Mixing`
- `Draw Mixing`

These are applied as inter-layer diffusion:

- passive mixing after standby/loss
- charge mixing after charging
- draw mixing after discharge

This allows the model to represent tanks that are not perfectly stratified in real operation.

## 11. Tank Heat Loss Model

Tank loss is entered as `% per day`.

The code converts that into a timestep retention factor:

```text
daily_retention = 1 - loss_percent_per_day / 100
step_retention = daily_retention ^ (timestep_hours / 24)
loss = stored_energy * (1 - step_retention)
```

Losses are applied every timestep.

## 12. Auxiliary Heating Model

After direct solar and tank discharge:

- the remaining load is met by auxiliary energy

### Short-Term and Seasonal Boiler

Remaining load is covered directly by the auxiliary system using `auxiliary_efficiency`.

### Seasonal Heat Pump

The heat pump can use lower-temperature tank energy first.

With fixed COP:

```text
hp_deliverable_factor = COP / (COP - 1)
hp_source_needed = remaining_load / hp_deliverable_factor
```

If source energy is available from the tank:

```text
hp_delivered_heat = hp_source_heat * hp_deliverable_factor
hp_power_input = hp_delivered_heat / COP
```

The model stores that compressor electricity as:

- `auxiliary_energy_for_hp_boost_kwh`

Any remaining load after that is covered by backup auxiliary input.

## 13. Seasonal Iteration Model

For long-term storage, one calendar year may not be enough because the tank can carry energy across years.

So the model can iterate the seasonal case for up to `3` years.

It stops early if the start/end tank energy difference is within the convergence tolerance.

This gives:

- `seasonal_years_used`
- `seasonal_converged`

## 14. Cost Model

Annualized total cost is:

```text
annualized_total_cost = annualized_capital_cost + annual_auxiliary_energy_cost
```

Where:

- collector capital = `collector_area * collector_cost_per_m2`
- tank capital = power-law cost function of tank volume
- annualized capital = total capital / project lifetime
- annual energy cost = auxiliary energy input * electricity price

The optimization is therefore cost-based, not only solar-fraction-based.

## 15. Optimization Model

The code supports three study styles:

### Full Grid

Varies:

- collector area
- tank volume

This is the most complete optimization path.

### Step 1: Collector Area Study

Varies collector area while tying tank volume to a fixed ratio:

```text
tank volume = collector area * tank ratio
```

### Step 2: Tank Volume Study

Fixes collector area and varies tank volume.

### Selection Logic

The code supports:

- strict minimum cost
- compact near-optimal selection

Near-optimal selection uses:

- cost tolerance band
- optional minimum solar coverage

Then prefers:

1. smaller tank
2. smaller collector area

## 16. Difference Between Long-Term Storage and Long-Term Storage With Heat Pump

This is the most important conceptual difference in the current code.

### Long-Term Storage With Boiler (`seasonal_boiler`)

The tank can directly help the load only when tank layers are hot enough to meet the heating supply temperature.

That means:

- heat above `heating_supply_temp` is useful
- heat below `heating_supply_temp` is not directly useful for heating

This option works best when the seasonal tank can maintain a large amount of high-temperature storage.

### Long-Term Storage With Heat Pump (`seasonal_hp`)

The tank can help in two ways:

1. direct heating from hot tank layers above supply temperature
2. heat pump source use from lower-temperature tank energy

That means lower-grade stored heat still has value.

This option works best when the tank often contains useful energy below supply temperature but above the HP source minimum temperature.

## 17. Example: Boiler vs Heat Pump

Assume:

- heating supply temperature = `45 C`
- heating return temperature = `35 C`
- long-term tank temperatures:
  - top = `50 C`
  - mean = `40 C`
  - bottom = `30 C`

### Case A: Long-Term Storage With Boiler

The boiler-style direct tank model can only use tank energy above `45 C`.

So:

- the very hot upper layer can help directly
- the large amount of energy stored at `30 C` to `44 C` is not directly counted as heating supply energy

Result:

- direct tank benefit is limited
- more backup heating is needed

### Case B: Long-Term Storage With Heat Pump

The HP case can:

- use the hot upper layer directly, same as the boiler case
- also use the `30 C` to `44 C` tank energy as a heat source for the HP

Result:

- more of the stored tank energy becomes useful
- auxiliary energy demand can be reduced
- total useful solar energy from storage is higher

### Which Option Is Better?

In the code, `seasonal_hp` is usually better when:

- the tank often sits below supply temperature
- a lot of energy is stored as medium-temperature heat
- the HP COP is favorable

`seasonal_boiler` can still be better when:

- the tank is often hot enough for direct heating
- electricity for HP operation is expensive
- you want a simpler system
- the added HP benefit is too small to justify the extra complexity

## 18. Practical Interpretation

### Choose Long-Term Storage With Boiler When:

- the heating system needs relatively high supply temperature
- the tank can stay hot enough for direct use
- simplicity is more important
- you want fewer moving parts

### Choose Long-Term Storage With Heat Pump When:

- a large part of the tank energy is below supply temperature
- you want to recover more low-grade seasonal storage energy
- low-temperature solar charging still has value
- the electricity/COP assumptions support the HP

## 19. Important Simplifications

The current model is useful, but simplified.

Important simplifications include:

- fixed heat pump COP
- no detailed pump or hydraulic control model
- no explicit mass-flow collector model
- no explicit heat exchanger pinch calculation
- direct tank heating requires supply-temperature threshold
- no DHW sub-model
- no export or secondary use for surplus solar

These simplifications are acceptable for concept comparison, but they matter for final engineering decisions.

## 20. Recommended Use

Use the current tool for:

- concept comparison
- sizing trends
- cost tradeoff screening
- comparison between short-term, seasonal boiler, and seasonal HP concepts

Do not use it as the only basis for:

- final equipment selection
- detailed control design
- final hydraulic design
- guaranteed performance contracts

## 21. Suggested Reading of Results

When comparing scenarios, review all of these together:

- solar heating ratio
- annualized total cost
- collector efficiency
- tank charge/discharge/loss
- solar curtailed energy
- heat pump power input
- final tank temperatures

For long-term systems, also check:

- whether seasonal convergence was reached
- whether the tank energy remains mostly above or below supply temperature
