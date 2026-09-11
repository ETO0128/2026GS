# Question 2 Forecast and Dispatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a causal, reproducible Question 2 pipeline that forecasts daily load and PV, fixes day-ahead grid purchases, simulates realized storage operation and emergency purchases, evaluates all baselines, and fills the official `result2.xlsx` template.

**Architecture:** Extract Question 1's physical LP into a shared storage-dispatch module, then layer validated annual data loading, causal forecast strategies, day-ahead planning, two execution policies, annual evaluation, and reporting around it. Every forecast and parameter choice is date-ordered; only the grid plan is fixed at 0:00, while the recommended policy may causally re-optimize storage using current observations and the original future forecast.

**Tech Stack:** Python 3, NumPy, SciPy HiGHS linear programming, openpyxl, Matplotlib, `unittest`, LaTeX.

**Spec:** `docs/superpowers/specs/2026-09-11-question2-forecast-dispatch-design.md`

## Global Constraints

- Time resolution is exactly 10 minutes with 144 slots per day; convert kW to kWh with `1/6 h` exactly once.
- Charge and discharge are AC-bus-side energy; use `E[t+1] = E[t] + 0.9*charge[t] - discharge[t]/0.9`.
- Charge and discharge are each bounded by `5000/6 kWh` per slot; SOC is bounded by `1200 <= E <= 10800 kWh`.
- Only `2025-01-01 00:00` starts at `6000 kWh`; every later day starts from the preceding realized end SOC.
- A day's planned grid purchase is fixed at 0:00 and paid in full; emergency purchase costs five times the normal slot price.
- Forecasting date `d` may read only dates earlier than `d`; parameter tuning must also obey this boundary.
- January is the warm-up period; official evaluation and workbook output cover `2025-02-01` through `2025-12-31`.
- Preserve Question 1 outputs and tests while extracting shared code.
- Do not write `result2.xlsx` unless all annual feasibility and completeness checks pass.

---

## File Map

- Create `docs/research/question2_reference_matrix.md`: claim-to-source matrix and modeling implications.
- Create `src/py/microgrid_core.py`: shared physical constants, dispatch types, LP solver, and feasibility checks.
- Modify `src/py/question1.py`: delegate physical optimization to `microgrid_core` while preserving its public behavior.
- Create `src/py/question2_data.py`: annual workbook loading, date/time normalization, and validation.
- Create `src/py/question2_forecast.py`: causal baselines, similar-day predictor, rolling selection, and forecast metrics.
- Create `src/py/question2_dispatch.py`: day-ahead planner, fixed-plan simulator, causal storage recourse, and emergency-event compression.
- Create `src/py/question2.py`: annual orchestration, evaluation, CLI, result writing, and plots.
- Create `src/py/test_microgrid_core.py`: shared LP regression and boundary tests.
- Create `src/py/test_question2_data.py`: annual input and time-mapping tests.
- Create `src/py/test_question2_forecast.py`: leakage, fallback, metrics, and weighting tests.
- Create `src/py/test_question2_dispatch.py`: emergency purchase, SOC, fixed-plan, and recourse tests.
- Create `src/py/test_question2_integration.py`: multi-day continuity, annual completeness, and template tests.
- Modify `src/py/README.md`: Question 2 model, commands, outputs, and reproducibility instructions.
- Modify `src/tex/main.tex`: Question 2 assumptions, forecast method, model, validation, results, and sensitivity analysis.
- Modify `src/tex/references.txt`: verified references actually used in the paper.
- Update `src/附件5/result2.xlsx`: official filled workbook after all checks pass.
- Create `src/data/question2_summary.xlsx`: compact forecast, cost, strategy, and sensitivity summaries.
- Create `src/figure/q2_forecast_error.pdf`, `src/figure/q2_cost_comparison.pdf`, and `src/figure/q2_specified_days.pdf`.

---

### Task 1: Reference Matrix and Modeling Claims

**Files:**
- Create: `docs/research/question2_reference_matrix.md`
- Modify: `src/tex/references.txt`

**Interfaces:**
- Consumes: Question 2 problem statement, Issue #2 workflow, Issue #9 design direction, and the approved spec.
- Produces: a table with columns `Claim`, `Source`, `Evidence`, `Use in Question 2`, and `Limit`; bibliographic entries ready for later LaTeX use.

- [ ] **Step 1: Write the claim inventory before collecting prose**

Create the matrix with these exact claims:

```markdown
| Claim | Required source type | Use in Question 2 |
| --- | --- | --- |
| Forecast validation must preserve time order | Forecasting textbook or primary methods source | Expanding-window evaluation |
| Similar days can be selected by calendar and curve similarity | Peer-reviewed load-forecasting paper | Similar-day predictor |
| Day-ahead schedules and real-time controls can be separated | Peer-reviewed PV-storage optimization paper | Planning/execution architecture |
| CVaR can be represented in an optimization model | Original CVaR paper | Later risk extension only |
```

