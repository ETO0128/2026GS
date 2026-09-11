# 问题 4-2 因果基线实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立问题 4-2 从附件 4 波动电价到因果电价预测、确定性日前计划、真实结算和完全信息下界的首个可复现闭环。

**Architecture:** 将全年真实源荷读取泛化为公共数据接口，再由问题 4-2 数据层对齐附件 4 电价。电价预测、调度与年度编排分别放在独立模块中；正式策略只能使用决策日前历史，完全信息求解仅在事后评价阶段调用公共物理 LP。

**Tech Stack:** Python 3、NumPy、SciPy `linprog`、openpyxl、标准库 `unittest`

**Spec:** `docs/superpowers/specs/2026-09-11-question4-2-safe-hierarchical-rl-design.md`

## Global Constraints

- 所有修改直接提交到现有 `xtc` 分支，不创建问题 4-2 的额外分支。
- 每日 0:00 只能使用前一日及更早的电价、负荷和光伏信息。
- 当天真实电价、负荷和光伏只用于事后结算和完全信息下界。
- 内部时序统一为 `00:00,...,23:50`，每个时段 10 分钟，共 144 点。
- SOC 范围为 1200–10800 kWh，充放电效率均为 0.9，单时段充放电上限为 `5000/6 kWh`。
- 新增生产函数必须先有失败测试；问题一、问题二的现有 20 项测试不得回归。
- 每个任务完成并通过完整测试后立即提交并推送到 `origin/xtc`。

---

### Task 1: 全年源荷与波动电价数据契约

**Status:** Completed and pushed in `19ba21b`.

**Files:**
- Modify: `src/py/question2_data.py`
- Create: `src/py/question4_2_data.py`
- Modify: `src/py/test_question2_data.py`
- Create: `src/py/test_question4_2_data.py`

**Interfaces:**
- Consumes: 附件 2 的 `小区负载`、`光伏发电实际功率` 工作表和附件 4 的 `Sheet1`。
- Produces: `ActualYearData`、`load_actual_year_data(path: Path) -> ActualYearData`、`Question42Data`、`load_question42_data(attachment2: Path, attachment4: Path) -> Question42Data`、`summarize_prices(data: Question42Data) -> dict[str, float]`。

- [ ] **Step 1: 为公共真实源荷接口编写失败测试**

在 `test_question2_data.py` 中加入：

```python
def test_actual_year_loader_matches_question2_curves(self):
    annual = load_year_data(self.attachment1, self.attachment2)
    actual = load_actual_year_data(self.attachment2)
    self.assertEqual(actual.dates, annual.dates)
    np.testing.assert_allclose(actual.load_kw, annual.load_kw)
    np.testing.assert_allclose(actual.pv_kw, annual.pv_kw)
```

- [ ] **Step 2: 运行测试并确认因接口不存在而失败**

Run: `python -m unittest src/py/test_question2_data.py -v`

Expected: `ImportError` 或 `AttributeError` 指向 `load_actual_year_data`。

- [ ] **Step 3: 最小化泛化问题二数据读取**

在 `question2_data.py` 中加入：

```python
@dataclass(frozen=True)
class ActualYearData:
    dates: tuple[date, ...]
    minute_of_day: np.ndarray
    load_kw: np.ndarray
    pv_kw: np.ndarray

def load_actual_year_data(attachment2: Path) -> ActualYearData:
    load_dates, load_headers, source_load = _read_sheet(attachment2, "小区负载")
    pv_dates, pv_headers, source_pv = _read_sheet(attachment2, "光伏发电实际功率")
    if load_dates != pv_dates or load_headers != pv_headers:
        raise ValueError("Load and PV sheets do not use identical dates and time columns")
    expected = tuple(date(2025, 1, 1) + timedelta(days=i) for i in range(365))
    if load_dates != expected:
        raise ValueError("Attachment 2 must contain the complete ordered 2025 calendar")
    return ActualYearData(
        dates=load_dates,
        minute_of_day=np.arange(0, 1440, SLOT_MINUTES, dtype=int),
        load_kw=np.concatenate((source_load[:, -1:], source_load[:, :-1]), axis=1),
        pv_kw=np.concatenate((source_pv[:, -1:], source_pv[:, :-1]), axis=1),
    )
```

