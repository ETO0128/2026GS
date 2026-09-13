"""Regenerate the auditable text report for the formal Question 2 model.

This entry point intentionally does not write ``result2.xlsx``.  The official
workbook is produced by ``question2.py --write-results`` after its formal
configuration guard has passed.
"""

from __future__ import annotations

from pathlib import Path

from question2 import OFFICIAL_START, Question2Config, run_question2
from question2_data import load_cold_start_forecast, load_year_data


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    attachment1 = root / "problems/C题/附件/附件1.xlsx"
    attachment2 = root / "problems/C题/附件/附件2.xlsx"
    output = root / "src/outputs/q2_report.txt"

    data = load_year_data(attachment1, attachment2)
    result = run_question2(data, Question2Config(), load_cold_start_forecast(attachment1))
    metrics = result.metrics
    meta = result.run_metadata
    lines = [
        "问题二正式方案可复核报告",
        "=" * 32,
        f"统计区间: {OFFICIAL_START.isoformat()}--2025-12-31（{len(result.official_days)} 天）",
        "信息边界: 每日 0:00 仅使用此前已实现的数据；全天计划与储能动作固定执行。",
        "点预测: 最近七日均值",
        "计划修正: 80% 条件残差加权分位数",
        f"残差候选日数: {meta['residual_candidate_count']}",
        f"指数衰减系数: {meta['residual_decay']:.2f}",
        f"日末储备下界: {Question2Config().reserve_kwh:.2f} kWh",
        f"紧急购电倍率: {Question2Config().emergency_multiplier:.2f}",
        "",
        f"计划购电量: {metrics['planned_purchase_kwh']:.2f} kWh",
        f"计划购电费: {metrics['planned_cost_yuan']:.2f} 元",
        f"紧急购电量: {metrics['emergency_purchase_kwh']:.2f} kWh",
        f"紧急购电费: {metrics['emergency_cost_yuan']:.2f} 元",
        f"总费用: {metrics['total_cost_yuan']:.2f} 元",
        f"净负荷 MAE: {metrics['net_mae_kw']:.2f} kW",
        f"净负荷 RMSE: {metrics['net_rmse_kw']:.2f} kW",
        f"净负荷 Bias: {metrics['net_bias_kw']:.2f} kW",
        "",
        "说明: 本文件由 src/py/run_question2.py 按正式默认参数重算生成；",
        "正文、result2.xlsx 与本报告必须使用同一配置。",
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"q2_report={output}")
    print(f"total_cost_yuan={metrics['total_cost_yuan']:.2f}")


if __name__ == "__main__":
    main()