- [ ] **Step 2: Record verified primary or author-maintained sources**

Use and summarize these sources without copying extended passages:

```text
https://otexts.com/fpp3/tscv.html
https://doi.org/10.1016/j.ijepes.2005.12.007
https://www.sciencedirect.com/science/article/pii/S2405896317316440
https://uryasev.github.io/publications/
https://doi.org/10.3390/forecast8020032
```

The reference matrix must distinguish foundational support from methods deferred beyond the first baseline. The 2026 similar-day review may organize terminology but cannot replace the original similar-day paper for the method claim.

- [ ] **Step 3: Verify every bibliography entry is used**

Run:

```powershell
rg -n "rolling|similar|Mandal|storage|CVaR|Rockafellar" docs/research/question2_reference_matrix.md src/tex/references.txt
```

Expected: every retained reference appears in the matrix with a concrete role; no unrelated source is added.

- [ ] **Step 4: Commit the research record**

```powershell
git add docs/research/question2_reference_matrix.md src/tex/references.txt
git commit -m "docs: record question 2 modeling references"
```

---

### Task 2: Extract the Shared Physical LP

**Files:**
- Create: `src/py/microgrid_core.py`
- Create: `src/py/test_microgrid_core.py`
- Modify: `src/py/question1.py`
- Test: `src/py/test_question1.py`

**Interfaces:**
- Consumes: one-day load, PV and price arrays in chronological `00:00` slot order.
- Produces: `StorageParameters`, `DispatchInput`, `DispatchSolution`, `solve_dispatch`, and `validate_dispatch`.

- [ ] **Step 1: Write failing tests for configurable boundary states**

```python
def test_solver_accepts_carried_initial_soc_and_terminal_floor(self) -> None:
    inputs = DispatchInput(
        price_yuan_per_kwh=np.ones(144),
        load_kwh=np.full(144, 100.0),
        pv_kwh=np.zeros(144),
    )
    result = solve_dispatch(
        inputs,
        StorageParameters(),
        initial_soc_kwh=7200.0,
        terminal_soc_min_kwh=6000.0,
    )
    self.assertAlmostEqual(result.soc_kwh[0], 7200.0, places=6)
    self.assertGreaterEqual(result.soc_kwh[-1], 6000.0 - 1e-6)

def test_question1_regression_keeps_equal_terminal_soc(self) -> None:
    minutes = np.arange(0, 1440, SLOT_MINUTES, dtype=int)
    data = Question1Data(
        minute_of_day=minutes,
        price_yuan_per_kwh=np.ones(144),
        load_kw=np.full(144, 1000.0),
        pv_kw=np.zeros(144),
    )
    result = solve_question1(data)
    self.assertAlmostEqual(result.soc_kwh[0], 6000.0, places=6)
    self.assertAlmostEqual(result.soc_kwh[-1], 6000.0, places=6)
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```powershell
python -m unittest src/py/test_microgrid_core.py src/py/test_question1.py -v
```

Expected: the new test fails because `microgrid_core` does not exist; the existing Question 1 test still passes when run separately.

- [ ] **Step 3: Add the shared types and solver signature**

Implement these public types exactly:

```python
@dataclass(frozen=True)
class StorageParameters:
    min_soc_kwh: float = 1200.0
    max_soc_kwh: float = 10800.0
    max_slot_energy_kwh: float = 5000.0 / 6.0
    charge_efficiency: float = 0.90
    discharge_efficiency: float = 0.90

@dataclass(frozen=True)
class DispatchInput:
    price_yuan_per_kwh: np.ndarray
    load_kwh: np.ndarray
    pv_kwh: np.ndarray

@dataclass(frozen=True)
class DispatchSolution:
    grid_kwh: np.ndarray
    charge_kwh: np.ndarray
    discharge_kwh: np.ndarray
    curtailment_kwh: np.ndarray
    soc_kwh: np.ndarray
    total_cost_yuan: float

def solve_dispatch(
    inputs: DispatchInput,
    parameters: StorageParameters,
    initial_soc_kwh: float,
    terminal_soc_min_kwh: float,
    terminal_soc_max_kwh: float | None = None,
) -> DispatchSolution:
    return _solve_lexicographic_lp(
        inputs=inputs,
        parameters=parameters,
        initial_soc_kwh=initial_soc_kwh,
        terminal_soc_min_kwh=terminal_soc_min_kwh,
        terminal_soc_max_kwh=terminal_soc_max_kwh,
    )
