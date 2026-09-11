"""Run the causal variable-price baseline for Question 4-2."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from question1 import load_question1_data
from question2_data import ColdStartForecast, YearData, load_cold_start_forecast
from question2_forecast import (ForecastConfig, ForecastResult,
                                apply_conditional_residual_quantile, forecast_day)
from question4_2_data import Question42Data, load_question42_data, summarize_prices
from question4_2_dispatch import (
    PerfectInformationResult,
    Question42Execution,
    Question42Plan,
    dispatch_regret_yuan,
    plan_causal_day,
    settle_causal_plan,
    solve_perfect_information_day,
)
from question4_2_forecast import (
    PriceForecastConfig,
    PriceForecastResult,
    forecast_price,
    price_forecast_metrics,
)


INITIAL_SOC_KWH = 6000.0
OFFICIAL_START = date(2025, 2, 1)


@dataclass(frozen=True)
class Question42Config:
    source_forecast: ForecastConfig = ForecastConfig(method="seven_day", planning_method="conditional_residual")
    price_forecast: PriceForecastConfig = PriceForecastConfig(method="seven_day")
    reserve_kwh: float = 6000.0
    emergency_multiplier: float = 5.0
    max_days: int | None = None


@dataclass(frozen=True)
class Question42DailyRecord:
    date: date
    source_forecast: ForecastResult
    price_forecast: PriceForecastResult
    plan: Question42Plan
    execution: Question42Execution
    perfect_information: PerfectInformationResult
    dispatch_regret_yuan: float


@dataclass(frozen=True)
class Question42YearResult:
    days: tuple[Question42DailyRecord, ...]
    metrics: dict[str, float | int]

    @property
    def official_days(self) -> tuple[Question42DailyRecord, ...]:
        return tuple(day for day in self.days if day.date >= OFFICIAL_START)


def _cold_start_price_result(
    decision_date: date,
    cold_start_price_yuan_per_kwh: np.ndarray,
) -> PriceForecastResult:
    price = np.asarray(cold_start_price_yuan_per_kwh, dtype=float)
    if price.shape != (144,) or not np.all(np.isfinite(price)) or np.any(price < 0.0):
        raise ValueError("Cold-start price must be a finite nonnegative 144-point vector")
    return PriceForecastResult(
        decision_date=decision_date,
        history_end_date=None,
        price_yuan_per_kwh=price.copy(),
        method="cold_start",
        source_dates=(),
        source_weights=np.asarray([], dtype=float),
        fallback_reason="no_realized_price_history",
    )


def _evaluate(days: tuple[Question42DailyRecord, ...]) -> dict[str, float | int]:
    if not days:
        raise ValueError("Question 4-2 evaluation requires at least one day")
    price_days = tuple(day for day in days if day.price_forecast.history_end_date is not None)
    if price_days:
        actual_prices = np.stack([day.execution.actual_price_yuan_per_kwh for day in price_days])
        predicted_prices = np.stack([day.price_forecast.price_yuan_per_kwh for day in price_days])
        price_metrics = price_forecast_metrics(actual_prices, predicted_prices)
    else:
        price_metrics = {
            "mae_yuan_per_kwh": 0.0,
            "rmse_yuan_per_kwh": 0.0,
            "bias_yuan_per_kwh": 0.0,
        }
    normal_cost = float(sum(day.execution.normal_purchase_cost_yuan for day in days))
    emergency_cost = float(sum(day.execution.emergency_cost_yuan for day in days))
    perfect_cost = float(sum(day.perfect_information.total_cost_yuan for day in days))
    return {
        "evaluated_days": len(days),
        "price_evaluated_days": len(price_days),
        "price_mae_yuan_per_kwh": price_metrics["mae_yuan_per_kwh"],
        "price_rmse_yuan_per_kwh": price_metrics["rmse_yuan_per_kwh"],
        "price_bias_yuan_per_kwh": price_metrics["bias_yuan_per_kwh"],
        "normal_purchase_cost_yuan": normal_cost,
        "emergency_cost_yuan": emergency_cost,
        "total_cost_yuan": normal_cost + emergency_cost,
        "perfect_information_cost_yuan": perfect_cost,
        "dispatch_regret_yuan": float(sum(day.dispatch_regret_yuan for day in days)),
        "constraint_violations": 0,
    }


def run_question42_baseline(
    data: Question42Data,
    cold_start: ColdStartForecast,
    cold_start_price_yuan_per_kwh: np.ndarray,
    config: Question42Config = Question42Config(),
) -> Question42YearResult:
    """Run fixed day-ahead plans in chronological order without future data."""

    total_days = len(data.dates) if config.max_days is None else min(config.max_days, len(data.dates))
    if total_days < 1:
        raise ValueError("Question 4-2 must run at least one day")
    source_data = YearData(
        dates=data.dates,
        minute_of_day=data.minute_of_day.copy(),
        price_yuan_per_kwh=np.asarray(cold_start_price_yuan_per_kwh, dtype=float).copy(),
        load_kw=data.load_kw,
        pv_kw=data.pv_kw,
    )
    carried_soc = INITIAL_SOC_KWH
    records: list[Question42DailyRecord] = []
    history_dates: list[date] = []
    history_point_net: list[np.ndarray] = []
    history_net_residual: list[np.ndarray] = []
    for index in range(total_days):
        run_date = data.dates[index]
        source_forecast = forecast_day(
            source_data,
            index,
            config.source_forecast,
            cold_start_load_kw=cold_start.load_kw,
            cold_start_pv_kw=cold_start.pv_kw,
        )
        point_net = source_forecast.load_kw - source_forecast.pv_kw
        if config.source_forecast.planning_method == "conditional_residual" and history_dates:
            source_forecast = apply_conditional_residual_quantile(
                source_forecast, run_date, tuple(history_dates),
                np.stack(history_point_net), np.stack(history_net_residual),
                config.source_forecast,
            )
        if index == 0:
            price_result = _cold_start_price_result(run_date, cold_start_price_yuan_per_kwh)
        else:
            price_result = forecast_price(data, index, config.price_forecast)
        plan = plan_causal_day(
            run_date,
            source_forecast.planning_net_kw,
            price_result.price_yuan_per_kwh,
            initial_soc_kwh=carried_soc,
            reserve_kwh=config.reserve_kwh,
        )
        execution = settle_causal_plan(
            plan,
            actual_load_kw=data.load_kw[index],
            actual_pv_kw=data.pv_kw[index],
            actual_price_yuan_per_kwh=data.price_yuan_per_kwh[index],
            emergency_multiplier=config.emergency_multiplier,
        )
        perfect = solve_perfect_information_day(
            run_date,
            actual_load_kw=data.load_kw[index],
            actual_pv_kw=data.pv_kw[index],
            actual_price_yuan_per_kwh=data.price_yuan_per_kwh[index],
            initial_soc_kwh=carried_soc,
            reserve_kwh=config.reserve_kwh,
        )
        regret = dispatch_regret_yuan(execution, perfect)
        records.append(Question42DailyRecord(
            date=run_date,
            source_forecast=source_forecast,
            price_forecast=price_result,
            plan=plan,
            execution=execution,
            perfect_information=perfect,
            dispatch_regret_yuan=regret,
        ))
        history_dates.append(run_date)
        history_point_net.append(point_net.copy())
        history_net_residual.append(data.load_kw[index] - data.pv_kw[index] - point_net)
        carried_soc = float(execution.soc_kwh[-1])
    completed = tuple(records)
    return Question42YearResult(completed, _evaluate(completed))


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    root = _project_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attachment1", type=Path, default=root / "problems/C题/附件/附件1.xlsx")
    parser.add_argument("--attachment2", type=Path, default=root / "problems/C题/附件/附件2.xlsx")
    parser.add_argument("--attachment4", type=Path, default=root / "problems/C题/附件/附件4.xlsx")
    parser.add_argument(
        "--price-forecast",
        choices=("previous_day", "seven_day", "week_type", "similar_day_decay"),
        default="seven_day",
    )
    parser.add_argument("--days", type=int)
    parser.add_argument("--reserve-kwh", type=float, default=6000.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    q1 = load_question1_data(args.attachment1)
    data = load_question42_data(args.attachment2, args.attachment4)
    result = run_question42_baseline(
        data,
        load_cold_start_forecast(args.attachment1),
        cold_start_price_yuan_per_kwh=q1.price_yuan_per_kwh,
        config=Question42Config(
            price_forecast=PriceForecastConfig(method=args.price_forecast),
            reserve_kwh=args.reserve_kwh,
            max_days=args.days,
        ),
    )
    print(json.dumps({
        "price_source": summarize_prices(data),
        "baseline": _evaluate(result.official_days) if result.official_days else result.metrics,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
