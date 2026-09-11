"""Day-ahead planning and realized fixed-plan settlement for Question 2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import lil_matrix

from microgrid_core import DispatchInput, StorageParameters, solve_dispatch
from question2_forecast import ForecastResult
from question2_scenarios import ScenarioSet


@dataclass(frozen=True)
class RealizedDay:
    date: date
    load_kwh: np.ndarray
    pv_kwh: np.ndarray


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


@dataclass(frozen=True)
class EmergencyEvent:
    start_minute: int
    end_minute: int
    energy_kwh: float


@dataclass(frozen=True)
class StochasticPlan:
    plan: DayAheadPlan
    scenario_emergency_kwh: np.ndarray
    scenario_surplus_kwh: np.ndarray
    scenario_probabilities: np.ndarray
    expected_emergency_cost_yuan: float
    objective_yuan: float


def plan_day_ahead(
    run_date: date,
    forecast: ForecastResult,
    price_yuan_per_kwh: np.ndarray,
    initial_soc_kwh: float,
    reserve_kwh: float = 6000.0,
    parameters: StorageParameters | None = None,
) -> DayAheadPlan:
    """Optimize the fixed normal-purchase plan against a causal 80% net-demand curve."""

    parameters = parameters or StorageParameters()
    price = np.asarray(price_yuan_per_kwh, dtype=float)
    net_kwh = np.asarray(forecast.planning_net_kw, dtype=float) / 6.0
    # Only the net curve matters for energy balance. Splitting it this way keeps
    # the common solver's no-export and curtailment semantics exact.
    load_kwh = np.maximum(net_kwh, 0.0)
    pv_kwh = np.maximum(-net_kwh, 0.0)
    solved = solve_dispatch(
        DispatchInput(price, load_kwh, pv_kwh),
        parameters,
        initial_soc_kwh=initial_soc_kwh,
        terminal_soc_min_kwh=reserve_kwh,
    )
    return DayAheadPlan(
        date=run_date,
        price_yuan_per_kwh=price.copy(),
        grid_kwh=solved.grid_kwh,
        charge_kwh=solved.charge_kwh,
        discharge_kwh=solved.discharge_kwh,
        curtailment_kwh=solved.curtailment_kwh,
        soc_kwh=solved.soc_kwh,
        planned_cost_yuan=solved.total_cost_yuan,
    )


def plan_two_stage_stochastic(
    run_date: date,
    scenarios: ScenarioSet,
    price_yuan_per_kwh: np.ndarray,
    initial_soc_kwh: float,
    reserve_kwh: float = 6000.0,
    emergency_multiplier: float = 5.0,
    parameters: StorageParameters | None = None,
) -> StochasticPlan:
    """Optimize one fixed plan against paired whole-day residual scenarios.

    Grid purchase and battery actions are shared first-stage decisions. Each
    scenario has its own emergency-purchase and surplus-energy settlement.
    """

    parameters = parameters or StorageParameters()
    if scenarios.decision_date != run_date or not scenarios.items:
        raise ValueError("Scenario set does not match the planning date")
    price = np.asarray(price_yuan_per_kwh, dtype=float)
    if price.shape != (144,) or np.any(price < 0.0) or not np.all(np.isfinite(price)):
        raise ValueError("Price must be a finite nonnegative 144-point vector")
    probabilities = scenarios.probabilities
    if not np.isclose(probabilities.sum(), 1.0) or np.any(probabilities <= 0.0):
        raise ValueError("Scenario probabilities must be positive and sum to one")

    n = 144
    scenario_count = len(scenarios.items)
    grid = slice(0, n)
    charge = slice(n, 2 * n)
    discharge = slice(2 * n, 3 * n)
    soc_start = 3 * n
    settlement_start = 4 * n + 1
    emergency_start = settlement_start
    surplus_start = emergency_start + scenario_count * n
    variable_count = surplus_start + scenario_count * n

    row_count = scenario_count * n + n
    equality = lil_matrix((row_count, variable_count), dtype=float)
    rhs = np.zeros(row_count)
    for scenario_index, scenario in enumerate(scenarios.items):
        load_kwh = np.asarray(scenario.load_kw, dtype=float) / 6.0
        pv_kwh = np.asarray(scenario.pv_kw, dtype=float) / 6.0
        emergency_offset = emergency_start + scenario_index * n
        surplus_offset = surplus_start + scenario_index * n
        for slot in range(n):
            row = scenario_index * n + slot
            equality[row, grid.start + slot] = 1.0
            equality[row, charge.start + slot] = -1.0
            equality[row, discharge.start + slot] = 1.0
            equality[row, emergency_offset + slot] = 1.0
            equality[row, surplus_offset + slot] = -1.0
            rhs[row] = load_kwh[slot] - pv_kwh[slot]
    soc_row_start = scenario_count * n
    for slot in range(n):
        row = soc_row_start + slot
        equality[row, soc_start + slot] = -1.0
        equality[row, soc_start + slot + 1] = 1.0
        equality[row, charge.start + slot] = -parameters.charge_efficiency
        equality[row, discharge.start + slot] = 1.0 / parameters.discharge_efficiency

    bounds: list[tuple[float, float | None]] = []
    bounds.extend((0.0, None) for _ in range(n))
    bounds.extend((0.0, parameters.max_slot_energy_kwh) for _ in range(n))
    bounds.extend((0.0, parameters.max_slot_energy_kwh) for _ in range(n))
    bounds.append((float(initial_soc_kwh), float(initial_soc_kwh)))
    bounds.extend((parameters.min_soc_kwh, parameters.max_soc_kwh) for _ in range(n - 1))
    bounds.append((reserve_kwh, parameters.max_soc_kwh))
    bounds.extend((0.0, None) for _ in range(2 * scenario_count * n))

    cost = np.zeros(variable_count)
    cost[grid] = price
    for scenario_index, probability in enumerate(probabilities):
        offset = emergency_start + scenario_index * n
        cost[offset : offset + n] = emergency_multiplier * probability * price
    equality_csr = equality.tocsr()
    economic = linprog(cost, A_eq=equality_csr, b_eq=rhs, bounds=bounds, method="highs")
    if not economic.success:
        raise RuntimeError(f"Stochastic economic LP failed on {run_date}: {economic.message}")

    throughput = np.zeros(variable_count)
    throughput[charge] = 1.0
    throughput[discharge] = 1.0
    tolerance = max(1e-8, abs(float(economic.fun)) * 1e-11)
    tie_break = linprog(
        throughput,
        A_ub=cost.reshape(1, -1),
        b_ub=np.asarray([economic.fun + tolerance]),
        A_eq=equality_csr,
        b_eq=rhs,
        bounds=bounds,
        method="highs",
    )
    if not tie_break.success:
        raise RuntimeError(f"Stochastic tie-break LP failed on {run_date}: {tie_break.message}")
    values = tie_break.x
    emergency_values = values[emergency_start:surplus_start].reshape(scenario_count, n)
    surplus_values = values[surplus_start:].reshape(scenario_count, n)
    planned_cost = float(np.dot(price, values[grid]))
    expected_emergency_cost = float(sum(
        probabilities[index] * emergency_multiplier * np.dot(price, emergency_values[index])
        for index in range(scenario_count)
    ))
    plan = DayAheadPlan(
        run_date,
        price.copy(),
        values[grid].copy(),
        values[charge].copy(),
        values[discharge].copy(),
        np.zeros(n),
        values[soc_start : soc_start + n + 1].copy(),
        planned_cost,
    )
    _validate_stochastic_plan(plan, scenarios, emergency_values, surplus_values, parameters)
    return StochasticPlan(
        plan=plan,
        scenario_emergency_kwh=emergency_values,
        scenario_surplus_kwh=surplus_values,
        scenario_probabilities=probabilities,
        expected_emergency_cost_yuan=expected_emergency_cost,
        objective_yuan=planned_cost + expected_emergency_cost,
    )


def _validate_stochastic_plan(
    plan: DayAheadPlan,
    scenarios: ScenarioSet,
    emergency: np.ndarray,
    surplus: np.ndarray,
    parameters: StorageParameters,
    tolerance: float = 1e-5,
) -> None:
    if np.min(plan.soc_kwh) < parameters.min_soc_kwh - tolerance or np.max(plan.soc_kwh) > parameters.max_soc_kwh + tolerance:
        raise RuntimeError("Stochastic plan violates SOC bounds")
    if np.min(plan.charge_kwh) < -tolerance or np.max(plan.charge_kwh) > parameters.max_slot_energy_kwh + tolerance:
        raise RuntimeError("Stochastic plan violates charge limits")
    if np.min(plan.discharge_kwh) < -tolerance or np.max(plan.discharge_kwh) > parameters.max_slot_energy_kwh + tolerance:
        raise RuntimeError("Stochastic plan violates discharge limits")
    if not np.all(np.isfinite(emergency)) or not np.all(np.isfinite(surplus)):
        raise RuntimeError("Stochastic settlement contains non-finite values")
    if np.min(emergency) < -tolerance or np.min(surplus) < -tolerance:
        raise RuntimeError("Stochastic settlement contains negative values")
    if np.any(np.minimum(plan.charge_kwh, plan.discharge_kwh) > tolerance):
        raise RuntimeError("Stochastic plan contains simultaneous charging and discharging")
    next_soc = plan.soc_kwh[:-1] + parameters.charge_efficiency * plan.charge_kwh - plan.discharge_kwh / parameters.discharge_efficiency
    if np.max(np.abs(plan.soc_kwh[1:] - next_soc)) > tolerance:
        raise RuntimeError("Stochastic plan violates the SOC transition")
    for index, scenario in enumerate(scenarios.items):
        balance = (
            plan.grid_kwh
            + scenario.pv_kw / 6.0
            + plan.discharge_kwh
            + emergency[index]
            - scenario.load_kw / 6.0
            - plan.charge_kwh
            - surplus[index]
        )
        if np.max(np.abs(balance)) > tolerance:
            raise RuntimeError(f"Stochastic scenario {index} violates energy balance")


def simulate_fixed_plan(
    plan: DayAheadPlan,
    realized: RealizedDay,
    initial_soc_kwh: float,
    emergency_multiplier: float = 5.0,
    reserve_kwh: float = 6000.0,
    parameters: StorageParameters | None = None,
) -> DayExecution:
    """Execute planned battery actions; settle any realized deficit as emergency energy."""

    parameters = parameters or StorageParameters()
    arrays = (realized.load_kwh, realized.pv_kwh, plan.grid_kwh, plan.charge_kwh, plan.discharge_kwh)
    if any(np.asarray(item).shape != (144,) for item in arrays):
        raise ValueError("Question 2 execution requires 144-point daily arrays")
    if plan.date != realized.date:
        raise ValueError("Plan and realization dates differ")
    if abs(float(plan.soc_kwh[0]) - initial_soc_kwh) > 1e-5:
        raise RuntimeError("Plan does not start at the carried SOC")

    raw_deficit = (
        np.asarray(realized.load_kwh, dtype=float)
        + plan.charge_kwh
        - np.asarray(realized.pv_kwh, dtype=float)
        - plan.discharge_kwh
        - plan.grid_kwh
    )
    emergency = np.maximum(raw_deficit, 0.0)
    curtailment = np.maximum(-raw_deficit, 0.0)
    emergency_cost = float(np.dot(plan.price_yuan_per_kwh * emergency_multiplier, emergency))
    execution = DayExecution(
        date=plan.date,
        charge_kwh=plan.charge_kwh.copy(),
        discharge_kwh=plan.discharge_kwh.copy(),
        curtailment_kwh=curtailment,
        emergency_kwh=emergency,
        soc_kwh=plan.soc_kwh.copy(),
        planned_cost_yuan=plan.planned_cost_yuan,
        emergency_cost_yuan=emergency_cost,
        terminal_reserve_shortfall_kwh=max(0.0, reserve_kwh - float(plan.soc_kwh[-1])),
    )
    validate_execution(plan, realized, execution, initial_soc_kwh, parameters)
    return execution


def validate_execution(
    plan: DayAheadPlan,
    realized: RealizedDay,
    execution: DayExecution,
    initial_soc_kwh: float,
    parameters: StorageParameters | None = None,
    tolerance: float = 1e-5,
) -> None:
    parameters = parameters or StorageParameters()
    balance = (
        plan.grid_kwh
        + realized.pv_kwh
        + execution.discharge_kwh
        + execution.emergency_kwh
        - realized.load_kwh
        - execution.charge_kwh
        - execution.curtailment_kwh
    )
    next_soc = (
        execution.soc_kwh[:-1]
        + parameters.charge_efficiency * execution.charge_kwh
        - execution.discharge_kwh / parameters.discharge_efficiency
    )
    if np.max(np.abs(balance)) > tolerance:
        raise RuntimeError("Realized execution violates bus energy balance")
    if np.max(np.abs(execution.soc_kwh[1:] - next_soc)) > tolerance:
        raise RuntimeError("Realized execution violates the SOC transition")
    if abs(float(execution.soc_kwh[0]) - initial_soc_kwh) > tolerance:
        raise RuntimeError("Realized execution does not start at carried SOC")
    if np.min(execution.soc_kwh) < parameters.min_soc_kwh - tolerance:
        raise RuntimeError("Realized SOC is below its lower bound")
    if np.max(execution.soc_kwh) > parameters.max_soc_kwh + tolerance:
        raise RuntimeError("Realized SOC is above its upper bound")
    if np.any(np.minimum(execution.charge_kwh, execution.discharge_kwh) > tolerance):
        raise RuntimeError("Execution contains simultaneous charging and discharging")


def compress_emergency_events(emergency_kwh: np.ndarray, tolerance: float = 1e-8) -> tuple[EmergencyEvent, ...]:
    values = np.asarray(emergency_kwh, dtype=float)
    if values.shape != (144,) or np.any(values < -tolerance):
        raise ValueError("Emergency energy must be a nonnegative 144-point array")
    events: list[EmergencyEvent] = []
    start: int | None = None
    energy = 0.0
    for slot, value in enumerate(values):
        if value > tolerance:
            start = slot if start is None else start
            energy += float(value)
        elif start is not None:
            events.append(EmergencyEvent(start * 10, slot * 10, energy))
            start, energy = None, 0.0
    if start is not None:
        events.append(EmergencyEvent(start * 10, 1440, energy))
    return tuple(events)
