"""问题四 4-3：波动电价下重做问题三的滚动调整，比较不同价格信息口径。

运行：
    python src/py/run_q4_3.py                 # 全年 334 天（约 10 分钟）
    python src/py/run_q4_3.py --days 20       # 调试

输出：
    src/outputs/q4_3_report.txt   可读报告
    src/outputs/q4_3_summary.json 机器可读结果（含主口径逐日记录，供填表与绘图）
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import q2_model as q2
import q3_model as q3
import q4_model as q4
from question4_2_data import load_question42_data
from question4_2_forecast import calibrate_price_method

# (名称, 价格信息口径, 决策规则)
VARIANTS = [
    ("fixed_price", None, "selective"),
    ("volatile_oracle", "oracle", "selective"),
    ("volatile_prev", "prev_day", "selective"),
    ("volatile_seven_day", "seven_day", "selective"),
    ("volatile_profile", "profile", "selective"),
    ("volatile_oracle_none", "oracle", "none"),
]
NAME_CN = {
    "fixed_price": "附件1 固定电价（问题三基准）",
    "volatile_oracle": "波动电价·0:00 已知当天电价",
    "volatile_prev": "波动电价·前一日电价作预测（因果）",
    "volatile_seven_day": "波动电价·近七日均值预测（因果，正式）",
    "volatile_profile": "波动电价·历史扩展均值预测（因果对照）",
    "volatile_oracle_none": "波动电价·已知电价但不做调整",
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=0, help="只跑前 N 天（调试）")
    ap.add_argument("--s-max", type=int, default=6)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    root = q2.project_root()
    att = q2.Attachment(root)
    f3 = q3.PvForecast3(root)
    p4 = q4.Prices4(root, att)
    price_data = load_question42_data(root / "problems/C题/附件/附件2.xlsx",
                                     root / "problems/C题/附件/附件4.xlsx")
    selected_method, calibration = calibrate_price_method(price_data)
    if selected_method != "seven_day":
        raise RuntimeError(f"Locked January calibration selected unexpected method: {selected_method}")
    win = att.window[:args.days] if args.days else att.window

    lines: list[str] = []
    out: dict = {"window": [str(att.dates[win[0]]), str(att.dates[win[-1]]), len(win)],
                 "formal_variant": "volatile_seven_day",
                 "price_calibration": {"window": "2025-01-08--2025-01-31",
                                       "criterion": "minimum RMSE; MAE and bias for audit",
                                       "selected_method": selected_method, "scores": calibration},
                 "price_stats": p4.stats(), "variants": {}}

    def emit(s=""):
        lines.append(str(s))
        print(s, flush=True)

    emit("问题四 4-3：波动电价下的滚动调整")
    emit(f"结果窗口 {att.dates[win[0]]} ~ {att.dates[win[-1]]}，共 {len(win)} 天")
    st = out["price_stats"]
    emit("")
    emit("附件4 电价特征")
    emit(f"  全天区间 {st['min']:.4f} ~ {st['max']:.4f} 元/kWh（均值 {st['mean']:.4f}）")
    emit(f"  各日极差均值 {st['daily_range_mean']:.4f} 元/kWh（附件1 为 {st['a1_range']:.4f}）")
    emit(f"  与附件1 曲线的逐日相关系数均值 {st['corr_with_a1_mean']:.4f}；"
         f"逐时段均值与附件1 最大偏差 {st['profile_vs_a1_maxdiff']:.2e} 元/kWh")
    emit("")

    pb = q4.perfect_bound(p4, att)
    out["perfect_bound"] = pb
    emit(f"完全信息下界（0:00 已知当天电价与真实负荷/光伏，无调整费、无紧急购电）："
         f"{pb['total']:,.2f} 元")
    emit("")

    emit(f"{'方案':<34}{'结算购电费':>16}{'紧急购电费':>16}{'合计':>16}{'调整次数':>10}")
    for name, mode, policy in VARIANTS:
        fee = emg = total = 0.0
        emg_kwh = 0.0
        adj = 0
        per_day = []
        for k, i in enumerate(win):
            if k % 40 == 0:
                print(f"  [{name}] {k}/{len(win)} ...", flush=True)
            price_act = att.price if mode is None else p4.day(i)
            if mode is None:
                r = q3.simulate_day(att, f3, price_act, i, s_max=args.s_max, policy=policy)
            else:
                r = q4.simulate_day4(att, f3, price_act, i, mode, p4,
                                     s_max=args.s_max, policy=policy)
            fee += r["fee"]
            emg += r["emg_cost"]
            total += r["total"]
            emg_kwh += r["emg_kwh"]
            n_adj = sum(1 for e in r["log"] if e["adjusted"])
            adj += n_adj
            per_day.append({"date": str(r["date"]), "fee": r["fee"], "emg_cost": r["emg_cost"],
                            "emg_kwh": r["emg_kwh"], "total": r["total"], "n_adj": n_adj})
        rec = {"name": name, "mode": mode, "policy": policy, "fee": fee, "emg_cost": emg,
               "emg_kwh": emg_kwh, "total": total, "adj_nodes": adj, "per_day": per_day}
        out["variants"][name] = rec
        emit(f"{NAME_CN[name]:<34}{fee:>16,.2f}{emg:>16,.2f}{total:>16,.2f}{adj:>10}")

    emit("")
    base = out["variants"]["fixed_price"]
    orac = out["variants"]["volatile_oracle"]
    prev = out["variants"]["volatile_prev"]
    seven = out["variants"]["volatile_seven_day"]
    prof = out["variants"]["volatile_profile"]
    emit("对比结论")
    emit(f"  1) 波动电价使全年费用上升：近七日均值正式方案合计 {seven['total']:,.2f} 元，"
         f"比固定电价基准高 {seven['total'] - base['total']:,.2f} 元"
         f"（{(seven['total'] - base['total']) / base['total'] * 100:.2f}%）")
    emit(f"  2) 价格信息价值：正式近七日均值方案比已知当天电价多 "
         f"{seven['total'] - orac['total']:,.2f} 元"
         f"（{(seven['total'] - orac['total']) / orac['total'] * 100:.2f}%）；"
         f"历史扩展均值因果对照比正式方案多 {prof['total'] - seven['total']:,.2f} 元，"
         f"前一日预测比正式方案多 {prev['total'] - seven['total']:,.2f} 元")
    emit(f"  3) 与完全信息下界 {pb['total']:,.2f} 元的差距即为预测误差与日内不可调部分的代价")

    out_path = args.out or root / "src" / "outputs" / "q4_3_report.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    (out_path.parent / "q4_3_summary.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done")


if __name__ == "__main__":
    main()