```

Implement `_solve_lexicographic_lp` in the same module using the current two-pass LP: minimize grid cost, then minimize charge plus discharge while fixing the optimum cost. Validate array lengths, finite nonnegative inputs, initial SOC bounds, terminal bounds, energy balance, SOC transition, and absence of simultaneous charging and discharging.

- [ ] **Step 4: Refactor Question 1 to call the shared solver**

Keep `Question1Data`, `ScheduleSolution`, `solve_question1`, workbook output, plots, and CLI behavior stable. In `solve_question1`, construct `DispatchInput`, call:

```python
solve_dispatch(
    inputs,
    StorageParameters(),
    initial_soc_kwh=INITIAL_SOC_KWH,
    terminal_soc_min_kwh=INITIAL_SOC_KWH,
    terminal_soc_max_kwh=INITIAL_SOC_KWH,
)
```

and adapt the returned shared solution to the existing `ScheduleSolution` type.

- [ ] **Step 5: Run regression and direct solver tests**

Run:

```powershell
python -m unittest src/py/test_microgrid_core.py src/py/test_question1.py -v
python src/py/question1.py --no-plots
```

Expected: all tests pass and Question 1 reproduces the existing total cost and feasible schedule within `1e-5`.

- [ ] **Step 6: Commit the shared LP extraction**

```powershell
git add src/py/microgrid_core.py src/py/test_microgrid_core.py src/py/question1.py src/py/test_question1.py
git commit -m "refactor: extract shared microgrid dispatch solver"
```

---

### Task 3: Annual Data Loading and Time Mapping

**Files:**
- Create: `src/py/question2_data.py`
- Create: `src/py/test_question2_data.py`

**Interfaces:**
- Consumes: `附件1.xlsx` and `附件2.xlsx`.
- Produces: `YearData`, `load_year_data`, `load_cold_start_forecast`, and `template_column_minutes`.

- [ ] **Step 1: Write failing shape, date and rotation tests**

```python
def test_year_data_has_complete_calendar_and_slots(self) -> None:
    data = load_year_data(ATTACHMENT_1, ATTACHMENT_2)
    self.assertEqual(data.dates[0], date(2025, 1, 1))
    self.assertEqual(data.dates[-1], date(2025, 12, 31))
    self.assertEqual(data.load_kw.shape, (365, 144))
    self.assertEqual(data.pv_kw.shape, (365, 144))
    np.testing.assert_array_equal(data.minute_of_day, np.arange(0, 1440, 10))

def test_last_source_column_rotates_to_midnight_slot(self) -> None:
    data = load_year_data(ATTACHMENT_1, ATTACHMENT_2)
    source = load_workbook(ATTACHMENT_2, read_only=True, data_only=True)["小区负载"]
    self.assertEqual(data.load_kw[0, 0], source.cell(2, 145).value)
    self.assertEqual(data.load_kw[0, 1], source.cell(2, 2).value)
```

- [ ] **Step 2: Run tests and verify missing-module failure**

```powershell
python -m unittest src/py/test_question2_data.py -v
```

Expected: FAIL because `question2_data` is not implemented.

- [ ] **Step 3: Implement immutable annual data types and validation**

```python
@dataclass(frozen=True)
class YearData:
    dates: tuple[date, ...]
    minute_of_day: np.ndarray
    price_yuan_per_kwh: np.ndarray
    load_kw: np.ndarray
    pv_kw: np.ndarray

    @property
    def load_kwh(self) -> np.ndarray:
        return self.load_kw / 6.0

    @property
    def pv_kwh(self) -> np.ndarray:
        return self.pv_kw / 6.0
```

Require 365 unique ordered dates, exactly 144 unique time columns, identical headers between the load and PV sheets, finite nonnegative values, and a 144-point fixed price vector. Rotate the source's final `0:00+1` column to internal index 0 and preserve a tested inverse mapping for output.

- [ ] **Step 4: Run data tests**

```powershell
python -m unittest src/py/test_question2_data.py -v
```

Expected: all annual shape, date, unit, and rotation tests pass.

- [ ] **Step 5: Commit the validated loader**

```powershell
git add src/py/question2_data.py src/py/test_question2_data.py
git commit -m "feat: load and validate question 2 annual data"
```

---

### Task 4: Causal Forecast Baselines and Similar-Day Predictor

**Files:**
- Create: `src/py/question2_forecast.py`
- Create: `src/py/test_question2_forecast.py`

**Interfaces:**
- Consumes: historical rows strictly before `day_index`, calendar dates, and a `ForecastConfig`.
- Produces: `ForecastResult`, `forecast_day`, `forecast_metrics`, and `select_forecast_config`.

- [ ] **Step 1: Write failing causal and fallback tests**

```python
def test_future_mutation_does_not_change_today_forecast(self) -> None:
    base = make_synthetic_year_data(days=40)
    first = forecast_day(base, day_index=31, config=ForecastConfig(method="seven_day"))
    changed_load = base.load_kw.copy()
    changed_pv = base.pv_kw.copy()
    changed_load[32:] += 99999.0
    changed_pv[32:] += 99999.0
    changed = dataclasses.replace(base, load_kw=changed_load, pv_kw=changed_pv)
    second = forecast_day(changed, day_index=31, config=ForecastConfig(method="seven_day"))
    np.testing.assert_allclose(first.load_kw, second.load_kw)
    np.testing.assert_allclose(first.pv_kw, second.pv_kw)

