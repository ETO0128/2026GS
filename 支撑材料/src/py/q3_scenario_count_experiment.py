"""问题三场景数稳定性与 18:00 节点增量效果实验。"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

import q2_model as q2
import q3_model as q3


SCENARIO_COUNTS = (3, 6, 9, 12, 18, 24)


def moving_block_interval(differences: np.ndarray, samples: int = 5000,
                          block: int = 7, seed: int = 20260912) -> list[float]:
    """返回全年费用差之和的循环移动块 Bootstrap 95% 区间。"""

    rng = np.random.default_rng(seed)
    starts = np.arange(len(differences))
    totals = np.empty(samples)
    for k in range(samples):
        selected: list[int] = []
        while len(selected) < len(differences):
            start = int(rng.choice(starts))
            selected.extend((start + offset) % len(differences) for offset in range(block))
        totals[k] = differences[np.asarray(selected[:len(differences)])].sum()
    return [float(value) for value in np.quantile(totals, [0.025, 0.975])]


def evaluate(att, forecast, scenario_count: int, node_subset=None, indices=None) -> dict:
    indices = list(att.window if indices is None else indices)
    started = time.perf_counter()
    fee = emergency_cost = emergency_kwh = 0.0
    adjustments = 0
    daily_totals: list[float] = []
    for position, day_index in enumerate(indices):
        if position % 50 == 0:
            print(f"  s={scenario_count}, nodes={node_subset}: {position}/{len(indices)}", flush=True)
        result = q3.simulate_day(
            att, forecast, att.price, day_index, s_max=scenario_count,
            policy="selective" if node_subset is None else "fixed",
            node_subset=node_subset,
        )
        fee += result["fee"]
        emergency_cost += result["emg_cost"]
        emergency_kwh += result["emg_kwh"]
        adjustments += sum(int(event["adjusted"]) for event in result["log"])
        daily_totals.append(float(result["total"]))
    return {
        "scenario_count": scenario_count,
        "fee_yuan": fee,
        "emergency_cost_yuan": emergency_cost,
        "emergency_kwh": emergency_kwh,
        "total_yuan": fee + emergency_cost,
        "runtime_seconds": time.perf_counter() - started,
        "adjustments": adjustments,
        "daily_total_yuan": daily_totals,
    }


def main() -> None:
    root = q2.project_root()
    att = q2.Attachment(root)
    forecast = q3.PvForecast3(root)

    calibration_indices = [index for index, day in enumerate(att.dates)
                           if "2025-01-15" <= str(day) <= "2025-01-31"]
    calibration_results = [evaluate(att, forecast, count, indices=calibration_indices)
                           for count in SCENARIO_COUNTS]
    selected_count = min(calibration_results, key=lambda result: result["total_yuan"])["scenario_count"]

    scenario_results = [evaluate(att, forecast, count) for count in SCENARIO_COUNTS]
    baseline = next(result for result in scenario_results if result["scenario_count"] == 6)
    for result in scenario_results:
        differences = np.asarray(result["daily_total_yuan"]) - np.asarray(baseline["daily_total_yuan"])
        result["difference_vs_6_yuan"] = float(differences.sum())
        result["difference_vs_6_ci95_yuan"] = moving_block_interval(differences)

    node_6_12 = evaluate(att, forecast, selected_count, node_subset=[1, 2])
    node_all = evaluate(att, forecast, selected_count, node_subset=[1, 2, 3])
    node_difference = np.asarray(node_all["daily_total_yuan"]) - np.asarray(node_6_12["daily_total_yuan"])
    node_result = {
        "six_and_twelve": node_6_12,
        "six_twelve_and_eighteen": node_all,
        "incremental_cost_of_1800_yuan": float(node_difference.sum()),
        "incremental_cost_ci95_yuan": moving_block_interval(node_difference),
        "days_1800_improves": int(np.sum(node_difference < 0.0)),
    }

    output = {"days": len(att.window),
              "calibration": {"window": ["2025-01-15", "2025-01-31"],
                              "results": calibration_results,
                              "selected_scenario_count": selected_count},
              "scenario_results": scenario_results,
              "node_1800": node_result}
    out_dir = root / "src" / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "q3_scenario_count_experiment.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = ["问题三场景数稳定性实验", "",
             f"1月15--31日因果校准选择：{selected_count} 个场景", "",
             "场景数  结算购电费/元  紧急购电量/kWh  总费用/元  运行时间/s  调整次数  相对6场景/元"]
    for result in scenario_results:
        lines.append(
            f"{result['scenario_count']:>6}  {result['fee_yuan']:>14,.2f}  "
            f"{result['emergency_kwh']:>15,.2f}  {result['total_yuan']:>12,.2f}  "
            f"{result['runtime_seconds']:>10.2f}  {result['adjustments']:>8}  "
            f"{result['difference_vs_6_yuan']:>12,.2f}"
        )
    lines += ["", f"加入 18:00 节点的实际费用变化：{node_result['incremental_cost_of_1800_yuan']:,.2f} 元",
              f"七日移动块 Bootstrap 95% 区间：{node_result['incremental_cost_ci95_yuan']}"]
    (out_dir / "q3_scenario_count_report.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
