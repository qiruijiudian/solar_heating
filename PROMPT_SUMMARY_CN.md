# 项目摘要

## 项目

本项目使用逐小时天气和供热负荷输入来对带有水箱存储的太阳能热系统进行建模与优化。

它支持：

- 短期储热(short-term storage)
- 使用电锅炉的长期季节性储热(long-term seasonal storage with electric boilers)
- 使用热泵的长期季节性储热(long-term seasonal storage with heat pump)

主要目标是确定尺寸：

- 太阳能集热器面积(solar collector area)，单位 `m2`
- 水箱容积(tank volume)，单位 `m3`

默认优化目标为最小化年化总成本(minimum `annualized_total_cost`)。

## 主要文件

- `thermal_storage_core.py`：核心仿真、储存模型、优化、成本逻辑
- `thermal_storage_gui.py`：Panel 面板仪表板与绘图用户界面
- `thermal_storage_sizing.py`：CLI 入口点
- `OPTIMIZATION_GUIDE.md`：项目说明与工作流笔记

## 输入

默认逐小时文件：

- `01 input files/weather and heating load data.xlsx`

保存的 GUI 默认值：

- `design_inputs.xlsx`

期望的逐小时列包含别名：

- `timestamp`
- `outside_temp`
- `solar_rad`
- `horizontal_solar_rad`
- `heating_load`

重要的内部假设：

- `solar_rad` 是用于集热器模型的集热平面上的太阳辐射(collector-plane solar radiation)
- `horizontal_solar_rad` 是可选的，用于分析/报告
- 如果未提供时间戳，默认为从 `2025-01-01 00:00:00` 开始的逐小时数据
- 辐射与负荷单位统一为基于 `kWh` 的逐小时值

## 核心模型规则

集热器模型(collector model)：

- 使用 `eta0`、`a1`、`a2` 的二次效率形式(quadratic efficiency form)
- 集热器效率在 `0.0` 与 `0.85` 之间截断

水箱模型(tank model)：

- 分层多段水箱(stratified multi-layer water tank)
- 短期储热执行单年的模拟
- 季节性储热可以重复同一年，最多可达 3 年，直到收敛

每小时的供热调度顺序(heating dispatch order)：

1. 将直接来自太阳能集热器的热量供给负载
2. 若水箱层温度足够高，直接从水箱放空到负载
3. 若有 `water_heat_pump`，从低温水箱能量提升为热泵(heat pump upgrade)
4. 其余未满足的负载由辅助加热(auxiliary heating)提供

热泵源规则(heat pump source rule)：

- 热泵使用水箱能量直至 `tank_min_temp`
- 对于长期热泵研究，由 GUI 输入 `Large Delta-T Tank Min Temp (C)` 触发

优化排序(optimization ranking)：

- 最优设计通过 `annualized_total_cost` 进行选择
- 平局时优先选择更高的 `solar_coverage_pct`，然后更小的集热面积，再者为更小的水箱尺寸

成本模型(cost model)：

- 年化资本成本(annualized capital cost) = `(collector_capital + tank_capital) / project_lifetime_years`
- 年化辅助能源成本(annual auxiliary energy cost) = `auxiliary_energy_input_kwh * electricity_price`
- 年化总成本(annualized total cost) = 年化资本成本 + 年化辅助能源成本

## 当前 GUI 行为

GUI 有以下标签页：

- Design Inputs - 设计输入
- Input Analysis Results - 输入分析结果
- Short-Term Storage - 短期储热
- Long-Term Storage With Electric Boilers - 带电锅炉的长期储热
- Long-Term Storage With Heat Pump - 带热泵的长期储热

重要的当前 UI 细节：

- 主要仪表板背景为白色
- 按小时的天气/负荷输入分为 3 个绘图：
  - 外界温度(outside temperature)
  - 供热负荷(heating load)
  - 太阳辐射(solar radiation)
