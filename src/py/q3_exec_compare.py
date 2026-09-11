"""问题三执行口径优化：口径 A（严格按计划执行）vs 口径 B（储能日内再调度）。

背景
----
问题三的日前计划只能精确约束 0:00-6:00；6:00/12:00/18:00 各节点会重排剩余时段，
因此“计划准不准”只对清晨几个小时有直接影响。选择执行口径后剩余的费用差别主要来自
“实际净负荷超出承诺购电量”时，是靠 5 倍紧急购电（口径 A），还是先让储能再调度吸收
（口径 B，与问题二 P2B 同口径）。

运行：
    python src/py/q3_exec_compare.py
输出：
    src/outputs/q3_exec_report.txt   两种口径 × 两种策略的全年费用
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np

import q2_model as q2
import q3_model as q3

POLICIES = [("none", "仅 0:00 计划、不调整"), ("selective", "择优调整")]
MODES = [("A", "严格按（调整后）计划执行储能"), ("B", "购电量照付不议、储能日内再调度")]


def main() -> None:
    root = q2.project_root()
    att = q2.Attachment(root)
    f3 = q3.PvForecast3(root)
    win = att.window

    lines: list[str] = []

    def emit(s: str = "") -> None:
        lines.append(str(s))
        print(s, flush=True)

    emit("问题三执行口径优化：A（严格执行）vs B（储能日内再调度）")
    emit(f"结果窗口 {att.dates[win[0]]} ~ {att.dates[win[-1]]}，共 {len(win)} 天")
    emit("")
    emit(f"{'策略':<12}{'口径':>4}{'结算购电费':>16}{'紧急购电费':>16}{'合计':>16}{'紧急电量/kWh':>15}")

    res: dict[tuple[str, str], dict] = {}
    for pol, pol_cn in POLICIES:
        for mode, mode_cn in MODES:
            t0 = time.time()
            fee = emg = tot = emg_kwh = 0.0
            for i in win:
                r = q3.simulate_day(att, f3, att.price, i, policy=pol, exec_mode=mode)
                fee += r["fee"]
                emg += r["emg_cost"]
                tot += r["total"]
                emg_kwh += r["emg_kwh"]
            res[(pol, mode)] = {"fee": fee, "emg": emg, "total": tot, "emg_kwh": emg_kwh}
            emit(f"{pol:<12}{mode:>4}{fee:>16,.2f}{emg:>16,.2f}{tot:>16,.2f}{emg_kwh:>15,.1f}"
                 f"   ({time.time()-t0:.0f}s)")

    emit("")
    a = res[("selective", "A")]["total"]
    emit("口径说明")
    for key, cn in MODES:
        emit(f"  口径 {key}：{cn}")
    emit("")
    emit("对比结论")
    for pol in ("none", "selective"):
        ta, tb = res[(pol, "A")]["total"], res[(pol, "B")]["total"]
        emit(f"  策略 {pol:<10} A {ta:>15,.2f} 元 → B {tb:>15,.2f} 元，"
             f"节省 {ta-tb:>13,.2f} 元（{(ta-tb)/ta*100:5.2f}%）")
    bn = res[("none", "B")]["total"]
    bs = res[("selective", "B")]["total"]
    emit(f"  口径 B 下：不调整 {bn:,.2f} 元，择优调整 {bs:,.2f} 元，"
         f"差额 {bs-bn:+,.2f} 元 —— B 下储能再调度已可吸收大部分预测偏差，"
         f"购电计划调整的净收益为负")
    emit(f"  口径 A 下最优（择优调整）{a:,.2f} 元；口径 B 下最优（不调整）{bn:,.2f} 元，"
         f"相对口径 A 节省 {(a-bn)/a*100:.2f}%")

    out = root / "src" / "outputs" / "q3_exec_report.txt"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("done ->", out)


if __name__ == "__main__":
    main()
