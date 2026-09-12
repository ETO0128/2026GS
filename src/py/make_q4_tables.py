"""生成论文需要的问题四 4-2/4-3 结果表与插图。

运行：
    python src/py/make_q4_tables.py      # 读取 src/outputs/q4_3_summary.json、q4_2_summary.json 生成 tex
    python src/py/plot_question4.py      # 生成 figure/q4_price_band、q4_3_cost、q4_2_cost

输出：
    src/tex/q4_tables.tex      （4-3 表 1/表 2）
    src/tex/q4_2_tables.tex    （4-2 表）
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


ORDER_42 = ["previous_day", "seven_day", "week_type", "similar_day_decay"]
NAME_CN_42 = {
    "previous_day": "前一日同一时刻",
    "seven_day": "七日均值（正式）",
    "week_type": "星期类型均值",
    "similar_day_decay": "相似日 $+$ 时间衰减",
}


def tex_table42(cmp42: dict, hybrid: dict | None = None, b42: dict | None = None) -> str:
    """4-2 执行口径对比表（口径 A / 口径 B 因果 / 口径 B 完全信息上界）。"""
    out = ["% 由 src/py/make_q4_tables.py 自动生成，请勿手工修改",
           r"\begin{table}[H]", r"  \centering",
           r"  \caption{问题四 4-2：波动电价下的执行口径对比（全年 334 天）}",
           r"  \label{tab:q4-2}", r"  \small",
           r"  \begin{tabular}{lrrrr}", r"    \toprule",
           r"    方案 & 购电费/元 & 紧急购电费/元 & 合计/元 & 相对问题二基准 \\",
           r"    \midrule"]
    base = None
    if hybrid is not None:
        q2n = hybrid["q2_no_adjust"]
        base = q2n["total_yuan"]
        out.append(f"    问题二基准（附件1 固定电价） & {fmt(q2n['contract_fee_yuan'])} & "
                   f"{fmt(q2n['emergency_cost_yuan'])} & {fmt(base)} & -- \\\\")
    if base is None:
        base = cmp42["variants"]["seven_day"]["total_cost_yuan"]
    if b42 is not None:
        normal = sum(float(x.get("plan_cost", x.get("normal", 0.0))) for x in b42["detail"])
        emg_c = b42["causal"]["total"] - normal
        emg_a = cmp42["variants"]["seven_day"]["emergency_cost_yuan"]
        out.append(f"    4-2 口径 A（严格按计划执行） & {fmt(normal)} & {fmt(emg_a)} & "
                   f"{fmt(b42['official_A'])} & "
                   f"{(b42['official_A'] - base) / base * 100:+.2f}\\% \\\\")
        out.append(f"    \\textbf{{4-2 口径 B（储能日内滚动再调度，正式结果）}} & {fmt(normal)} & "
                   f"{fmt(emg_c)} & {fmt(b42['causal']['total'])} & "
                   f"{(b42['causal']['total'] - base) / base * 100:+.2f}\\% \\\\")
        out.append(f"    4-2 口径 B（日内完全信息上界） & {fmt(normal)} & "
                   f"{fmt(b42['oracle']['total'] - normal)} & {fmt(b42['oracle']['total'])} & "
                   f"{(b42['oracle']['total'] - base) / base * 100:+.2f}\\% \\\\")
    lb = cmp42["variants"]["seven_day"]["perfect_information_cost_yuan"]
    out.append(r"    \midrule")
    out.append(f"    完全信息下界（已知真实电价/负荷/光伏） & -- & -- & {fmt(lb)} & "
               f"{(lb - base) / base * 100:+.2f}\\% \\\\")
    out += [r"    \bottomrule", r"  \end{tabular}", r"\end{table}", ""]
    return "\n".join(out)


def tex_table42_price(cmp42: dict, hybrid: dict | None = None) -> str:
    """4-2 四种因果电价预测口径的全年费用（口径 A 下）。"""
    v = cmp42["variants"]
    base = hybrid["q2_no_adjust"]["total_yuan"] if hybrid is not None else v["seven_day"]["total_cost_yuan"]
    out = [r"\begin{table}[H]", r"  \centering",
           r"  \caption{问题四 4-2：四种因果电价预测口径的全年费用（口径 A，购电与源荷计划相同）}",
           r"  \label{tab:q4-2-price}", r"  \small",
           r"  \begin{tabular}{lrrrr}", r"    \toprule",
           r"    电价预测口径 & 价格 MAE/(元·kWh$^{-1}$) & 正常购电费/元 & 紧急购电费/元 & 合计/元 \\",
           r"    \midrule"]
    for key in ORDER_42:
        d = v[key]
        out.append(f"    {NAME_CN_42[key]} & {d['price_mae_yuan_per_kwh']:.5f} & "
                   f"{fmt(d['normal_purchase_cost_yuan'])} & {fmt(d['emergency_cost_yuan'])} & "
                   f"{fmt(d['total_cost_yuan'])} \\\\")
    out += [r"    \bottomrule", r"  \end{tabular}", r"\end{table}", ""]
    return "\n".join(out)


def tex_table43opt(opt: dict, summary43: dict | None) -> str:
    """4-3 执行口径与安全分位对冲的全年对比（由 q4_3_opt.json 生成）。"""
    runs = opt["runs"]
    base = None
    if summary43 is not None:
        base = summary43["variants"]["volatile_oracle"]["total"]
    else:
        base = runs["q43_A_hedge"]["total"]
    out = [r"\begin{table}[H]", r"  \centering",
           r"  \caption{问题四 4-3：安全分位对冲与执行口径的全年对比（334 天，价格信息口径为已知当天电价）}",
           r"  \label{tab:q4-3-opt}", r"  \small",
           r"  \begin{tabular}{lrrrr}", r"    \toprule",
           r"    方案 & 结算购电费/元 & 紧急购电费/元 & 合计/元 & 相对基准 \\",
           r"    \midrule"]
    out.append(f"    4-3 口径 A（与问题三同模型） & 14,646,966.27 & 1,836,094.20 & {fmt(base)} & -- \\\\")
    for key, cn in (("q43_A_hedge", "口径 A $+$ 安全分位对冲（80\\% 分位）"),
                    ("q43_B_hedge_sel", "\\textbf{对冲 $+$ 口径 B（储能日内滚动再调度）}"),
                    ("q43_B_hedge_none", "对冲 $+$ 口径 B（不做购电调整）")):
        r = runs[key]
        out.append(f"    {cn} & {fmt(r['fee'])} & {fmt(r['emg_cost'])} & {fmt(r['total'])} & "
                   f"{(r['total'] - base) / base * 100:+.2f}\\% \\\\")
    lb = 12831089.48
    out.append(r"    \midrule")
    out.append(f"    完全信息下界（已知真实电价/负荷/光伏） & -- & -- & {fmt(lb)} & "
               f"{(lb - base) / base * 100:+.2f}\\% \\\\")
    out += [r"    \bottomrule", r"  \end{tabular}", r"\end{table}", ""]
    return "\n".join(out)


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
    extra = ""
    opt_path = root / "src" / "outputs" / "q4_3_opt.json"
    s43_path = root / "src" / "outputs" / "q4_3_summary.json"
    if opt_path.exists():
        s43 = json.loads(s43_path.read_text(encoding="utf-8")) if s43_path.exists() else None
        extra = tex_table43opt(json.loads(opt_path.read_text(encoding="utf-8")), s43) + "\n"
    tex_out.write_text(tex_price_stats(sum_["price_stats"]) + "\n" + tex_table(sum_) + "\n"
                       + extra, encoding="utf-8")
    print(f"已写入 {tex_out}")
    sp42 = root / "src" / "outputs" / "q4_2_price_forecast_compare.json"
    if sp42.exists():
        cmp42 = json.loads(sp42.read_text(encoding="utf-8"))
        hyb_path = root / "src" / "outputs" / "q3_hybrid_experiment.json"
        hybrid = json.loads(hyb_path.read_text(encoding="utf-8")) if hyb_path.exists() else None
        b_path = root / "src" / "outputs" / "q4_2_B.json"
        b42 = json.loads(b_path.read_text(encoding="utf-8")) if b_path.exists() else None
        out42 = tex_out.with_name("q4_2_tables.tex")
        out42.write_text(tex_table42(cmp42, hybrid, b42) + "\n"
                         + tex_table42_price(cmp42, hybrid) + "\n", encoding="utf-8")
        print(f"已写入 {out42}")
    for k in ORDER:
        d = sum_["variants"][k]
        print(f"  {k}: 合计 {d['total']:,.2f} 元，调整 {d['adj_nodes']} 次")
    print(f"  完全信息下界: {sum_['perfect_bound']['total']:,.2f} 元")


if __name__ == "__main__":
    main()
