"""问题三补充实验：引入"其他时刻"的光伏预报到底值多少钱（价值上界）。

背景
----
题目只在 0:00、6:00、12:00、18:00 提供未来 24 小时光伏预报（附件3）。
问题三末尾要求回答"是否还需要引入其他时刻的光伏发电功率预报"。
附件3 在其余时刻没有预报，无法直接评估；本脚本用两种可辩护的测度给出结论：

1) **实际预报价值**：对 6:00、12:00、18:00 直接使用附件3，测出"仅在这一个时刻
   做一次调整（其余时刻不调整）"相对"只在 0:00 定计划、之后不再调整"的全年节省。
2) **完美预报上界**：对其余时刻（3:00、9:00、15:00、21:00）假设该时刻能拿到
   剩余时段的**完美**预报（场景退化为 1 个、残差为 0）。真实预报的信息量不可能超过
   完美预报，因此这是该时刻预报价值的**上界**。若上界已经很小，就足以否定"引入该时刻"。

口径与 ``run_q3.py`` 一致：节点上直接采用调整后的计划（本实验固定采用，不设择优门限），
已执行时段不可改；最终计划严格执行，缺口按 5 倍价紧急购电；日周期 e_144 = e_0 = 6000 kWh。

输出
----
    src/outputs/q3_upper_report.txt   可读报告
    src/outputs/q3_upper.json         机器可读结果（供 make_q3_tables.py 使用）
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import q2_model as q2
import q3_model as q3

# (显示名, 分钟, 信息类型)
CASES = [
    ("3:00", 180, "perfect"),
    ("6:00", 360, "real"),
    ("9:00", 540, "perfect"),
    ("12:00", 720, "real"),
    ("15:00", 900, "perfect"),
    ("18:00", 1080, "real"),
    ("21:00", 1260, "perfect"),
]
KIND_NAME = {"real": "附件3 实际光伏预报", "perfect": "完美光伏预报（负荷预测不变）"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--days", type=int, default=0, help="只跑前 N 天（调试）")
    ap.add_argument("--s-max", type=int, default=6)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    root = q2.project_root()
    att = q2.Attachment(root)
    f3 = q3.PvForecast3(root)
    win = att.window[:args.days] if args.days else att.window
    price = att.price

    lines: list[str] = []
    out: dict = {"window": [str(att.dates[win[0]]), str(att.dates[win[-1]]), len(win)],
                 "cases": [], "baseline": None}

    def emit(s=""):
        lines.append(str(s))
        print(s, flush=True)

    emit("问题三补充实验：固定负荷信息后的其他时刻光伏预报价值")
    emit(f"结果窗口 {att.dates[win[0]]} ~ {att.dates[win[-1]]}，共 {len(win)} 天")
    emit("")

    # ---------------------------------------------------------------- 每日 0:00 计划（只算一次）
    plans: dict[int, dict] = {}
    net_act: dict[int, np.ndarray] = {}
    base_total = 0.0
    base_emg = 0.0
    for k, i in enumerate(win):
        if k % 40 == 0:
            print(f"  [plan] {k}/{len(win)} ...", flush=True)
        l_fc, v_fc = q3.forecast_full(att, f3, i, 0)
        scen, w = q3.residual_scenarios(att, f3, i, 0, args.s_max)
        plan = q3.seg_lp(price, None, l_fc, v_fc, q2.E0_KWH, scen, w, "plan")
        plans[i] = plan
        net = att.load_kwh[i] - att.pv_kwh[i]
        net_act[i] = net
        committed = plan["q"] + plan["d"] - plan["c"]
        short = np.maximum(0.0, net - committed)
        base_total += float((price * plan["q"]).sum()) + 5.0 * float((price * short).sum())
        base_emg += float(short.sum())

    out["baseline"] = {"name": "0:00", "kind": "plan_only", "total": base_total,
                       "emg_kwh": base_emg, "gain": 0.0, "gain_pct": 0.0}
    emit("基线：只在 0:00 制定计划、之后不再获得任何预报、不调整")
    emit(f"  全年合计 {base_total:>15,.2f} 元，紧急购电量 {base_emg:>12,.2f} kWh")
    emit("")

    # ---------------------------------------------------------------- 单节点情形
    emit("单独引入一个 τ 时刻预报（仅在该时刻调整一次）")
    emit(f"{'时刻':<7}{'信息类型':<20}{'全年合计/元':>16}{'相对基线节省/元':>18}{'节省占比':>10}{'紧急购电量/kWh':>16}")
    for name, minute, kind in CASES:
        j0 = minute // 10
        tot = 0.0
        emg = 0.0
        for i in win:
            plan = plans[i]
            q_cur = plan["q"].copy()
            c_cur = plan["c"].copy()
            d_cur = plan["d"].copy()
            if kind == "perfect":
                # 只提高光伏信息：负荷仍使用决策日前可得的因果预测及其历史残差。
                l_fc = q3.forecast_full(att, f3, i, 0)[0]
                v_fc = att.pv_kwh[i]
                scen, w = q3.load_only_residual_scenarios(
                    att, f3, i, minute, v_fc[j0:], args.s_max)
            else:
                l_fc, v_fc = q3.forecast_full(att, f3, i, minute)
                scen, w = q3.residual_scenarios(att, f3, i, minute, args.s_max)
            adj = q3.seg_lp(price[j0:], plan["q"][j0:], l_fc[j0:], v_fc[j0:],
                            plan["e"][j0], scen, w, "adjust")
            q_cur[j0:], c_cur[j0:], d_cur[j0:] = adj["q"], adj["c"], adj["d"]
            committed = q_cur + d_cur - c_cur
            short = np.maximum(0.0, net_act[i] - committed)
            tot += q3.fee_seg(price, plan["q"], q_cur) + 5.0 * float((price * short).sum())
            emg += float(short.sum())
        gain = base_total - tot
        rec = {"name": name, "minute": minute, "kind": kind,
               "total": tot, "emg_kwh": emg, "gain": gain,
               "gain_pct": gain / base_total * 100}
        out["cases"].append(rec)
        emit(f"{name:<7}{KIND_NAME[kind]:<20}{tot:>16,.2f}{gain:>18,.2f}"
             f"{gain / base_total * 100:>9.2f}%{emg:>16,.2f}")

    emit("")
    emit("结论")
    emit("  1) 本表是相对仅 0:00 计划的单节点上界；已有节点后的条件边际价值需另行比较；")
    emit("  2) 日落后（21:00）的价值上界已明显收缩——剩余可调整时段短且无光照，")
    emit("     此时再投入一次预报通讯/计算几乎没有意义；")
    emit("  3) 实际可得的 18:00 预报（附件3）价值接近于零（见 run_q3.py 的节点累积实验），")
    emit("     原因是 18:00 之后光伏≈0，新预报不再包含任何光照信息。")
    emit("  判据：某时刻预报是否有价值，取决于它能否覆盖尚未执行的、且仍有光伏出力的时段。")

    out_path = args.out or root / "src" / "outputs" / "q3_upper_report.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    json_path = (out_path.parent / "q3_upper.json" if args.out is None
                 else out_path.with_suffix(".json"))
    json_path.write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done")


if __name__ == "__main__":
    main()
