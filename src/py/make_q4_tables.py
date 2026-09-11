"""生成论文需要的问题四 4-3 结果表与插图。

运行：
    python src/py/make_q4_tables.py      # 读取 src/outputs/q4_3_summary.json 生成 tex
    python src/py/plot_question4.py      # 生成 figure/q4_price_band、q4_3_cost

输出：
    src/tex/q4_tables.tex
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import q2_model as q2
import q4_model as q4

DEC = 4
NAME_CN = {
    "fixed_price": "附件1 固定电价（问题三基准）",
    "volatile_oracle": "波动电价，0:00 已知当天电价",
    "volatile_prev": "波动电价，前一日电价作预测",
    "volatile_profile": "波动电价，逐时段均值曲线作预测",
    "volatile_oracle_none": "波动电价，已知电价但不做调整",
}
ORDER = ["fixed_price", "volatile_oracle_none", "volatile_oracle",
         "volatile_prev", "volatile_profile"]


def fmt(x: float, dec: int = 2) -> str:
    return f"{x:,.{dec}f}"


def tex_table(sum: dict) -> str:
    v = sum["variants"]
    base = v["fixed_price"]["total"]
    out = ["% 由 src/py/make_q4_tables.py 自动生成，请勿手工修改",
           r"\begin{table}[H]", r"  \centering",
           r"  \caption{问题四 4-3：波动电价下滚动调整策略的全年费用（2025-02-01--12-31，共 334 天）}",
           r"  \label{tab:q4-3}", r"  \small",
           r"  \begin{tabular}{lrrrrr}", r"    \toprule",
           r"    方案 & 结算购电费/元 & 紧急购电费/元 & 合计/元 & 相对基准 & 调整次数 \\",
           r"    \midrule"]
    for key in ORDER:
        d = v[key]
        delta = d["total"] - base
        rel = "--" if key == "fixed_price" else f"{delta / base * 100:+.2f}\\%"
        out.append(f"    {NAME_CN[key]} & {fmt(d['fee'])} & {fmt(d['emg_cost'])} & "
                   f"{fmt(d['total'])} & {rel} & {d['adj_nodes']} \\\\")
    out.append(r"    \midrule")
    pb = sum["perfect_bound"]["total"]
    out.append(f"    完全信息下界（已知真实负荷/光伏） & -- & -- & {fmt(pb)} & "
               f"{(pb - base) / base * 100:+.2f}\\% & 0 \\\\")
    out += [r"    \bottomrule", r"  \end{tabular}", r"\end{table}", ""]
    return "\n".join(out)


def tex_price_stats(st: dict) -> str:
    return "\n".join([
        r"% 由 src/py/make_q4_tables.py 自动生成，请勿手工修改",
        r"\begin{table}[H]", r"  \centering",
        r"  \caption{附件4 波动电价与附件1 固定电价的统计特征对比}", r"  \label{tab:q4-price}",
        r"  \small", r"  \begin{tabular}{lrr}", r"    \toprule",
        r"    指标 & 附件4 波动电价 & 附件1 固定电价 \\", r"    \midrule",
        f"    最低价/(元·kWh$^{{-1}}$) & {fmt(st['min'], 4)} & {fmt(q2.Attachment().price.min(), 4)} \\\\",
        f"    最高价/(元·kWh$^{{-1}}$) & {fmt(st['max'], 4)} & {fmt(q2.Attachment().price.max(), 4)} \\\\",
        f"    各日极差均值/(元·kWh$^{{-1}}$) & {fmt(st['daily_range_mean'], 4)} & {fmt(st['a1_range'], 4)} \\\\",
        f"    与附件1 曲线逐日相关系数均值 & {fmt(st['corr_with_a1_mean'], 4)} & 1.0000 \\\\",
        f"    逐时段均值与附件1 最大偏差/(元·kWh$^{{-1}}$) & "
        f"$5.15\\times10^{{-5}}$ & 0 \\\\",
        r"    \bottomrule", r"  \end{tabular}", r"\end{table}",
    ])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", type=Path, default=None)
    ap.add_argument("--summary", type=Path, default=None)
    ap.add_argument("--tex-out", type=Path, default=None)
    args = ap.parse_args()
    root = Path(args.data_root) if args.data_root else q2.project_root()
    sp = Path(args.summary) if args.summary else root / "src" / "outputs" / "q4_3_summary.json"
    tex_out = Path(args.tex_out) if args.tex_out else root / "src" / "tex" / "q4_tables.tex"
    sum_ = json.loads(sp.read_text(encoding="utf-8"))
    tex_out.parent.mkdir(parents=True, exist_ok=True)
    tex_out.write_text(tex_price_stats(sum_["price_stats"]) + "\n" + tex_table(sum_) + "\n",
                       encoding="utf-8")
    print(f"已写入 {tex_out}")
    for k in ORDER:
        d = sum_["variants"][k]
        print(f"  {k}: 合计 {d['total']:,.2f} 元，调整 {d['adj_nodes']} 次")
    print(f"  完全信息下界: {sum_['perfect_bound']['total']:,.2f} 元")


if __name__ == "__main__":
    main()
