"""问题一完善：套利阈值推导、储能参数敏感性、约束对偶变量与边际经济价值。

运行：python src/py/q1_sensitivity.py
输出：src/outputs/q1_sensitivity_report.txt、src/tex/q1_sensitivity.tex
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy.optimize import linprog

import question1 as q1
from microgrid_core import DispatchInput, StorageParameters, solve_dispatch

ROOT = Path(__file__).resolve().parents[2]
ATTACH = ROOT / "problems" / "C题" / "附件" / "附件1.xlsx"
E0 = q1.INITIAL_SOC_KWH
NO_STORAGE_COST = 48052.0466          # 储能不参与运行时的购电费（基准方案）


def build_lp(data: q1.Question1Data, params: StorageParameters):
    """复刻公共调度 LP，用于读取对偶变量（影子价格）。"""
    price, load, pv = (np.asarray(x, float) for x in
                       (data.price_yuan_per_kwh, data.load_kwh, data.pv_kwh))
    n = price.size
    grid, charge, disch, curt = slice(0, n), slice(n, 2 * n), slice(2 * n, 3 * n), slice(3 * n, 4 * n)
    soc0 = 4 * n
    nv = 5 * n + 1
    obj = np.zeros(nv)
    obj[grid] = price
    eq = np.zeros((2 * n, nv))
    rhs = np.zeros(2 * n)
    for t in range(n):
        eq[t, grid.start + t] = 1.0
        eq[t, charge.start + t] = -1.0
        eq[t, disch.start + t] = 1.0
        eq[t, curt.start + t] = -1.0
        rhs[t] = load[t] - pv[t]
        eq[n + t, soc0 + t] = -1.0
        eq[n + t, soc0 + t + 1] = 1.0
        eq[n + t, charge.start + t] = -params.charge_efficiency
        eq[n + t, disch.start + t] = 1.0 / params.discharge_efficiency
    bounds = ([(0.0, None)] * n
              + [(0.0, params.max_slot_energy_kwh)] * n
              + [(0.0, params.max_slot_energy_kwh)] * n
              + [(0.0, float(v)) for v in pv]
              + [(float(E0), float(E0))]
              + [(params.min_soc_kwh, params.max_soc_kwh)] * (n - 1)
              + [(float(E0), float(E0))])
    return obj, eq, rhs, bounds, n


def cost_with(data, params) -> float:
    sol = solve_dispatch(DispatchInput(data.price_yuan_per_kwh, data.load_kwh, data.pv_kwh),
                         params, E0, E0, E0)
    return float(sol.total_cost_yuan)


def throughput_and_curtail(data, params):
    sol = solve_dispatch(DispatchInput(data.price_yuan_per_kwh, data.load_kwh, data.pv_kwh),
                         params, E0, E0, E0)
    return float(sol.charge_kwh.sum() + sol.discharge_kwh.sum()), float(sol.curtailment_kwh.sum())


def main() -> None:
    data = q1.load_question1_data(ATTACH)
    price = np.asarray(data.price_yuan_per_kwh, float)
    base = q1.solve_question1(data)
    base_cost = float(base.total_cost_yuan)
    p_min, p_max = float(price.min()), float(price.max())
    eta = q1.CHARGE_EFFICIENCY

    lines = []
    lines.append("=== 问题一完善：套利阈值、参数敏感性、约束对偶 ===")
    lines.append(f"基准方案（无储能）购电费 {NO_STORAGE_COST:,.4f} 元；"
                 f"优化方案 {base_cost:,.4f} 元；节省 {NO_STORAGE_COST - base_cost:,.4f} 元"
                 f"（{(NO_STORAGE_COST - base_cost) / NO_STORAGE_COST * 100:.2f}%）")
    lines.append("")
    lines.append("—— 1. 套利阈值（考虑往返效率）——")
    rt = eta * eta
    lines.append(f"  往返效率 η² = {rt:.4f}；盈亏平衡价差比 p_d/p_c = 1/η² = {1 / rt:.4f}")
    lines.append(f"  本题电价：最低 {p_min:.4f} 元/kWh，最高 {p_max:.4f} 元/kWh，"
                 f"价差比 {p_max / p_min:.4f} > {1 / rt:.4f}，故套利可行")
    lines.append(f"  盈亏平衡单程效率（按最低/最高价）η* = sqrt(p_min/p_max) = "
                 f"{np.sqrt(p_min / p_max):.4f}")

    lines.append("")
    lines.append("—— 2. 参数敏感性 ——")
    lines.append(f"  {'配置':<22}{'购电费/元':>14}{'节省/元':>12}{'节省率':>9}"
                 f"{'周转量/kWh':>13}{'弃光/kWh':>11}")
    rows = []
    for eff in (0.80, 0.85, 0.90, 0.95):
        p = StorageParameters(charge_efficiency=eff, discharge_efficiency=eff)
        c = cost_with(data, p)
        tp, cu = throughput_and_curtail(data, p)
        rows.append((f"效率 η={eff:.2f}", c, tp, cu))
    for s in (0.6, 0.8, 1.0, 1.2, 1.5):
        p = StorageParameters(min_soc_kwh=1200 * s, max_soc_kwh=10800 * s)
        c = cost_with(data, p)
        tp, cu = throughput_and_curtail(data, p)
        rows.append((f"容量 ×{s:.1f}", c, tp, cu))
    for s in (0.5, 0.75, 1.0, 1.25, 1.5):
        p = StorageParameters(max_slot_energy_kwh=5000 / 6 * s)
        c = cost_with(data, p)
        tp, cu = throughput_and_curtail(data, p)
        rows.append((f"功率 ×{s:.1f}", c, tp, cu))
    for name, c, tp, cu in rows:
        lines.append(f"  {name:<22}{c:>14,.2f}{NO_STORAGE_COST - c:>12,.2f}"
                     f"{(NO_STORAGE_COST - c) / NO_STORAGE_COST * 100:>8.2f}%"
                     f"{tp:>13,.1f}{cu:>11,.3f}")

    lines.append("")
    lines.append("—— 3. 约束对偶变量与边际价值 ——")
    params = StorageParameters()
    obj, eq, rhs, bounds, n = build_lp(data, params)
    res = linprog(obj, A_eq=eq, b_eq=rhs, bounds=bounds, method="highs")
    assert res.success, res.message
    up = np.asarray(res.upper.marginals, float)     # d(obj)/d(上限) <= 0
    lo = np.asarray(res.lower.marginals, float)
    ch, ds, sc = slice(n, 2 * n), slice(2 * n, 3 * n), slice(4 * n, 5 * n + 1)

    def binding(idx, kind="upper"):
        arr = up if kind == "upper" else lo
        return int(np.sum(np.abs(arr[idx]) > 1e-9))

    power_val = -float(up[ch].sum() + up[ds].sum()) * (1.0 / 6.0)     # 元/kW（提高功率）
    cap_val = -float(up[sc].sum()) / 1.0                             # 元/kWh（扩大容量上限）
    floor_val = -float(lo[sc].sum())
    lines.append(f"  功率上限（833.3333 kWh/时段）触发的时段数："
                 f"充电 {binding(ch)}、放电 {binding(ds)}（共 144）")
    lines.append(f"  储电量上限 {params.max_soc_kwh:.0f} kWh 触发的时段数：{binding(sc)}")
    lines.append(f"  储电量下限 {params.min_soc_kwh:.0f} kWh 触发的时段数："
                 f"{binding(sc, 'lower')}")
    lines.append(f"  功率上限的影子价格合计：提高额定功率的边际价值 ≈ "
                 f"{power_val:,.4f} 元/kW·日（即每增加 1 kW 功率每天省这么多）")
    lines.append(f"  容量上限的影子价格合计：扩大容量的边际价值 ≈ {cap_val:,.4f} 元/kWh·日")
    lines.append(f"  容量下限的影子价格合计：{floor_val:,.4f} 元/kWh·日")

    text = "\n".join(lines)
    (ROOT / "src" / "outputs" / "q1_sensitivity_report.txt").write_text(text, encoding="utf-8")
    print(text)

    # ---- 论文表格 ----
    tex = ["% 由 src/py/q1_sensitivity.py 自动生成，请勿手工修改",
           r"\begin{table}[H]", r"  \centering",
           r"  \caption{问题一：储能参数的敏感性（基准为无储能方案的 "
           r"\num{48052.0466} 元）}", r"  \label{tab:q1-sens}", r"  \small",
           r"  \begin{tabular}{lrrrr}", r"    \toprule",
           r"    配置 & 购电费/元 & 节省/元 & 节省率 & 弃光量/kWh \\", r"    \midrule"]
    for name, c, tp, cu in rows:
        tex.append(f"    {name} & {c:,.2f} & {NO_STORAGE_COST - c:,.2f} & "
                   f"{(NO_STORAGE_COST - c) / NO_STORAGE_COST * 100:.2f}\\% & {cu:,.2f} \\\\")
    tex += [r"    \bottomrule", r"  \end{tabular}", r"\end{table}",
            r"% 功率/容量上限的影子价格：" + f"{power_val:.4f} 元/kW·日，{cap_val:.4f} 元/kWh·日"]
    (ROOT / "src" / "tex" / "q1_sensitivity.tex").write_text("\n".join(tex), encoding="utf-8")
    print("\n已写入 src/tex/q1_sensitivity.tex")


if __name__ == "__main__":
    main()