def test_week_type_without_candidates_falls_back_to_recent_mean(self) -> None:
    result = forecast_day(make_synthetic_year_data(days=2), 1, ForecastConfig(method="week_type"))
    self.assertEqual(result.fallback_reason, "no_matching_week_type")
```

Define `make_synthetic_year_data(days)` in the test file. It must return a `YearData` whose dates start on Wednesday, 2025-01-01; `load_kw[d, t] = 1000 + 10*d + t`; `pv_kw[d, t] = max(0, 500 - abs(t - 72)*20)`; price has 144 ones; and minutes are `np.arange(0, 1440, 10)`.

- [ ] **Step 2: Run tests and verify failure**

```powershell
python -m unittest src/py/test_question2_forecast.py -v
```

- [ ] **Step 3: Implement forecast contracts and three baselines**

```python
@dataclass(frozen=True)
class ForecastConfig:
    method: Literal["previous_day", "seven_day", "week_type", "similar_day"]
    window_days: int = 28
    candidate_count: int = 7
    lambda_load: float = 0.95
    lambda_pv: float = 0.95

@dataclass(frozen=True)
class ForecastResult:
    load_kw: np.ndarray
    pv_kw: np.ndarray
    history_end: date
    method: str
    parameters: dict[str, float | int | str]
    candidate_dates: tuple[date, ...]
    fallback_reason: str | None
```

Implement previous-day, rolling-seven-day, and workday/weekend forecasts independently for load and PV. Clip only tiny negative numerical values to zero; reject non-finite forecasts.

- [ ] **Step 4: Add similar-day weighting and expanding-window selection**

Use normalized curve distance plus calendar compatibility. For each target, sort eligible dates by similarity, keep at most `candidate_count`, multiply similarity by `lambda ** age_days`, and normalize weights. Search only this bounded grid:

```python
CANDIDATE_COUNTS = (3, 5, 7, 14)
DECAY_VALUES = (0.90, 0.95, 0.98, 1.00)
```

Re-select at the first day of each month using only earlier rolling-origin forecast errors. Load and PV may choose different decay values. Minimize the mean of load and PV normalized RMSE; break differences below `1e-9` by the smaller candidate set, then the decay value closer to 1. Dispatch cost is evaluated later in `evaluate_year` and does not create a reverse dependency from forecasting to dispatch.

- [ ] **Step 5: Test metrics and known weighted averages**

Add exact-array tests for MAE, RMSE and Bias, and a three-candidate case whose weighted mean can be calculated by hand. Run:

```powershell
python -m unittest src/py/test_question2_forecast.py -v
```

Expected: all leakage, fallback, metric, weighting, and monthly-selection tests pass.

- [ ] **Step 6: Commit forecasting**

```powershell
git add src/py/question2_forecast.py src/py/test_question2_forecast.py
git commit -m "feat: add causal question 2 forecasts"
```

---

### Task 5: Day-Ahead Planning and Fixed-Plan Execution

**Files:**
- Create: `src/py/question2_dispatch.py`
- Create: `src/py/test_question2_dispatch.py`

**Interfaces:**
- Consumes: `ForecastResult`, realized day arrays, `StorageParameters`, initial SOC, reserve, and price.
- Produces: `DayAheadPlan`, `DayExecution`, `plan_day_ahead`, `simulate_fixed_plan`, and `compress_emergency_events`.

- [ ] **Step 1: Write failing cost and emergency tests**

```python
def test_one_slot_shortfall_uses_five_times_price(self) -> None:
    plan = make_flat_plan(grid_kwh=100.0, charge_kwh=0.0, discharge_kwh=0.0)
    realized = make_flat_realized(load_kwh=100.0, pv_kwh=0.0)
    realized.load_kwh[12] = 130.0
    result = simulate_fixed_plan(plan, realized, initial_soc_kwh=6000.0)
    self.assertAlmostEqual(result.emergency_kwh[12], 30.0)
    self.assertAlmostEqual(result.emergency_cost_yuan, 30.0 * 5.0 * plan.price_yuan_per_kwh[12])

def test_day_ahead_plan_uses_carried_soc(self) -> None:
    predicted = ForecastResult(
        load_kw=np.full(144, 600.0),
        pv_kw=np.zeros(144),
        history_end=date(2025, 1, 31),
        method="seven_day",
        parameters={},
        candidate_dates=(),
        fallback_reason=None,
    )
    plan = plan_day_ahead(date(2025, 2, 1), predicted, np.ones(144), 7200.0, reserve_kwh=6000.0)
    self.assertAlmostEqual(plan.soc_kwh[0], 7200.0)
