# 太阳能供热蓄热系统设计研究工具（Solar Heating Storage Design Study）

本工具基于逐小时仿真，对"太阳能集热器 + 蓄热水池"供暖系统进行容量选型与优化：在给定的全年气象与热负荷数据下，比较三种系统方案（短期蓄热、长期蓄热+电锅炉、长期蓄热+热泵）的太阳能保证率与年化总成本，给出集热器面积与水池容积的推荐组合。

- 仿真核心：`thermal_storage_core.py`
- 图形界面（Panel + hvPlot）：`thermal_storage_gui.py`
- 命令行入口（可选）：`thermal_storage_sizing.py`
- 详细模型说明：`MODEL_DESCRIPTION.md`、`OPTIMIZATION_GUIDE.md`

> 本工具用于方案比选与容量趋势研究，不能替代详细工程设计。

---

## 一、运行环境与安装

1. 安装 **Python 3.13+**（含 pip）。
2. 在项目根目录创建虚拟环境并安装依赖：

```bash
python -m venv .venv
# Windows
.venv\Scripts\python.exe -m pip install numpy pandas openpyxl panel hvplot holoviews bokeh
# macOS / Linux
.venv/bin/python -m pip install numpy pandas openpyxl panel hvplot holoviews bokeh
```

国内网络可追加清华镜像：`-i https://pypi.tuna.tsinghua.edu.cn/simple`

3. 启动程序：

```bash
python thermal_storage_gui.py
```

4. 程序会自动打开浏览器；若没有自动打开，请看**控制台打印的 `Bokeh app running at: http://localhost:<端口>/`**，手动访问该地址。请用 `localhost` 访问，不要用 `127.0.0.1`（Bokeh 的 WebSocket 校验默认只放行 localhost）。

> 根目录的 `run_gui.bat` 借用了原作者机器上的虚拟环境绝对路径，**新下载用户请按上面步骤自建环境**，不要直接双击它。

---

## 二、准备输入数据（重要）

仿真需要一个**完整年度、逐小时**的 Excel/CSV 文件（8760 行，1 月 1 日 00:00 起）。仓库不自带样例数据（`01 input files/` 不入库），请自行准备，可放入 `01 input files/` 目录，或在界面用 **Upload Hourly Input File** 上传。

程序按列名识别数据，**三个必需列**及可接受的列名：

| 数据 | 可接受的列名（不区分大小写和特殊字符） | 单位 |
|---|---|---|
| 室外温度 | `outside_temp` / `outside_air_temp` 等 | ℃ |
| 集热面辐照（55°倾角面） | `solar_rad` / `solar_rad_55deg_surface` 等 | kWh/m²（Wh/m² 会自动换算，见下） |
| 供暖热负荷 | `heating_load`（全县城总负荷一列即可，不需要分项） | kWh |
| 时间戳（可选） | `timestamp` / `time_step` | 任意可解析时间 |

**自动单位换算规则：**
- 辐照列：列名含 `whm2`、或数值最大值 > 50（说明是 Wh/m²）→ 自动 ÷1000 转为 kWh/m²；
- 负荷列：列名以 `w` / `wh` 结尾 → 自动换算为 kWh；
- **时间列可省略**：缺省时程序自动生成"从 2025-01-01 00:00 起、每小时一行"的时间戳。数据必须从 1 月 1 日开始按顺序排列；若数据起点不是年初（如仅采暖季），必须自带时间列，否则月度统计会错位。

---

## 三、Design Inputs 参数说明（左侧 Design Inputs 页）

### 1. 项目与数据

| 参数 | 含义与用途 |
|---|---|
| Project Name | 项目名，决定导出文件名与报告目录 |
| Hourly Input File / Upload | 小时数据文件路径或直接上传 |
| Scenarios To Analyze | 勾选要分析的方案（短期 / 长期电锅炉 / 长期热泵） |

### 2. 温度与集热器运行

