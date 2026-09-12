"""问题 4-3 口径 B：0:00 计划 + 储能日内因果滚动再调度（购电量照付不议）。

对比两种购电策略：
  none      —— 只在 0:00 定计划，之后不调整购电量（口径 B 下的最优候选）
  selective —— 仍在 6:00/12:00/18:00 择优调整购电量
价格信息口径默认 oracle（已知当天电价），与论文 4-3 章节一致。

运行：python src/py/run_q4_3_B.py [--limit 40] [--price-mode oracle]
输出：src/outputs/q4_3_B.json / q4_3_B.txt
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import q2_model as q2
import q3_model as q3
import q4_model as q4


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--price-mode", default="oracle", choices=list(q4.PRICE_MODES))
    ap.add_argument("--policies", default="none,selective")
    args = ap.parse_args()

    root = q2.project_root()
    att = q2.Attachment(root)
    f3 = q3.PvForecast3(root)
    p4 = q4.Prices4(root, att)
    win = att.window[:args.limit] if args.limit else att.window

    out: dict = {"window": [str(att.dates[win[0]]), str(att.dates[win[-1]]), len(win)],
                 "price_mode": args.price_mode, "policies": {}}
    lines = [f"问题 4-3 口径 B：储能日内因果滚动再调度（价格口径 {args.price_mode}）",
             f"窗口 {att.dates[win[0]]} ~ {att.dates[win[-1]]}，{len(win)} 天", ""]
    for pol in [p for p in args.policies.split(",") if p]:
        fee = emg = tot = emg_kwh = 0.0
        detail = []
        for k, i in enumerate(win):
            if k % 40 == 0:
                print(f"  [{pol}] {k}/{len(win)}", flush=True)
            r = q3.simulate_day(att, f3, p4.day(i), i, policy=pol, exec_mode="B_causal",
                                price_plan=p4.forecast(i, args.price_mode))
            fee += r["fee"]
            emg += r["emg_cost"]
            tot += r["total"]
            emg_kwh += r["emg_kwh"]
            detail.append({"date": str(r["date"]), "index": i,
                           "q_plan": r["q_plan"].tolist(), "q_adj": r["q_adj"].tolist(),
                           "charge": r["c_adj"].tolist(), "discharge": r["d_adj"].tolist(),
                           "soc_start": float(r["e_adj"][0]), "soc_end": float(r["e_adj"][-1]),
                           "shortfall": np.asarray(
                               np.maximum(0.0, (att.load_kwh[i] - att.pv_kwh[i])
                                          - (r["q_adj"] + r["d_adj"] - r["c_adj"]))).tolist(),
                           "plan_cost": r["plan_cost"], "fee": r["fee"],
                           "emg_kwh": r["emg_kwh"], "emg_cost": r["emg_cost"],
                           "total": r["total"]})
        out["policies"][pol] = {"fee": fee, "emg_cost": emg, "emg_kwh": emg_kwh,
                                "total": tot, "detail": detail}
        lines.append(f"  策略 {pol:<10} 结算购电费 {fee:>15,.2f}  紧急购电费 {emg:>14,.2f}  "
                     f"合计 {tot:>15,.2f}  紧急电量 {emg_kwh:>10,.1f} kWh")
        print(lines[-1], flush=True)

    (root / "src" / "outputs" / "q4_3_B.json").write_text(
        json.dumps(out, ensure_ascii=False), encoding="utf-8")
    (root / "src" / "outputs" / "q4_3_B.txt").write_text("\n".join(lines), encoding="utf-8")
    print("done")


if __name__ == "__main__":
    main()