```

Define `make_flat_plan` in the test file to construct 144-point constant arrays, a 145-point constant SOC array, a `2025-02-01` date, and unit prices. Define `make_flat_realized` to return a `RealizedDay` with 144-point constant `load_kwh` and `pv_kwh` arrays. Add this production input type in `question2_dispatch.py`:

```python
@dataclass(frozen=True)
class RealizedDay:
    date: date
    load_kwh: np.ndarray
    pv_kwh: np.ndarray
```

- [ ] **Step 2: Run the tests and verify failure**

```powershell
python -m unittest src/py/test_question2_dispatch.py -v
```

- [ ] **Step 3: Implement day-ahead and execution result types**

```python
@dataclass(frozen=True)
class DayAheadPlan:
    date: date
    price_yuan_per_kwh: np.ndarray
    grid_kwh: np.ndarray
    charge_kwh: np.ndarray
    discharge_kwh: np.ndarray
    curtailment_kwh: np.ndarray
    soc_kwh: np.ndarray
    planned_cost_yuan: float

@dataclass(frozen=True)
class DayExecution:
    date: date
    charge_kwh: np.ndarray
    discharge_kwh: np.ndarray
    curtailment_kwh: np.ndarray
    emergency_kwh: np.ndarray
    soc_kwh: np.ndarray
    planned_cost_yuan: float
    emergency_cost_yuan: float
    terminal_reserve_shortfall_kwh: float

    @property
    def total_cost_yuan(self) -> float:
        return self.planned_cost_yuan + self.emergency_cost_yuan
```

- [ ] **Step 4: Implement the fixed-plan baseline explicitly**

Execute planned charge and discharge exactly. Recalculate the real bus balance by slot; set emergency purchase to the positive deficit and curtailment to the positive surplus. Preserve the planned SOC trajectory, because planned storage actions determine SOC. Document that this strict baseline can purchase emergency energy while maintaining a planned charge and is intentionally conservative.

- [ ] **Step 5: Add emergency interval compression**

```python
@dataclass(frozen=True)
class EmergencyEvent:
    start_minute: int
    end_minute: int
    energy_kwh: float

def compress_emergency_events(emergency_kwh: np.ndarray, tolerance: float = 1e-8) -> tuple[EmergencyEvent, ...]:
    events: list[EmergencyEvent] = []
    start: int | None = None
    energy = 0.0
    for slot, value in enumerate(emergency_kwh):
        if value > tolerance:
            start = slot if start is None else start
            energy += float(value)
        elif start is not None:
            events.append(EmergencyEvent(start * 10, slot * 10, energy))
            start, energy = None, 0.0
    if start is not None:
        events.append(EmergencyEvent(start * 10, 1440, energy))
    return tuple(events)
```

Merge adjacent positive ten-minute slots, preserve midnight boundaries, and sum energy without rounding before workbook output.

- [ ] **Step 6: Run dispatch tests**

```powershell
python -m unittest src/py/test_question2_dispatch.py -v
```

Expected: known deficits, 5x costs, carried SOC, fixed-plan SOC, and event compression all pass.

- [ ] **Step 7: Commit planning and fixed execution**

```powershell
git add src/py/question2_dispatch.py src/py/test_question2_dispatch.py
git commit -m "feat: add question 2 day-ahead and fixed execution"
```

---

### Task 6: Causal Storage Recourse

**Files:**
- Modify: `src/py/question2_dispatch.py`
- Modify: `src/py/test_question2_dispatch.py`

**Interfaces:**
- Consumes: fixed day-ahead grid plan, original future forecast, current realized slot, current SOC, reserve, and emergency multiplier.
- Produces: `simulate_causal_recourse -> DayExecution`.

- [ ] **Step 1: Write a failing no-future-information test**

```python
def test_recourse_before_noon_is_unchanged_by_afternoon_actuals(self) -> None:
    first_actual = make_flat_realized(load_kwh=100.0, pv_kwh=0.0)
    changed_load = first_actual.load_kwh.copy()
    changed_load[72:] += 5000.0
    changed_actual = dataclasses.replace(first_actual, load_kwh=changed_load)
    day_plan = make_flat_plan(grid_kwh=100.0, charge_kwh=0.0, discharge_kwh=0.0)
    predicted = make_flat_forecast(load_kw=600.0, pv_kw=0.0)
    a = simulate_causal_recourse(day_plan, predicted, first_actual, 6000.0, 6000.0)
    b = simulate_causal_recourse(day_plan, predicted, changed_actual, 6000.0, 6000.0)
    np.testing.assert_allclose(a.charge_kwh[:72], b.charge_kwh[:72])
    np.testing.assert_allclose(a.discharge_kwh[:72], b.discharge_kwh[:72])
