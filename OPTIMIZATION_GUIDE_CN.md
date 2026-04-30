# 太阳能供热系统优化指南

本文档解释了在本项目中如何对太阳能供热系统进行优化、每个研究步骤的含义，以及如何解读结果。

## 项目目的

该项目基于逐小时输入数据对具备热储存的太阳能供热系统进行规模设定。它比较三种固定系统情景：

- 短期储热(short-term storage)
- 带电锅炉的长期储热(long-term storage with electric boilers)
- 带热泵的长期储热(long-term storage with heat pump)

对于每种情况，工具会评估集热器面积(collector area)与水箱尺寸(tank size)，逐小时计算能量流，并基于年化成本(annualized cost)给出设计建议，单位为 `RMB`。

## 主要文件

- `thermal_storage_core.py` - 核心仿真与优化逻辑
- `thermal_storage_gui.py` - Panel + hvPlot 仪表板
- `thermal_storage_sizing.py` - CLI 入口点

## 所需输入数据

默认逐小时输入文件为：

- `01 input files/weather and heating load data.xlsx`

保存的 GUI 默认值：

- `design_inputs.xlsx`

期望列为：

- `time_step`
- `outside_air_temp(℃）`
- `horizontal_solar_rad(Wh/m2)`
- `solar_rad_55deg_surface`
- `heating_load`

内部假设：

- `time_step`：逐小时时间戳
- `outside_air_temp(℃）`: 室外温度(°C)
- `horizontal_solar_rad(Wh/m2)`: 水平面上的逐小时太阳辐射
- `solar_rad_55deg_surface`: 集热器平面上的逐小时太阳辐射
- `heating_load`: 每小时建筑供热能量

集热器计算使用 `solar_rad_55deg_surface`。

## 三个系统情景

### 1. 短期储热

用于研究日尺度或短期多日储热。

太阳能供热比(solar heating ratio)计算为：

`(direct solar heating + tank discharge for heating) / heating load`

### 2. 带电锅炉的长期储热

用于研究带有电动辅助加热的季节性储热。

太阳能供热比(solar heating ratio)计算为：

`(direct solar heating + tank discharge for heating) / heating load`

### 3. 带热泵的长期储热

用于研究低温水箱能量通过热泵升级后的季节性储热。

太阳能供热比(solar heating ratio)计算为：

`(direct solar heating + tank discharge for heating + low-temperature tank discharge used by heat pump) / heating load`

重要：

- 热泵所用的电力不计入太阳能
- 只有来自水箱的太阳能源能量才计入太阳能供热比

## 集热器模型

太阳能集热器使用标准二次效率形式：

`eta = eta0 - a1 * (Tm - Ta) / G - a2 * (Tm - Ta)^2 / G`

其中：

- `eta0`：光学效率(optical efficiency)
- `a1`：一阶热损失系数(first-order heat loss coefficient)
- `a2`：二阶热损失系数(second-order heat loss coefficient)
- `Tm`：集热液体温度估计值(collector fluid temperature estimate)
- `Ta`：户外空气温度(outdoor air temperature)
- `G`：太阳辐照度(solar irradiance)

GUI 包含一个集热类型下拉菜单，填充典型值，但用户仍可编辑 `eta0`、`a1`、`a2`。

## 水箱模型

储能水箱建模为分层多层水箱(stratified multi-layer water tank)。

模型包括：

- 从太阳能集热器的充电
- 当水箱温度足够高时的直接放热(direct discharge)
- 热泵情景中的低温源提取(low-temperature source extraction)
- 水箱热损失(tank thermal loss)
- 针对长期储热的季节性滚动，最多可重复三年

短期水箱使用单年度逐小时仿真。

长期水箱重复同一年，直到：

- 水箱状态收敛，或
- 仿真达到3年

## GUI 中的优化工作流

GUI 具有左侧控制面板和五个主要标签页：

- `Design Inputs` - 设计输入
- `Input Analysis Results` - 输入分析结果
- `Short-Term Storage` - 短期储热
- `Long-Term Storage With Electric Boilers` - 带电锅炉的长期储热
- `Long-Term Storage With Heat Pump` - 带热泵的长期储热

### 步骤 A. 分析输入数据

优先使用 `Analyze Input Data`（分析输入数据）。

这会填充 `Input Analysis Results` 选项卡并显示：

- 年度供热负荷(annual heating load)
- 供热季负荷(heating-season load)
- 年度倾斜日照辐射(annual tilted solar radiation)
- 年度水平日照辐射(annual horizontal solar radiation)
- 月度汇总表(monthly summary table)
- 每小时持续时间曲线(hourly duration curves)
- 建议的集热器面积(collector-area)与水箱尺寸(tank-size)区间

