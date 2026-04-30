# 太阳能加热模型描述（Solar Heating Model Description）

本文说明当前在以下文件中使用的计算模型：

- `thermal_storage_core.py`
- `thermal_storage_gui.py`
- `thermal_storage_sizing.py`

本文旨在描述代码当前的实际运行行为。

## 1. 模型范围

该工具比较三种系统概念：

1. `short_term`（短期储热）
2. `seasonal_boiler`（季节性锅炉储热）
3. `seasonal_hp`（季节性热泵储热）

在实际层面上：

- `short_term` = 短期储热直接加热并辅以电辅助
- `seasonal_boiler` = 长期储热直接加热，辅以锅炉/电备份
- `seasonal_hp` = 长期储热直接加热，再加上可提升低温罐体能量的水源热泵

该模型为逐小时仿真，采用简化的集热器(collector)、储能、控制和成本逻辑。它旨在用于对比设计研究，而非最终的详细工程设计。

## 2. 输入数据模型

仿真使用按小时的数据：

- `timestamp`
- `solar_rad`
- `outside_temp`
- `heating_load`

代码将输入在需要处转换为按小时的 `kWh` 值，并逐时间步执行系统逻辑。

## 3. 太阳能集热器模型

集热器的可用热量通过标准效率方程计算：

```text
eta = eta0 - a1 * (Tm - Ta) / G - a2 * (Tm - Ta)^2 / G
Qsolar = Area * SolarRadiation * eta
```

其中：

- `eta0` = 光学效率(optical efficiency)
- `a1`, `a2` = 热损失系数(heat loss coefficients)
- `Tm` = 集热液体平均温度(mean collector fluid temperature)
- `Ta` = 室外温度(outdoor temperature)
- `G` = 辐照度(irradiance)

结果受以下限制：

- 最小效率 `0`
- 最大效率 `0.85`

随后应用污垢折扣：

```text
eta_effective = eta * collector_soiling_factor
```

示例：

- `1.00` = 清洁的集热器
- `0.95` = 输出折扣5%
- `0.90` = 输出折扣10%

## 4. 集热器入口温度逻辑

当前的集热器入口温度策略如下：

### 短期储热

- 集热器入口温度 = 平均罐内温度(average tank temperature)
- 当集热器出口温度达到供热温度时，可直接对负载加热
- 否则可用的集热热量首先进入储罐

### 长期储热

- 如果 `heating_load > 0`：集热器入口温度 = `max(bottom tank temperature, heating return temperature)`
- 如果 `heating_load = 0`：集热器入口温度 = `bottom tank temperature`

在代码逻辑中表示为：

```text
if tank_type == short_term:
    collector_inlet = tank_mean_temp
elif heating_load > 0:
    collector_inlet = max(tank_bottom_temp, heating_supply_temp - heating_delta_t)
else:
    collector_inlet = tank_bottom_temp
```

随后对入口温度进行截断，确保不低于 `tank_min_temp`。

然后：

```text
collector outlet temperature = inlet temperature + actual_collector_delta_t
collector mean fluid temperature = (inlet + outlet) / 2
```

目前的模型不再假设一个固定的集热器温差 `deltaT`。

相反地，它通过以下公式计算动态的集热温升：

```text
Q = m_dot * Cp * deltaT
deltaT = Q / (m_dot * Cp)
```

其中：

- `Q` = 有用的集热器功率(useful collector power)
- `m_dot` = 集热回路质量流量(collector loop mass flow rate)
- `Cp` = 水的热容量(water heat capacity)

代码使用：

- `Nominal Solar Collector Delta T` 作为初始猜测
- `Collector Flow (L/h/m2)` 将面积转化为回路流量
- `Collector Delta T Min`
- `Collector Delta T Max`

然后进行若干次迭代：

1. 猜测 `deltaT`
2. 计算集热器平均温度
3. 计算有用的太阳热
4. 根据 `Q = mCpΔT` 更新 `deltaT`
5. 将结果裁剪至配置的最小值和最大值

该平均温度随后用于集热效率方程中。

实际含义：

- 短期储热罐：集热器使用平均罐体温度，当集热器出口温度足够热时可直接用于加热
- 长期储热罐在主动加热时：集热器使用罐底温度和供热回水温度中的较高者
- 长期储热罐仅在储热充电时：集热器使用罐体的较冷底部

这是当前模型中最重要的控制假设之一，因为它直接影响集热器效率以及还能存储多少太阳热能。

## 5. 直接太阳加热逻辑

只有在以下条件满足时才允许直接太阳加热：

1. 集热器已启用
2. 有用的采集太阳热为正值
3. `collector outlet temperature >= heating supply temperature`
4. `heating_load > 0`

如果直接模式被启用：

```text
direct_solar_to_load = min(solar_collected, heating_load)
```

如果直接模式未启用：