让现有 `load_year_data` 调用该公共函数，再附加问题一固定电价。保持时间旋转、日期检查和异常信息不变。

- [ ] **Step 4: 运行问题二数据测试并确认通过**

Run: `python -m unittest src/py/test_question2_data.py -v`

Expected: 所有 `Question2DataTests` 通过。

- [ ] **Step 5: 为附件 4 对齐与拒绝错位日期编写失败测试**

在 `test_question4_2_data.py` 使用临时工作簿构造 365 天、每天 144 点的源荷与价格，验证：

```python
data = load_question42_data(attachment2, attachment4)
self.assertEqual(data.price_yuan_per_kwh.shape, (365, 144))
self.assertEqual(data.minute_of_day[0], 0)
self.assertEqual(data.price_yuan_per_kwh[0, 0], source_prices[0, -1])
```

再将附件 4 第二天日期改为重复日期，并断言抛出 `ValueError("Attachment 4 dates must match Attachment 2")`。

- [ ] **Step 6: 运行测试并确认因模块不存在而失败**

Run: `python -m unittest src/py/test_question4_2_data.py -v`

Expected: `ModuleNotFoundError: No module named 'question4_2_data'`。

- [ ] **Step 7: 实现问题 4-2 数据对象、价格读取和摘要**

`Question42Data` 包含 `dates`、`minute_of_day`、`price_yuan_per_kwh`、`load_kw` 和 `pv_kw`，并提供 `load_kwh`、`pv_kwh` 属性。价格读取复用问题二的日期与 144 点检查语义，将源文件最后一列旋转到内部第 0 时段。

`summarize_prices` 固定返回：

```python
{
    "minimum_yuan_per_kwh": float,
    "maximum_yuan_per_kwh": float,
    "mean_yuan_per_kwh": float,
    "lag1_curve_correlation": float,
    "lag7_curve_correlation": float,
}
```

- [ ] **Step 8: 运行数据层测试和完整回归测试**

Run: `python -m unittest src/py/test_question2_data.py src/py/test_question4_2_data.py -v`

Run: `python -m unittest discover -s src/py -p "test_*.py" -v`

Expected: 新旧测试全部通过。

- [ ] **Step 9: 提交并推送数据层**

```powershell
git add src/py/question2_data.py src/py/question4_2_data.py src/py/test_question2_data.py src/py/test_question4_2_data.py
git commit -m "feat: load question 4-2 variable prices"
git push origin xtc
```

### Task 2: 无泄漏电价预测基线

**Status:** Completed and pushed in `cb36379`.

**Files:**
- Create: `src/py/question4_2_forecast.py`
- Create: `src/py/test_question4_2_forecast.py`

**Interfaces:**
- Consumes: `Question42Data` 及目标日期下标。
- Produces: `PriceForecastConfig`、`PriceForecastResult`、`forecast_price(data: Question42Data, target_index: int, config: PriceForecastConfig) -> PriceForecastResult`、`price_forecast_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]`。

- [ ] **Step 1: 为昨日、七日和星期类型预测编写失败测试**

使用按日期和时段可辨识的合成价格矩阵，分别断言：

```python
previous = forecast_price(data, 8, PriceForecastConfig(method="previous_day"))
np.testing.assert_allclose(previous.price_yuan_per_kwh, data.price_yuan_per_kwh[7])

seven = forecast_price(data, 8, PriceForecastConfig(method="seven_day"))
np.testing.assert_allclose(seven.price_yuan_per_kwh, data.price_yuan_per_kwh[1:8].mean(axis=0))
```

星期类型样例只允许选择目标日前同为工作日或同为周末的日期。

- [ ] **Step 2: 运行测试并确认模块缺失失败**