- 成本热图(cost heatmap)以绿色表示低成本、以红色表示高成本
- 两张热图都较宽并包含等高线(contour lines)
- 步骤 2 使用来自候选列表的可选集热面积(collector-area)下拉框
- 步骤 2 会从步骤 2 自动填充区域，步骤 3 的面积和水箱尺寸仍可编辑
- 步骤 3 仅在用户点击 `Run Step 3 Final Results` 时运行
- 步骤 3 将 `Run Step 3 Final Results` 与 `Export Excel Report` 放在输入项下方
- `Export Excel Report` 是一个普通按钮，将报告保存至 `02 reports/`
- 步骤 3 摘要包含太阳能集热器效率(solar collector efficiency)
- 可见的完整设计表(Full Design Table)区域已从 GUI 中移除
- 月度汇总表显示全部行，不分页也不内嵌滚动
- 候选尺寸输入分组为 `Short-Term Storage` 与 `Long-Term Storage`

## 候选尺寸行为

对于 GUI 中的 `Auto Generate` 模式：

- 候选集热面积与水箱尺寸由最小/最大/数量输入生成
- 生成的值采用工程舍入方式向上取整(engineering-style rounding)

对于 `Upload Excel` 模式：

- 上传的集热面积与水箱数值按提供的值使用

## 报告与输出

GUI 可在步骤 3 最终结果可用后导出 Excel 报告。

报告写入至：

- `02 reports/`

Excel 报表工作表目前包括：

- `project_inputs`
- `final_summary`
- `step1_results`
- `step2_results`
- `optimization_grid`
- `monthly_summary`
- `hourly_results`
- `input_monthly_data`

Excel 报表格式已改进：

- 样式化的标题行(styled header rows)
- 顶行冻结(frozen top row)
- 自动筛选(auto filters)
- 调整列宽(adjusted column widths)
- 日期与数值列格式化
- 边框/对齐更加整洁，隐藏网格线

步骤 3 摘要显示的度量指标包括：

- 集热面积(collector area)
- 水箱容积(tank volume)
- 总供热负荷(total heating load)
- 太阳能集热器效率(solar collector efficiency)
- 太阳能直接热(solar direct heat)
- 通过热泵的太阳能热(solar heat via heat pump)
- 可用太阳能热(usable solar heat)
- 交付的太阳能供热(solar heating delivered)
- 太阳能利用率(solar energy use ratio)
- 太阳能加热比(solar heating ratio)
- 辅助加热供给量(auxiliary heating delivered)
- 辅助能源输入(auxiliary energy input)
- 热泵功率输入(heat pump power input)
- 年化总成本(annualized total cost)
- 水箱最终温度(final tank temperature)

## 未来工作时的有用提示上下文

在处理本项目时，请假设：

- 用户通常希望直接的代码变更，而非仅分析
- GUI 变更应保留现有的 Panel/hvPlot 结构
- 步骤 2 与步骤 3 明确解耦：
  - 步骤 2 的变更更新水箱研究图并自动填充步骤 3 区域
  - 步骤 3 的仿真不得在数值修改后自动重新运行
- 避免在无关文件中回滚用户编辑
- 使用 `apply_patch` 进行文件编辑
- 修改后通过 `python3 -m py_compile thermal_storage_gui.py` 或相关文件来验证 Python 语法

## 示例复用提示

使用此项目上下文：

本代码库是一个带 Panel GUI 的太阳能热储存尺寸工具。主要文件为 `thermal_storage_core.py`、`thermal_storage_gui.py` 和 `thermal_storage_sizing.py`。该工具对逐小时的太阳能集热、分层水箱储存、辅助加热以及可选的低温水箱能源热泵升级进行仿真。GUI 支持短期储热、带有电锅炉的长期储热，以及带热泵的长期储热。请仔细保留当前工作流程：步骤 2 使用可选的候选集热面积，步骤 3 使用可编辑的最终面积/水箱输入，只有在点击按钮时才进行计算，Excel 导出将报告保存到 `02 reports`，且热图/绘图视图是决策流程的一部分。
