"""Causal experiments for Question 4 innovation candidates.

The script does not overwrite any official result workbook.  It compares:
1) the locked seven-day price forecast baseline;
2) an online exponential-weight ensemble whose expert loss is realized dispatch cost;
3) whole-day scenarios coupling price, load and PV residuals from the same historical day.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import lil_matrix

from microgrid_core import DispatchInput, StorageParameters, solve_dispatch
from question1 import load_question1_data
from question2_data import YearData, load_cold_start_forecast
from question2_forecast import (ForecastConfig, ForecastResult,
                                apply_conditional_residual_quantile, forecast_day)
from question2_scenarios import ScenarioSet, build_joint_residual_scenarios
from question4_2 import INITIAL_SOC_KWH, OFFICIAL_START
from question4_2_data import Question42Data, load_question42_data
from question4_2_dispatch import Question42Plan, plan_causal_day, settle_causal_plan
from question4_2_forecast import PriceForecastConfig, forecast_price


METHODS = ("previous_day", "seven_day", "week_type", "similar_day_decay", "expanding_mean")
FORECAST_CONFIG = ForecastConfig(method="seven_day", planning_method="conditional_residual")


@dataclass(frozen=True)
class DailyCost:
    day: date
    total: float
    emergency_cost: float
    emergency_kwh: float
    end_soc_kwh: float


def source_forecast(data: Question42Data, cold, index: int, history: dict) -> object:
    year = YearData(data.dates, data.minute_of_day, np.zeros(144), data.load_kw, data.pv_kw)
    fc = forecast_day(year, index, FORECAST_CONFIG,
                      cold_start_load_kw=cold.load_kw, cold_start_pv_kw=cold.pv_kw)
    point_net = fc.load_kw - fc.pv_kw
    if history["dates"]:
        fc = apply_conditional_residual_quantile(
            fc, data.dates[index], tuple(history["dates"]),
            np.stack(history["point_net"]), np.stack(history["net_residual"]), FORECAST_CONFIG)
    return fc, point_net


def update_source_history(history: dict, data: Question42Data, index: int, fc, point_net) -> None:
    history["dates"].append(data.dates[index])
    history["actual_load"].append(data.load_kw[index].copy())
    history["actual_pv"].append(data.pv_kw[index].copy())
    history["load_residual"].append(data.load_kw[index] - fc.load_kw)
    history["pv_residual"].append(data.pv_kw[index] - fc.pv_kw)
    history["point_net"].append(point_net.copy())
    history["net_residual"].append(data.load_kw[index] - data.pv_kw[index] - point_net)


def empty_history() -> dict:
    return {key: [] for key in ("dates", "actual_load", "actual_pv", "load_residual",
                                "pv_residual", "point_net", "net_residual")}


def price_candidates(data: Question42Data, cold_price: np.ndarray, index: int) -> np.ndarray:
    if index == 0:
        return np.repeat(cold_price[None, :], len(METHODS), axis=0)
    return np.stack([forecast_price(data, index, PriceForecastConfig(method=m)).price_yuan_per_kwh
                     for m in METHODS])


def execute(run_date, fc, price_fc, data, index, soc) -> tuple[Question42Plan, object]:
    plan = plan_causal_day(run_date, fc.planning_net_kw, price_fc, soc)
    execution = settle_causal_plan(plan, data.load_kw[index], data.pv_kw[index],
                                   data.price_yuan_per_kwh[index])
    return plan, execution


def run_baseline(data: Question42Data, cold, cold_price: np.ndarray) -> list[DailyCost]:
    history, soc, out = empty_history(), INITIAL_SOC_KWH, []
    for i, run_date in enumerate(data.dates):
        fc, point_net = source_forecast(data, cold, i, history)
        price = cold_price if i == 0 else forecast_price(
            data, i, PriceForecastConfig(method="seven_day")).price_yuan_per_kwh
        plan, execution = execute(run_date, fc, price, data, i, soc)
        out.append(DailyCost(run_date, execution.total_cost_yuan, execution.emergency_cost_yuan,
                             float(execution.emergency_kwh.sum()), float(plan.soc_kwh[-1])))
        update_source_history(history, data, i, fc, point_net)
        soc = float(plan.soc_kwh[-1])
    return out


def run_online_ensemble(data: Question42Data, cold, cold_price: np.ndarray,
                        eta: float, loss_scale: float = 1000.0,
                        max_days: int | None = None) -> list[DailyCost]:
    history, soc, out = empty_history(), INITIAL_SOC_KWH, []
    log_weights = np.zeros(len(METHODS))
    day_count = len(data.dates) if max_days is None else min(max_days, len(data.dates))
    for i, run_date in enumerate(data.dates[:day_count]):
        fc, point_net = source_forecast(data, cold, i, history)
        candidates = price_candidates(data, cold_price, i)
        weights = np.exp(log_weights - np.max(log_weights))
        weights /= weights.sum()
        ensemble_price = weights @ candidates
        plan, execution = execute(run_date, fc, ensemble_price, data, i, soc)
        out.append(DailyCost(run_date, execution.total_cost_yuan, execution.emergency_cost_yuan,
                             float(execution.emergency_kwh.sum()), float(plan.soc_kwh[-1])))

        # Full-information expert feedback is available only after the day closes.
        expert_loss = np.empty(len(METHODS))
        for k, candidate in enumerate(candidates):
            _, counterfactual = execute(run_date, fc, candidate, data, i, soc)
            expert_loss[k] = counterfactual.total_cost_yuan
        centered = expert_loss - np.min(expert_loss)
        log_weights -= eta * centered / loss_scale
        log_weights -= np.max(log_weights)

        update_source_history(history, data, i, fc, point_net)
        soc = float(plan.soc_kwh[-1])
    return out


def coupled_plan(run_date: date, scenarios: ScenarioSet, price_scenarios: np.ndarray,
                 initial_soc: float, reserve: float = 6000.0,
                 emergency_multiplier: float = 5.0) -> Question42Plan:
    """Shared day-ahead actions with scenario-specific price and emergency settlement."""
    params, n, s = StorageParameters(), 144, len(scenarios.items)
    probabilities = scenarios.probabilities
    grid, charge, discharge = slice(0, n), slice(n, 2*n), slice(2*n, 3*n)
    soc_start, emergency_start = 3*n, 4*n + 1
    surplus_start, nv = emergency_start + s*n, emergency_start + 2*s*n
    eq = lil_matrix((s*n+n, nv), dtype=float)
    rhs = np.zeros(s*n+n)
    for k, scenario in enumerate(scenarios.items):
        for t in range(n):
            row = k*n+t
            eq[row, t], eq[row, n+t], eq[row, 2*n+t] = 1.0, -1.0, 1.0
            eq[row, emergency_start+k*n+t], eq[row, surplus_start+k*n+t] = 1.0, -1.0
            rhs[row] = (scenario.load_kw[t]-scenario.pv_kw[t])/6.0
    for t in range(n):
        row = s*n+t
        eq[row, soc_start+t], eq[row, soc_start+t+1] = -1.0, 1.0
        eq[row, n+t] = -params.charge_efficiency
        eq[row, 2*n+t] = 1.0/params.discharge_efficiency
    bounds = [(0.0, None)]*n
    bounds += [(0.0, params.max_slot_energy_kwh)]*(2*n)
    bounds += [(initial_soc, initial_soc)]
    bounds += [(params.min_soc_kwh, params.max_soc_kwh)]*(n-1)
    bounds += [(reserve, params.max_soc_kwh)]
    bounds += [(0.0, None)]*(2*s*n)
    cost = np.zeros(nv)
    cost[grid] = probabilities @ price_scenarios
    for k in range(s):
        cost[emergency_start+k*n:emergency_start+(k+1)*n] = (
            emergency_multiplier*probabilities[k]*price_scenarios[k])
    result = linprog(cost, A_eq=eq.tocsr(), b_eq=rhs, bounds=bounds, method="highs")
    if not result.success:
        raise RuntimeError(f"coupled LP failed on {run_date}: {result.message}")
    x = result.x
    mean_price = probabilities @ price_scenarios
    return Question42Plan(run_date, mean_price, x[grid].copy(), x[charge].copy(),
                          x[discharge].copy(), np.zeros(n),
                          x[soc_start:soc_start+n+1].copy(), float(mean_price @ x[grid]))


def run_coupled_scenarios(data: Question42Data, cold, cold_price: np.ndarray,
                          scenario_count: int = 14, decay: float = 0.95,
                          window_days: int = 90) -> list[DailyCost]:
    history, soc, out = empty_history(), INITIAL_SOC_KWH, []
    price_residuals: list[np.ndarray] = []
    for i, run_date in enumerate(data.dates):
        fc, point_net = source_forecast(data, cold, i, history)
        price_fc = cold_price if i == 0 else forecast_price(
            data, i, PriceForecastConfig(method="seven_day")).price_yuan_per_kwh
        if not history["dates"]:
            plan, execution = execute(run_date, fc, price_fc, data, i, soc)
        else:
            scenarios = build_joint_residual_scenarios(
                tuple(history["dates"]), np.stack(history["actual_load"]),
                np.stack(history["actual_pv"]), np.stack(history["load_residual"]),
                np.stack(history["pv_residual"]), fc, run_date,
                max_scenarios=scenario_count, decay=decay, window_days=window_days)
            index_by_date = {d: k for k, d in enumerate(history["dates"])}
            prices = np.stack([np.maximum(price_fc + price_residuals[index_by_date[item.source_date]], 0.0)
                               for item in scenarios.items])
            plan = coupled_plan(run_date, scenarios, prices, soc)
            execution = settle_causal_plan(plan, data.load_kw[i], data.pv_kw[i], data.price_yuan_per_kwh[i])
        out.append(DailyCost(run_date, execution.total_cost_yuan, execution.emergency_cost_yuan,
                             float(execution.emergency_kwh.sum()), float(plan.soc_kwh[-1])))
        update_source_history(history, data, i, fc, point_net)
        price_residuals.append(data.price_yuan_per_kwh[i] - price_fc)
        soc = float(plan.soc_kwh[-1])
    return out


def forecast_unseen_date(data: Question42Data, cutoff: int, target: date,
                         values: np.ndarray, method: str, cold_curve: np.ndarray) -> np.ndarray:
    """Forecast a known calendar date using rows strictly before ``cutoff``."""
    if cutoff < 1:
        return np.asarray(cold_curve, dtype=float).copy()
    eligible = np.arange(max(0, cutoff-90), cutoff)
    if method == "seven_day":
        selected = np.arange(max(0, cutoff-7), cutoff)
    elif method == "week_type":
        target_weekend = target.weekday() >= 5
        selected = eligible[np.array([(data.dates[k].weekday() >= 5) == target_weekend
                                      for k in eligible])]
        if selected.size < 2:
            selected = np.arange(max(0, cutoff-7), cutoff)
    else:
        raise ValueError(method)
    return np.mean(values[selected], axis=0)


def run_two_day_lookahead(data: Question42Data, cold, cold_price: np.ndarray,
                          tomorrow_method: str = "week_type", end_reserve: float = 6000.0,
                          max_days: int | None = None) -> list[DailyCost]:
    """Receding two-day LP; tomorrow's curves use no realization from today."""
    history, soc, out = empty_history(), INITIAL_SOC_KWH, []
    params = StorageParameters()
    count = len(data.dates) if max_days is None else min(max_days, len(data.dates))
    for i, run_date in enumerate(data.dates[:count]):
        fc, point_net = source_forecast(data, cold, i, history)
        price_today = cold_price if i == 0 else forecast_price(
            data, i, PriceForecastConfig(method="seven_day")).price_yuan_per_kwh
        if i == len(data.dates)-1:
            plan, execution = execute(run_date, fc, price_today, data, i, soc)
        else:
            tomorrow = data.dates[i+1]
            load_next = forecast_unseen_date(data, i, tomorrow, data.load_kw, tomorrow_method, cold.load_kw)
            pv_next = forecast_unseen_date(data, i, tomorrow, data.pv_kw, tomorrow_method, cold.pv_kw)
            next_fc = ForecastResult(load_next, pv_next, load_next-pv_next,
                                     history["dates"][-1] if history["dates"] else None,
                                     f"causal_{tomorrow_method}", {}, (), None)
            if history["dates"]:
                next_fc = apply_conditional_residual_quantile(
                    next_fc, tomorrow, tuple(history["dates"]),
                    np.stack(history["point_net"]), np.stack(history["net_residual"]), FORECAST_CONFIG)
            price_next = forecast_unseen_date(data, i, tomorrow,
                                              data.price_yuan_per_kwh, tomorrow_method, cold_price)
            net = np.concatenate([fc.planning_net_kw, next_fc.planning_net_kw])
            price = np.concatenate([price_today, price_next])
            solved = solve_dispatch(
                DispatchInput(price, np.maximum(net, 0.0)/6.0, np.maximum(-net, 0.0)/6.0),
                params, initial_soc_kwh=soc, terminal_soc_min_kwh=end_reserve)
            plan = Question42Plan(run_date, price_today.copy(), solved.grid_kwh[:144].copy(),
                                  solved.charge_kwh[:144].copy(), solved.discharge_kwh[:144].copy(),
                                  solved.curtailment_kwh[:144].copy(), solved.soc_kwh[:145].copy(),
                                  float(price_today @ solved.grid_kwh[:144]))
            execution = settle_causal_plan(plan, data.load_kw[i], data.pv_kw[i],
                                           data.price_yuan_per_kwh[i])
        out.append(DailyCost(run_date, execution.total_cost_yuan, execution.emergency_cost_yuan,
                             float(execution.emergency_kwh.sum()), float(plan.soc_kwh[-1])))
        update_source_history(history, data, i, fc, point_net)
        soc = float(plan.soc_kwh[-1])
    return out


