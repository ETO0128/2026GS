"""问题四执行层（口径 B）：购电量照付不议 + 储能日内再调度。

两种实现
--------
``redispatch_oracle``
    给定全天实际负荷/光伏，一次性解全天 LP 最小化 5 倍紧急购电费。
    对应问题二 P2B 的口径，是日内再调度的**上界（乐观）**。

``redispatch_causal``
    严格因果的滚动实现：每 10 分钟重优化一次剩余时段，只执行当前时段。
    决策时只已知当前及此前时段的实际源荷（当前时段用实际值），未来时段用
    0:00 点预测；电价未来值用因果价格预测。这是**可实现的**日内再调度。

两者都保持“购电量照付不议”，日末储电量按储备要求约束，跨日传递由调用方处理。
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import linprog

ETA, CMAX, EMIN, EMAX, MULT = 0.9, 5000 / 6, 1200.0, 10800.0, 5.0


def _solve(price: np.ndarray, g: np.ndarray, net_kwh: np.ndarray, e_start: float,
           e_terminal_min: float | None) -> dict:
    """给定购电量 g 与净负荷 net（kWh），解储能再调度 LP。"""
    m = len(price)
    nv = 4 * m + m + 1
    c, d, emg, dump = slice(0, m), slice(m, 2 * m), slice(2 * m, 3 * m), slice(3 * m, 4 * m)
    e = slice(4 * m, 4 * m + m + 1)
    obj = np.zeros(nv)
    obj[emg] = MULT * price
    obj[c] += 1e-7
    obj[d] += 1e-7
    A = np.zeros((2 * m, nv))
    b = np.zeros(2 * m)
    for t in range(m):
        A[t, c.start + t] = -1.0
        A[t, d.start + t] = 1.0
        A[t, emg.start + t] = 1.0
        A[t, dump.start + t] = -1.0
        b[t] = net_kwh[t] - g[t]
        A[m + t, e.start + t] = -1.0
        A[m + t, e.start + t + 1] = 1.0
        A[m + t, c.start + t] = -ETA
        A[m + t, d.start + t] = 1.0 / ETA
    bounds = ([(0.0, CMAX)] * m + [(0.0, CMAX)] * m + [(0.0, None)] * 2 * m
              + [(e_start, e_start)] + [(EMIN, EMAX)] * m)
    if e_terminal_min is not None:
        bounds[-1] = (e_terminal_min, EMAX)
    res = linprog(obj, A_eq=A, b_eq=b, bounds=bounds, method="highs")
    if not res.success:
        return {}
    x = res.x
    return {"c": x[c], "d": x[d], "emg": x[emg], "dump": x[dump], "e": x[e]}


def redispatch_causal_seg(price_act: np.ndarray, price_fc: np.ndarray, g: np.ndarray,
                          load_kwh: np.ndarray, pv_kwh: np.ndarray, segments, e_start: float,
                          e_terminal: float | None) -> dict:
    """分段信息的因果滚动再调度。

    segments 为 [(起始时段 j0, 未来净负荷 kWh 数组)]，数组长度 = n - j0，
    表示“在 [j0, 下一节点) 这段时间内的可用信息下，对 j>=j0 各时段的计划净负荷”。
    每个时刻 t 用包含 t 的最近一个分段的数组作为未来估计。
    """
    n = len(g)
    net_act = load_kwh - pv_kwh
    c = np.zeros(n)
    d = np.zeros(n)
    emg = np.zeros(n)
    e = np.zeros(n + 1)
    e[0] = e_start
    for t in range(n):
        seg = None
        for j0, net in segments:
            if j0 <= t:
                seg = (j0, net)
        if seg is None:
            raise RuntimeError("segments 未覆盖时段 t")
        j0, net = seg
        fut = np.asarray(net)[t + 1 - j0:] if t + 1 < n else np.array([])
        net_h = np.concatenate([[net_act[t]], fut]) if fut.size else np.array([net_act[t]])
        price_h = (np.concatenate([[price_act[t]], price_fc[t + 1:n]]) if fut.size
                   else np.array([price_act[t]]))
        sol = _solve(price_h, g[t:n], net_h, float(e[t]), e_terminal)
        if not sol:
            sol = _solve(price_h, g[t:n], net_h, float(e[t]), None)
        if not sol:
            raise RuntimeError(f"因果分段再调度 LP 不可行（t={t}）")
        c[t], d[t] = float(sol["c"][0]), float(sol["d"][0])
        e[t + 1] = e[t] + ETA * c[t] - d[t] / ETA
        emg[t] = max(0.0, net_act[t] + c[t] - d[t] - g[t])
    return {"c": c, "d": d, "emg": emg, "e": e,
            "emg_kwh": float(emg.sum()), "emg_cost": float(MULT * (price_act * emg).sum())}


def redispatch_oracle(price: np.ndarray, g: np.ndarray, load_kwh: np.ndarray,
                      pv_kwh: np.ndarray, e_start: float, e_terminal: float) -> dict:
    out = _solve(price, g, load_kwh - pv_kwh, e_start, e_terminal)
    if not out:
        raise RuntimeError("oracle 再调度 LP 不可行")
    out["emg_kwh"] = float(out["emg"].sum())
    out["emg_cost"] = float(MULT * (price * out["emg"]).sum())
    return out


def redispatch_causal(price_act: np.ndarray, price_fc: np.ndarray, g: np.ndarray,
                      load_kwh: np.ndarray, pv_kwh: np.ndarray, net_fc_kw: np.ndarray,
                      e_start: float, e_terminal: float) -> dict:
    """严格因果的滚动再调度：每 10 分钟重优化，只执行当前时段。"""
    n = len(g)
    net_act = load_kwh - pv_kwh
    c = np.zeros(n)
    d = np.zeros(n)
    emg = np.zeros(n)
    e = np.zeros(n + 1)
    e[0] = e_start
    for t in range(n):
        m = n - t
        future = (net_fc_kw[t + 1:n] / 6.0) if m > 1 else np.array([])
        net_h = np.concatenate([[net_act[t]], future])
        price_h = np.concatenate([[price_act[t]], price_fc[t + 1:n]]) if m > 1 else np.array([price_act[t]])
        sol = _solve(price_h, g[t:n], net_h, float(e[t]), e_terminal)
        if not sol:                      # 极端情况下放宽日末储备
            sol = _solve(price_h, g[t:n], net_h, float(e[t]), None)
        if not sol:
            raise RuntimeError(f"causal 再调度 LP 不可行（t={t}）")
        c[t], d[t] = float(sol["c"][0]), float(sol["d"][0])
        e[t + 1] = e[t] + ETA * c[t] - d[t] / ETA
        emg[t] = max(0.0, net_act[t] + c[t] - d[t] - g[t])
    return {"c": c, "d": d, "emg": emg, "e": e,
            "emg_kwh": float(emg.sum()), "emg_cost": float(MULT * (price_act * emg).sum())}