- 直接用于负载的太阳热为 `0`
- 已采集的太阳热被视为用于罐充电的可用量

当前的实际含义：

- `short_term`：当热量足够热时优先直接加热，否则先充储
- `seasonal_boiler`：直接加热优先，然后把剩余部分用于罐充
- `seasonal_hp`：直接加热优先，然后把剩余部分用于罐充

## 6. 过剩太阳热逻辑

直接太阳加热后：

```text
surplus_solar = max(solar_collected - direct_solar_to_load, 0)
```

模型随后尝试用该过剩量对罐进行充电。

不能存储的剩余太阳热将变为：

```text
solar_energy_curtailed_kwh
```

## 7. 分层罐模型

罐体被建模为分层节点罐(stratified node tank)：

- 短期储热罐：8 个温度节点
- 长期储热罐：12 个温度节点

对于每一个时间步，代码跟踪：

- 罐体的平均温度(average tank temperature)
- 罐顶温度(top tank temperature)
- 罐底温度(bottom tank temperature)
- 储存罐能量(stored tank energy)

### 顶部、平均值与底部的含义

节点温度始终保持降序：

```text
top node >= middle nodes >= bottom node
```

因此：

- `top tank temperature` = 最高温节点
- `mean tank temperature` = 所有节点的算术平均值
- `bottom tank temperature` = 最低温节点

### 罐体几何

罐体几何基于：

- `tank volume`
- `tank height`

据此模型计算：

- 罐径(tank diameter)
- `H/D` 比
- 分层效率(stratification efficiency)

### 理想分层

如果：

- passive mixing = `0`
- charge mixing = `0`
- discharge mixing = `0`

则模型把罐体视为理想分层，并强制：

```text
stratification_efficiency = 1.0
```

## 8. 罐充电模型

罐体通过太阳能过剩充电。

充电能量应用于罐中的各层，直到达到：

```text
source_temp = collector outlet temperature
```

充电过程仅在层低于源温时才进行加热。

因此，如果顶层已经比集热器源温高，该层将不再被加热。

## 8A. 各层温度的计算方式

模型并非先计算一个统一的罐温度再分层，而是直接逐层更新每个节点。

在每个时间步的开始：

1. 读取当前节点温度
2. 计算：
   - 顶部温度
   - 平均温度
   - 底部温度
3. 确定太阳能收集量和控制模式
4. 按以下顺序更新罐层：
   - 充电(charging)
   - 直接放电(direct discharge)
   - 若适用，热泵源放电(heat-pump source discharge)
   - 损失(heat loss)
   - 被动混合(passive mixing)
5. 再次从热到冷对节点排序

### 层能量标度

每个节点有一个温度到能量的换算系数：

```text
kWh per K per node = tank_volume * rho_water * cp_water / 3.6e6 / number_of_nodes
```

因此，每提升 1°C 的单个节点，其对应的能量值是一个固定的 kWh。

### 充电步骤

对每个节点，从上到下：

```text
target_temp = min(tank_max_temp, source_temp)
capacity_kwh = (target_temp - node_temp) * kWh_per_K_per_node
applied_kwh = min(remaining_charge_kwh, capacity_kwh)
new_node_temp = old_node_temp + applied_kwh / kWh_per_K_per_node
```

重要行为：

- 如果某节点已经高于集热源温度，则跳过该节点
- 模型按节点顺序进行，直到充能用完
- 充完后重新从热到冷排序

### 直接放电步骤

现在所有情景均使用 withdraw-to-return 的直接放电模型并在底部回注(bottom reinjection)。

规则为：

- 只有当 `layer_temp > heating_supply_temp` 时，某层才能直接用于加热
- 该层的有用热量基于将其冷却至 `heating_return_temp`
- 冷却后的回水被回注到罐底

简化的节点模型实现为：

```text
available_useful_kwh = (layer_temp - return_temp) * kWh_per_K_per_node
used_kwh = min(remaining_load_kwh, available_useful_kwh)
circulation_fraction = used_kwh / available_useful_kwh
bottom_new = bottom_old + circulation_fraction * (return_temp - bottom_old)
top_energy_removed = used_kwh + bottom_energy_change
top_new = top_old - top_energy_removed / kWh_per_K_per_node
```

这是一种近似但能量一致的表示方式，用于描述：

- 来自顶部的热水提取
- 热量向负载的传递
- 底部回注的较冷回水

因此，在所有直接加热情形中，罐体可以被有效地冷却向回注温度，而不仅仅是向供热温度。

## 9A. 存储质量诊断

该模型现在还跟踪整个仿真过程中的平均存储能量质量：

- 高于供应温度的能量
- 在回水与供应温度之间的能量
- 低于回温的能量

这些以两种方式报告：

- 平均 `kWh`
- 平均存储罐能量的百分比

它们有助于对比大小罐之间的一致性：

