"""问题二定稿：日末储备（终端 SOC）取 4000 / 6000 / 8000 kWh 时，
终端约束成为紧约束的比例、全年费用与日内周转量。

运行：python src/py/q2_terminal_soc.py
输出：src/outputs/q2_terminal_soc_report.txt
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from question2 import Question2Config, run_question2
from question2_data import load_cold_start_forecast, load_year_data

ROOT = Path(__file__).resolve().parents[2]
ATT = ROOT / "problems" / "C题" / "附件"


def main() -> None:
    data = load_year_data(ATT / "附件1.xlsx", ATT / "附件2.xlsx")
    cold = load_cold_start_forecast(ATT / "附件1.xlsx")
    lines = ["=== 问题二：终端 SOC（日末储备）设定对费用与约束紧性的影响（官方 334 天） ===",
             f"  {'终端SOC/kWh':>11}{'全年费用/元':>16}{'紧急购电费/元':>16}"
             f"{'紧约束天数':>11}{'占比':>8}{'日均充放周转/kWh':>18}"]
    rows = []
    for reserve in (4000.0, 6000.0, 8000.0):
        res = run_question2(data, Question2Config(reserve_kwh=reserve), cold)
        days = res.official_days
        n = len(days)
        bind = sum(1 for d in days if abs(float(d.plan.soc_kwh[-1]) - reserve) < 1e-6)
        total = sum(float(d.execution.total_cost_yuan) for d in days)
        emg = sum(float(d.execution.emergency_cost_yuan) for d in days)
        thr = float(np.mean([float(d.plan.charge_kwh.sum() + d.plan.discharge_kwh.sum())
                             for d in days]))
        lines.append(f"  {reserve:>11.0f}{total:>16,.2f}{emg:>16,.2f}"
                     f"{bind:>11d}{bind / n * 100:>7.1f}%{thr:>18,.1f}")
        rows.append((reserve, total, emg, bind, n, thr))
        print(lines[-1], flush=True)
    (ROOT / "src" / "outputs" / "q2_terminal_soc_report.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8")
    tex = ["% 由 src/py/q2_terminal_soc.py 自动生成，请勿手工修改",
           r"\begin{table}[H]", r"  \centering",
           r"  \caption{问题二：终端 SOC（日末储备）设定对费用与约束紧性的影响（全部 334 天）}",
           r"  \label{tab:q2-terminal}", r"  \small",
           r"  \begin{tabular}{rrrrr}", r"    \toprule",
           r"    终端 SOC/kWh & 全年费用/元 & 紧急购电费/元 & 紧约束天数 & 占比 \\",
           r"    \midrule"]
    for reserve, total, emg, bind, n, thr in rows:
        tex.append(f"    {reserve:,.0f} & {total:,.2f} & {emg:,.2f} & {bind} & "
                   f"{bind / n * 100:.1f}\\% \\\\")
    tex += [r"    \bottomrule", r"  \end{tabular}", r"\end{table}"]
    (ROOT / "src" / "tex" / "q2_terminal_soc.tex").write_text("\n".join(tex), encoding="utf-8")
    print("已写入 src/outputs/q2_terminal_soc_report.txt 与 src/tex/q2_terminal_soc.tex")


if __name__ == "__main__":
    main()