```

- [ ] **Step 2: Write a failing useful-recourse test**

```python
def test_recourse_uses_available_battery_before_emergency_purchase(self) -> None:
    day_plan = make_flat_plan(grid_kwh=100.0, charge_kwh=0.0, discharge_kwh=0.0)
    shortage = make_flat_realized(load_kwh=110.0, pv_kwh=0.0)
    predicted = make_flat_forecast(load_kw=600.0, pv_kw=0.0)
    fixed = simulate_fixed_plan(day_plan, shortage, 6000.0)
    recourse = simulate_causal_recourse(day_plan, predicted, shortage, 6000.0, 6000.0)
    self.assertLess(recourse.emergency_kwh.sum(), fixed.emergency_kwh.sum())
    self.assertGreaterEqual(recourse.soc_kwh.min(), 1200.0 - 1e-6)
```

Define `make_flat_forecast(load_kw, pv_kw)` in the test file using the `ForecastResult` fields from Task 4. Reuse `make_flat_plan` and `make_flat_realized` from the same test module rather than introducing separate fixture modules.

- [ ] **Step 3: Run focused tests and verify failure**

```powershell
python -m unittest src/py/test_question2_dispatch.py -v
```

- [ ] **Step 4: Implement slot-by-slot receding-horizon LP**

At slot `t`, build a remaining-horizon problem with:

```python
remaining_load = forecast.load_kw[t:].copy() / 6.0
remaining_pv = forecast.pv_kw[t:].copy() / 6.0
remaining_load[0] = realized.load_kwh[t]
remaining_pv[0] = realized.pv_kwh[t]
fixed_grid = plan.grid_kwh[t:]
```

Decision variables are charge, discharge, curtailment, emergency purchase, SOC, and nonnegative terminal reserve shortfall. Grid values are fixed parameters. Minimize `5 * price * emergency + reserve_penalty * terminal_shortfall`, then lexicographically minimize storage throughput. Bound emergency in each slot by the positive pre-storage physical deficit so it cannot be used solely to charge the battery. Execute only index 0, update realized SOC, and repeat.

- [ ] **Step 5: Add performance and feasibility guards**

Prebuild reusable sparse coefficient patterns by remaining horizon length. Record solve count and elapsed seconds. Raise with date and slot if HiGHS fails. Validate every executed slot and the full SOC trajectory. A seven-day benchmark must complete before attempting the full year; record the observed runtime in the run metadata rather than asserting a machine-specific threshold.

- [ ] **Step 6: Run recourse tests and seven-day benchmark**

```powershell
python -m unittest src/py/test_question2_dispatch.py -v
python src/py/question2.py --strategy causal --start 2025-02-01 --end 2025-02-07 --dry-run
```

Expected: no leakage, lower emergency purchase in the constructed case, no physical violations, and benchmark timing printed.

- [ ] **Step 7: Commit causal recourse**

```powershell
git add src/py/question2_dispatch.py src/py/test_question2_dispatch.py
git commit -m "feat: add causal storage recourse"
```

---

### Task 7: Annual Orchestration, Baseline Comparison, and Evaluation

**Files:**
- Create: `src/py/question2.py`
- Create: `src/py/test_question2_integration.py`

**Interfaces:**
- Consumes: validated `YearData`, forecast configurations, reserve, execution strategy, and output interval.
- Produces: `Question2Config`, `DailyRecord`, `YearResult`, `run_question2`, and `evaluate_year`.

- [ ] **Step 1: Write a failing three-day continuity test**

```python
def test_realized_soc_is_carried_across_days(self) -> None:
    data = make_synthetic_year_data(days=3)
    config = Question2Config(
        forecast=ForecastConfig(method="previous_day"),
        strategy="causal",
    )
    result = run_question2(data, config, cold_start_forecast=make_flat_forecast(600.0, 0.0))
    for previous, current in zip(result.days, result.days[1:]):
        self.assertAlmostEqual(previous.execution.soc_kwh[-1], current.execution.soc_kwh[0], places=6)
```

- [ ] **Step 2: Write a failing January warm-up boundary test**

```python
def test_official_rows_start_february_first_after_january_warmup(self) -> None:
    data = load_year_data(ATTACHMENT_1, ATTACHMENT_2)
    config = Question2Config(
        forecast=ForecastConfig(method="seven_day"),
        strategy="fixed",
    )
    result = run_question2(data, config, cold_start_forecast=load_cold_start_forecast(ATTACHMENT_1))
    self.assertEqual(result.days[0].date, date(2025, 1, 1))
    self.assertEqual(result.official_days[0].date, date(2025, 2, 1))
    self.assertEqual(len(result.official_days), 334)
```

Copy the deterministic `make_synthetic_year_data` and `make_flat_forecast` helpers into `test_question2_integration.py`; tests must not import helpers from another test module.

- [ ] **Step 3: Implement orchestration contracts**

```python
@dataclass(frozen=True)
class Question2Config:
    forecast: ForecastConfig
    strategy: Literal["fixed", "causal"]
    reserve_kwh: float = 6000.0
    emergency_multiplier: float = 5.0