Run: `python -m unittest src/py/test_question4_2_forecast.py -v`

Expected: `ModuleNotFoundError`。

- [ ] **Step 3: 实现三个简单因果基线和明确回退**

`PriceForecastConfig.method` 只接受 `previous_day`、`seven_day`、`week_type`、`similar_day_decay`。结果必须记录 `decision_date`、`history_end_date`、`source_dates`、`method` 和 `fallback_reason`。目标下标为 0 时使用附件 4 首日以前不可获得的价格，因此函数明确拒绝并要求编排层提供冷启动价格先验。

- [ ] **Step 4: 验证简单基线测试通过**

Run: `python -m unittest src/py/test_question4_2_forecast.py -v`

Expected: 简单基线测试通过。

- [ ] **Step 5: 为时间衰减和未来变异编写失败测试**

构造两个候选历史日，使较近历史日获得更大权重；断言 `decay=0.5` 时近日日权重大于远日日。复制数据并任意修改目标日及未来价格后，断言预测曲线、来源日期和元数据完全不变。

- [ ] **Step 6: 实现因果相似日与时间衰减**

目标日原型只由最近最多七个历史日均值构成。候选日限定在过去 `window_days`，先按星期类型和季节筛选；不足两个候选时依次回退到同星期类型和全部历史。曲线距离比较候选历史价格与历史原型，权重为 `similarity * decay ** age_days`，选取最近似的 `candidate_count` 个历史日。

- [ ] **Step 7: 实现预测指标并运行完整测试**

指标定义为：

```python
error = predicted - actual
mae = np.mean(np.abs(error))
rmse = np.sqrt(np.mean(error ** 2))
bias = np.mean(error)
```

Run: `python -m unittest src/py/test_question4_2_forecast.py -v`

Run: `python -m unittest discover -s src/py -p "test_*.py" -v`

Expected: 全部通过，未来变异测试无差异。

- [ ] **Step 8: 提交并推送预测层**

```powershell
git add src/py/question4_2_forecast.py src/py/test_question4_2_forecast.py
git commit -m "feat: add causal price forecast baselines"
git push origin xtc
```

### Task 3: 因果确定性调度、真实结算与完全信息下界

**Status:** Completed and pushed in `3188efd`.

**Files:**
- Create: `src/py/question4_2_dispatch.py`
- Create: `src/py/test_question4_2_dispatch.py`

**Interfaces:**
- Consumes: 144 点预测净负荷、预测价格、真实源荷、真实价格、日初 SOC 和 `StorageParameters`。
- Produces: `Question42Plan`、`Question42Execution`、`PerfectInformationResult`，以及以下接口：

```python
def plan_causal_day(
    run_date: date,
    forecast_net_kw: np.ndarray,
    forecast_price_yuan_per_kwh: np.ndarray,
    initial_soc_kwh: float,
    reserve_kwh: float = 6000.0,
    parameters: StorageParameters | None = None,
) -> Question42Plan

def settle_causal_plan(
    plan: Question42Plan,
    actual_load_kw: np.ndarray,
    actual_pv_kw: np.ndarray,
    actual_price_yuan_per_kwh: np.ndarray,
    emergency_multiplier: float = 5.0,
) -> Question42Execution

def solve_perfect_information_day(
    run_date: date,
    actual_load_kw: np.ndarray,
    actual_pv_kw: np.ndarray,
    actual_price_yuan_per_kwh: np.ndarray,
    initial_soc_kwh: float,
    reserve_kwh: float = 6000.0,
    parameters: StorageParameters | None = None,
) -> PerfectInformationResult

def dispatch_regret_yuan(
    execution: Question42Execution,
    perfect: PerfectInformationResult,
) -> float
```

- [ ] **Step 1: 为因果计划只使用预测量编写失败测试**

构造 144 点平坦预测净负荷和价格，调用：

