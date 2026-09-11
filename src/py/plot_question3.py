"""问题三结果绘图（论文用图）。

运行：
    python src/py/plot_question3.py

输出（同时保存 pdf 与 png）：
    src/tex/figure/q3_forecast_value.pdf 其他时刻预报的价值（上界）与节点累积价值
    src/tex/figure/q3_adjust_day.pdf     指定日期的计划购电量 vs 调整购电量
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import q2_model as q
import q3_model as q3

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


def figure_forecast_value(upper: dict, summary: dict, fig_dir: Path) -> None:
    cases = upper["cases"]
    names = [c["name"] for c in cases]
    gains = [c["gain"] for c in cases]
    colors = [ORANGE if c["kind"] == "perfect" else BLUE for c in cases]
    fig, axes = plt.subplots(1, 2, figsize=(7.6, 3.3), constrained_layout=True)

    ax = axes[0]
    ax.bar(range(len(cases)), gains, color=colors, width=0.62)
    ax.set_xticks(range(len(cases)))
    ax.set_xticklabels(names, fontsize=8.5)
    ax.axhline(0, color="#666666", linewidth=0.6)
    for k, g in enumerate(gains):
        ax.text(k, g + max(gains) * 0.02, f"{g/1e4:.1f}", ha="center", fontsize=7.5)
    ax.set_xlabel("预报发布时刻 $\\tau$")
    ax.set_ylabel("全年节省/元")
    ax.set_title("单独引入一个 $\\tau$ 时刻预报的全年价值\n"
                 "橙色=完美预报上界，蓝色=附件3 实际预报", fontsize=9)
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.5)

    ax = axes[1]
    ns = summary["node_sets"]
    order = ["0", "6", "6+12", "6+12+18"]
    label = ["仅 0:00", "+6:00", "+12:00", "+18:00"]
    tot = [ns[k]["total"] / 1e7 for k in order]
    ax.plot(range(4), tot, marker="o", color=BLUE, linewidth=1.6)
    for k, (x, y) in enumerate(zip(range(4), tot)):
        ax.annotate(f"{y:.4f}", (x, y), textcoords="offset points", xytext=(0, 7),
                    ha="center", fontsize=8)
    ax.set_xticks(range(4))
    ax.set_xticklabels(label, fontsize=8.5)
    ax.set_ylim(min(tot) - 0.008, max(tot) + 0.012)
    ax.set_xlabel("可用的预报时刻（累积）")
    ax.set_ylabel("全年合计费用/$10^{7}$元")
    ax.set_title("逐次增加预报时刻的全年费用\n（固定调整策略）", fontsize=9)
    ax.grid(color="#D9D9D9", linewidth=0.5)

    fig.savefig(fig_dir / "q3_forecast_value.pdf", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def figure_adjust_day(att: q.Attachment, f3: q3.PvForecast3, fig_dir: Path, day: dt.date,
                      policy: str) -> None:
    i = att.day_index(day)
    r = q3.simulate_day(att, f3, att.price, i, policy=policy)
    hour = np.arange(q.N + 1) * 10 / 60
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 5.0), sharex=True, constrained_layout=True)

    ax = axes[0]
    ax.step(np.append(hour[:-1], 24), np.append(r["q_plan"], r["q_plan"][-1]), where="post",
            color=GRAY, linewidth=1.5, label="0:00 计划购电量 $q^{\\mathrm{plan}}$")
    ax.step(np.append(hour[:-1], 24), np.append(r["q_adj"], r["q_adj"][-1]), where="post",
            color=RED, linewidth=1.7, label="调整后购电量 $q^{\\mathrm{adj}}$")
    ax.fill_between(np.append(hour[:-1], 24),
                    np.append(r["q_plan"], r["q_plan"][-1]),
                    np.append(r["q_adj"], r["q_adj"][-1]),
                    step="post", color=RED, alpha=0.15, label="调整量")
    ax2 = ax.twinx()
    ax2.step(np.append(hour[:-1], 24), np.append(att.price, att.price[-1]), where="post",
             color=ORANGE, linewidth=1.0, alpha=0.75, linestyle="--", label="交易时刻电价")
    ax2.set_ylabel("电价/(元·kWh$^{-1}$)", color=ORANGE)
    ax2.tick_params(axis="y", colors=ORANGE)
    ax.set_ylabel("购电量/(kWh/时段)")
    ax.set_xlim(0, 24)
    ax.set_xticks(np.arange(0, 25, 4))
    ax.set_title(f"{day:%Y-%m-%d} 滚动调整：计划购电量与调整后购电量", fontsize=10)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, frameon=False, loc="upper left", ncol=2)
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.6)

    ax = axes[1]
    ax.plot(hour, r["e_plan"], color=GRAY, linewidth=1.5, label="计划储电量")
    ax.plot(hour, r["e_adj"], color=RED, linewidth=1.7, label="调整后储电量")
    ax.axhline(q.E_MIN, color=GRAY, linestyle=":", linewidth=0.9, label="储电量上/下限")
    ax.axhline(q.E_MAX, color=GRAY, linestyle=":", linewidth=0.9)
    for tau in (360, 720, 1080):
        ax.axvline(tau / 60, color=BLUE, linestyle="--", linewidth=0.8, alpha=0.6)
    ax.text(0.02, 0.92, "蓝色虚线为 6:00/12:00/18:00 预报更新节点", transform=ax.transAxes,
            fontsize=8, color=BLUE)
    ax.set_ylabel("储电量/kWh")
    ax.set_xlabel("时刻/h")
    ax.set_xlim(0, 24)
    ax.set_ylim(0, 12000)
    ax.legend(frameon=False, ncol=3, loc="lower left")
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.6)
    fig.savefig(fig_dir / "q3_adjust_day.pdf", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--day", default="2025-09-23")
    ap.add_argument("--policy", default="selective")
    ap.add_argument("--data-root", type=Path, default=None)
    ap.add_argument("--figure-dir", type=Path, default=None)
    args = ap.parse_args()

    root = Path(args.data_root) if args.data_root else q.project_root()
    fig_dir = Path(args.figure_dir) if args.figure_dir else root / "src" / "tex" / "figure"
    fig_dir.mkdir(parents=True, exist_ok=True)
    outs = root / "src" / "outputs"

    upper_path = outs / "q3_upper.json"
    summary_path = outs / "q3_summary.json"
    if not upper_path.exists() or not summary_path.exists():
        raise SystemExit(f"缺少 {upper_path} 或 {summary_path}，请先运行 run_q3.py 与 run_q3_upper.py")
    upper = json.loads(upper_path.read_text(encoding="utf-8"))
    summary = json.loads(summary_path.read_text(encoding="utf-8"))

    att = q.Attachment(root)
    f3 = q3.PvForecast3(root)
    figure_forecast_value(upper, summary, fig_dir)
    figure_adjust_day(att, f3, fig_dir, dt.date.fromisoformat(args.day), args.policy)
    print(f"图片已写入 {fig_dir}")


if __name__ == "__main__":
    main()
