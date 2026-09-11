"""Safe high-level Q-learning experiment for Question 4-2.

The agent selects only the next-day SOC reserve.  The common LP produces all
144 physical controls, so Q-learning can never violate storage constraints.
Training uses January--June, model selection uses July--August, and the frozen
test interval is September--December.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from question1 import load_question1_data
from question2_data import ColdStartForecast, YearData, load_cold_start_forecast
from question2_forecast import ForecastConfig, apply_conditional_residual_quantile, forecast_day
from question4_2 import _cold_start_price_result
from question4_2_data import Question42Data, load_question42_data
from question4_2_dispatch import plan_causal_day, settle_causal_plan
from question4_2_forecast import PriceForecastConfig, forecast_price


RESERVES = np.asarray([3600.0, 4800.0, 6000.0, 7200.0, 8400.0])
_STEP_CACHE: dict[tuple[int, float, float], tuple[float, float, float]] = {}


@dataclass(frozen=True)
class KnownDay:
    index: int
    net_kw: np.ndarray
    predicted_price: np.ndarray
    actual_price: np.ndarray
    actual_load: np.ndarray
    actual_pv: np.ndarray


def prepare_days(data: Question42Data, cold: ColdStartForecast, cold_price: np.ndarray) -> list[KnownDay]:
    source = YearData(data.dates, data.minute_of_day, cold_price, data.load_kw, data.pv_kw)
    days = []
    cfg = ForecastConfig(method="seven_day", planning_method="conditional_residual")
    history_dates, history_points, history_residuals = [], [], []
    for i, run_date in enumerate(data.dates):
        fc = forecast_day(source, i, cfg, cold.load_kw, cold.pv_kw)
        point_net = fc.load_kw - fc.pv_kw
        if history_dates:
            fc = apply_conditional_residual_quantile(
                fc, run_date, tuple(history_dates), np.stack(history_points),
                np.stack(history_residuals), cfg)
        pf = _cold_start_price_result(run_date, cold_price) if i == 0 else forecast_price(
            data, i, PriceForecastConfig(method="seven_day"))
        days.append(KnownDay(i, fc.planning_net_kw, pf.price_yuan_per_kwh,
                             data.price_yuan_per_kwh[i], data.load_kw[i], data.pv_kw[i]))
        history_dates.append(run_date)
        history_points.append(point_net.copy())
        history_residuals.append(data.load_kw[i] - data.pv_kw[i] - point_net)
    return days


def state_of(data: Question42Data, day: KnownDay, soc: float, previous_price_mae: float) -> tuple[int, int, int]:
    spread = float(np.max(day.predicted_price) - np.min(day.predicted_price))
    spread_bin = int(np.digitize(spread, [0.9, 1.1]))
    error_bin = int(np.digitize(previous_price_mae, [0.06, 0.10]))
    soc_bin = int(np.digitize(soc, [4800.0, 7200.0]))
    return spread_bin, error_bin, soc_bin


def step(data: Question42Data, day: KnownDay, soc: float, reserve: float):
    key = (day.index, round(float(soc), 6), float(reserve))
    if key in _STEP_CACHE:
        return _STEP_CACHE[key]
    plan = plan_causal_day(data.dates[day.index], day.net_kw, day.predicted_price,
                           initial_soc_kwh=soc, reserve_kwh=reserve)
    execution = settle_causal_plan(plan, day.actual_load, day.actual_pv, day.actual_price)
    mae = float(np.mean(np.abs(day.predicted_price - day.actual_price)))
    result = execution.total_cost_yuan, float(execution.soc_kwh[-1]), mae
    _STEP_CACHE[key] = result
    return result


def train(data, days, seed: int, episodes: int = 80, alpha: float = 0.12,
          gamma: float = 1.0, epsilon: float = 0.20):
    rng = np.random.default_rng(seed)
    q: dict[tuple[int, int, int], np.ndarray] = {}
    train_days = [day for day in days if data.dates[day.index] <= date(2025, 6, 30)]
    for _ in range(episodes):
        soc, last_mae = 6000.0, 0.08
        for pos, day in enumerate(train_days):
            state = state_of(data, day, soc, last_mae)
            values = q.setdefault(state, np.zeros(len(RESERVES)))
            action = int(rng.integers(len(RESERVES))) if rng.random() < epsilon else int(np.argmin(values))
            cost, next_soc, next_mae = step(data, day, soc, RESERVES[action])
            stage_cost = cost / 100000.0
            if pos + 1 < len(train_days):
                nxt = state_of(data, train_days[pos + 1], next_soc, next_mae)
                target = stage_cost + gamma * float(np.min(q.setdefault(nxt, np.zeros(len(RESERVES)))))
            else:
                target = stage_cost
            values[action] += alpha * (target - values[action])
            soc, last_mae = next_soc, next_mae
    return q


def evaluate(data, days, q=None, fixed_reserve=None, start=date(2025, 9, 1), end=date(2025, 12, 31)):
    selected = [day for day in days if start <= data.dates[day.index] <= end]
    soc, last_mae, total = 6000.0, 0.08, 0.0
    counts = np.zeros(len(RESERVES), dtype=int)
    daily = []
    for day in selected:
        if fixed_reserve is None:
            values = q.get(state_of(data, day, soc, last_mae), np.zeros(len(RESERVES)))
            action = int(np.argmin(values))
        else:
            action = int(np.argmin(np.abs(RESERVES - fixed_reserve)))
        cost, soc, last_mae = step(data, day, soc, RESERVES[action])
        total += cost
        counts[action] += 1
        daily.append(cost)
    return {"total_yuan": total, "mean_daily_yuan": total / len(selected),
            "reserve_counts": counts.tolist(), "daily_cost_yuan": daily}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", default="7,17,27,37,47")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    a = root / "problems" / "C题" / "附件"
    data = load_question42_data(a / "附件2.xlsx", a / "附件4.xlsx")
    cold = load_cold_start_forecast(a / "附件1.xlsx")
    cold_price = load_question1_data(a / "附件1.xlsx").price_yuan_per_kwh
    days = prepare_days(data, cold, cold_price)
    fixed = {str(int(r)): evaluate(data, days, fixed_reserve=r) for r in RESERVES}
    runs = []
    for seed in map(int, args.seeds.split(",")):
        print(f"training seed {seed}", flush=True)
        runs.append({"seed": seed, **evaluate(data, days, q=train(data, days, seed))})
    totals = np.asarray([run["total_yuan"] for run in runs])
    result = {"split": "train Jan-Jun; frozen test Sep-Dec", "fixed_reserve": fixed,
              "rl_runs": runs, "rl_mean_yuan": float(totals.mean()),
              "rl_std_yuan": float(totals.std(ddof=1)),
              "best_fixed_yuan": min(item["total_yuan"] for item in fixed.values())}
    result["rl_gain_vs_best_fixed_yuan"] = result["best_fixed_yuan"] - result["rl_mean_yuan"]
    out = args.out or root / "src" / "outputs" / "question4_2_rl.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rl_runs"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
