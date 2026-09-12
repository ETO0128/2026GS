"""把问题四 4-3（波动电价下的滚动调整）结果回填到官方模板 result4-3.xlsx。

模板与 result3.xlsx 完全同构（计划购电量 / 调整购电量 / 充放电量 / 紧急购电量 四张表），
因此直接复用 ``fill_result3.fill`` 与 ``fill_result3.verify``，只是把电价换成附件4 的波动电价。

价格信息口径（默认经一月校准选定的 seven_day）
---------------------------
``seven_day``：用最近七日已实现价格的逐时段均值预测（正式提交口径）；
``profile``  ：用决策日前历史价格的逐时段扩展均值预测（对照）；
``oracle``   ：0:00 即知当天全部时段电价（仅作不可实施的信息基准）；
``prev_day`` ：只用前一日实际电价作预测（因果，作为稳健性对照）。

用法：
    python src/py/fill_result4_3.py                  # 近七日均值，择优调整（默认）
    python src/py/fill_result4_3.py --price-mode prev_day
    python src/py/fill_result4_3.py --limit 20        # 只填前 20 天（检查格式）
输出：src/附件5/result4-3.xlsx
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

import q2_model as q2
import q3_model as q3
import q4_model as q4
from fill_result3 import fill, verify


def compute_days(att: q2.Attachment, f3: q3.PvForecast3, p4: q4.Prices4,
                 price_mode: str, policy: str, s_max: int = 6,
                 limit: int | None = None) -> list[dict]:
    window = att.window[:limit] if limit else att.window
    days = []
    for i in window:
        r = q4.simulate_day4(att, f3, p4.day(i), i, price_mode, p4,
                             s_max=s_max, policy=policy)
        committed = r["q_adj"] + r["d_adj"] - r["c_adj"]
        shortfall = np.maximum(0.0, (att.load_kwh[i] - att.pv_kwh[i]) - committed)
        assert abs(shortfall.sum() - r["emg_kwh"]) < 1e-6, "紧急购电量与仿真不一致"
        days.append({
            "date": att.dates[i], "index": i,
            "q_plan": r["q_plan"], "q_adj": r["q_adj"],
            "charge": r["c_adj"], "discharge": r["d_adj"],
            "soc_start": float(r["e_adj"][0]), "soc_end": float(r["e_adj"][-1]),
            "shortfall": shortfall,
            "plan_cost": r["plan_cost"], "fee": r["fee"],
            "emg_kwh": r["emg_kwh"], "emg_cost": r["emg_cost"], "total": r["total"],
        })
    return days


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--price-mode", choices=list(q4.PRICE_MODES), default="seven_day")
    ap.add_argument("--policy", choices=["none", "fixed", "selective"], default="selective")
    ap.add_argument("--s-max", type=int, default=6)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--data-root", type=Path, default=None)
    ap.add_argument("--template", type=Path, default=None)
    ap.add_argument("--output", type=Path, default=None)
    args = ap.parse_args()

    root = Path(args.data_root) if args.data_root else q2.project_root()
    template = Path(args.template) if args.template else \
        root / "problems" / "C题" / "附件" / "附件5" / "result4-3.xlsx"
    output = Path(args.output) if args.output else root / "src" / "附件5" / "result4-3.xlsx"

    att = q2.Attachment(root)
    f3 = q3.PvForecast3(root)
    p4 = q4.Prices4(root, att)
    days = compute_days(att, f3, p4, args.price_mode, args.policy, args.s_max, args.limit)
    fill(template, output, days)
    print(f"已写入 {output}（价格口径 {q4.MODE_CN[args.price_mode]}，策略 {args.policy}，"
          f"{len(days)} 天）")
    verify(output, days, args.policy)


if __name__ == "__main__":
    main()
