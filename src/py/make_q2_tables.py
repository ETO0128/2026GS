"""生成论文需要的问题二结果表（题目表 1 / 表 2 / 表 3 格式）。

数字全部由代码算出，避免手抄出错；口径与 src/附件5/result2.xlsx 保持一致（变体 A）。

运行：
    python src/py/make_q2_tables.py
输出：
    src/tex/q2_tables.tex        论文用 LaTeX 表格（main.tex 中 \\input{q2_tables} 引入）
    src/outputs/q2_tables.txt    纯文本版，便于核对
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import numpy as np

import q2_model as q
from fill_result2 import BLOCKS, block_label, fmt_clock
from question2 import Question2Config, run_question2
from question2_data import load_cold_start_forecast, load_year_data
from question2_dispatch import compress_emergency_events

DATES = [(3, 20), (6, 21), (9, 23), (12, 21)]
SPECIFIED = [600, 720, 840, 960, 1080, 1200]      # 题目表 1 指定的六个时段起始分钟
BLOCK_NAMES = ["0:00-4:00", "4:00-8:00", "8:00-12:00",
               "12:00-16:00", "16:00-20:00", "20:00-24:00"]   # 与模板充放电量表一致
DEC = 4


def collect(record) -> dict:
    plan, execution = record.plan, record.execution
    events = compress_emergency_events(execution.emergency_kwh)
    emg = [(event.start_minute // 10, event.end_minute // 10, event.energy_kwh)
           for event in events]
    return {"date": record.date,
            "g": plan.grid_kwh, "c": plan.charge_kwh, "d": plan.discharge_kwh,
            "soc0": float(plan.soc_kwh[0]), "soc24": float(plan.soc_kwh[-1]),
            "purchase": float(plan.grid_kwh.sum()), "cost": float(plan.planned_cost_yuan),
            "emg": emg, "emg_kwh": float(execution.emergency_kwh.sum()),
            "emg_cost": float(execution.emergency_cost_yuan)}


def num(x: float, dec: int = DEC) -> str:
    return f"{x:.{dec}f}"


def tex_tables(rows: list[dict]) -> str:
    out = []
    # ---------------- 表 1：指定时段购电量 + 全天购电量/购电费
    out.append("% 由 src/py/make_q2_tables.py 自动生成，请勿手工修改")
    out.append(r"\begin{table}[H]")
    out.append(r"  \centering")
    out.append(r"  \caption{问题二指定日期的计划购电量与全天购电量、购电费}")
    out.append(r"  \label{tab:q2-purchase}")
    out.append(r"  \begin{tabular}{lcccc}")
    out.append(r"    \toprule")
    out.append("    时间段 & " + " & ".join(f"{d['date'].month}\u6708{d['date'].day}\u65e5"
                                          for d in rows) + r" \\")
    out.append(r"    \midrule")
    for m in SPECIFIED:
        j = m // 10
        out.append(f"    {fmt_clock(m)}--{fmt_clock(m + 10)} & " +
                   " & ".join(num(d["g"][j]) for d in rows) + r" \\")
    out.append(r"    \midrule")
    out.append("    全天购电量/kWh & " + " & ".join(num(d["purchase"]) for d in rows) + r" \\")
    out.append("    全天购电费/元 & " + " & ".join(num(d["cost"]) for d in rows) + r" \\")
    out.append(r"    \bottomrule")
    out.append(r"  \end{tabular}")
    out.append(r"\end{table}")
    out.append("")

    # ---------------- 表 2：四小时充放电 + 0:00/24:00 储电量
    out.append(r"\begin{table}[H]")
    out.append(r"  \centering")
    out.append(r"  \caption{问题二指定日期的储能充放电量与日首日末储电量}")
    out.append(r"  \label{tab:q2-storage}")
    out.append(r"  \begin{tabular}{lcccc}")
    out.append(r"    \toprule")
    out.append("    项目 & " + " & ".join(f"{d['date'].month}\u6708{d['date'].day}\u65e5"
                                          for d in rows) + r" \\")
    out.append(r"    \midrule")
    for k, (a, b) in enumerate(BLOCKS):
        out.append(f"    {BLOCK_NAMES[k]}\\ 充电量/kWh & " +
                   " & ".join(num(d["c"][a // 10:b // 10].sum()) for d in rows) + r" \\")
        out.append(f"    {BLOCK_NAMES[k]}\\ 放电量/kWh & " +
                   " & ".join(num(d["d"][a // 10:b // 10].sum()) for d in rows) + r" \\")
    out.append(r"    \midrule")
    out.append("    0:00 储电量/kWh & " + " & ".join(num(d["soc0"]) for d in rows) + r" \\")
    out.append("    24:00 储电量/kWh & " + " & ".join(num(d["soc24"]) for d in rows) + r" \\")
    out.append(r"    \bottomrule")
    out.append(r"  \end{tabular}")
    out.append(r"\end{table}")
    out.append("")

    # ---------------- 表 3：紧急购电（正文汇总）
    out.append(r"\begin{table}[H]")
    out.append(r"  \centering")
    out.append(r"  \caption{问题二指定日期的紧急购电汇总}")
    out.append(r"  \label{tab:q2-emergency}")
    out.append(r"  \begin{tabular}{lrrr}")
    out.append(r"    \toprule")
    out.append(r"    日期 & 紧急购电时段数 & 紧急购电量/kWh & 紧急购电费/元 \\")
    out.append(r"    \midrule")
    for d in rows:
        label = f"{d['date'].year}/{d['date'].month}/{d['date'].day}"
        out.append(f"    {label} & {len(d['emg'])} & {num(d['emg_kwh'])} & {num(d['emg_cost'])} \\\\")
    out.append(r"    \midrule")
    out.append(f"    合计 & {sum(len(d['emg']) for d in rows)} & "
               f"{num(sum(d['emg_kwh'] for d in rows))} & "
               f"{num(sum(d['emg_cost'] for d in rows))} \\\\")
    out.append(r"    \bottomrule")
    out.append(r"  \end{tabular}")
    out.append(r"\end{table}")
    return "\n".join(out)


def tex_appendix(rows: list[dict]) -> str:
    """附录：紧急购电的时段明细（题目表 3 / 表 4 的写法）。"""
    out = ["% 由 src/py/make_q2_tables.py 自动生成，请勿手工修改"]
    out.append(r"\begin{table}[H]")
    out.append(r"  \centering")
    out.append(r"  \caption{问题二指定日期紧急购电的时段明细}")
    out.append(r"  \label{tab:q2-emergency-full}")
    out.append(r"  \begin{tabular}{llr}")
    out.append(r"    \toprule")
    out.append(r"    日期 & 紧急购电时间段 & 紧急购电量/kWh \\")
    out.append(r"    \midrule")
    for d in rows:
        items = d["emg"]
        label = f"{d['date'].year}/{d['date'].month}/{d['date'].day}"
        if not items:
            out.append(f"    {label} & -- & 0.0000 \\\\")
            continue
        for n, (t0, t1, energy) in enumerate(items):
            date_cell = label if n == 0 else ""
            out.append(f"    {date_cell} & {fmt_clock(10 * t0)}--{fmt_clock(10 * t1)} & "
                       f"{num(energy)} \\\\")
    out.append(r"    \bottomrule")
    out.append(r"  \end{tabular}")
    out.append(r"\end{table}")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", type=Path, default=None)
    ap.add_argument("--tex-out", type=Path, default=None)
    ap.add_argument("--tex-appendix-out", type=Path, default=None)
    ap.add_argument("--txt-out", type=Path, default=None)
    args = ap.parse_args()
    root = Path(args.data_root) if args.data_root else q.project_root()
    tex_out = Path(args.tex_out) if args.tex_out else root / "src" / "tex" / "q2_tables.tex"
    app_out = Path(args.tex_appendix_out) if args.tex_appendix_out else \
        root / "src" / "tex" / "q2_tables_appendix.tex"
    txt_out = Path(args.txt_out) if args.txt_out else root / "src" / "outputs" / "q2_tables.txt"

    attachment_dir = root / "problems" / "C题" / "附件"
    data = load_year_data(attachment_dir / "附件1.xlsx", attachment_dir / "附件2.xlsx")
    cold = load_cold_start_forecast(attachment_dir / "附件1.xlsx")
    result = run_question2(data, Question2Config(), cold)
    by_date = {record.date: record for record in result.official_days}
    rows = [collect(by_date[dt.date(2025, m, d)]) for m, d in DATES]

    lines = ["问题二指定日期结果（口径：变体 A 严格按计划执行，与 result2.xlsx 一致）", ""]
    for d in rows:
        lines.append(f"== {d['date']} ==")
        lines.append("  指定时段购电量/kWh：" + "  ".join(
            f"{fmt_clock(m)}-{fmt_clock(m+10)}={d['g'][m//10]:.4f}" for m in SPECIFIED))
        lines.append(f"  全天购电量 {d['purchase']:.4f} kWh；全天购电费 {d['cost']:.4f} 元")
        lines.append("  四小时充/放：" + " | ".join(
            f"{block_label(a)} {d['c'][a//10:b//10].sum():.4f}/{d['d'][a//10:b//10].sum():.4f}"
            for a, b in BLOCKS))
        lines.append(f"  0:00 储电量 {d['soc0']:.4f} kWh；24:00 储电量 {d['soc24']:.4f} kWh")
        lines.append(f"  紧急购电 {len(d['emg'])} 段，合计 {d['emg_kwh']:.4f} kWh，"
                     f"费用 {d['emg_cost']:.4f} 元")
        for t0, t1, e in d["emg"]:
            lines.append(f"    {fmt_clock(10*t0)}-{fmt_clock(10*t1)}  {e:.4f}")
        lines.append("")

    tex_out.parent.mkdir(parents=True, exist_ok=True)
    tex_out.write_text(tex_tables(rows), encoding="utf-8")
    app_out.parent.mkdir(parents=True, exist_ok=True)
    app_out.write_text(tex_appendix(rows), encoding="utf-8")
    txt_out.parent.mkdir(parents=True, exist_ok=True)
    txt_out.write_text("\n".join(lines), encoding="utf-8")
    print(f"已写入 {tex_out}")
    print(f"已写入 {app_out}")
    print(f"已写入 {txt_out}")
    for d in rows:
        print(f"  {d['date']}: 全天购电量 {d['purchase']:.4f} kWh，购电费 {d['cost']:.4f} 元，"
              f"紧急购电 {len(d['emg'])} 段 {d['emg_kwh']:.4f} kWh")


if __name__ == "__main__":
    import datetime  # noqa: F401  仅为类型注解可读性
    main()
