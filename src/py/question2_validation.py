"""Validate the conditional-residual planning curve without touching result workbooks."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import numpy as np

from question2 import INITIAL_SOC_KWH, DailyRecord, Question2Config, evaluate_period, run_question2
from question2_data import load_cold_start_forecast, load_year_data
from question2_dispatch import RealizedDay, plan_day_ahead, simulate_fixed_plan
from question2_forecast import ForecastConfig, ForecastResult


VALIDATION_START = date(2025, 2, 1)
VALIDATION_END = date(2025, 2, 28)
TEST_START = date(2025, 3, 1)
TEST_END = date(2025, 12, 31)


def _print_metrics(name: str, period: str, metrics: dict[str, float]) -> None:
    keys = (
        "planned_cost_yuan",
        "emergency_cost_yuan",
        "total_cost_yuan",
        "surplus_energy_kwh",
        "emergency_event_count",
        "soc_min_kwh",
        "soc_max_kwh",
    )
    values = ",".join(f"{metrics[key]:.6f}" for key in keys)
    print(f"{name},{period},{values}")


def run_perfect_information(data, reserve_kwh: float = 6000.0) -> tuple[DailyRecord, ...]:
    """Compute a causal-state, perfect-next-day-information cost lower benchmark."""

    carried_soc = INITIAL_SOC_KWH
    records: list[DailyRecord] = []
    for index, run_date in enumerate(data.dates):
        forecast = ForecastResult(
            load_kw=data.load_kw[index].copy(),
            pv_kw=data.pv_kw[index].copy(),
            planning_net_kw=(data.load_kw[index] - data.pv_kw[index]).copy(),
            history_end=run_date,
            method="perfect_information_benchmark",
            parameters={"reserve_kwh": reserve_kwh},
            candidate_dates=(),
            fallback_reason=None,
        )
        plan = plan_day_ahead(run_date, forecast, data.price_yuan_per_kwh, carried_soc, reserve_kwh)
        realized = RealizedDay(run_date, data.load_kwh[index].copy(), data.pv_kwh[index].copy())
        execution = simulate_fixed_plan(plan, realized, carried_soc, reserve_kwh=reserve_kwh)
        records.append(DailyRecord(run_date, forecast, plan, execution, data.load_kw[index], data.pv_kw[index]))
        carried_soc = float(execution.soc_kwh[-1])
    return tuple(records)


def paired_bootstrap(differences: np.ndarray, repetitions: int = 10_000) -> dict[str, float]:
    """Summarize paired daily cost differences with a reproducible percentile interval."""

    values = np.asarray(differences, dtype=float)
    generator = np.random.default_rng(20260911)
    means = np.empty(repetitions)
    for start in range(0, repetitions, 500):
        size = min(500, repetitions - start)
        samples = generator.choice(values, size=(size, values.size), replace=True)
        means[start : start + size] = samples.mean(axis=1)
    low, high = np.quantile(means, (0.025, 0.975))
    return {
        "days": float(values.size),
        "mean_daily_saving_yuan": float(values.mean()),
        "median_daily_saving_yuan": float(np.median(values)),
        "improved_day_fraction": float(np.mean(values > 0.0)),
        "bootstrap_95_low_yuan": float(low),
        "bootstrap_95_high_yuan": float(high),
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    attachment_directory = root / "problems" / "C题" / "附件"
    data = load_year_data(attachment_directory / "附件1.xlsx", attachment_directory / "附件2.xlsx")
    cold_start = load_cold_start_forecast(attachment_directory / "附件1.xlsx")
    conditional = ForecastConfig(
        method="seven_day",
        planning_method="conditional_residual",
        residual_candidate_count=42,
        residual_decay=0.95,
    )
    cases = (
        (
            "historical_net_6000",
            Question2Config(
                forecast=ForecastConfig(method="seven_day", planning_method="historical_net"),
                reserve_kwh=6000.0,
            ),
        ),
    ) + tuple(
        (f"conditional_{reserve:.0f}", Question2Config(forecast=conditional, reserve_kwh=reserve))
        for reserve in (1200.0, 4000.0, 6000.0, 8000.0, 10800.0)
    )
    print(
        "case,period,planned_cost_yuan,emergency_cost_yuan,total_cost_yuan,"
        "surplus_energy_kwh,emergency_event_count,soc_min_kwh,soc_max_kwh"
    )
    for name, config in cases:
        result = run_question2(data, config, cold_start)
        _print_metrics(
            name,
            "validation",
            evaluate_period(result.days, VALIDATION_START, VALIDATION_END),
        )
        _print_metrics(name, "test", evaluate_period(result.days, TEST_START, TEST_END))
        _print_metrics(
            name,
            "official",
            evaluate_period(result.days, VALIDATION_START, TEST_END),
        )

    official = run_question2(data, Question2Config(forecast=conditional, reserve_kwh=6000.0), cold_start)
    baseline = run_question2(
        data,
        Question2Config(
            forecast=ForecastConfig(method="seven_day", planning_method="historical_net"),
            reserve_kwh=6000.0,
        ),
        cold_start,
    )
    perfect = run_perfect_information(data, reserve_kwh=6000.0)
    official_days = tuple(item for item in official.days if VALIDATION_START <= item.date <= TEST_END)
    baseline_days = tuple(item for item in baseline.days if VALIDATION_START <= item.date <= TEST_END)
    perfect_days = tuple(item for item in perfect if VALIDATION_START <= item.date <= TEST_END)
    savings = np.asarray([base.execution.total_cost_yuan - final.execution.total_cost_yuan for base, final in zip(baseline_days, official_days, strict=True)])
    regret = np.asarray([final.execution.total_cost_yuan - lower.execution.total_cost_yuan for final, lower in zip(official_days, perfect_days, strict=True)])
    print("paired_bootstrap," + ",".join(f"{key}={value:.6f}" for key, value in paired_bootstrap(savings).items()))
    print(f"perfect_information_cost_yuan={sum(item.execution.total_cost_yuan for item in perfect_days):.6f}")
    print(f"official_dispatch_regret_yuan={regret.sum():.6f}")
    print(f"mean_daily_dispatch_regret_yuan={regret.mean():.6f}")
    print(f"median_daily_dispatch_regret_yuan={np.median(regret):.6f}")


if __name__ == "__main__":
    main()