| 参数 | 含义与用途 |
|---|---|
| Tank Max Temp (C) | 水池蓄热上限温度，充电最高加热到此温度 |
| Small Delta-T Tank Min Temp (C) | 短期水池下限温度（热损计算基准，低于它的能量不再损失） |
| Large Delta-T Tank Min Temp (C) | 长期水池（含热泵源侧）下限温度 |
| Initial Tank Temp (C) | 仿真开始时水池初始温度 |
| Heating Supply Temp (C) | 供暖供水温度：水池某层温度 ≥ 该值才能直供供暖 |
| Heating System Delta T (C) | 供回水温差 → 回水温度 = 供水温度 − ΔT；直供时水层可被冷却到回水温度 |
| Nominal Solar Collector Delta T (C) | 集热器温升迭代初值（实际温升由 Q=mCpΔT 动态求出） |
| Collector Flow (L/h/m2) | 集热回路单位面积流量，决定动态温升幅度 |
| Collector Delta T Min / Max (C) | 集热器温升上下限幅 |
| Direct Solar Delivery Margin (C) | 集热器出口温度须超过"供水温度 + 该余量"才允许集热器直接供暖 |

### 3. 水池物理与分层

| 参数 | 含义与用途 |
|---|---|
| Short/Long-Term Tank Loss (%/day) | 水池每日热损百分比，逐小时折算扣减 |
| Short/Long-Term Tank Height (m) | 水池高度（由容积+高度推直径与 H/D 比） |
| Thermal Stratification Model | 分层预设：Ideal / Good / Average / Poor，一键填入高度与三个混合系数 |
| Passive / Charge / Draw Mixing | 静态/充电/放热三种层间混合系数；全为 0 视为理想分层（分层效率=1） |
| Short-Term / Seasonal Large Tank Ratio (L/m2) | 两步法 Step 1 的"容积=面积×比值"绑定系数（Auto Generate 两步法时使用） |

### 4. 造价（Cost Inputs）

| 参数 | 含义与用途 |
|---|---|
| Collector Cost (RMB/m2) | 集热器单价，集热器投资 = 面积 × 单价 |
| Project Lifetime (years) | 项目年限，资本年化 = 总投资 ÷ 年限（直线，无折现） |
| Electricity Price (RMB/kWh) | 电价，用于辅助能源年费用 |
| Electric Boiler Efficiency | 电锅炉效率，耗电 = 需热量 ÷ 效率 |
| Heat Pump COP | 热泵 COP（仅热泵方案用） |
| Tank Cost Asymptote / Scale / Power | 水池**单价曲线**参数（短期、长期各一组）：单价(RMB/m³) = k·(c + a·V^b)，c=Asymptote，a=Scale，b=Power |
| Tank Cost Correction Factor | 修正系数 k（短期/长期各一）：统一上浮或下调整条单价曲线（如水池类 k=1.1） |

年化总成本 = 年化资本（集热器+水池）+ 辅助能源年费用，是优化的目标函数。

### 5. 候选尺寸网格（Candidate Sizes）

| 参数 | 含义与用途 |
|---|---|
| Candidate Sizes | `Auto Generate`：按下面的区间自动生成候选点；`Upload Excel`：上传含 `collector_area_m2`、`tank_volume_m3` 两列的表格 |
| Short/Long Collector Min / Max / Count | 集热器面积搜索区间与点数 |
| Short/Long Tank Min / Max / Count | 水池容积搜索区间与点数 |

Auto Generate 在区间内均匀取 Count 个点再做工程取整。**区间+点数共同决定网格密度，直接影响 Compact 模式的推荐结果**（见第五节），复现结果时必须固定网格口径。

### 6. 集热器性能

| 参数 | 含义与用途 |
|---|---|
| Collector Type | 预设：Flat Plate（η0=0.72, a1=3.2, a2=0）、Evacuated Tube（η0=0.65, a1=1.5, a2=0.005）、Custom 手填 |
| Collector eta0 / a1 / a2 | 效率曲线系数：η = η0 − a1·(Tm−Ta)/G − a2·(Tm−Ta)²/G，结果限制在 [0, 0.85] |
| Collector Soiling Factor | 灰尘折减系数，η 再乘该系数（0.95 = 折减 5%） |

### 7. 优化设置