当前设计输入也会自动保存到：

- `design_inputs.xlsx`

### 建议区间的计算方式

#### 短期建议

短期建议仅使用有供热负荷的小时。

目标太阳能供热比：

- `70%` 到 `90%`

建议的集热器面积从以下估算得到：

- 供热季供热负荷
- 供热季倾斜日照辐射
- 当前 `eta0`、`a1`、`a2` 的参考集热效率

随后用以下估算水箱尺寸：

- `10` 到 `300 L/m2`

#### 长期建议

长期建议使用整年数据。

目标太阳能供热比：

- `95%` 到 `100%`

建议的集热器面积从以下估算得到：

- 年度供热负荷
- 年度倾斜日照辐射
- 当前 `eta0`、`a1`、`a2` 的参考集热效率

随后用以下估算水箱尺寸：

- `300` 到 `3000 L/m2`

这些建议仅为筛选值(screening values)，帮助为全面仿真选取候选区间。它们并非最终优化设计。

### 步骤 B. 运行研究

使用侧边栏的任意一个按钮：

- `Run Two-Step Analysis` - 运行两步分析
- `Run Cost Optimization Analysis` - 运行成本优化分析
- `Run Cost + Two-Step Analysis` - 运行成本+两步分析

对于三种固定情景中的每一种，工具执行：

1. 成本优化网格(cost optimization grid)，若被选中
2. 第1步：集热面积研究(collector-area study)
3. 第2步：在选定集热面积下的水箱尺寸研究(tank-size study)

运行期间，状态面板会显示：

- 当前情景(active scenario)
- 当前处理过程(active process)
- 完成百分比(percent complete)
- 当前集热面积(current collector area)
- 当前水箱体积(current tank volume)

### 步骤 C. 查看每个情景的结果标签页

每个情景标签页显示：

- 成本优化结果表(cost optimization result table)
- 成本热力图(cost heatmap)
- 太阳能供热比热力图(solar heating ratio heatmap)
- 第1步：太阳热比 vs 集热面积
- 第1步：集热效率 vs 集热面积
- 第2步：太阳热比 vs 水箱尺寸
- 第2步：集热效率 vs 水箱尺寸
- 第3步 最终选定结果区域(final selected result section)
- 第3步 时间序列图(time-series plots)
- 月度汇总表(monthly summary table)
- 完整设计表(full design table)

### 步骤 D. 运行最终决策情景

在查看完第1步与第2步后：

1. 选择一个集热面积
2. 选择一个水箱尺寸
3. 点击 `Run Step 3 Final Results`

这将对所选设计运行最终逐小时仿真并更新：

- 最终选定结果摘要(final selected result summary)
- 水箱温度图(tank temperature plot)
- 供热源图(heating source plot)
- 水箱充放电图(tank charge/discharge plot)
- 天气与负荷图(weather and load plot)
- 月度汇总表(monthly summary table)
- 完整设计表(full design table)

## 该工具优化的目标

优化目标为年化总成本(annualized total cost)，单位为 `RMB`。

对于每个候选设计：

- 集热面积(collector area)
- 水箱尺寸(tank size)

工具会计算：

- 集热器资本成本(collector capital cost)
- 水箱资本成本(tank capital cost)
- 年化资本成本(annualized capital cost)
- 辅助能源投入(auxiliary energy input)
- 年度辅助能源成本(annual auxiliary energy cost)
- 年化总成本(annualized total cost)

最佳设计为最低的：

- `annualized_total_cost`

平局时优先考虑：

- 更高的太阳能供热比
- 更小的集热面积
- 更小的水箱尺寸

## 关键输出定义

### 收集的太阳能(Solar Energy Collected)

经过集热器效率损失后的有用热量。

### 直接向负荷供热的太阳能(Solar Direct Collector to Load)

用于在同一小时内直接满足供热需求的太阳热量。

### 来自水箱的直接放热(Solar from Tank Direct)

水箱放热在温度足够高时直接用于供热。

### 通过水箱经热泵升级后的太阳能(Solar from Tank via Heat Pump)

经热泵升级后提供的供热量。

重要：

- 该值包含热泵的电力影响
- 对系统能量平衡有用
- 并非直接用于计算太阳能供热比

### 用于供热的太阳源能量(Solar Source Energy Used)

实际用于供热的太阳来源热量：

- 直接太阳向负荷
- 水箱直接放热
- 由热泵使用的低温水箱源能量

这是以下指标的基础：

- `solar_heating_ratio_pct`

