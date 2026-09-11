"""Causal planning, realized settlement and oracle bounds for Question 4-2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from microgrid_core import DispatchInput, DispatchSolution, StorageParameters, solve_dispatch


@dataclass(frozen=True)
class Question42Plan:
    date: date
    forecast_price_yuan_per_kwh: np.ndarray
    grid_kwh: np.ndarray
    charge_kwh: np.ndarray
    discharge_kwh: np.ndarray
    curtailment_kwh: np.ndarray
    soc_kwh: np.ndarray
    predicted_cost_yuan: float


@dataclass(frozen=True)
class Question42Execution:
    date: date
    actual_price_yuan_per_kwh: np.ndarray
    grid_kwh: np.ndarray
    charge_kwh: np.ndarray
    discharge_kwh: np.ndarray
    surplus_kwh: np.ndarray
    emergency_kwh: np.ndarray
    soc_kwh: np.ndarray
    normal_purchase_cost_yuan: float
    emergency_cost_yuan: float

    @property
    def total_cost_yuan(self) -> float:
        return self.normal_purchase_cost_yuan + self.emergency_cost_yuan


@dataclass(frozen=True)
class PerfectInformationResult:
    date: date
    solution: DispatchSolution
    information_scope: str = "realized_day_oracle"

    @property
    def total_cost_yuan(self) -> float:
        return self.solution.total_cost_yuan


def _price_vector(values: np.ndarray, label: str) -> np.ndarray:
    price = np.asarray(values, dtype=float)
    if price.shape != (144,) or not np.all(np.isfinite(price)) or np.any(price < 0.0):
        raise ValueError(f"{label} must be a finite nonnegative 144-point vector")
    return price


def _power_vector(values: np.ndarray, label: str) -> np.ndarray:
    power = np.asarray(values, dtype=float)
    if power.shape != (144,) or not np.all(np.isfinite(power)) or np.any(power < 0.0):
        raise ValueError(f"{label} must be a finite nonnegative 144-point vector")
    return power


def plan_causal_day(
    run_date: date,
    forecast_net_kw: np.ndarray,
    forecast_price_yuan_per_kwh: np.ndarray,
    initial_soc_kwh: float,
    reserve_kwh: float = 6000.0,
    parameters: StorageParameters | None = None,
) -> Question42Plan:
    """Create a fixed day-ahead plan using only 0:00 forecast curves."""

    net_kw = np.asarray(forecast_net_kw, dtype=float)
    if net_kw.shape != (144,) or not np.all(np.isfinite(net_kw)):
        raise ValueError("Forecast net load must be a finite 144-point vector")
    price = _price_vector(forecast_price_yuan_per_kwh, "Forecast price")
    load_kwh = np.maximum(net_kw, 0.0) / 6.0
    pv_kwh = np.maximum(-net_kw, 0.0) / 6.0
    solved = solve_dispatch(
        DispatchInput(price, load_kwh, pv_kwh),
        parameters or StorageParameters(),
        initial_soc_kwh=initial_soc_kwh,
        terminal_soc_min_kwh=reserve_kwh,
    )
    return Question42Plan(
        date=run_date,
        forecast_price_yuan_per_kwh=price.copy(),
        grid_kwh=solved.grid_kwh,
        charge_kwh=solved.charge_kwh,
        discharge_kwh=solved.discharge_kwh,
        curtailment_kwh=solved.curtailment_kwh,
        soc_kwh=solved.soc_kwh,
        predicted_cost_yuan=solved.total_cost_yuan,
    )


def settle_causal_plan(
    plan: Question42Plan,
    actual_load_kw: np.ndarray,
    actual_pv_kw: np.ndarray,
    actual_price_yuan_per_kwh: np.ndarray,
    emergency_multiplier: float = 5.0,
) -> Question42Execution:
    """Settle a fixed plan against realized source, load and prices."""

    load_kwh = _power_vector(actual_load_kw, "Actual load") / 6.0
    pv_kwh = _power_vector(actual_pv_kw, "Actual PV") / 6.0
    actual_price = _price_vector(actual_price_yuan_per_kwh, "Actual price")
    if not np.isfinite(emergency_multiplier) or emergency_multiplier < 1.0:
        raise ValueError("Emergency price multiplier must be finite and at least one")
    raw_deficit = load_kwh + plan.charge_kwh - pv_kwh - plan.discharge_kwh - plan.grid_kwh
    emergency = np.maximum(raw_deficit, 0.0)
    surplus = np.maximum(-raw_deficit, 0.0)
    execution = Question42Execution(
        date=plan.date,
        actual_price_yuan_per_kwh=actual_price.copy(),
        grid_kwh=plan.grid_kwh.copy(),
        charge_kwh=plan.charge_kwh.copy(),
        discharge_kwh=plan.discharge_kwh.copy(),
        surplus_kwh=surplus,
        emergency_kwh=emergency,
        soc_kwh=plan.soc_kwh.copy(),
        normal_purchase_cost_yuan=float(np.dot(actual_price, plan.grid_kwh)),
        emergency_cost_yuan=float(np.dot(emergency_multiplier * actual_price, emergency)),
    )
    _validate_execution(execution, load_kwh, pv_kwh)
    return execution


def _validate_execution(
    execution: Question42Execution,
    actual_load_kwh: np.ndarray,
    actual_pv_kwh: np.ndarray,
    tolerance: float = 1e-5,
) -> None:
    balance = (
        execution.grid_kwh
        + actual_pv_kwh
        + execution.discharge_kwh
        + execution.emergency_kwh
        - actual_load_kwh
        - execution.charge_kwh
        - execution.surplus_kwh
    )
    if np.max(np.abs(balance)) > tolerance:
        raise RuntimeError("Question 4-2 realized settlement violates energy balance")
    nonnegative = (
        execution.grid_kwh,
        execution.charge_kwh,
        execution.discharge_kwh,
        execution.surplus_kwh,
        execution.emergency_kwh,
    )
    if any(values.shape != (144,) or np.min(values) < -tolerance for values in nonnegative):
        raise RuntimeError("Question 4-2 settlement contains an invalid flow")
    if execution.soc_kwh.shape != (145,) or not np.all(np.isfinite(execution.soc_kwh)):
        raise RuntimeError("Question 4-2 settlement contains an invalid SOC trajectory")


def solve_perfect_information_day(
    run_date: date,
    actual_load_kw: np.ndarray,
    actual_pv_kw: np.ndarray,
    actual_price_yuan_per_kwh: np.ndarray,
    initial_soc_kwh: float,
    reserve_kwh: float = 6000.0,
    parameters: StorageParameters | None = None,
) -> PerfectInformationResult:
    """Solve a realized-day oracle LP used only as an evaluation lower bound."""

    price = _price_vector(actual_price_yuan_per_kwh, "Actual price")
    load_kwh = _power_vector(actual_load_kw, "Actual load") / 6.0
    pv_kwh = _power_vector(actual_pv_kw, "Actual PV") / 6.0
    solved = solve_dispatch(
        DispatchInput(price, load_kwh, pv_kwh),
        parameters or StorageParameters(),
        initial_soc_kwh=initial_soc_kwh,
        terminal_soc_min_kwh=reserve_kwh,
    )
    return PerfectInformationResult(run_date, solved)


def dispatch_regret_yuan(
    execution: Question42Execution,
    perfect: PerfectInformationResult,
) -> float:
    """Return realized causal cost above the same-state daily oracle."""

    if execution.date != perfect.date:
        raise ValueError("Causal execution and perfect-information result use different dates")
    regret = execution.total_cost_yuan - perfect.total_cost_yuan
    if regret < -1e-5:
        raise RuntimeError("Perfect-information cost exceeded the causal realized cost")
    return float(regret)
