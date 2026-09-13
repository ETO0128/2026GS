"""Generate the official Question 4-2 comparison and workbook.

The formal strategy reuses Question 2's source/load forecast and uses a
seven-day causal price forecast. The oracle variant is a benchmark only.
"""
from __future__ import annotations

import json
from pathlib import Path

from fill_result2 import fill, verify
from question1 import load_question1_data
from question2 import Question2Config, evaluate_period, run_question2
from question2_data import load_cold_start_forecast, load_year_data
from question4_2 import Question42Config, _evaluate, run_question42_baseline
from question4_2_data import load_question42_data, summarize_prices
from question4_2_forecast import PriceForecastConfig, calibrate_price_method

METHODS = {
    "volatile_seven_day": "seven_day",
    "volatile_previous_day": "previous_day",
    "volatile_week_type": "week_type",
    "volatile_similar_decay": "similar_day_decay",
    "volatile_expanding_mean": "expanding_mean",
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def compact(metrics: dict) -> dict:
    return {
        "plan_cost": float(metrics.get("normal_purchase_cost_yuan", metrics.get("planned_cost_yuan", 0.0))),
        "emg_cost": float(metrics["emergency_cost_yuan"]),
        "emg_kwh": float(metrics.get("emergency_purchase_kwh", 0.0)),
        "total": float(metrics["total_cost_yuan"]),
        **{k: float(v) for k, v in metrics.items() if k.startswith("price_")},
    }


def workbook_days(records) -> list[dict]:
    return [{
        "date": r.date, "g": r.plan.grid_kwh,
        "charge": r.execution.charge_kwh, "discharge": r.execution.discharge_kwh,
        "soc_start": float(r.execution.soc_kwh[0]), "soc_end": float(r.execution.soc_kwh[-1]),
        "shortfall": r.execution.emergency_kwh,
        "plan_cost": r.execution.normal_purchase_cost_yuan,
        "emg_cost": r.execution.emergency_cost_yuan,
    } for r in records]


def main() -> None:
    root = project_root()
    a1 = root / "problems/C题/附件/附件1.xlsx"
    a2 = root / "problems/C题/附件/附件2.xlsx"
    a4 = root / "problems/C题/附件/附件4.xlsx"
    cold = load_cold_start_forecast(a1)
    q1 = load_question1_data(a1)
    data = load_question42_data(a2, a4)
    selected_method, calibration = calibrate_price_method(data)
    if selected_method != "seven_day":
        raise RuntimeError(f"Locked January calibration selected unexpected method: {selected_method}")

    fixed = run_question2(load_year_data(a1, a2), Question2Config(), cold)
    variants: dict[str, dict] = {"fixed_price": compact(evaluate_period(fixed.official_days))}
    selected = None
    for key, method in METHODS.items():
        result = run_question42_baseline(
            data, cold, q1.price_yuan_per_kwh,
            Question42Config(price_forecast=PriceForecastConfig(method=method)),
        )
        variants[key] = compact(_evaluate(result.official_days))
        if method == "seven_day":
            selected = result
    oracle = run_question42_baseline(
        data, cold, q1.price_yuan_per_kwh,
        Question42Config(price_information="oracle_benchmark"),
    )
    variants["volatile_oracle_benchmark"] = compact(_evaluate(oracle.official_days))
    assert selected is not None
    perfect_bound = float(sum(r.perfect_information.total_cost_yuan for r in selected.official_days))
    summary = {
        "window": [str(selected.official_days[0].date), str(selected.official_days[-1].date), len(selected.official_days)],
        "formal_variant": "volatile_seven_day",
        "price_calibration": {
            "window": "2025-01-08--2025-01-31",
            "criterion": "minimum RMSE; MAE and bias reported for audit",
            "selected_method": selected_method,
            "scores": calibration,
        },
        "information_boundary": "At 00:00 only prices realized through the previous day are available.",
        "price_stats": summarize_prices(data),
        "perfect_bound": {"total": perfect_bound}, "variants": variants,
    }
    lines = ["问题四 4-2：统一问题二源荷预测后的波动电价日前调度", ""]
    for key, value in variants.items():
        lines.append(f"{key}: 计划购电费 {value['plan_cost']:,.2f}，紧急购电费 {value['emg_cost']:,.2f}，合计 {value['total']:,.2f}")
    lines += ["", f"完全信息下界: {perfect_bound:,.2f}",
              "正式方案: volatile_seven_day；oracle 仅作不可实施的信息基准。"]
    out_dir = root / "src/outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "q4_2_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "q4_2_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    days = workbook_days(selected.official_days)
    output_book = root / "src/附件5/result4-2.xlsx"
    fill(root / "problems/C题/附件/附件5/result4-2.xlsx", output_book, days, "causal-seven-day")
    verify(output_book, days)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