@dataclass(frozen=True)
class DailyRecord:
    date: date
    forecast: ForecastResult
    plan: DayAheadPlan
    execution: DayExecution

@dataclass(frozen=True)
class YearResult:
    days: tuple[DailyRecord, ...]
    metrics: dict[str, float]
    run_metadata: dict[str, str | float | int]

    @property
    def official_days(self) -> tuple[DailyRecord, ...]:
        return tuple(day for day in self.days if day.date >= date(2025, 2, 1))
```

Use attachment 1 only for the January 1 cold-start forecast. From January 2 onward call the causal forecasting interface. Always carry realized SOC.

- [ ] **Step 4: Implement metrics and baseline runs**

Compute MAE, RMSE and Bias for load, PV and net load; plan and emergency costs; emergency energy and event count; charge, discharge, curtailment, PV utilization, SOC boundary hits, maximum physical residual, and elapsed time. Run these named cases:

```text
previous_day_fixed
seven_day_fixed
week_type_fixed
selected_baseline_fixed
selected_baseline_causal
similar_day_causal
```

Select the official candidate only from causal information. Report every case; do not delete an unfavorable baseline.

- [ ] **Step 5: Run integration and full fixed-policy tests**

```powershell
python -m unittest src/py/test_question2_integration.py -v
python src/py/question2.py --strategy fixed --forecast all --dry-run
```

Expected: 365 simulated days, 334 official days, no leakage, no physical violation, and a printed comparison table.

- [ ] **Step 6: Commit annual evaluation**

```powershell
git add src/py/question2.py src/py/test_question2_integration.py
git commit -m "feat: add annual question 2 evaluation"
```

---

### Task 8: Workbook Output, Figures, and Sensitivity Results

**Files:**
- Modify: `src/py/question2.py`
- Modify: `src/py/test_question2_integration.py`
- Update: `src/附件5/result2.xlsx`
- Create: `src/data/question2_summary.xlsx`
- Create: `src/figure/q2_forecast_error.pdf`
- Create: `src/figure/q2_cost_comparison.pdf`
- Create: `src/figure/q2_specified_days.pdf`

**Interfaces:**
- Consumes: fully validated `YearResult` objects and the untouched official template structure.
- Produces: `write_result2_workbook(...)`, `write_question2_summary(...)`, `plot_question2(...)`, the official workbook, summary workbook, and three publication figures.

- [ ] **Step 1: Write failing workbook completeness tests**

```python
def test_result2_contains_all_official_purchase_rows(self) -> None:
    result = make_three_day_year_result(start=date(2025, 2, 1))
    write_result2_workbook(TEMPLATE_COPY, OUTPUT, result)
    workbook = load_workbook(OUTPUT, read_only=True, data_only=True)
    sheet = workbook["计划购电量"]
    self.assertEqual(sheet.max_row, 335)
    for row in range(2, 336):
        self.assertTrue(all(sheet.cell(row, col).value is not None for col in range(2, 148)))

def test_result2_preserves_template_sheet_names(self) -> None:
    workbook = load_workbook(OUTPUT, read_only=True)
    self.assertEqual(workbook.sheetnames, ["计划购电量", "充放电量", "紧急购电量"])
