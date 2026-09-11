"""Day-ahead planning and realized fixed-plan settlement for Question 2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from microgrid_core import DispatchInput, StorageParameters, solve_dispatch
from question2_forecast import ForecastResult


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
