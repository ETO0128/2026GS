"""问题四 4-3 结果绘图（论文用图）。

运行：
    python src/py/plot_question4.py

输出（同时保存 pdf 与 png）：
    src/tex/figure/q4_price_band.pdf 附件4 电价的日间波动带与附件1 曲线
    src/tex/figure/q4_3_cost.pdf     4-3 各方案全年费用对比
    src/tex/figure/q4_2_cost.pdf     4-2 各方案全年费用对比
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import q2_model as q2
import q4_model as q4

plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei"],
    "axes.unicode_minus": False,
    "font.size": 10,
    "axes.labelsize": 10,
    "legend.fontsize": 8.5,
    "figure.dpi": 120,
    "savefig.dpi": 300,
})
BLUE, RED, GRAY, ORANGE = "#2F5597", "#C00000", "#7F7F7F", "#C65911"
NAME_CN = {
    "fixed_price": "固定电价\n（问题三基准）",
    "volatile_oracle_none": "波动电价\n不调整",
    "volatile_oracle": "波动电价\n已知当天电价",
    "volatile_prev": "波动电价\n前一日价格预测",
    "volatile_profile": "波动电价\n历史扩展均值",
    "volatile_seven_day": "波动电价\n近七日均值",
    "volatile_previous_day": "波动电价\n前一日曲线",
    "volatile_week_type": "波动电价\n同星期类型",
    "volatile_similar_decay": "波动电价\n相似日衰减",
    "volatile_expanding_mean": "波动电价\n历史扩展均值",
    "volatile_oracle_benchmark": "当日电价\n信息基准",
}
NAME_CN_42 = {
    "fixed_price": "固定电价\n（问题二基准）",
    "volatile_seven_day": "波动电价\n近七日均值",
    "volatile_previous_day": "波动电价\n前一日曲线",
    "volatile_week_type": "波动电价\n同星期类型",
    "volatile_similar_decay": "波动电价\n相似日衰减",
    "volatile_expanding_mean": "波动电价\n历史扩展均值",
    "volatile_oracle_benchmark": "当日电价\n信息基准",
}


def figure_price_band(p4: q4.Prices4, att: q2.Attachment, fig_dir: Path) -> None:
    pr = p4.price
    hour = np.arange(q2.N + 1) * 10 / 60
    qs = np.quantile(pr, [0.1, 0.25, 0.5, 0.75, 0.9], axis=0)
    fig, ax = plt.subplots(figsize=(7.2, 3.4), constrained_layout=True)
    ax.fill_between(hour[:-1], qs[0], qs[4], step="post", color=BLUE, alpha=0.12,
                    label="附件4 电价 10%~90% 分位带")
    ax.fill_between(hour[:-1], qs[1], qs[3], step="post", color=BLUE, alpha=0.25,
                    label="25%~75% 分位带")
    ax.step(hour[:-1], qs[2], where="post", color=BLUE, linewidth=1.4, label="附件4 逐时段中位数")
    ax.step(hour[:-1], att.price, where="post", color=RED, linewidth=1.6,
            label="附件1 固定电价（= 附件4 逐时段均值）")
    ax.set_xlim(0, 24)
    ax.set_xticks(np.arange(0, 25, 2))
    ax.set_xlabel("时刻/h")
    ax.set_ylabel("电价/(元·kWh$^{-1}$)")
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.6)
    ax.legend(frameon=False, ncol=2, loc="upper left")
    ax.set_title("附件4 波动电价：平均日内形态接近附件1，单日价格仍有明显偏差", fontsize=10)
    fig.savefig(fig_dir / "q4_price_band.pdf", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def figure_cost(sum_: dict, fig_dir: Path) -> None:
    order = ["fixed_price", "volatile_seven_day", "volatile_profile",
             "volatile_prev", "volatile_oracle", "volatile_oracle_none"]
    v = sum_["variants"]
    tot = [v[k]["total"] / 1e4 for k in order]
    colors = [GRAY, BLUE, BLUE, BLUE, BLUE, ORANGE]
    alphas = [1.0, 1.0, 0.65, 0.65, 0.65, 1.0]
    fig, ax = plt.subplots(figsize=(7.2, 3.4), constrained_layout=True)
    bars = ax.bar(range(len(order)), tot, color=colors, width=0.62)
    for b, a in zip(bars, alphas):
        b.set_alpha(a)
    for k, y in enumerate(tot):
        ax.text(k, y + 12, f"{y:,.1f}", ha="center", fontsize=8)
    ax.axhline(sum_["perfect_bound"]["total"] / 1e4, color=RED, linestyle="--", linewidth=1.2,
               label=f"完全信息下界 {sum_['perfect_bound']['total']/1e4:,.1f} 万元")
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([NAME_CN[k] for k in order], fontsize=8)
    ax.set_ylabel("全年费用/万元")
    ax.set_ylim(min(tot + [sum_["perfect_bound"]["total"] / 1e4]) * 0.93, max(tot) * 1.04)
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.6)
    ax.legend(frameon=False, loc="lower right")
    ax.set_title("问题四：波动电价下日内方案的全年费用", fontsize=10)
    fig.savefig(fig_dir / "q4_3_cost.pdf", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def figure_cost42(sum42: dict, fig_dir: Path) -> None:
    order = ["fixed_price", "volatile_seven_day", "volatile_similar_decay",
             "volatile_expanding_mean", "volatile_previous_day", "volatile_oracle_benchmark"]
    v = sum42["variants"]
    tot = [v[k]["total"] / 1e4 for k in order]
    fig, ax = plt.subplots(figsize=(7.2, 3.4), constrained_layout=True)
    bars = ax.bar(range(len(order)), tot, color=[GRAY, BLUE, BLUE, BLUE], width=0.62)
    for b, a in zip(bars, [1.0, 1.0, 0.6, 0.6]):
        b.set_alpha(a)
    for k, y in enumerate(tot):
        ax.text(k, y + 12, f"{y:,.1f}", ha="center", fontsize=8)
    ax.axhline(sum42["perfect_bound"]["total"] / 1e4, color=RED, linestyle="--", linewidth=1.2,
               label=f"完全信息下界 {sum42['perfect_bound']['total']/1e4:,.1f} 万元")
    ax.set_xticks(range(len(order)))
    ax.set_xticklabels([NAME_CN_42[k] for k in order], fontsize=8)
    ax.set_ylabel("全年费用/万元")
    ax.set_ylim(min(tot + [sum42["perfect_bound"]["total"] / 1e4]) * 0.93, max(tot) * 1.04)
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.6)
    ax.legend(frameon=False, loc="lower right")
    ax.set_title("问题四：波动电价下日前方案的全年费用", fontsize=10)
    fig.savefig(fig_dir / "q4_2_cost.pdf", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-root", type=Path, default=None)
    ap.add_argument("--figure-dir", type=Path, default=None)
    args = ap.parse_args()
    root = Path(args.data_root) if args.data_root else q2.project_root()
    fig_dir = Path(args.figure_dir) if args.figure_dir else root / "src" / "tex" / "figure"
    fig_dir.mkdir(parents=True, exist_ok=True)
    att = q2.Attachment(root)
    p4 = q4.Prices4(root, att)
    sp = root / "src" / "outputs" / "q4_3_summary.json"
    if not sp.exists():
        raise SystemExit(f"缺少 {sp}，请先运行 run_q4_3.py")
    sum_ = json.loads(sp.read_text(encoding="utf-8"))
    figure_price_band(p4, att, fig_dir)
    figure_cost(sum_, fig_dir)
    sp42 = root / "src" / "outputs" / "q4_2_summary.json"
    if sp42.exists():
        figure_cost42(json.loads(sp42.read_text(encoding="utf-8")), fig_dir)
    print(f"图片已写入 {fig_dir}")


if __name__ == "__main__":
    main()
