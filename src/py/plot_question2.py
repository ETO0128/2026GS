"""问题二随机规划结果绘图（论文用图）。

运行：
    python src/py/run_question2.py       # 先生成 src/outputs/q2_margin_slots.npy
    python src/py/plot_question2.py      # 再绘图

输出（同时保存 pdf 与 png）：
    src/tex/figure/q2_scenario_plan.pdf 场景扇形 + 确定性/随机计划 + 储电量轨迹
    src/tex/figure/q2_safety_margin.pdf 安全余量随不确定性增大、集中在高价时段
"""
from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import q2_model as q
import q2_stochastic as qs

plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei"],
    "axes.unicode_minus": False,
    "font.size": 10,
    "axes.labelsize": 10,
    "legend.fontsize": 9,
    "figure.dpi": 120,
    "savefig.dpi": 300,
})
BLUE, RED, GRAY, ORANGE = "#2F5597", "#C00000", "#7F7F7F", "#C65911"


def figure_scenario_plan(att: q.Attachment, cache: dict, fig_dir: Path, day: dt.date,
                         s_max: int) -> None:
    i = att.day_index(day)
    fl, fv = cache[i]
    scen, w = qs.make_scenarios(att, i, cache, s_max=s_max)
    det = q.plan_lp(att.price, fl, fv, q.E0_KWH, "cycle")
    sto = qs.stochastic_plan(att, (fl, fv), scen, w, q.E0_KWH, beta=0.0)

    hour = np.arange(q.N + 1) * 10 / 60
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 5.6), sharex=True, constrained_layout=True)
    ax = axes[0]
    for k, (Lk, Vk) in enumerate(scen):
        ax.step(np.append(hour[:-1], 24), np.append(Lk - Vk, (Lk - Vk)[-1]), where="post",
                color=GRAY, linewidth=0.8, alpha=0.55,
                label="场景净负荷（历史残差整日抽样）" if k == 0 else None)
    ax.step(np.append(hour[:-1], 24), np.append(det["g"], det["g"][-1]), where="post",
            color=BLUE, linewidth=1.8, label="确定性计划购电量（点预测）")
    ax.step(np.append(hour[:-1], 24), np.append(sto["g"], sto["g"][-1]), where="post",
            color=RED, linewidth=1.8, label="两阶段随机计划购电量（含安全余量）")
    ax.axhline(0, color="#666666", linewidth=0.6)
    ax.set_ylabel("电量/(kWh/时段)")
    ax.set_xlim(0, 24)
    ax.set_xticks(np.arange(0, 25, 4))
    ax.legend(frameon=False, loc="upper left")
    ax.set_title(f"{day:%Y-%m-%d} 两阶段随机规划：场景、确定性计划与随机计划", fontsize=10)
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.6)

    ax = axes[1]
    ax.plot(hour, det["e"], color=BLUE, linewidth=1.7, label="确定性计划的储电量")
    ax.plot(hour, sto["e1"], color=RED, linewidth=1.7, label="随机计划的储电量")
    ax.axhline(q.E_MIN, color=GRAY, linestyle="--", linewidth=0.9, label="储电量上/下限")
    ax.axhline(q.E_MAX, color=GRAY, linestyle="--", linewidth=0.9)
    ax.set_ylabel("储电量/kWh")
    ax.set_xlabel("时刻/h")
    ax.set_xlim(0, 24)
    ax.set_ylim(0, 12000)
    ax.legend(frameon=False, ncol=2, loc="upper left")
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.6)
    fig.savefig(fig_dir / "q2_scenario_plan.pdf", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def figure_safety_margin(margin_file: Path, fig_dir: Path) -> None:
    ms = np.load(margin_file)
    sig, mg, pr = ms[:, 0], ms[:, 1], ms[:, 2]
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.3), constrained_layout=True)
    ax = axes[0]
    ax.scatter(sig, mg, s=3, color=BLUE, alpha=0.25, edgecolors="none")
    if len(sig) > 10:
        b = np.polyfit(sig, mg, 1)
        xs = np.linspace(sig.min(), sig.max(), 50)
        ax.plot(xs, np.polyval(b, xs), color=RED, linewidth=1.5,
                label=f"线性拟合（斜率 {b[0]:.3f}）")
        ax.set_title(f"安全余量随预测不确定性增大\n相关系数 "
                     f"{np.corrcoef(sig, mg)[0,1]:+.2f}", fontsize=9.5)
        ax.legend(frameon=False, loc="upper left")
    ax.axhline(0, color="#666666", linewidth=0.6)
    ax.set_xlabel("场景净负荷标准差 σ/(kWh/时段)")
    ax.set_ylabel("安全余量 Δ购电量/(kWh/时段)")
    ax.grid(color="#D9D9D9", linewidth=0.5)

    ax = axes[1]
    labels, vals = [], []
    for a, b in zip(np.quantile(pr, [0, .25, .5, .75]), np.quantile(pr, [.25, .5, .75, 1.0])):
        sel = (pr >= a) & (pr <= b)
        if sel.sum():
            labels.append(f"{a:.2f}~{b:.2f}")
            vals.append(mg[sel].mean())
    ax.bar(range(len(vals)), vals, color=ORANGE, width=0.6)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=20, fontsize=8)
    ax.axhline(0, color="#666666", linewidth=0.6)
    ax.set_xlabel("电价区间/(元·kWh$^{-1}$)")
    ax.set_ylabel("平均安全余量/(kWh/时段)")
    ax.set_title("安全余量集中在高价时段", fontsize=9.5)
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.5)
    fig.savefig(fig_dir / "q2_safety_margin.pdf", bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--day", default="2025-09-23", help="场景扇形图所用的日期")
    ap.add_argument("--s-max", type=int, default=6)
    ap.add_argument("--data-root", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--figure-dir", type=Path, default=None)
    args = ap.parse_args()

    root = Path(args.data_root) if args.data_root else q.project_root()
    out_dir = Path(args.out_dir) if args.out_dir else root / "src" / "outputs"
    fig_dir = Path(args.figure_dir) if args.figure_dir else root / "src" / "tex" / "figure"
    fig_dir.mkdir(parents=True, exist_ok=True)

    att = q.Attachment(root)
    cache = qs.precompute_forecasts(att)
    day = dt.date.fromisoformat(args.day)
    figure_scenario_plan(att, cache, fig_dir, day, args.s_max)
    margin_file = out_dir / "q2_margin_slots.npy"
    if margin_file.exists():
        figure_safety_margin(margin_file, fig_dir)
    else:
        print(f"未找到 {margin_file}，跳过安全余量图（请先运行 run_question2.py）")
    print(f"图片已写入 {fig_dir}")


if __name__ == "__main__":
    main()
