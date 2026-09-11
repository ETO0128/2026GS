"""问题四 4-2：把问题二的固定电价换成附件4 的逐日波动电价，重做日前计划与结算。

口径
----
- 沿用问题二的方法：0:00 用因果预测构造日前计划（LP），实际净负荷超出“计划购电量 +
  计划放电 - 计划充电”的部分按 5 倍实际电价紧急购电；储能严格执行计划（口径 A）。
- 决策用**价格预测**、结算用**实际波动电价**：与 4-3 完全一致。
  价格信息口径：oracle（0:00 已知当天全部电价，正式提交口径）/ prev_day（前一日实际
  电价作预测，因果）/ profile（附件4 逐时段均值，因果）。
- 另给“完全信息下界”：0:00 已知当天电价与当天真实负荷/光伏的确定性最优费用。

运行：
    python src/py/run_q4_2.py
输出：
    src/outputs/q4_2_report.txt / q4_2_summary.json
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

import q2_model as q2
import q4_model as q4

VARIANTS = [
    ("fixed_price", None, "附件1 固定电价（问题二基准）"),
    ("volatile_oracle", "oracle", "波动电价·0:00 已知当天电价"),
    ("volatile_prev", "prev_day", "波动电价·前一日电价作预测（因果）"),
    ("volatile_profile", "profile", "波动电价·逐时段均值曲线作预测（因果）"),
]


def simulate_day(att: q2.Attachment, p4: q4.Prices4, i: int, price_mode) -> dict:
    """单日：决策用价格预测，结算用实际电价；缺口 5 倍紧急购电。"""
    price_plan = att.price if price_mode is None else p4.forecast(i, price_mode)
    price_act = att.price if price_mode is None else p4.day(i)
    l_fc, v_fc = q2.forecast_day(att, i)
    plan = q2.plan_lp(price_plan, l_fc, v_fc, q2.E0_KWH, "cycle")
    net_act = att.load_kwh[i] - att.pv_kwh[i]
    committed = plan["g"] + plan["d"] - plan["c"]
    shortfall = np.maximum(0.0, net_act - committed)
    return {
        "date": att.dates[i], "index": i,
        "g": plan["g"], "charge": plan["c"], "discharge": plan["d"],
        "soc_start": q2.E0_KWH, "soc_end": float(plan["e"][-1]),
        "shortfall": shortfall,
        "plan_cost": float(np.dot(price_act, plan["g"])),
        "emg_kwh": float(shortfall.sum()),
        "emg_cost": float(q2.EMG_MULTIPLIER * np.dot(price_act, shortfall)),
    }


def main() -> None:
    root = q2.project_root()
    att = q2.Attachment(root)
    p4 = q4.Prices4(root, att)
    win = att.window

    lines: list[str] = []
    out: dict = {"window": [str(att.dates[win[0]]), str(att.dates[win[-1]]), len(win)],
                 "price_stats": p4.stats(), "variants": {}}

    def emit(s="") -> None:
        lines.append(str(s))
        print(s, flush=True)

    emit("问题四 4-2：波动电价下重做问题二（日前计划 + 5 倍紧急购电）")
    emit(f"结果窗口 {att.dates[win[0]]} ~ {att.dates[win[-1]]}，共 {len(win)} 天")
    st = out["price_stats"]
    emit("")
    emit(f"附件4 电价：{st['min']:.4f} ~ {st['max']:.4f} 元/kWh（均值 {st['mean']:.4f}）；"
         f"各日极差均值 {st['daily_range_mean']:.4f}（附件1 为 {st['a1_range']:.4f}）")
    emit("")

    pb = q4.perfect_bound(p4, att)
    out["perfect_bound"] = pb
    emit(f"完全信息下界（已知当天电价与真实负荷/光伏，无紧急购电）：{pb['total']:,.2f} 元")
    emit("")
    emit(f"{'方案':<34}{'计划购电费':>16}{'紧急购电费':>16}{'合计':>16}{'紧急电量/kWh':>15}")

    for name, mode, cn in VARIANTS:
        plan = emg = emg_kwh = 0.0
        per_day = []
        for i in win:
            r = simulate_day(att, p4, i, mode)
            plan += r["plan_cost"]
            emg += r["emg_cost"]
            emg_kwh += r["emg_kwh"]
            per_day.append({"date": str(r["date"]), "plan_cost": r["plan_cost"],
                            "emg_cost": r["emg_cost"], "emg_kwh": r["emg_kwh"],
                            "total": r["plan_cost"] + r["emg_cost"]})
        total = plan + emg
        out["variants"][name] = {"name": name, "mode": mode, "plan_cost": plan,
                                 "emg_cost": emg, "emg_kwh": emg_kwh, "total": total,
                                 "per_day": per_day}
        emit(f"{cn:<34}{plan:>16,.2f}{emg:>16,.2f}{total:>16,.2f}{emg_kwh:>15,.1f}")

    emit("")
    base = out["variants"]["fixed_price"]
    orac = out["variants"]["volatile_oracle"]
    prev = out["variants"]["volatile_prev"]
    prof = out["variants"]["volatile_profile"]
    emit("对比结论")
    emit(f"  1) 波动电价抬高费用：已知当天电价时合计 {orac['total']:,.2f} 元，"
         f"比附件1 固定电价基准 {base['total']:,.2f} 元高 {orac['total']-base['total']:,.2f} 元"
         f"（{(orac['total']-base['total'])/base['total']*100:.2f}%）")
    emit(f"  2) 价格信息价值有限：前一日电价预测 {prev['total']:,.2f} 元，"
         f"比已知当天电价多 {prev['total']-orac['total']:,.2f} 元"
         f"（{(prev['total']-orac['total'])/orac['total']*100:.2f}%）；"
         f"逐时段均值预测 {prof['total']:,.2f} 元，多 {prof['total']-orac['total']:,.2f} 元")
    emit(f"  3) 与完全信息下界 {pb['total']:,.2f} 元的差距主要来自光伏/负荷预测误差，"
         f"而非价格不确定性")

    out_path = root / "src" / "outputs" / "q4_2_report.txt"
    out_path.write_text("\n".join(lines), encoding="utf-8")
    import json
    (out_path.parent / "q4_2_summary.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done ->", out_path)


if __name__ == "__main__":
    main()