### 太阳能供热比(Solar Heating Ratio)

当前项目的太阳分数指标：

`solar_source_energy_used_kwh / heating_load_kwh`

以百分比形式报告。

### 辅助加热已送达(Auxiliary Heating Delivered)

在太阳能与水箱贡献之后，仍由电锅炉、热泵或其他辅助系统提供的供热。

### 辅助能源输入(Auxiliary Energy Input)

辅助系统实际使用的电力或等效燃料能源。

## 读取主图

### 成本热力图(Cost Heatmap)

- X 轴：集热面积(collector area)
- Y 轴：水箱尺寸(tank size)
- 颜色：以 `RMB` 计的年化总成本
- 等值线：等成本线(equal-cost lines)

使用此图识别低成本设计区域。

### 太阳能供热比热力图(Solar Heating Ratio Heatmap)

- X 轴：集热面积
- Y 轴：水箱尺寸
- 颜色：太阳能供热比(solar heating ratio)
- 等值线：等比线(equal-ratio lines)

使用此图查看随着尺寸变化太阳能贡献如何改变。

### 太阳能供热比 vs 集热面积

这是步骤 1 的筛选图(screening plot)。

当前 GUI 显示并排的两个步骤 1 图：

- 太阳能供热比 vs 集热面积
- 集热效率 vs 集热面积

这些图显示增加集热面积是否仍然带来显著增益，以及集热器在此区间内的工作效率如何变化。

### 太阳能供热比 vs 水箱尺寸

这是步骤 2。

当前 GUI 显示并排的两个步骤 2 图：

- 太阳能供热比 vs 水箱尺寸
- 集热效率 vs 水箱尺寸

这些图显示在所选集热面积下，水箱尺寸的增加在多大程度上仍能提高太阳能贡献，以及集热器的工作效率如何随水箱尺寸变化。

### 水箱温度图(Tank Temperature Plot)

显示：

- 水箱顶部温度(top tank temperature)
- 水箱平均温度(mean tank temperature)
- 水箱底部温度(bottom tank temperature)
- 供热供给/返回参考线(heating supply / return reference lines)

### 供热负荷与能量来源图(Heating Load and Sources Plot)

逐小时显示：

- 供热负荷(heating load)
- 直接太阳供热(direct solar heating)
- 水箱直接放热(tank direct discharge)
- 水箱热泵辅助贡献(tank heat-pump-assisted contribution)
- 辅助供热(auxiliary heating)

### 水箱充放电图(Tank Charging and Discharging Plot)

逐小时显示：

- 水箱充电(tank charging)
- 水箱放电(tank discharging)
- 水箱损失(tank loss)

## 导出的 Excel 报告

Excel 导出包含每个情景的独立文件。

每个工作簿包含：

- 第 1 步结果
- 第 2 步结果
- 最终选定结果
- 优化结果
- 按小时数据
- 按月数据
- 年度汇总

## 推荐的实际工作流

1. 检查逐小时输入文件
2. 运行 `Analyze Input Data`（分析输入数据）
3. 使用建议区间设定候选的集热器区间与水箱区间
4. 选择以下任一项：
   `Run Two-Step Analysis`、`Run Cost Optimization Analysis`，或 `Run Cost + Two-Step Analysis`
5. 查看成本热力图和太阳能供热比热力图
6. 使用步骤 1 选择集热面积
7. 使用步骤 2 选择水箱尺寸
8. 运行 `Run Step 3 Final Results`
9. 导出 Excel 报告

## 月度汇总表

每个情景标签页在步骤 3 之后包含月度汇总表。

当前表包含：

- `Month` - 月份
- `Total Heating Load` - 总供热负荷
- `Average Heating Load` - 平均供热负荷
- `Usable Solar Heat` - 可用太阳热量
- `Solar Heating Energy` - 太阳能供热能量
- `Auxiliary Energy` - 辅助能源
- `Collector Efficiency` - 集热效率
- `Tank Charge` - 水箱充电
- `Tank Loss` - 水箱损失
- `Solar Heat Ratio` - 太阳能供热比

最后一行为：

- `Annual Summary` - 年度汇总

## 当前模型限制

这是一个有用的设计研究模型，但仍然简化。

主要限制：

- 归并集热器水力学(lumped collector hydraulics)
- 无详细泵功率模型
- 无分层管道/端口几何
- 简化成本模型
- 重复年度的季节性近似

该工具最适用于：

- 早期尺寸确定(early-stage sizing)
- 选项比较(option comparison)
- 灵敏度研究(sensitivity study)

而非最终的详细工程设计。