```

Define `make_three_day_year_result(start)` in the integration test with three `DailyRecord` values whose 144-point grid arrays, six four-hour storage totals, SOC endpoints, and emergency events are distinct and exactly checkable. For the 334-row completeness test, construct a separate deterministic `YearResult` spanning all official dates; do not reuse a three-day result for a 334-day assertion.

- [ ] **Step 2: Run tests and verify writer failure**

```powershell
python -m unittest src/py/test_question2_integration.py -v
```

- [ ] **Step 3: Implement exact template writing**

Fill all 334 purchase rows and 144 interval columns, then the daily total energy and planned purchase cost. Fill the six four-hour charge/discharge blocks and 0:00/24:00 SOC for the template's specified dates. Replace the emergency worksheet's example/ellipsis region with one row per compressed event for every official day that has emergency purchase, repeating the date only on the first event row of each day. Preserve sheet names, headers, styles, merged cells, and number formats.

Write to a temporary file first, reopen it, validate every date and total against `YearResult`, and atomically replace the requested output only after validation.

- [ ] **Step 4: Implement compact summary and plots**

The summary workbook contains `策略汇总`, `预测误差`, `指定日期`, and `敏感性分析`. The three figures show monthly forecast error, cost components by strategy, and the four specified dates (`2025-03-20`, `2025-06-21`, `2025-09-23`, `2025-12-21`). Do not create decorative charts unrelated to a paper claim.

- [ ] **Step 5: Run one-factor sensitivity cases**

Use these explicit values:

```text
reserve_kwh: 3600, 6000, 8400
forecast_error_scale: 0.75, 1.00, 1.25
emergency_multiplier: 3, 5, 7
max_power_kw: 3000, 5000, 7000
```

For each case record total cost, emergency cost, emergency energy, curtailment, and minimum/maximum SOC. Keep the base case unchanged between runs.

- [ ] **Step 6: Generate and verify artifacts**

Before editing workbooks, follow the spreadsheet artifact workflow for a template-preserving edit and visual verification. Run:

```powershell
python src/py/question2.py --strategy causal --forecast similar_day --write-results --plots
python -m unittest src/py/test_question2_integration.py -v
```

Expected: all template assertions pass, all figures render legibly, and all summary totals reconcile to the annual result.

- [ ] **Step 7: Commit verified artifacts and writer**

```powershell
git add src/py/question2.py src/py/test_question2_integration.py src/附件5/result2.xlsx src/data/question2_summary.xlsx src/figure/q2_forecast_error.pdf src/figure/q2_cost_comparison.pdf src/figure/q2_specified_days.pdf
git commit -m "feat: generate question 2 results"
```

---

### Task 9: Paper and Reproducibility Documentation

**Files:**
- Modify: `src/py/README.md`
- Modify: `src/tex/main.tex`
- Modify: `src/tex/references.txt`

**Interfaces:**
- Consumes: verified reference matrix, model equations, annual metrics, specified-date tables, sensitivity results, and figures.
- Produces: reproducible commands and a complete Question 2 paper section with traceable claims.

- [ ] **Step 1: Replace Question 2 placeholder sections with verified content**

Document the information set, expanding-window validation, independent load/PV forecasts, day-ahead LP, fixed grid plan, 5x emergency purchase, cross-day SOC, fixed-plan comparison, causal recourse, and why the LP remains the physical feasibility layer.

- [ ] **Step 2: Insert only result-backed tables and figures**

Add forecast metrics, cost decomposition, emergency-purchase results for the four specified dates, strategy comparison, and one-factor sensitivity results. Every number must come from `question2_summary.xlsx` or `result2.xlsx`; do not transcribe unverified console output.

- [ ] **Step 3: Update reproducibility instructions**

Include these commands and explain dry-run versus artifact-writing behavior:

```powershell
python -m unittest discover -s src/py -p "test_*.py" -v
python src/py/question2.py --strategy fixed --forecast all --dry-run
python src/py/question2.py --strategy causal --forecast similar_day --write-results --plots
```

- [ ] **Step 4: Compile and inspect the paper**

Use the LaTeX compile workflow, render the affected pages, and verify that tables fit, figure labels are legible, symbols match the code, references resolve, and no Question 2 placeholder remains.

Run:

```powershell
rg -n "问题二|紧急购电|相似日|滚动验证|安全储备" src/tex/main.tex
```

Expected: the command locates the completed narrative. Inspect the former Question 2 placeholder lines directly and confirm they now contain substantive prose, equations, tables, or figures.

- [ ] **Step 5: Commit paper and README**

```powershell
git add src/py/README.md src/tex/main.tex src/tex/references.txt
git commit -m "docs: explain question 2 model and results"
```

---

### Task 10: Final Verification and Issue Handoff

**Files:**
- Verify all files changed in Tasks 1–9.
- No new production file is introduced in this task.

**Interfaces:**
- Consumes: the completed implementation, tests, workbooks, figures, and paper.
- Produces: a verification record and a concise Issue #9 progress comment only after user confirmation to publish.

- [ ] **Step 1: Run the complete automated test suite**

```powershell
python -m unittest discover -s src/py -p "test_*.py" -v
```

Expected: all tests pass with zero errors and failures.

- [ ] **Step 2: Re-run the official model from clean inputs**

```powershell
python src/py/question1.py --no-plots
python src/py/question2.py --strategy causal --forecast similar_day --write-results --plots
```

Expected: Question 1 remains reproducible; Question 2 prints 365 simulated days, 334 official days, zero physical violations, output paths, and reconciled totals.

- [ ] **Step 3: Verify repository and artifact integrity**

```powershell
git diff --check
git status --short
```

Reopen both Question 2 workbooks, inspect formulas/values and specified-date ranges, scan for spreadsheet errors, and render every affected sheet. Recompile and render the LaTeX paper. Compare `result2.xlsx`, `question2_summary.xlsx`, paper tables, and console metrics.

- [ ] **Step 4: Review the branch before integration**

Use the code-review workflow on the complete branch. Resolve all correctness findings, rerun affected tests, and retain unrelated user changes untouched.

- [ ] **Step 5: Prepare but do not publish the Issue comment without confirmation**

The comment must list completed workflow stages, model choice, information boundary, baseline comparisons, main metrics, sensitivity conclusions, artifact paths, commit hashes, and any remaining limitation. Ask for action-time confirmation immediately before posting to GitHub.

- [ ] **Step 6: Commit any verification-driven corrections**

Review `git diff --name-only`, stage only files actually corrected during verification, and commit them with message `fix: address question 2 verification findings`. Skip this commit when verification required no corrections.