def metrics(values: list[DailyCost], baseline: list[DailyCost] | None = None) -> dict:
    selected = [x for x in values if x.day >= OFFICIAL_START]
    costs = np.array([x.total for x in selected])
    result = {
        "days": len(selected), "total_cost_yuan": float(costs.sum()),
        "emergency_cost_yuan": float(sum(x.emergency_cost for x in selected)),
        "emergency_kwh": float(sum(x.emergency_kwh for x in selected)),
        "worst_5pct_daily_mean_yuan": float(np.mean(np.sort(costs)[-max(1, int(np.ceil(.05*len(costs)))):])),
        "half_year_cost_yuan": [float(costs[:len(costs)//2].sum()), float(costs[len(costs)//2:].sum())],
        "quarter_cost_yuan": [float(chunk.sum()) for chunk in np.array_split(costs, 4)],
        "end_soc_min_mean_max_kwh": [float(np.min([x.end_soc_kwh for x in selected])),
                                      float(np.mean([x.end_soc_kwh for x in selected])),
                                      float(np.max([x.end_soc_kwh for x in selected]))],
        "final_soc_kwh": float(selected[-1].end_soc_kwh),
    }
    if baseline is not None:
        base = np.array([x.total for x in baseline if x.day >= OFFICIAL_START])
        delta = costs-base
        rng = np.random.default_rng(20260912)
        iid = np.array([delta[rng.integers(0, len(delta), len(delta))].sum() for _ in range(5000)])
        block = 7
        starts = np.arange(len(delta)-block+1)
        moving = []
        for _ in range(5000):
            sample = []
            while len(sample) < len(delta):
                start = int(rng.choice(starts))
                sample.extend(delta[start:start+block])
            moving.append(np.sum(sample[:len(delta)]))
        result.update({"delta_yuan": float(delta.sum()), "improvement_pct": float(-delta.sum()/base.sum()*100),
                       "daily_win_rate": float(np.mean(delta < -1e-6)),
                       "daily_delta_median_yuan": float(np.median(delta)),
                       "iid_bootstrap_delta_95pct_yuan": [float(x) for x in np.quantile(iid, [.025,.975])],
                       "moving_block_7d_delta_95pct_yuan": [float(x) for x in np.quantile(moving, [.025,.975])],
                       "monthly_delta_yuan": [float(delta[[x.day.month == month for x in selected]].sum())
                                              for month in range(2,13)]})
    return result


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    a = root / "problems" / "C题" / "附件"
    data = load_question42_data(a/"附件2.xlsx", a/"附件4.xlsx")
    cold, cold_price = load_cold_start_forecast(a/"附件1.xlsx"), load_question1_data(a/"附件1.xlsx").price_yuan_per_kwh
    baseline = run_baseline(data, cold, cold_price)

    # Eta is selected using Jan 8--31 only; February--December remain locked test data.
    eta_grid = (0.1, 0.25, 0.5, 1.0, 2.0)
    candidates = {}
    ensemble_runs = {}
    for eta in eta_grid:
        run = run_online_ensemble(data, cold, cold_price, eta, max_days=31)
        candidates[str(eta)] = float(sum(x.total for x in run if date(2025,1,8) <= x.day <= date(2025,1,31)))
    selected_eta = min(eta_grid, key=lambda x: candidates[str(x)])
    ensemble_runs[selected_eta] = run_online_ensemble(data, cold, cold_price, selected_eta)
    coupled = run_coupled_scenarios(data, cold, cold_price)

    lookahead_grid = ((method, reserve) for method in ("seven_day", "week_type")
                      for reserve in (4000.0, 6000.0, 8000.0))
    lookahead_scores = {}
    for method, reserve in lookahead_grid:
        run = run_two_day_lookahead(data, cold, cold_price, method, reserve, max_days=31)
        lookahead_scores[f"{method},reserve={reserve:.0f}"] = float(sum(
            x.total for x in run if date(2025,1,8) <= x.day <= date(2025,1,31)))
    selected_lookahead = min(lookahead_scores, key=lookahead_scores.get)
    selected_method, reserve_text = selected_lookahead.split(",reserve=")
    lookahead = run_two_day_lookahead(data, cold, cold_price, selected_method, float(reserve_text))
    report = {
        "baseline": metrics(baseline),
        "online_ensemble_calibration": {"scores": candidates, "selected_eta": selected_eta},
        "online_ensemble": metrics(ensemble_runs[selected_eta], baseline),
        "coupled_scenarios": metrics(coupled, baseline),
        "two_day_lookahead_calibration": {"scores": lookahead_scores, "selected": selected_lookahead},
        "two_day_lookahead": metrics(lookahead, baseline),
    }
    output = root / "src" / "outputs" / "q4_innovation_experiment.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
