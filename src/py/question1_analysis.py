"""Economic diagnostics for Question 1: threshold, sensitivity and marginal value."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import numpy as np

from microgrid_core import DispatchInput, StorageParameters, solve_dispatch
from question1 import (
    CAPACITY_KWH, CHARGE_EFFICIENCY, DELTA_HOURS, DISCHARGE_EFFICIENCY,
    MAX_POWER_KW, load_question1_data,
)


def solve_case(data, capacity_scale=1.0, power_scale=1.0, efficiency=0.90):
    capacity = CAPACITY_KWH * capacity_scale
    initial = 0.5 * capacity
    solution = solve_dispatch(
        DispatchInput(data.price_yuan_per_kwh, data.load_kwh, data.pv_kwh),
        StorageParameters(
            min_soc_kwh=0.1 * capacity,
            max_soc_kwh=0.9 * capacity,
            max_slot_energy_kwh=MAX_POWER_KW * power_scale * DELTA_HOURS,
            charge_efficiency=efficiency,
            discharge_efficiency=efficiency,
        ),
        initial_soc_kwh=initial,
        terminal_soc_min_kwh=initial,
        terminal_soc_max_kwh=initial,
    )
    return {
        "cost_yuan": solution.total_cost_yuan,
        "charge_kwh": float(solution.charge_kwh.sum()),
        "discharge_kwh": float(solution.discharge_kwh.sum()),
        "curtailment_kwh": float(solution.curtailment_kwh.sum()),
    }


def plot_sensitivity(results: dict, path: Path) -> None:
    cache = Path(tempfile.gettempdir()) / "cumcm-matplotlib"
    cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(cache))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
        "axes.unicode_minus": False, "font.size": 9,
    })
    specs = [
        ("capacity", "额定容量倍率", "%"),
        ("power", "最大充放电功率倍率", "%"),
        ("efficiency", "单向效率", ""),
    ]
    base = results["base"]["cost_yuan"]
    fig, axes = plt.subplots(1, 3, figsize=(7.4, 2.75), constrained_layout=True)
    for ax, (key, xlabel, suffix) in zip(axes, specs):
        rows = results["sensitivity"][key]
        x = np.asarray([row["level"] for row in rows])
        y = np.asarray([(row["cost_yuan"] / base - 1) * 100 for row in rows])
        display_x = x * 100 if suffix else x
        ax.plot(display_x, y, marker="o", color="#2F5597", linewidth=1.5)
        ax.axhline(0, color="#808080", linewidth=0.7)
        ax.set_xlabel(xlabel + suffix)
        ax.set_ylabel("费用相对基准变化/%")
        ax.grid(axis="y", color="#D9D9D9", linewidth=0.6)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def plot_capacity_power_surface(results: dict, path: Path) -> None:
    """Plot the cost reduction surface relative to the smallest device."""
    import matplotlib.pyplot as plt

    surface = results["capacity_power_surface"]
    values = np.asarray(surface["cost_yuan"], dtype=float)
    saving = (values[0, 0] - values) / 1e3
    fig, ax = plt.subplots(figsize=(5.5, 3.8), constrained_layout=True)
    image = ax.imshow(saving, origin="lower", cmap="YlGnBu", aspect="auto")
    for row in range(saving.shape[0]):
        for col in range(saving.shape[1]):
            ax.text(col, row, f"{saving[row, col]:.2f}", ha="center", va="center", fontsize=8,
                    color="white" if saving[row, col] > 3.5 else "#222222")
    ax.set_xticks(range(len(surface["power_scales"])),
                  [f"{100*x:.0f}%" for x in surface["power_scales"]])
    ax.set_yticks(range(len(surface["capacity_scales"])),
                  [f"{100*x:.0f}%" for x in surface["capacity_scales"]])
    ax.set_xlabel("最大充放电功率倍率")
    ax.set_ylabel("额定容量倍率")
    bar = fig.colorbar(image, ax=ax, shrink=0.88)
    bar.set_label("相对最小配置的日费用降低/千元")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    data = load_question1_data(root / "problems/C题/附件/附件1.xlsx")
    base = solve_case(data)
    no_storage_cost = float(np.dot(data.price_yuan_per_kwh, np.maximum(data.load_kwh - data.pv_kwh, 0)))
    levels = {
        "capacity": (0.6, 0.8, 1.0, 1.2, 1.4),
        "power": (0.5, 0.75, 1.0, 1.25, 1.5),
        "efficiency": (0.75, 0.80, 0.85, 0.90, 0.95),
    }
    sensitivity = {
        "capacity": [{"level": x, **solve_case(data, capacity_scale=x)} for x in levels["capacity"]],
        "power": [{"level": x, **solve_case(data, power_scale=x)} for x in levels["power"]],
        "efficiency": [{"level": x, **solve_case(data, efficiency=x)} for x in levels["efficiency"]],
    }
    capacity_scales = (0.6, 0.8, 1.0, 1.2, 1.4)
    power_scales = (0.5, 0.75, 1.0, 1.25, 1.5)
    capacity_power_cost = [
        [solve_case(data, capacity_scale=c, power_scale=p)["cost_yuan"] for p in power_scales]
        for c in capacity_scales
    ]
    cap_plus = solve_case(data, capacity_scale=1.01)["cost_yuan"]
    power_plus = solve_case(data, power_scale=1.01)["cost_yuan"]
    eff_plus = solve_case(data, efficiency=0.91)["cost_yuan"]
    round_trip = CHARGE_EFFICIENCY * DISCHARGE_EFFICIENCY
    result = {
        "base": base,
        "no_storage_cost_yuan": no_storage_cost,
        "saving_yuan": no_storage_cost - base["cost_yuan"],
        "saving_percent": (no_storage_cost - base["cost_yuan"]) / no_storage_cost * 100,
        "arbitrage": {
            "round_trip_efficiency": round_trip,
            "minimum_price_ratio": 1.0 / round_trip,
            "minimum_price_yuan_per_kwh": float(data.price_yuan_per_kwh.min()),
            "maximum_price_yuan_per_kwh": float(data.price_yuan_per_kwh.max()),
            "observed_price_ratio": float(data.price_yuan_per_kwh.max() / data.price_yuan_per_kwh.min()),
        },
        "sensitivity": sensitivity,
        "capacity_power_surface": {
            "capacity_scales": capacity_scales,
            "power_scales": power_scales,
            "cost_yuan": capacity_power_cost,
        },
        "marginal_value": {
            "capacity_yuan_per_added_kwh": (base["cost_yuan"] - cap_plus) / (0.01 * CAPACITY_KWH),
            "power_yuan_per_added_kw": (base["cost_yuan"] - power_plus) / (0.01 * MAX_POWER_KW),
            "efficiency_yuan_per_percentage_point": (base["cost_yuan"] - eff_plus),
            "definition": "one-sided 1% expansion; efficiency changes from 0.90 to 0.91",
        },
    }
    out = root / "src/outputs/q1_analysis.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    plot_sensitivity(result, root / "src/tex/figure/q1_sensitivity.pdf")
    plot_capacity_power_surface(result, root / "src/tex/figure/q1_capacity_power_surface.pdf")
    print(json.dumps(result["arbitrage"], ensure_ascii=False, indent=2))
    print(json.dumps(result["marginal_value"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
