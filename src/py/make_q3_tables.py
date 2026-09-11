"""生成论文需要的问题三结果表。

数据来源全部是代码产物，不手抄：
    src/outputs/q3_summary.json             由 run_q3.py 生成
    src/outputs/q3_upper.json               由 run_q3_upper.py 生成
    src/outputs/q3_hybrid_experiment.json   由 q3_hybrid_experiment.py 生成（双层方案）
    src/outputs/q3_improvement_full.json    由 q3_improvement_experiment.py 生成（消融/稳健性）
    src/py/q3_model.simulate_day            指定日期结果现算（4 天，秒级）

运行：
    python src/py/make_q3_tables.py
输出：
    src/tex/q3_tables.tex         论文用 LaTeX 表格（main.tex 中 \\input{q3_tables} 引入）
    src/tex/q3_bridge_tables.tex  双层方案表与消融表（\\input{q3_bridge_tables} 引入）
    src/outputs/q3_tables.txt     纯文本版，便于核对
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


def fmt_ci(x: float) -> str:
    """区间端点：用 {,} 保护千分位逗号，避免 LaTeX 把它当成数学模式的数字。"""
    s = f"{x:,.2f}"
    return s.replace(",", "{,}")


def pct(x: float) -> str:
    """百分比，接近 0 时避免出现 -0.00。"""
    return "0.00" if abs(x) < 0.005 else f"{x:.2f}"


def tex_strategy(summary: dict) -> str:
    pol = summary["policies"]
    out = ["% 由 src/py/make_q3_tables.py 自动生成，请勿手工修改",
           r"\begin{table}[H]", r"  \centering",
           r"  \caption{问题三三种滚动调整策略的全年费用对比（2025 年 2 月 1 日--12 月 31 日，共 334 天）}",
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
           r"  \caption{问题三各预报节点的期望边际价值（全年累计，期望值在模型自身的场景测度下计算）}",
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
           r"  \caption{问题三逐次增加可用预报时刻的全年费用（固定调整策略，用以回答“是否需要其他时刻的预报”）}",
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
    kind = {"real": "附件3 实际预报", "perfect": "完美预报（上界）"}
    out = [r"\begin{table}[H]", r"  \centering",
           r"  \caption{其他时刻光伏预报的全年价值：仅在 0:00 定计划后，单独引入一个 $\tau$ 时刻预报并调整一次}",
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
           r"  \caption{问题三指定日期的滚动调整结果（择优调整策略，与 \texttt{result3.xlsx} 一致）}",
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


def tex_bridge(hybrid: dict) -> str:
    """双层方案：问题二合同 + 问题三滚动（严格递进）与 0:00 联合优化。"""
    q2n = hybrid["q2_no_adjust"]
    strict = hybrid["q2_contract_plus_lcy_rolling"]
    joint = hybrid["lcy_baseline"]
    b1 = hybrid["bootstrap_hybrid_vs_q2"]["ci95_yuan"]
    b2 = hybrid["bootstrap_lcy_vs_hybrid"]["ci95_yuan"]
    out = [r"\begin{table}[H]", r"  \centering",
           r"  \caption{问题三与问题二的衔接：两种信息边界下的全年结果（334 天）}",
           r"  \label{tab:q3-bridge}", r"  \small",
           r"  \begin{tabular}{llrrrr}", r"    \toprule",
           r"    方案 & 0:00 计划来源 & 全年费用/元 & 紧急购电量/kWh & 相对上一行节省/元 & 节省 95\% 区间/元 \\",
           r"    \midrule"]
    out.append(f"    问题二方案（不调整） & 问题二日前计划 & {fmt(q2n['total_yuan'], 2)} & "
               f"{fmt(q2n['emergency_kwh'], 2)} & -- & -- \\\\")
    out.append(f"    严格递进方案 & 沿用问题二合同 & {fmt(strict['total_yuan'], 2)} & "
               f"{fmt(strict['emergency_kwh'], 2)} & {fmt(hybrid['hybrid_saving_vs_q2_yuan'], 2)} & "
               f"$[{fmt_ci(b1[0])},\\;{fmt_ci(b1[1])}]$ \\\\")
    out.append(f"    \\textbf{{联合方案（正式结果）}} & 0:00 联合优化 & "
               f"{fmt(joint['total_yuan'], 2)} & {fmt(joint['emergency_kwh'], 2)} & "
               f"{fmt(hybrid['hybrid_difference_vs_lcy_yuan'], 2)} & "
               f"$[{fmt_ci(b2[0])},\\;{fmt_ci(b2[1])}]$ \\\\")
    out += [r"    \bottomrule", r"  \end{tabular}", r"\end{table}", ""]
    return "\n".join(out)


ABLATION_CN = {
    "legacy_reproduction": "基准（本文方案）",
    "official_forecast_only": "换成问题二正式七日均值负荷预测",
    "plus_pv_interpolation": "七日均值 + 光伏线性插值",
    "plus_weighted_scenarios": "七日均值 + 插值 + 时间衰减场景",
    "legacy_plus_interpolation": "本文预测 + 光伏线性插值",
    "legacy_plus_weighted_scenarios": "本文预测 + 时间衰减场景",
    "legacy_plus_both": "本文预测 + 插值 + 时间衰减场景",
}
ABLATION_ORDER = ["legacy_reproduction", "official_forecast_only", "plus_pv_interpolation",
                  "plus_weighted_scenarios", "legacy_plus_interpolation",
                  "legacy_plus_weighted_scenarios", "legacy_plus_both"]


def tex_ablation(improve: dict) -> str:
    """消融/稳健性：负荷预测口径、光伏插值、场景权重。"""
    v = improve["variants"]
    base = v["legacy_reproduction"]["total_yuan"]
    out = [r"\begin{table}[H]", r"  \centering",
           r"  \caption{问题三消融实验（全年 334 天，锁定区间）：负荷预测口径、光伏插值与场景权重}",
           r"  \label{tab:q3-ablation}", r"  \small",
           r"  \begin{tabular}{lrrr}", r"    \toprule",
           r"    变体 & 全年费用/元 & 相对基准 & 紧急购电量/kWh \\", r"    \midrule"]
    for key in ABLATION_ORDER:
        d = v[key]
        rel = "--" if key == "legacy_reproduction" else \
            f"{(d['total_yuan'] - base) / base * 100:+.2f}\\%"
        out.append(f"    {ABLATION_CN[key]} & {fmt(d['total_yuan'], 2)} & {rel} & "
                   f"{fmt(d['emergency_kwh'], 2)} \\\\")
    out += [r"    \bottomrule", r"  \end{tabular}", r"\end{table}", ""]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", type=Path, default=None)
    ap.add_argument("--summary", type=Path, default=None)
    ap.add_argument("--upper", type=Path, default=None)
    ap.add_argument("--hybrid", type=Path, default=None)
    ap.add_argument("--improve", type=Path, default=None)
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
    hybrid_path = Path(args.hybrid) if args.hybrid else outs / "q3_hybrid_experiment.json"
    improve_path = Path(args.improve) if args.improve else outs / "q3_improvement_full.json"

    att = q2.Attachment(root)
    f3 = q3.PvForecast3(root)
    rows = [collect_date(att, f3, dt.date(2025, m, d), args.policy) for m, d in DATES]

    blocks = [tex_strategy(summary), tex_node(summary), tex_accum(summary),
              tex_forecast_value(upper), tex_dates(rows, args.policy)]
    tex_out.parent.mkdir(parents=True, exist_ok=True)
    tex_out.write_text("\n".join(blocks), encoding="utf-8")

    if hybrid_path.exists() and improve_path.exists():
        hybrid = json.loads(hybrid_path.read_text(encoding="utf-8"))
        improve = json.loads(improve_path.read_text(encoding="utf-8"))
        bridge_tex = tex_out.with_name("q3_bridge_tables.tex")
        bridge_tex.write_text(tex_bridge(hybrid) + "\n" + tex_ablation(improve) + "\n",
                              encoding="utf-8")
        print(f"已写入 {bridge_tex}")
    else:
        print(f"跳过双层/消融表（缺少 {hybrid_path.name} 或 {improve_path.name}）")

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
