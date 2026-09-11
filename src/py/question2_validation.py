"""Validate the conditional-residual planning curve without touching result workbooks."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from question2 import Question2Config, evaluate_period, run_question2
from question2_data import load_cold_start_forecast, load_year_data
from question2_forecast import ForecastConfig


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
        for reserve in (4000.0, 6000.0, 8000.0)
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


if __name__ == "__main__":
    main()
