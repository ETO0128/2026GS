"""问题 4-2：四种因果电价预测口径的全年费用比较（官方 Q2 源荷预测 + 条件残差）。

运行：python src/py/q4_2_price_forecast_compare.py
输出：src/outputs/q4_2_price_forecast_compare.json / .txt
"""
from __future__ import annotations

import json
from pathlib import Path

from question1 import load_question1_data
from question2_data import load_cold_start_forecast
from question4_2 import Question42Config, run_question42_baseline, _evaluate
from question4_2_data import load_question42_data
from question4_2_forecast import PriceForecastConfig

METHODS = ["previous_day", "seven_day", "week_type", "similar_day_decay"]
CN = {"previous_day": "前一日同一时刻", "seven_day": "七日均值", "week_type": "星期类型均值",
      "similar_day_decay": "相似日 + 时间衰减"}


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    att = root / "problems" / "C题" / "附件"
    q1 = load_question1_data(att / "附件1.xlsx")
    data = load_question42_data(att / "附件2.xlsx", att / "附件4.xlsx")
    cold = load_cold_start_forecast(att / "附件1.xlsx")

    out: dict = {"days": 334, "variants": {}}
    lines = ["问题 4-2：因果电价预测口径比较（334 天，官方源荷预测 + 条件残差 80% 分位）", ""]
    lines.append(f"{'电价预测方法':<20}{'价格MAE':>10}{'正常购电/元':>16}{'紧急购电/元':>16}"
                 f"{'合计/元':>16}{'调度遗憾/元':>16}")
    for m in METHODS:
        cfg = Question42Config(price_forecast=PriceForecastConfig(method=m))
        res = run_question42_baseline(data, cold, cold_start_price_yuan_per_kwh=q1.price_yuan_per_kwh,
                                      config=cfg)
        met = _evaluate(res.official_days)
        out["variants"][m] = met
        lines.append(f"{CN[m]:<20}{met['price_mae_yuan_per_kwh']:>10.5f}"
                     f"{met['normal_purchase_cost_yuan']:>16,.2f}"
                     f"{met['emergency_cost_yuan']:>16,.2f}"
                     f"{met['total_cost_yuan']:>16,.2f}"
                     f"{met['dispatch_regret_yuan']:>16,.2f}")
        print(lines[-1], flush=True)

    best = min(out["variants"], key=lambda k: out["variants"][k]["total_cost_yuan"])
    lines += ["", f"最优口径：{CN[best]}（{out['variants'][best]['total_cost_yuan']:,.2f} 元）",
              f"完全信息下界（各口径相同）：{out['variants'][best]['perfect_information_cost_yuan']:,.2f} 元"]
    (root / "src" / "outputs" / "q4_2_price_forecast_compare.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (root / "src" / "outputs" / "q4_2_price_forecast_compare.txt").write_text(
        "\n".join(lines), encoding="utf-8")
    print("\n".join(lines[-3:]))


if __name__ == "__main__":
    main()