```python
plan = plan_causal_day(
    run_date,
    forecast_net_kw,
    forecast_price,
    initial_soc_kwh=6000.0,
    reserve_kwh=6000.0,
)
```

断言计划保存预测价格、初末 SOC 满足边界、购电非负且能量平衡成立。

- [ ] **Step 2: 运行测试并确认模块缺失失败**

Run: `python -m unittest src/py/test_question4_2_dispatch.py -v`

Expected: `ModuleNotFoundError`。

- [ ] **Step 3: 用公共物理求解器实现因果计划**

将预测净负荷正部映射为负荷、负部映射为光伏，调用 `microgrid_core.solve_dispatch`。计划对象同时保存优化使用的预测价格和固定购电、充放电、SOC 序列。

- [ ] **Step 4: 为真实价格结算和五倍紧急购电编写失败测试**

构造一个时段真实净负荷比计划高 1 kWh，真实价格为 2 元/kWh，断言紧急购电为 1 kWh、紧急费用为 10 元；正常费用必须等于 `dot(actual_price, plan.grid_kwh)`，不得使用预测价格结算。

- [ ] **Step 5: 实现固定计划真实结算与物理验证**

计划购电和储能动作保持固定，真实缺口取正部为紧急购电，负部为弃电。验证日初 SOC、SOC 转移、所有流量非负、形状为 144 点，以及真实能量平衡残差低于 `1e-5`。

- [ ] **Step 6: 为完全信息下界和非负遗憾编写失败测试**

同一天使用真实价格、负荷和光伏求解完全信息 LP，并断言：

```python
self.assertLessEqual(perfect.total_cost_yuan, execution.total_cost_yuan + 1e-5)
self.assertAlmostEqual(
    dispatch_regret_yuan(execution, perfect),
    execution.total_cost_yuan - perfect.total_cost_yuan,
)
```

- [ ] **Step 7: 实现完全信息求解和遗憾计算**

完全信息 LP 使用与因果计划相同的日初 SOC、终端储备和物理参数。完全信息对象记录 `information_scope="realized_day_oracle"`，防止其被误当作正式策略。

- [ ] **Step 8: 运行调度测试和完整回归测试**

Run: `python -m unittest src/py/test_question4_2_dispatch.py -v`

Run: `python -m unittest discover -s src/py -p "test_*.py" -v`

Expected: 新调度测试与全部旧测试通过。

- [ ] **Step 9: 提交并推送调度层**

```powershell
git add src/py/question4_2_dispatch.py src/py/test_question4_2_dispatch.py
git commit -m "feat: add question 4-2 causal dispatch baseline"
git push origin xtc
```

### Task 4: 顺序运行、指标与首轮真实数据验证

**Status:** Completed and pushed in `a329716`.

**Files:**
- Create: `src/py/question4_2.py`
- Create: `src/py/test_question4_2_integration.py`
- Modify: `src/py/README.md`
- Create: `docs/research/question4_2_causal_baseline.md`

**Interfaces:**
- Consumes: `Question42Data`、问题二净负荷预测、问题 4-2 电价预测与调度接口。
- Produces: `Question42Config`、`Question42DailyRecord`、`Question42YearResult`，以及：

```python
def run_question42_baseline(
    data: Question42Data,
    cold_start: ColdStartForecast,
    cold_start_price_yuan_per_kwh: np.ndarray,
    config: Question42Config,
) -> Question42YearResult
```

- [ ] **Step 1: 为三天顺序闭环和未来变异编写失败测试**

构造三天合成数据和冷启动预测，断言：

- 第二、三天 `price_forecast.history_end_date < run_date`；
- 每天日初 SOC 等于上一天日末 SOC；
- 修改第三天及以后真实数据不改变第二天计划；
- 每天 `perfect_information_cost <= causal_realized_cost + 1e-5`；
- 全部约束违反计数为零。

- [ ] **Step 2: 运行测试并确认编排模块缺失失败**

Run: `python -m unittest src/py/test_question4_2_integration.py -v`

Expected: `ModuleNotFoundError`。