- 存储能量中高于供应温度的部分越多，直热能力越强
- 在回水与供应温度之间的能量越多，直接加热部分的信用越高
- 低于回温的能量越多，主要是低等级存储

### 热泵源回注步骤

对于 `seasonal_hp`，罐也可以提供较低等级的源能量。

对每个节点：

```text
upper_temp = min(node_temp, max_source_temp)
lower_temp = min_source_temp
available_kwh = (upper_temp - lower_temp) * kWh_per_K_per_node
used_kwh = min(remaining_hp_source_need_kwh, available_kwh)
new_node_temp = old_node_temp - used_kwh / kWh_per_K_per_node
```

这使得热泵模型能够从罐层抽取热量，即使这些层的温度低于供热温度。

### 损失步骤

对每个节点按相对于 `tank_min_temp` 的比例进行损失：

```text
new_node_temp = tank_min_temp + (old_node_temp - tank_min_temp) * step_retention
```

因此温度更高的节点会经历更大的绝对温降。

### 混合步骤

混合被建模为与相邻节点的扩散式交换。

对于中间节点：

```text
new_T[i] = old_T[i] + coeff * (old_T[i-1] - 2*old_T[i] + old_T[i+1])
```

对于顶部和底部节点，模型将它们向各自的单一邻节点混合。

然后再次从热到冷对所有节点排序。

### 为什么罐温度可能快速下降

当：

- 顶部的热点层被放电以满足负载
- 剩余能量以较低温度的层存储
- 每个时间步都会应用热损失
- 直接罐加热仅计入高于供应温度的能量

因此，罐体的顶部或平均温度可能快速下降，但罐中仍可能包含大量能量。

## 9. 罐放电模型

### 直接从罐中加热

对于所有情景，只有当某一层温度达到或高于 heating supply temperature 时，才能直接向负载供热：

```text
threshold = heating_supply_temp
```

一旦某层变得符合条件，直接加热模型可以将该循环水冷却向回注温度，因为回水被回注到罐底。

因此，低于供应温度的热量不被计入直接可用的直接加热模型中。

### 热泵源使用

在 `seasonal_hp` 情景中，罐还可以为热泵提供较低等级的热源。

热泵源可从罐能量中提取，范围为：

- `tank_min_temp`
- 与 `tank_max_temp` 和 `heating_supply_temp` 的最小值之间的上限

这也是为什么热泵场景可以使用低于直接加热所需温度但高于热泵源最小温度的存储热量。

## 10. 罐混合模型

模型包含三项非理想混合系数：

- 被动混合(Passive Mixing)
- 充电混合(Charge Mixing)
- 放电混合(Draw Mixing)

这些系数以层间扩散的方式应用：

- 停机/损失后进行被动混合
- 充电后进行充电混合
- 放电后进行放电混合

这使得模型能够表示在实际运行中并非完全分层的罐体。

## 11. 罐热损失模型

罐损失以每日百分比(% per day)表示。

代码将其转换为一个时间步的保留因子：

```text
daily_retention = 1 - loss_percent_per_day / 100
step_retention = daily_retention ^ (timestep_hours / 24)
loss = stored_energy * (1 - step_retention)
```

损失在每一个时间步中应用。

## 12. 辅助加热模型

在直接太阳热和罐放电后：

- 剩余负载通过辅助能源(auxiliary energy)来满足

### 短期与季节性锅炉

剩余负载直接由辅助系统以 `auxiliary_efficiency` 来覆盖。

### 季节性热泵

热泵可以先使用较低温度的罐能量。

固定 COP 情况下：

```text
hp_deliverable_factor = COP / (COP - 1)
hp_source_needed = remaining_load / hp_deliverable_factor
```

如果罐中有来源能量可用：

```text
hp_delivered_heat = hp_source_heat * hp_deliverable_factor
hp_power_input = hp_delivered_heat / COP
```

该模型将压缩机用电量记为：

- `auxiliary_energy_for_hp_boost_kwh`

其余负载由备用辅助输入来覆盖。

## 13. 季节迭代模型

对于长期储存，单个日历年可能不够，因为罐体能跨年储存能量。

因此该模型可以对季节情景进行最多 `3` 年的迭代。

若起始/结束时罐能量差异位于收敛公差以内则提前结束。

这将给出：

- `seasonal_years_used`
- `seasonal_converged`

## 14. 成本模型

年化总成本(annualized total cost)为：

```text
annualized_total_cost = annualized_capital_cost + annual_auxiliary_energy_cost
```

其中：

- 集热器资本成本(collector capital) = `collector_area * collector_cost_per_m2`
- 罐资本成本(tank capital) = 以罐体体积为自变量的幂律成本函数
- 年化资本成本(annualized capital) = 总资本 / 项目寿命
- 年化能源成本(annual energy cost) = 辅助能源投入 * 电价

