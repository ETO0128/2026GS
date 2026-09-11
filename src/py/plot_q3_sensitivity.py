"""问题三敏感性分析插图（论文用图）。

运行：python src/py/plot_q3_sensitivity.py
输出：src/figure/q3_sensitivity.pdf / .png
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

import q2_model as q2

plt.rcParams.update({
    "font.sans-serif": ["Microsoft YaHei", "SimHei"],
    "axes.unicode_minus": False,
    "font.size": 9,
    "axes.labelsize": 9,
    "figure.dpi": 120,
    "savefig.dpi": 300,
})
BLUE, RED = "#2F5597", "#C00000"

PANELS = [
    ("cap", "储能容量", "容量相对基准", 1.0),
    ("pow", "储能功率", "功率相对基准", 1.0),
    ("eta", "往返效率", "往返效率", q2.ETA_C),
    ("e0", "初始储电量", "初始储电量/kWh", q2.E0_KWH),
    ("emg", "紧急购电倍率", "紧急购电倍率", q2.EMG_MULTIPLIER),
    ("fcst", "预报误差标定倍率", "标定倍率", 1.0),
]


def main() -> None:
    root = q2.project_root()
    res = json.loads((root / "src" / "outputs" / "q3_sens.json").read_text(encoding="utf-8"))
    base = res["base"]["total"]
    fig, axes = plt.subplots(2, 3, figsize=(9.6, 5.0), constrained_layout=True)
    for ax, (fac, cn, xlabel, base_lv) in zip(axes.ravel(), PANELS):
        if fac not in res:
            ax.axis("off")
            continue
        lv = sorted([float(k) for k in res[fac]] + [base_lv])
        rel = []
        for v in lv:
            tot = base if abs(v - base_lv) < 1e-12 else res[fac][f"{v:g}"]["total"]
            rel.append((tot - base) / base * 100)
        lv, rel = np.array(lv), np.array(rel)
        ax.axhline(0, color="#BFBFBF", linewidth=0.8, linestyle="--")
        ax.plot(lv, rel, "o-", color=BLUE, linewidth=1.4, markersize=4)
        i0 = int(np.argmin(np.abs(lv - base_lv)))
        ax.plot(lv[i0], rel[i0], "o", color=RED, markersize=6, zorder=5)
        ax.set_title(cn, fontsize=9.5)
        ax.set_xlabel(xlabel)
        ax.set_ylabel("全年费用相对变化/%")
        ax.grid(color="#E6E6E6", linewidth=0.6)
    for ext in ("pdf", "png"):
        fig.savefig(root / "src" / "figure" / f"q3_sensitivity.{ext}",
                    bbox_inches="tight", facecolor="white")
    print("图片已写入 src/figure/q3_sensitivity.pdf/.png")


if __name__ == "__main__":
    main()