- [ ] **Step 3: 实现按日期扩展窗口运行器**

第 1 天价格冷启动使用附件 1 已给出的固定价格曲线作为赛题先验，不读取附件 4 第 1 天真实电价制定计划；第 2 天起只用已经发生的附件 4 历史价格形成因果预测。负荷和光伏预测沿用问题二接口及附件 1 冷启动曲线。每个日期依次执行预测、因果计划、真实结算、完全信息评价和 SOC 传递。1 月只用于热启动与参数形成，正式统计仍从 2 月 1 日开始。

- [ ] **Step 4: 实现年度汇总指标**

汇总至少包含：

```python
{
    "evaluated_days": int,
    "price_mae_yuan_per_kwh": float,
    "price_rmse_yuan_per_kwh": float,
    "price_bias_yuan_per_kwh": float,
    "normal_purchase_cost_yuan": float,
    "emergency_cost_yuan": float,
    "total_cost_yuan": float,
    "perfect_information_cost_yuan": float,
    "dispatch_regret_yuan": float,
    "constraint_violations": int,
}
```

- [ ] **Step 5: 增加命令行入口和复现说明**

默认读取 `problems/C题/附件/附件1.xlsx`、附件 2 和附件 4，只打印摘要，不修改官方 `result4-2.xlsx`。提供 `--price-forecast`、`--days` 和 `--reserve-kwh` 参数。README 明确真实电价仅用于结算和下界。

- [ ] **Step 6: 运行集成测试和完整回归测试**

Run: `python -m unittest src/py/test_question4_2_integration.py -v`

Run: `python -m unittest discover -s src/py -p "test_*.py" -v`

Expected: 所有测试通过。

- [ ] **Step 7: 在真实数据上运行 14 天冒烟验证**

Run: `python src/py/question4_2.py --days 14 --price-forecast seven_day`

Expected: 输出 14 个已运行日和 13 个具有历史价格预测误差的日期；费用与预测指标均为有限值，完全信息费用不高于因果真实费用，约束违反次数为 0。

- [ ] **Step 8: 记录首轮结果和限制**

在 `docs/research/question4_2_causal_baseline.md` 记录数据范围、模型信息边界、命令、配置、14 天指标、完全信息口径和尚未实现的联合场景/CVaR/RL，禁止把冒烟结果称为正式全年结果。

- [ ] **Step 9: 提交并推送首个闭环**

```powershell
git add src/py/question4_2.py src/py/test_question4_2_integration.py src/py/README.md docs/research/question4_2_causal_baseline.md
git commit -m "feat: run question 4-2 causal baseline"
git push origin xtc
```

### Task 5: 第一里程碑验收

**Status:** Verification completed; Issue #16 report awaits user confirmation before publication.

**Files:**
- Modify: `docs/superpowers/plans/2026-09-11-question4-2-causal-baseline.md`

**Interfaces:**
- Consumes: Tasks 1–4 的提交、测试输出和真实数据冒烟结果。
- Produces: 勾选完成的实施计划及第一里程碑审计结论。

- [ ] **Step 1: 运行完整测试**

Run: `python -m unittest discover -s src/py -p "test_*.py" -v`

Expected: 0 failures、0 errors。

- [ ] **Step 2: 检查仓库差异与分支**

Run: `git status --short --branch`

Run: `git branch --show-current`

Expected: 当前分支为 `xtc`，没有未提交修改，没有新建问题 4-2 分支。

- [ ] **Step 3: 检查提交与远端同步**

Run: `git log -5 --oneline --decorate`

Run: `git rev-parse HEAD`

Run: `git rev-parse origin/xtc`

Expected: 第一里程碑提交均位于 `xtc`，`HEAD` 与 `origin/xtc` 相同。

- [ ] **Step 4: 在 Issue #16 汇报第一里程碑**

评论只报告已验证的完成项、测试数量、14 天冒烟结果、文件位置和下一阶段联合场景计划。发布前展示完整评论并取得用户确认。
