"""生成论文需要的问题三结果表。

数据来源全部是代码产物，不手抄：
    src/outputs/q3_summary.json   由 run_q3.py 生成（三策略全年对比、节点边际价值、节点累积实验）
    src/outputs/q3_upper.json     由 run_q3_upper.py 生成（引入其他时刻预报的价值上界）
    src/py/q3_model.simulate_day  指定日期结果现算（4 天，秒级）

运行：
    python src/py/make_q3_tables.py            # 先确保上面两个 json 已存在
输出：
    src/tex/q3_tables.tex        论文用 LaTeX 表格（main.tex 中 \\input{q3_tables} 引入）
    src/outputs/q3_tables.txt    纯文本版，便于核对
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import numpy as np

import q2_model as q2
import q3_model as q3
from fill_result2 import block_label, fmt_clock
from fill_result3 import BLOCKS

DATES = [(3, 20), (6, 21), (9, 23), (12, 21)]
DEC = 4
POLICY_CN = {"none": "仅 0:00 计划", "fixed": "每节点固定调整", "selective": "择优调整"}


def fmt(x: float, dec: int = DEC) -> str:
    return f"{x:,.{dec}f}"


def pct(x: float) -> str:
    """百分比，接近 0 时避免出现 -0.00。"""
    return "0.00" if abs(x) < 0.005 else f"{x:.2f}"


def tex_strategy(summary: dict) -> str:
    pol = summary["policies"]
    out = ["% 由 src/py/make_q3_tables.py 自动生成，请勿手工修改",
           r"\begin{table}[H]", r"  \centering",
           r"  \caption{问题三三种滚动调整策略在 2--12 月评价期的费用对比}",
           r"  \label{tab:q3-strategy}", r"  \small",
           r"  \begin{tabular}{lrrrrr}", r"    \toprule",
           r"    策略 & 结算购电费/元 & 紧急购电费/元 & 合计/元 & 调整次数 & 累计调整量/kWh \\",
           r"    \midrule"]
    for key in ("none", "fixed", "selective"):
        d = pol[key]
        out.append(f"    {POLICY_CN[key]} & {fmt(d['fee'], 2)} & {fmt(d['emg_cost'], 2)} & "
                   f"{fmt(d['total'], 2)} & {d['adj_nodes']} & {fmt(d['dq_kwh'], 2)} \\\\")
    none, sel = pol["none"], pol["selective"]
    out.append(r"    \midrule")
    out.append(f"    择优相对仅计划节省 & -- & -- & {fmt(none['total'] - sel['total'], 2)} & -- & -- \\\\")
    out.append(f"    择优相对固定调整节省 & -- & -- & "
               f"{fmt(pol['fixed']['total'] - sel['total'], 2)} & -- & -- \\\\")
    out += [r"    \bottomrule", r"  \end{tabular}", r"\end{table}", ""]
    return "\n".join(out)


def tex_node(summary: dict) -> str:
    pol = summary["policies"]
    out = [r"\begin{table}[H]", r"  \centering",
           r"  \caption{问题三各预报节点的期望边际价值}",
           r"  \label{tab:q3-node}", r"  \small",
           r"  \begin{tabular}{lrrrrr}", r"    \toprule",
           r"    预报时刻 & 期望费用$J_{\text{不调整}}$/元 & 期望费用$J_{\text{调整}}$/元 & "
           r"期望收益/元 & 择优采用次数 & 固定策略采用次数 \\",
           r"    \midrule"]
    for name in ("6:00", "12:00", "18:00"):
        s = pol["selective"]["nodes"][name]
        f = pol["fixed"]["nodes"][name]
        out.append(f"    {name} & {fmt(s['J_keep'], 2)} & {fmt(s['J_adj'], 2)} & "
                   f"{fmt(s['gain'], 2)} & {s['take']}/334 & {f['take']}/334 \\\\")
    out += [r"    \bottomrule", r"  \end{tabular}", r"\end{table}", ""]
    return "\n".join(out)


def tex_accum(summary: dict) -> str:
    ns = summary["node_sets"]
    order = ["0", "6", "6+12", "6+12+18"]
    label = {"0": "仅 0:00", "6": "0:00, 6:00", "6+12": "0:00, 6:00, 12:00",
             "6+12+18": "0:00, 6:00, 12:00, 18:00"}
    out = [r"\begin{table}[H]", r"  \centering",
           r"  \caption{问题三逐次增加预报时刻的评价期费用}",
           r"  \label{tab:q3-accum}", r"  \small",
           r"  \begin{tabular}{lrrrr}", r"    \toprule",
           r"    可用预报时刻 & 全年合计/元 & 相对仅 0:00 降低/元 & 降低占比 & 紧急购电量/kWh \\",
           r"    \midrule"]
    for key in order:
        d = ns[key]
        out.append(f"    {label[key]} & {fmt(d['total'], 2)} & {fmt(d['gain'], 2)} & "
                   f"{pct(d['gain_pct'])}\\% & {fmt(d['emg_kwh'], 2)} \\\\")
    out += [r"    \bottomrule", r"  \end{tabular}", r"\end{table}", ""]
    return "\n".join(out)


def tex_forecast_value(upper: dict) -> str:
    kind = {"real": "附件3 实际预报", "perfect": "完美光伏预报，负荷预测不变"}
    out = [r"\begin{table}[H]", r"  \centering",
           r"  \caption{仅增加一个预报时刻时的评价期信息价值}",
           r"  \label{tab:q3-fv}", r"  \small",
           r"  \begin{tabular}{llrrr}", r"    \toprule",
           r"    发布时刻 $\tau$ & 信息类型 & 全年合计/元 & 相对基线节省/元 & 节省占比 \\",
           r"    \midrule"]
    b = upper["baseline"]
    out.append(f"    无（仅 0:00 计划） & -- & {fmt(b['total'], 2)} & 0.00 & 0.00\\% \\\\")
    out.append(r"    \midrule")
    for c in upper["cases"]:
        out.append(f"    {c['name']} & {kind[c['kind']]} & {fmt(c['total'], 2)} & "
                   f"{fmt(c['gain'], 2)} & {pct(c['gain_pct'])}\\% \\\\")
    out += [r"    \bottomrule", r"  \end{tabular}", r"\end{table}", ""]
    return "\n".join(out)


def collect_date(att: q2.Attachment, f3: q3.PvForecast3, day: dt.date, policy: str) -> dict:
    i = att.day_index(day)
    r = q3.simulate_day(att, f3, att.price, i, policy=policy)
    adj = [e["node"] for e in r["log"] if e["adjusted"]]
    return {"date": day, "plan": float(r["q_plan"].sum()), "adj": float(r["q_adj"].sum()),
            "dq": float(np.abs(r["q_adj"] - r["q_plan"]).sum()),
            "charge": float(r["c_adj"].sum()), "discharge": float(r["d_adj"].sum()),
            "emg_kwh": r["emg_kwh"], "fee": r["fee"], "emg_cost": r["emg_cost"],
            "total": r["total"], "adj_nodes": adj}


def tex_dates(rows: list[dict], policy: str) -> str:
    head = " & ".join(f"{d['date'].month}月{d['date'].day}日" for d in rows)
    out = [r"\begin{table}[H]", r"  \centering",
           r"  \caption{问题三指定日期的滚动调整结果}",
           r"  \label{tab:q3-dates}", r"  \small",
           r"  \begin{tabular}{lrrrr}", r"    \toprule", f"    项目 & {head} \\\\", r"    \midrule"]
    items = [("计划购电量/kWh", "plan", DEC), ("调整购电量/kWh", "adj", DEC),
             ("调整量 $\\sum|\\Delta q|$/kWh", "dq", DEC), ("充电量/kWh", "charge", DEC),
             ("放电量/kWh", "discharge", DEC), ("紧急购电量/kWh", "emg_kwh", DEC),
             ("结算购电费/元", "fee", 2), ("紧急购电费/元", "emg_cost", 2),
             ("全天费用/元", "total", 2)]
    for label, key, dec in items:
        out.append(f"    {label} & " + " & ".join(fmt(d[key], dec) for d in rows) + r" \\")
    out.append(r"    \midrule")
    out.append("    调整节点 & " + " & ".join(
        ("、".join(d["adj_nodes"]) if d["adj_nodes"] else "无") for d in rows) + r" \\")
    out += [r"    \bottomrule", r"  \end{tabular}", r"\end{table}"]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", type=Path, default=None)
    ap.add_argument("--summary", type=Path, default=None)
    ap.add_argument("--upper", type=Path, default=None)
    ap.add_argument("--tex-out", type=Path, default=None)
    ap.add_argument("--txt-out", type=Path, default=None)
    ap.add_argument("--policy", default="selective")
    args = ap.parse_args()

    root = Path(args.data_root) if args.data_root else q2.project_root()
    outs = root / "src" / "outputs"
    summary_path = Path(args.summary) if args.summary else outs / "q3_summary.json"
    upper_path = Path(args.upper) if args.upper else outs / "q3_upper.json"
    tex_out = Path(args.tex_out) if args.tex_out else root / "src" / "tex" / "q3_tables.tex"
    txt_out = Path(args.txt_out) if args.txt_out else outs / "q3_tables.txt"

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    upper = json.loads(upper_path.read_text(encoding="utf-8"))

    att = q2.Attachment(root)
    f3 = q3.PvForecast3(root)
    rows = [collect_date(att, f3, dt.date(2025, m, d), args.policy) for m, d in DATES]

    blocks = [tex_strategy(summary), tex_node(summary), tex_accum(summary),
              tex_forecast_value(upper), tex_dates(rows, args.policy)]
    tex_out.parent.mkdir(parents=True, exist_ok=True)
    tex_out.write_text("\n".join(blocks), encoding="utf-8")

    txt = ["问题三结果表（纯文本核对版）", ""]
    for name in ("none", "fixed", "selective"):
        d = summary["policies"][name]
        txt.append(f"[{name}] 结算 {d['fee']:,.2f} 紧急 {d['emg_cost']:,.2f} "
                   f"合计 {d['total']:,.2f} 调整次数 {d['adj_nodes']} 调整量 {d['dq_kwh']:,.2f}")
    for key, d in summary["node_sets"].items():
        txt.append(f"[node_set {key}] 合计 {d['total']:,.2f} 降低 {d['gain']:,.2f} "
                   f"({d['gain_pct']:.2f}%) 紧急 {d['emg_kwh']:,.2f}")
    b = upper["baseline"]
    txt.append(f"[upper base] 合计 {b['total']:,.2f} 紧急 {b['emg_kwh']:,.2f}")
    for c in upper["cases"]:
        txt.append(f"[upper {c['name']} {c['kind']}] 合计 {c['total']:,.2f} "
                   f"节省 {c['gain']:,.2f} ({c['gain_pct']:.2f}%) 紧急 {c['emg_kwh']:,.2f}")
    for d in rows:
        txt.append(f"[date {d['date']}] 计划 {d['plan']:.4f} 调整 {d['adj']:.4f} "
                   f"调整量 {d['dq']:.4f} 充 {d['charge']:.4f} 放 {d['discharge']:.4f} "
                   f"紧急 {d['emg_kwh']:.4f} kWh/{d['emg_cost']:.4f} 元 "
                   f"费用 {d['fee']:.4f}+{d['emg_cost']:.4f}={d['total']:.4f} 节点 {d['adj_nodes']}")
    txt_out.parent.mkdir(parents=True, exist_ok=True)
    txt_out.write_text("\n".join(txt), encoding="utf-8")
    print(f"已写入 {tex_out}")
    print(f"已写入 {txt_out}")
    print("\n".join(txt))


if __name__ == "__main__":
    main()
