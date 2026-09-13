"""Compact validation experiments for the paper's improvement directions."""

from __future__ import annotations

import json
from pathlib import Path

from question1 import load_question1_data
from question2_data import load_cold_start_forecast
from question4_2 import Question42Config, _evaluate, run_question42_baseline
from question4_2_data import load_question42_data
from question4_2_forecast import PriceForecastConfig


METHODS = ("previous_day", "seven_day", "week_type", "similar_day_decay", "expanding_mean")


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    a1 = root / "problems/C题/附件/附件1.xlsx"
    data = load_question42_data(
        root / "problems/C题/附件/附件2.xlsx",
        root / "problems/C题/附件/附件4.xlsx",
    )
    cold = load_cold_start_forecast(a1)
    fixed_price = load_question1_data(a1).price_yuan_per_kwh
    scores = {}
    for method in METHODS:
        result = run_question42_baseline(
            data,
            cold,
            fixed_price,
            Question42Config(price_forecast=PriceForecastConfig(method=method), max_days=31),
        )
        # Seven warm-up days, followed by a January-only causal decision validation.
        scores[method] = _evaluate(result.days[7:31])
    best_cost = min(scores[name]["total_cost_yuan"] for name in METHODS)
    # Cost is primary.  Forecasts within 0.1% of the minimum are economically
    # indistinguishable on the short calibration window, so RMSE breaks the tie.
    eligible = tuple(
        name for name in METHODS
        if scores[name]["total_cost_yuan"] <= best_cost * 1.001
    )
    selected = min(eligible, key=lambda name: scores[name]["price_rmse_yuan_per_kwh"])
    output = {
        "decision_oriented_price_selection": {
            "window": "2025-01-08--2025-01-31",
            "criterion": "downstream cost primary; methods within 0.1% use price RMSE as tie-break",
            "cost_indifference_band": 0.001,
            "eligible_methods": eligible,
            "selected_method": selected,
            "scores": scores,
        }
    }
    path = root / "src/outputs/innovation_summary.json"
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"selected={selected}")
    for method in METHODS:
        item = scores[method]
        print(method, item["total_cost_yuan"], item["dispatch_regret_yuan"])


if __name__ == "__main__":
    main()
