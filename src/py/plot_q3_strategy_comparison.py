"""Generate the compact Question 3 strategy comparison used in the paper."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams.update({"font.sans-serif": ["Microsoft YaHei", "SimHei"],
                     "axes.unicode_minus": False, "font.size": 9})


def main():
    root = Path(__file__).resolve().parents[2]
    out = root / "src" / "tex" / "figure"
    out.mkdir(parents=True, exist_ok=True)
    names = ["仅0:00计划", "每节点固定调整", "择优调整"]
    purchase = np.array([13970022.16, 14064076.89, 14021846.77]) / 1e4
    emergency = np.array([2042560.73, 1727402.48, 1751767.95]) / 1e4
    fig, axes = plt.subplots(1, 2, figsize=(7.3, 3.25), constrained_layout=True)
    x = np.arange(3)
    axes[0].bar(x, purchase, color="#4472C4", label="结算购电费")
    axes[0].bar(x, emergency, bottom=purchase, color="#ED7D31", label="紧急购电费")
    totals = purchase + emergency
    for i, value in enumerate(totals):
        axes[0].text(i, value + 5, f"{value:.1f}", ha="center", fontsize=8)
    axes[0].set_xticks(x, names)
    axes[0].set_ylabel("全年费用/万元")
    axes[0].set_title("(a) 三种调整策略的费用构成")
    axes[0].legend(frameon=False, fontsize=8)
    nodes = ["6:00", "12:00", "18:00"]
    gains = np.array([111650.49, 109441.61, 11.42]) / 1e4
    bars = axes[1].bar(nodes, gains, color=["#70AD47", "#70AD47", "#A5A5A5"])
    for bar, value in zip(bars, gains):
        axes[1].text(bar.get_x() + bar.get_width()/2, value + 0.15,
                     f"{value:.2f}", ha="center", fontsize=8)
    axes[1].set_ylabel("新增节点的边际节省/万元")
    axes[1].set_title("(b) 逐次增加预测节点的边际价值")
    for ax in axes:
        ax.grid(axis="y", color="#D9D9D9", linewidth=0.6)
        ax.spines[["top", "right"]].set_visible(False)
    fig.savefig(out / "q3_strategy_comparison.pdf", bbox_inches="tight", facecolor="white")
    plt.close(fig)


if __name__ == "__main__":
    main()
