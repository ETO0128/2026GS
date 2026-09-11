"""Shared physical dispatch model for daily microgrid scheduling.

All energy quantities are AC-bus kWh in chronological slot order.  The SOC
trajectory includes both boundaries: index zero is the carried initial state.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linprog


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
    """Minimize grid cost, then storage throughput at the same optimum cost."""

    return _solve_lexicographic_lp(
        inputs=inputs,
        parameters=parameters,
        initial_soc_kwh=initial_soc_kwh,
        terminal_soc_min_kwh=terminal_soc_min_kwh,
        terminal_soc_max_kwh=terminal_soc_max_kwh,
    )


def _validate_inputs(inputs: DispatchInput, parameters: StorageParameters) -> int:
    arrays = {
        "price_yuan_per_kwh": np.asarray(inputs.price_yuan_per_kwh, dtype=float),
        "load_kwh": np.asarray(inputs.load_kwh, dtype=float),
        "pv_kwh": np.asarray(inputs.pv_kwh, dtype=float),
    }
    lengths = {name: values.size for name, values in arrays.items()}
    if len(set(lengths.values())) != 1 or not next(iter(lengths.values())):
        raise ValueError(f"Input arrays must have the same nonzero length: {lengths}")
    for name, values in arrays.items():
        if values.ndim != 1:
            raise ValueError(f"{name} must be a one-dimensional array")
        if not np.all(np.isfinite(values)) or np.any(values < 0.0):
            raise ValueError(f"{name} must contain finite nonnegative values")

    parameter_values = (
        parameters.min_soc_kwh,
        parameters.max_soc_kwh,
        parameters.max_slot_energy_kwh,
        parameters.charge_efficiency,
        parameters.discharge_efficiency,
    )
    if not all(np.isfinite(value) for value in parameter_values):
        raise ValueError("Storage parameters must be finite")
    if parameters.min_soc_kwh > parameters.max_soc_kwh:
        raise ValueError("Storage minimum SOC cannot exceed maximum SOC")
    if parameters.max_slot_energy_kwh < 0.0:
        raise ValueError("Maximum slot energy must be nonnegative")
    if not 0.0 < parameters.charge_efficiency <= 1.0:
        raise ValueError("Charge efficiency must be in (0, 1]")
    if not 0.0 < parameters.discharge_efficiency <= 1.0:
        raise ValueError("Discharge efficiency must be in (0, 1]")
    return next(iter(lengths.values()))


def _validate_boundary_states(
    parameters: StorageParameters,
    initial_soc_kwh: float,
    terminal_soc_min_kwh: float,
    terminal_soc_max_kwh: float | None,
) -> tuple[float, float]:
    boundary_values = [initial_soc_kwh, terminal_soc_min_kwh]
    if terminal_soc_max_kwh is not None:
        boundary_values.append(terminal_soc_max_kwh)
    if not all(np.isfinite(value) for value in boundary_values):
        raise ValueError("Initial and terminal SOC bounds must be finite")
    if not parameters.min_soc_kwh <= initial_soc_kwh <= parameters.max_soc_kwh:
        raise ValueError("Initial SOC violates storage bounds")
    if not parameters.min_soc_kwh <= terminal_soc_min_kwh <= parameters.max_soc_kwh:
        raise ValueError("Terminal minimum SOC violates storage bounds")

    terminal_max = parameters.max_soc_kwh if terminal_soc_max_kwh is None else terminal_soc_max_kwh
    if not parameters.min_soc_kwh <= terminal_max <= parameters.max_soc_kwh:
        raise ValueError("Terminal maximum SOC violates storage bounds")
    if terminal_soc_min_kwh > terminal_max:
        raise ValueError("Terminal minimum SOC cannot exceed terminal maximum SOC")
    return float(terminal_soc_min_kwh), float(terminal_max)


def _solve_lexicographic_lp(
    inputs: DispatchInput,
    parameters: StorageParameters,
    initial_soc_kwh: float,
    terminal_soc_min_kwh: float,
    terminal_soc_max_kwh: float | None,
) -> DispatchSolution:
    n = _validate_inputs(inputs, parameters)
    terminal_min, terminal_max = _validate_boundary_states(
        parameters, initial_soc_kwh, terminal_soc_min_kwh, terminal_soc_max_kwh
    )
    price = np.asarray(inputs.price_yuan_per_kwh, dtype=float)
    load = np.asarray(inputs.load_kwh, dtype=float)
    pv = np.asarray(inputs.pv_kwh, dtype=float)
    grid = slice(0, n)
    charge = slice(n, 2 * n)
    discharge = slice(2 * n, 3 * n)
    curtailment = slice(3 * n, 4 * n)
    soc_start = 4 * n
    variable_count = 5 * n + 1

    cost_objective = np.zeros(variable_count)
    cost_objective[grid] = price
    equality = np.zeros((2 * n, variable_count))
    rhs = np.zeros(2 * n)
    for slot in range(n):
        equality[slot, grid.start + slot] = 1.0
        equality[slot, charge.start + slot] = -1.0
        equality[slot, discharge.start + slot] = 1.0
        equality[slot, curtailment.start + slot] = -1.0
        rhs[slot] = load[slot] - pv[slot]
        equality[n + slot, soc_start + slot] = -1.0
        equality[n + slot, soc_start + slot + 1] = 1.0
        equality[n + slot, charge.start + slot] = -parameters.charge_efficiency
        equality[n + slot, discharge.start + slot] = 1.0 / parameters.discharge_efficiency

    bounds: list[tuple[float, float | None]] = []
    bounds.extend((0.0, None) for _ in range(n))
    bounds.extend((0.0, parameters.max_slot_energy_kwh) for _ in range(n))
    bounds.extend((0.0, parameters.max_slot_energy_kwh) for _ in range(n))
    bounds.extend((0.0, float(pv[slot])) for slot in range(n))
    bounds.append((float(initial_soc_kwh), float(initial_soc_kwh)))
    bounds.extend((parameters.min_soc_kwh, parameters.max_soc_kwh) for _ in range(n - 1))
    bounds.append((terminal_min, terminal_max))

    economic_result = linprog(cost_objective, A_eq=equality, b_eq=rhs, bounds=bounds, method="highs")
    if not economic_result.success:
        raise RuntimeError(f"Economic LP failed: {economic_result.message}")
    throughput_objective = np.zeros(variable_count)
    throughput_objective[charge] = 1.0
    throughput_objective[discharge] = 1.0
    tie_break_result = linprog(
        throughput_objective,
        A_eq=np.vstack((equality, cost_objective)),
        b_eq=np.append(rhs, economic_result.fun),
        bounds=bounds,
        method="highs",
    )
    if not tie_break_result.success:
        raise RuntimeError(f"Tie-break LP failed: {tie_break_result.message}")

    values = tie_break_result.x.copy()
    values[np.abs(values) < 1e-8] = 0.0
    solution = DispatchSolution(
        grid_kwh=values[grid].copy(),
        charge_kwh=values[charge].copy(),
        discharge_kwh=values[discharge].copy(),
        curtailment_kwh=values[curtailment].copy(),
        soc_kwh=values[soc_start : soc_start + n + 1].copy(),
        total_cost_yuan=float(np.dot(price, values[grid])),
    )
    validate_dispatch(
        inputs,
        parameters,
        solution,
        initial_soc_kwh,
        terminal_soc_min_kwh,
        terminal_soc_max_kwh,
    )
    return solution


def validate_dispatch(
    inputs: DispatchInput,
    parameters: StorageParameters,
    solution: DispatchSolution,
    initial_soc_kwh: float,
    terminal_soc_min_kwh: float,
    terminal_soc_max_kwh: float | None = None,
    tolerance: float = 1e-5,
) -> None:
    """Raise an error when a dispatch violates physical or boundary constraints."""

    n = _validate_inputs(inputs, parameters)
    terminal_min, terminal_max = _validate_boundary_states(
        parameters, initial_soc_kwh, terminal_soc_min_kwh, terminal_soc_max_kwh
    )
    if tolerance < 0.0:
        raise ValueError("Validation tolerance must be nonnegative")
    flows = {
        "grid_kwh": np.asarray(solution.grid_kwh, dtype=float),
        "charge_kwh": np.asarray(solution.charge_kwh, dtype=float),
        "discharge_kwh": np.asarray(solution.discharge_kwh, dtype=float),
        "curtailment_kwh": np.asarray(solution.curtailment_kwh, dtype=float),
    }
    for name, values in flows.items():
        if values.shape != (n,) or not np.all(np.isfinite(values)):
            raise RuntimeError(f"{name} must contain {n} finite values")
    soc = np.asarray(solution.soc_kwh, dtype=float)
    if soc.shape != (n + 1,) or not np.all(np.isfinite(soc)):
        raise RuntimeError(f"soc_kwh must contain {n + 1} finite boundary states")
    if not np.isfinite(solution.total_cost_yuan):
        raise RuntimeError("Total cost must be finite")

    price = np.asarray(inputs.price_yuan_per_kwh, dtype=float)
    load = np.asarray(inputs.load_kwh, dtype=float)
    pv = np.asarray(inputs.pv_kwh, dtype=float)
    balance = flows["grid_kwh"] + pv + flows["discharge_kwh"] - load - flows["charge_kwh"] - flows["curtailment_kwh"]
    expected_next_soc = soc[:-1] + parameters.charge_efficiency * flows["charge_kwh"] - flows["discharge_kwh"] / parameters.discharge_efficiency
    checks = {
        "energy balance": float(np.max(np.abs(balance))),
        "SOC transition": float(np.max(np.abs(soc[1:] - expected_next_soc))),
        "initial SOC": abs(float(soc[0]) - initial_soc_kwh),
        "terminal minimum SOC": max(0.0, terminal_min - float(soc[-1])),
        "terminal maximum SOC": max(0.0, float(soc[-1]) - terminal_max),
        "total cost": abs(float(solution.total_cost_yuan) - float(np.dot(price, flows["grid_kwh"]))),
    }
    failed = {name: value for name, value in checks.items() if value > tolerance}
    if failed:
        raise RuntimeError(f"Dispatch validation failed: {failed}")
    if np.min(flows["grid_kwh"]) < -tolerance:
        raise RuntimeError("Grid purchase became negative")
    if np.min(flows["charge_kwh"]) < -tolerance or np.max(flows["charge_kwh"]) > parameters.max_slot_energy_kwh + tolerance:
        raise RuntimeError("Charge energy violates its slot bound")
    if np.min(flows["discharge_kwh"]) < -tolerance or np.max(flows["discharge_kwh"]) > parameters.max_slot_energy_kwh + tolerance:
        raise RuntimeError("Discharge energy violates its slot bound")
    if np.min(flows["curtailment_kwh"]) < -tolerance or np.any(flows["curtailment_kwh"] - pv > tolerance):
        raise RuntimeError("Curtailment violates photovoltaic availability")
    if np.min(soc) < parameters.min_soc_kwh - tolerance or np.max(soc) > parameters.max_soc_kwh + tolerance:
        raise RuntimeError("SOC violates storage bounds")
    if np.any(np.minimum(flows["charge_kwh"], flows["discharge_kwh"]) > tolerance):
        raise RuntimeError("The result contains simultaneous charging and discharging")
