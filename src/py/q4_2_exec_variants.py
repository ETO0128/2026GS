"""问题 4-2 执行层优化实验：口径 A（严格执行）vs 口径 B（储能日内再调度）。

默认三种方案（均为 334 天，附件4 实际波动电价结算）：
  1) 官方基线：80% 条件残差分位数计划 + 储能严格执行（当前 result4-2.xlsx 口径）
  2) 官方计划 + 储能日内再调度：购电量照付不议，储能按实际源荷再调度
  3) 点预测计划 × 安全系数 s + 储能日内再调度（--s 指定，扫描用）

口径 B 的再调度 LP 给定外部购电量 g（照付不议），选择 c,d,emg,dump 最小化 5 倍紧急购电费，
储能受物理约束，日末储电量与计划一致以保持跨日状态。

运行：python src/py/q4_2_exec_variants.py [--s 1.15]
输出：src/outputs/q4_2_exec_variants.json / .txt
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
from scipy.optimize import linprog

import q2_model as q2
from question1 import load_question1_data
from question2_data import load_cold_start_forecast
from question2_forecast import ForecastConfig, forecast_day
from question4_2 import Question42Config, _evaluate
from question4_2_data import load_question42_data
from question4_2_dispatch import plan_causal_day
from question4_2_forecast import PriceForecastConfig, forecast_price

ETA, CMAX, EMIN, EMAX, E0, MULT = 0.9, 5000 / 6, 1200.0, 10800.0, 6000.0, 5.0


def redispatch(price: np.ndarray, g: np.ndarray, load_kwh: np.ndarray, pv_kwh: np.ndarray,
               e_start: float, e_end: float) -> dict:
    """给定计划购电量 g，储能日内再调度以最小化 5 倍紧急购电费（口径 B）。"""
    n = 144
    nv = 4 * n + n + 1
    c, d, emg, dump = slice(0, n), slice(n, 2 * n), slice(2 * n, 3 * n), slice(3 * n, 4 * n)
    e = slice(4 * n, 4 * n + n + 1)
    obj = np.zeros(nv)
    obj[emg] = MULT * price
    obj[c] += 1e-7
    obj[d] += 1e-7
    A = np.zeros((2 * n, nv))
    b = np.zeros(2 * n)
    for t in range(n):
        A[t, c.start + t] = -1.0
        A[t, d.start + t] = 1.0
        A[t, emg.start + t] = 1.0
        A[t, dump.start + t] = -1.0
        b[t] = load_kwh[t] - pv_kwh[t] - g[t]
        A[n + t, e.start + t] = -1.0
        A[n + t, e.start + t + 1] = 1.0
        A[n + t, c.start + t] = -ETA
        A[n + t, d.start + t] = 1.0 / ETA
    bounds = ([(0.0, CMAX)] * n + [(0.0, CMAX)] * n + [(0.0, None)] * 2 * n
              + [(e_start, e_start)] + [(EMIN, EMAX)] * (n - 1) + [(e_end, e_end)])
    res = linprog(obj, A_eq=A, b_eq=b, bounds=bounds, method="highs")
    if not res.success:
        raise RuntimeError(res.message)
    x = res.x
    return {"c": x[c], "d": x[d], "emg": x[emg], "dump": x[dump], "e": x[e],
            "emg_kwh": float(x[emg].sum()), "emg_cost": float(MULT * (price * x[emg]).sum())}


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--s", type=float, default=1.0, help="点预测计划的安全系数（口径 B 扫描）")
    args = ap.parse_args()
    S = args.s
    root = q2.project_root()
    att_dir = root / "problems" / "C题" / "附件"
    q1 = load_question1_data(att_dir / "附件1.xlsx")
    data = load_question42_data(att_dir / "附件2.xlsx", att_dir / "附件4.xlsx")
    cold = load_cold_start_forecast(att_dir / "附件1.xlsx")
    price_cfg = PriceForecastConfig(method="seven_day")
    official_cfg = ForecastConfig(method="seven_day", planning_method="conditional_residual")
    point_cfg = ForecastConfig(method="seven_day", planning_method="historical_net")

    # 顺序推进三天变量：分别记录三种方案的成本
    variants = {k: {"normal": 0.0, "emg": 0.0, "emg_kwh": 0.0} for k in
                ("A_official", "B_official_plan", "B_point_scaled", "A_daily_q80", "B_daily_q80")}
    soc_A = soc_B1 = soc_B2 = soc_A2 = soc_B3 = E0
    hist_dates, hist_point, hist_resid = [], [], []
    daily_resid: list[float] = []
    for idx in range(len(data.dates)):
        day = data.dates[idx]
        # --- 源荷预测（官方：点预测 + 80% 条件分位；确定性：只用点预测）
        fc = forecast_day(data, idx, official_cfg,
                          cold_start_load_kw=cold.load_kw, cold_start_pv_kw=cold.pv_kw)
        point_net = fc.load_kw - fc.pv_kw
        from question2_forecast import apply_conditional_residual_quantile
        if hist_dates:
            fc_q = apply_conditional_residual_quantile(
                fc, day, tuple(hist_dates), np.stack(hist_point), np.stack(hist_resid), official_cfg)
        else:
            fc_q = fc
        # --- 电价预测
        price_fc = (np.asarray(q1.price_yuan_per_kwh, float) if idx == 0
                    else forecast_price(data, idx, price_cfg).price_yuan_per_kwh)
        p_act = data.price_yuan_per_kwh[idx]
        load_kwh, pv_kwh = data.load_kw[idx] / 6.0, data.pv_kw[idx] / 6.0

        plan_q = plan_causal_day(day, fc_q.planning_net_kw, price_fc, initial_soc_kwh=soc_A)
        plan_p = plan_causal_day(day, S * point_net, price_fc, initial_soc_kwh=soc_B2)
        # A'：安全余量改为“日总量 80% 分位”（因果，历史日残差总量）
        if daily_resid:
            offset = float(np.quantile(daily_resid, 0.8)) / 144.0   # kW/时段
            plan_d = plan_causal_day(day, point_net + offset, price_fc, initial_soc_kwh=soc_A2)
        else:
            plan_d = None
        # A：严格
        if idx >= 31:  # 只统计官方窗口（2025-02-01 起，共 334 天）
            committed = plan_q.grid_kwh + plan_q.discharge_kwh - plan_q.charge_kwh
            short = np.maximum(0.0, load_kwh - pv_kwh - committed)
            variants["A_official"]["normal"] += float(p_act @ plan_q.grid_kwh)
            variants["A_official"]["emg"] += float(MULT * (p_act @ short))
            variants["A_official"]["emg_kwh"] += float(short.sum())
        # B1：官方计划 + 再调度（照付不议）
        rt1 = redispatch(p_act, plan_q.grid_kwh, load_kwh, pv_kwh, soc_B1, float(plan_q.soc_kwh[-1]))
        # B2：确定性计划 + 再调度
        rt2 = redispatch(p_act, plan_p.grid_kwh, load_kwh, pv_kwh, soc_B2, float(plan_p.soc_kwh[-1]))
        if plan_d is not None:
            rt3 = redispatch(p_act, plan_d.grid_kwh, load_kwh, pv_kwh, soc_B3,
                             float(plan_d.soc_kwh[-1]))
        if idx >= 31:
            variants["B_official_plan"]["normal"] += float(p_act @ plan_q.grid_kwh)
            variants["B_official_plan"]["emg"] += rt1["emg_cost"]
            variants["B_official_plan"]["emg_kwh"] += rt1["emg_kwh"]
            variants["B_point_scaled"]["normal"] += float(p_act @ plan_p.grid_kwh)
            variants["B_point_scaled"]["emg"] += rt2["emg_cost"]
            variants["B_point_scaled"]["emg_kwh"] += rt2["emg_kwh"]
            if plan_d is not None:
                com = plan_d.grid_kwh + plan_d.discharge_kwh - plan_d.charge_kwh
                sht = np.maximum(0.0, load_kwh - pv_kwh - com)
                variants["A_daily_q80"]["normal"] += float(p_act @ plan_d.grid_kwh)
                variants["A_daily_q80"]["emg"] += float(MULT * (p_act @ sht))
                variants["A_daily_q80"]["emg_kwh"] += float(sht.sum())
                variants["B_daily_q80"]["normal"] += float(p_act @ plan_d.grid_kwh)
                variants["B_daily_q80"]["emg"] += rt3["emg_cost"]
                variants["B_daily_q80"]["emg_kwh"] += rt3["emg_kwh"]
        soc_A, soc_B1, soc_B2 = (float(plan_q.soc_kwh[-1]), float(plan_q.soc_kwh[-1]),
                                 float(plan_p.soc_kwh[-1]))
        if plan_d is not None:
            soc_A2 = float(plan_d.soc_kwh[-1])
            soc_B3 = float(plan_d.soc_kwh[-1])
        daily_resid.append(float((data.load_kw[idx] - data.pv_kw[idx] - point_net).sum()))
        hist_dates.append(day)
        hist_point.append(point_net.copy())
        hist_resid.append(data.load_kw[idx] - data.pv_kw[idx] - point_net)

    lines = [f"问题 4-2 执行层优化实验（334 天，附件4 实际波动电价结算；安全系数 s={S}）", ""]
    lines.append(f"{'方案':<34}{'正常购电/元':>16}{'紧急购电/元':>16}{'合计/元':>16}{'紧急/kWh':>14}")
    out = {}
    for k, cn in (("A_official", "官方基线（逐时段 80% 分位 + 严格执行）"),
                  ("A_daily_q80", "日总量 80% 分位计划 + 严格执行"),
                  ("B_official_plan", "官方计划 + 储能日内再调度"),
                  ("B_daily_q80", "日总量 80% 分位计划 + 储能再调度"),
                  ("B_point_scaled", f"点预测计划 ×{S:g} + 储能日内再调度")):
        d = variants[k]
        tot = d["normal"] + d["emg"]
        out[k] = {"normal": d["normal"], "emg": d["emg"], "total": tot, "emg_kwh": d["emg_kwh"]}
        lines.append(f"{cn:<34}{d['normal']:>16,.2f}{d['emg']:>16,.2f}{tot:>16,.2f}"
                     f"{d['emg_kwh']:>14,.1f}")
        print(lines[-1], flush=True)
    base = out["A_official"]["total"]
    lines += ["", f"相对官方基线的节省：",
              f"  日总量 80% 分位计划：{base - out['A_daily_q80']['total']:,.2f} 元 "
              f"（{(base-out['A_daily_q80']['total'])/base*100:.2f}%）",
              f"  官方计划 + 再调度：{base - out['B_official_plan']['total']:,.2f} 元 "
              f"（{(base-out['B_official_plan']['total'])/base*100:.2f}%）",
              f"  日总量 80% 分位 + 再调度：{base - out['B_daily_q80']['total']:,.2f} 元 "
              f"（{(base-out['B_daily_q80']['total'])/base*100:.2f}%）",
              f"  点预测×{S:g} + 再调度：{base - out['B_point_scaled']['total']:,.2f} 元 "
              f"（{(base-out['B_point_scaled']['total'])/base*100:.2f}%）"]
    (root / "src" / "outputs" / "q4_2_exec_variants.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    (root / "src" / "outputs" / "q4_2_exec_variants.txt").write_text(
        "\n".join(lines), encoding="utf-8")
    print("\n".join(lines[-3:]))


if __name__ == "__main__":
    main()