| 参数 | 含义与用途 |
|---|---|
| Optimization Selection | 推荐模式：`Absolute Minimum` 或 `Compact Near-Optimal`（见第五节） |
| Cost Tolerance (%) | Compact 模式的成本容差带 |
| Minimum Solar Heating Ratio (%) | 覆盖率硬性下限，低于该值的方案直接淘汰（注意：覆盖率只是门槛，**不是**优化目标） |
| Auto Refine Search | 是否在初筛最优点附近自动加密网格再跑一轮 |
| Refine Span (%) | 自动细化的搜索窗口宽度（围绕种子点 ±span/2） |

---

## 四、操作流程

1. **准备并加载数据**：放好小时数据文件（或上传），在 Design Inputs 检查各参数。
2. **Analyze Input Data**：点击后程序校验并解析输入，在 Input Analysis Results 页给出全年/采暖季负荷、辐照量、逐月表、负荷持续曲线，以及候选面积/容积的建议范围（用于设置第五节网格区间）。**此操作同时把当前参数保存到 `design_inputs.xlsx`**。
3. **运行优化**：侧栏选择 Scenarios 后，三种运行方式任选其一：
   - **Run Cost Optimization Analysis**（整网格）：面积×容积全组合寻优，出成本热力图、覆盖率热力图与推荐方案。**推荐方案以此为准。**
   - **Run Two-Step Analysis**（两步法）：Step 1 固定"容积=面积×比值"扫面积 → 选定面积 → Step 2 固定面积扫容积。面积与容积绑定，结果偏向大面积。
   - **Run Cost + Two-Step Analysis**（组合）：两者都跑；**推荐面板与最优表以整网格结果为准**，两步法只用于出曲线。
4. **查看结果**：每个 Scenario 页有最优方案表、近优候选表、两张热力图、Step 1/2 曲线和完整设计表。
5. **Step 3 定稿**：在 Selected Collector Area / Final Tank Size 填入（或沿用推荐值），点 **Run Step 3 Final Results**，得到最终方案的逐时仿真结果（水温曲线、热源构成、水池充放热、逐月汇总等）。
6. **导出报告**：Export Excel（含 project_inputs / final_summary / step1 / step2 / optimization_grid / monthly / daily / hourly 等九张表）和 Export HTML 报告（含推荐面板与全部图表），文件存入 `02 reports/<项目名>/`。
7. **Report Center**：侧栏的报告中心可浏览、下载历史导出文件。

> **保存机制提醒**：界面参数只在点击分析/运行/导出按钮时写入 `design_inputs.xlsx`；改了参数不点按钮就重启，修改会丢失。

---

## 五、两种推荐模式的区别

两种模式都在"满足覆盖率下限"的方案中按**年化总成本**排序，区别在最终怎么挑：

| | Absolute Minimum | Compact Near-Optimal |
|---|---|---|
| 规则 | 直接取成本最低点 | 取 [最低成本, 最低×(1+容差)] 带内全部方案，按"容积最小→面积最小→成本最低→覆盖率最高"挑第一个 |
| 容差参数 | 无效 | 核心参数，容差越大推荐水池越小 |
| 倾向 | 年花费最少，水池大、覆盖率接近 100% | 多花不超过容差的钱，换尽量小的水池；覆盖率只保下限 |
| 对网格密度的敏感性 | 低（结果在成本谷底，基本不随网格移动） | **高**：网格加密后推荐点会沿"大面积换小水池"方向移动，贴近容差带边缘 |

**复现 Compact 结果必须注明网格口径（区间+点数）**；跨版本对比时请先核对 project_inputs 表中的网格参数是否一致。

---

## 六、常见问题

- **浏览器打不开页面**：用控制台打印的 `Bokeh app running at` 地址（端口可能变化），且用 `localhost` 而非 `127.0.0.1`。
- **报 Missing required columns**：输入文件缺必需列或列名不在别名表内（去掉单位后缀等再试，详见第二节）。
- **月度统计错位**：数据不是从 1 月 1 日开始但没带时间列，程序默认从 2025-01-01 生成时间戳。
- **两次运行推荐结果不同**：先对比导出文件 project_inputs 表的网格区间/点数/容差/模式，再对比 design_inputs 是否漂移。
- **界面改的参数没生效/丢了**：参数需点按钮触发保存；重启前记得点一次分析或导出。