优化因此基于成本，而不仅仅是太阳能份额。

## 15. 优化模型

代码支持三种研究风格：

### 全网格(Full Grid)

变量：

- 集热面积(collector area)
- 罐体体积(tank volume)

这是最完整的优化路径。

### 第1步：集热面积研究

在固定比率的同时改变集热面积，罐体体积与之相关：

```text
tank volume = collector area * tank ratio
```

### 第2步：罐体积研究

固定集热面积，改变罐体体积。

### 选择逻辑

代码支持：

- 严格最小成本
- 紧凑的接近最优选择

近似最优选择使用：

- 成本容忍带(cost tolerance band)
- 可选的最小太阳覆盖

然后偏好：

1. 更小的罐体
2. 更小的集热面积

## 16. 长期储热与带热泵的长期储热之间的区别

这是当前代码中最重要的概念性差异。

### 带锅炉的长期储热（`seasonal_boiler`）

只有当罐层足够热以达到供热温度时，罐才能直接帮助负载。

这意味着：

- 高于 `heating_supply_temp` 的热量有用
- 低于 `heating_supply_temp` 的热量对直接加热没有直接用处

当季节性罐能够维持大量高温储存时，此选项效果最好。

### 带热泵的长期储热（`seasonal_hp`）

罐体可以通过两种方式提供帮助：

1. 来自高于供热温度的热罐层的直接加热
2. 使用较低温度罐能量的热泵来源

这意味着低等级的储存热量仍然有价值。

当罐中经常包含低于供应温度但高于热泵源最低温度的有用能量时，此选项效果最佳。

## 17. 示例：锅炉 vs 热泵

设定如下：

- 供热温度(heating supply temperature) = 45°C
- 回热温度(heating return temperature) = 35°C
- 长期罐温度分布：
  - 顶部 = 50°C
  - 平均 = 40°C
  - 底部 = 30°C

### 情景A：带锅炉的长期储热

锅炉式直接罐模型只能使用高于 45°C 的罐能量。

因此：

- 最高温层可直接帮助
- 罐中从 30°C 到 44°C 的大量能量不直接计入供热能量

结果：

- 直接罐体收益有限
- 需要更多的辅助加热

### 情景B：带热泵的长期储热

热泵情景可以：

- 直接使用来自高温上层的热量，与锅炉情景相同
- 还可将 30°C 至 44°C 的罐能量作为热泵的热源使用

结果：

- 罐中更多储存的能量变得有用
- 可以降低辅助能源需求
- 储存中的总可用太阳能量提高

### 哪个选项更好？

在代码中，当满足以下条件时，`seasonal_hp` 通常更好：

- 罐大部分时间温度低于供应温度
- 以中温热量存储的能量较大
- 热泵的 COP 较有利

如果要保持系统简单，则 `seasonal_boiler` 在以下情况下可能更好：

- 罐经常足够热以直接加热
- 热泵运行的电力成本较高
- 你希望一个更简单的系统
- 增加的热泵收益不足以抵消额外的复杂性

## 18. 实际解释

### 选择带锅炉的长期储热时的情形：

- 供热系统需要相对较高的供应温度
- 罐能保持足够高的温度以直接使用
- 追求简化
- 希望减少移动部件

### 选择带热泵的长期储热时的情形：

- 罐中有很大一部分能量低于供应温度
- 希望回收更多低等级的季节性储存能量
- 低温太阳充电仍有价值
- 电价/ COP 的假设支持热泵

## 19. 重要的简化项

当前模型有一定简化，虽有用但不是完全精确。

重要的简化包括：

- 固定的热泵 COP
- 无详细的泵或水力控制模型
- 无显式的质量流量集热器模型
- 无显式的换热器压降/pinch 计算
- 直接罐加热需要供应温度阈值
- 无家庭热水(DHW)子模型
- 无对过剩太阳能的出口或二次利用

这些简化适用于概念对比，但对最终的工程决策确有影响。

## 20. 建议用途

将当前工具用于：

- 概念对比
- 规模趋势分析
- 成本权衡筛选
- 对比短期、季节性锅炉和季节性热泵三种概念

不要仅以此作为以下依据：

- 最终设备选型
- 详细控制设计
- 最终水力设计
- 确保性能合同

## 21. 结果阅读建议

在比较情景时，请把以下内容一并审阅：

- 太阳能加热比(solar heating ratio)
- 年化总成本(annualized total cost)
- 集热器效率(collector efficiency)
- 罐充电/放电/损失(tank charge/discharge/loss)
- 太阳能受限量(solar curtailed energy)
- 热泵功率输入(heat pump power input)
- 最终罐温度(final tank temperatures)

对长期系统，还应检查：

- 是否达到季节性收敛(seasonal convergence)
- 罐能量是否仍主要高于或低于供应温度
