"""问题二随机优化层：整日残差场景 + 两阶段随机规划 + CVaR + 实时再调度。

模型结构（变体 B 执行口径）
--------------------------
第一阶段（0:00，与场景无关）：计划购电量 g、计划充放电 c1/d1、计划弃光 w1、计划储电量 e1
第二阶段（每个场景一份）：储能可日内再调度 c2/d2、紧急购电 emg2、过剩 dump2、实际储电量 e2
目标：E[计划购电费 + 5×紧急购电费]，可选叠加 CVaR 风险项
约束：两阶段共用同一份计划购电量；日末储电量 e2[144] = 计划值 e1[144]（跨日一致）

变量顺序
--------
[g(n)] [c1(n)] [d1(n)] [w1(n)] [e1(n+1)]
  | 每个场景 k: [c2(n)] [d2(n)] [emg2(n)] [dump2(n)] [e2(n+1)]
  | [eta] [t_1..t_S]
"""
from __future__ import annotations

import numpy as np
from scipy.optimize import linprog

import q2_model as q

N = q.N


def precompute_forecasts(att: q.Attachment, model: dict | None = None) -> dict:
    """预先算好每一天的因果预测（供残差构造与实验复用）。"""
    model = model or dict(use_month=True, use_type=True)
    return {i: q.forecast_day(att, i, **model) for i in range(len(att.dates))}


def make_scenarios(att: q.Attachment, i: int, cache: dict, s_max: int = 6):
    """用第 i 天之前的历史残差整日抽样构造场景。

    残差 = 历史日实际值 - 该历史日当时可做出的因果预测；
    场景 = 当日预测 + 历史残差曲线。
    整日抽取可保留日内持续性与源荷相关性（优于逐时段独立抽样）。
    """
    idx = [j for j in q.history_index(att, i) if j < i and j in cache]
    if not idx:
        idx = [max(0, i - 1)]
    rl = np.array([att.load_kwh[j] - cache[j][0] for j in idx])
    rv = np.array([att.pv_kwh[j] - cache[j][1] for j in idx])
    if len(idx) > s_max:                      # 按负荷残差排序等距抽代表场景（保留离散程度）
        order = np.argsort(rl.sum(1))
        pick = np.unique(np.linspace(0, len(idx) - 1, s_max).round().astype(int))
        sel = order[pick]
    else:
        sel = np.arange(len(idx))
    fl, fv = cache[i]
    scen = [(np.maximum(0.0, fl + rl[j]), np.maximum(0.0, fv + rv[j])) for j in sel]
    w = np.ones(len(scen)) / len(scen)
    return scen, w


# --------------------------------------------------------------------------- 报童 LP（机制校验用）
def newsvendor_lp(att: q.Attachment, scen, w, beta: float = 0.0, alpha: float = 0.95) -> dict:
    """无储能两阶段随机模型：min Σ_k w_k [p·g + 5p·(D_k−g)^+]，可叠加 CVaR。

    beta=0 时的最优解应当等于逐时段场景分布的 80% 分位数（理论校验）。
    由 C(g)=p·g+5p·E[(D−g)^+] 的一阶条件 5p·P(D>g)=p 得 P(D>g)=1/5，
    即最优计划购电量取净需求的 80% 分位数（报童临界分位 Cu/(Cu+Co)=4p/5p=0.8）。
    """
    S, n = len(scen), N
    price = att.price
    D = np.array([l - v for l, v in scen])                     # (S, n) 净需求
    g = slice(0, n)
    emg0 = n
    eta_i = n + S * n
    t_i = eta_i + 1
    nv = n + S * n + 1 + S

    A_ub = np.zeros((S * n + S, nv))
    b_ub = np.zeros(S * n + S)
    for k in range(S):
        for t in range(n):
            r = k * n + t
            A_ub[r, t] = -1.0                                   # −g_t
            A_ub[r, emg0 + k * n + t] = -1.0                    # −emg
            b_ub[r] = -D[k, t]                                  # −g − emg ≤ −D  ⟺  g + emg ≥ D
        row = S * n + k
        A_ub[row, t_i + k] = -1.0
        A_ub[row, eta_i] = -1.0
        for t in range(n):
            A_ub[row, t] += price[t]
            A_ub[row, emg0 + k * n + t] += 5.0 * price[t]

    obj = np.zeros(nv)
    obj[g] = (1 - beta) * price
    for k in range(S):
        obj[emg0 + k * n: emg0 + (k + 1) * n] = (1 - beta) * 5.0 * w[k] * price
    obj[eta_i] = beta
    for k in range(S):
        obj[t_i + k] = beta * w[k] / (1 - alpha)

    bounds = [(0.0, None)] * n + [(0.0, None)] * (S * n) + [(None, None)] + [(0.0, None)] * S
    res = linprog(obj, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method="highs")
    if not res.success:
        raise RuntimeError(f"报童 LP 求解失败: {res.message}")
    x = res.x
    return {"g": np.maximum(0.0, x[g]),
            "exp_cost": float(sum(w[k] * ((price * x[g]).sum() +
                                          5 * (price * x[emg0 + k * n: emg0 + (k + 1) * n]).sum())
                                  for k in range(S)))}


def newsvendor_quantile_plan(scen, w) -> np.ndarray:
    """报童理论解：逐时段取场景分布的 80% 分位数。"""
    S = np.array([l - v for l, v in scen])
    order = np.argsort(S, axis=0)
    cw = np.cumsum(w[order], axis=0)
    out = np.zeros(N)
    for t in range(N):
        k = int(np.searchsorted(cw[:, t], 0.8 - 1e-12))
        out[t] = S[order[min(k, len(w) - 1), t], t]
    return np.maximum(0.0, out)


# --------------------------------------------------------------------------- 完整两阶段模型
def stochastic_plan(att: q.Attachment, fc, scen, w, e_start: float, beta: float = 0.0,
                    alpha: float = 0.95, terminal: str = "cycle") -> dict:
    """两阶段随机 LP（含储能日内再调度）。fc = (预测负荷 kWh, 预测光伏 kWh)。"""
    n, S = N, len(scen)
    price = att.price
    fl, fv = fc
    ib_g = 0
    ib_c1, ib_d1, ib_w1, ib_e1 = n, 2 * n, 3 * n, 4 * n
    F = 4 * n + (n + 1)
    G = 4 * n + (n + 1)
    eta_i = F + S * G
    t_i = eta_i + 1
    nv = F + S * G + 1 + S

    def sb(k, off):
        return F + k * G + off

    rows, rhs = [], []

    def add(row, val):
        rows.append(row)
        rhs.append(val)

    for t in range(n):                                        # 第一阶段平衡
        row = np.zeros(nv)
        row[ib_g + t] = 1.0
        row[ib_d1 + t] = 1.0
        row[ib_c1 + t] = -1.0
        row[ib_w1 + t] = -1.0
        add(row, float(fl[t] - fv[t]))
        row = np.zeros(nv)                                    # 第一阶段状态转移
        row[ib_e1 + t] = -1.0
        row[ib_e1 + t + 1] = 1.0
        row[ib_c1 + t] = -q.ETA_C
        row[ib_d1 + t] = 1.0 / q.ETA_D
        add(row, 0.0)

    for k in range(S):
        L, V = scen[k]
        for t in range(n):                                    # 第二阶段平衡
            row = np.zeros(nv)
            row[ib_g + t] = 1.0
            row[sb(k, n + t)] = 1.0                           # d2
            row[sb(k, 2 * n + t)] = 1.0                       # emg2
            row[sb(k, 0 + t)] = -1.0                          # c2
            row[sb(k, 3 * n + t)] = -1.0                      # dump2
            add(row, float(L[t] - V[t]))
            row = np.zeros(nv)                                # 第二阶段状态转移
            row[sb(k, 4 * n + t)] = -1.0
            row[sb(k, 4 * n + t + 1)] = 1.0
            row[sb(k, 0 + t)] = -q.ETA_C
            row[sb(k, n + t)] = 1.0 / q.ETA_D
            add(row, 0.0)
        row = np.zeros(nv)                                    # 跨日衔接 e2[144] = e1[144]
        row[sb(k, 4 * n + n)] = 1.0
        row[ib_e1 + n] = -1.0
        add(row, 0.0)

    A_eq = np.array(rows)
    b_eq = np.array(rhs)

    A_ub = np.zeros((S, nv))
    b_ub = np.zeros(S)
    for k in range(S):
        A_ub[k, t_i + k] = -1.0
        A_ub[k, eta_i] = -1.0
        for t in range(n):
            A_ub[k, ib_g + t] += price[t]
            A_ub[k, sb(k, 2 * n + t)] += 5.0 * price[t]

    obj = np.zeros(nv)
    for t in range(n):
        obj[ib_g + t] = (1 - beta) * price[t]
        for k in range(S):
            obj[sb(k, 2 * n + t)] = (1 - beta) * 5.0 * w[k] * price[t]
    obj[ib_c1: ib_c1 + n] += 1e-7                 # 平局扰动，避免无意义循环充放电
    obj[ib_d1: ib_d1 + n] += 1e-7
    for k in range(S):
        obj[sb(k, 0): sb(k, 0) + n] += 1e-7
        obj[sb(k, n): sb(k, n) + n] += 1e-7
    obj[eta_i] = beta
    for k in range(S):
        obj[t_i + k] = beta * w[k] / (1 - alpha)

    bounds = [(0.0, None)] * n                                # g
    bounds += [(0.0, q.C_MAX_KWH)] * n                        # c1
    bounds += [(0.0, q.C_MAX_KWH)] * n                        # d1
    bounds += [(0.0, float(fv[t])) for t in range(n)]         # w1
    bounds += [(e_start, e_start)] + [(q.E_MIN, q.E_MAX)] * (n - 1) + \
              [(e_start, e_start) if terminal == "cycle" else (q.E_MIN, q.E_MAX)]
    for k in range(S):
        bounds += [(0.0, q.C_MAX_KWH)] * n                    # c2
        bounds += [(0.0, q.C_MAX_KWH)] * n                    # d2
        bounds += [(0.0, None)] * n                           # emg2
        bounds += [(0.0, None)] * n                           # dump2
        bounds += [(e_start, e_start)] + [(q.E_MIN, q.E_MAX)] * (n - 1) + [(q.E_MIN, q.E_MAX)]
    bounds += [(None, None)]                                  # eta
    bounds += [(0.0, None)] * S                               # t_k

    res = linprog(obj, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
    if not res.success:
        raise RuntimeError(f"两阶段随机 LP 求解失败: {res.message}")
    x = res.x.copy()
    x[np.abs(x) < 1e-9] = 0.0
    exp_cost = float(sum(
        w[k] * ((price * x[ib_g: ib_g + n]).sum() +
                5 * (price * x[sb(k, 2 * n): sb(k, 2 * n) + n]).sum()) for k in range(S)))
    return {"g": x[ib_g: ib_g + n], "c1": x[ib_c1: ib_c1 + n], "d1": x[ib_d1: ib_d1 + n],
            "w1": x[ib_w1: ib_w1 + n], "e1": x[ib_e1: ib_e1 + n + 1],
            "exp_cost": exp_cost,
            "cvar": float(x[eta_i] + np.sum(w * x[t_i: t_i + S]) / (1 - alpha))}


# --------------------------------------------------------------------------- 实时再调度
def realtime_dispatch(att: q.Attachment, g_plan: np.ndarray, load_actual_kwh: np.ndarray,
                      pv_actual_kwh: np.ndarray, e_start: float, e_terminal: float) -> dict:
    """给定计划购电量，储能日内再调度以最小化 5 倍紧急购电费（变体 B 的执行层）。

    计划购电量照付不议；日末储电量固定为计划值，保持跨日一致。
    """
    n = N
    nv = 4 * n + n + 1
    c, d, emg, dump, e = (slice(0, n), slice(n, 2 * n), slice(2 * n, 3 * n),
                          slice(3 * n, 4 * n), slice(4 * n, 4 * n + n + 1))
    obj = np.zeros(nv)
    obj[emg] = 5.0 * att.price
    obj[c] += 1e-7
    obj[d] += 1e-7
    A = np.zeros((2 * n, nv))
    b = np.zeros(2 * n)
    for t in range(n):
        A[t, c.start + t] = -1.0
        A[t, d.start + t] = 1.0
        A[t, emg.start + t] = 1.0
        A[t, dump.start + t] = -1.0
        b[t] = load_actual_kwh[t] - pv_actual_kwh[t] - g_plan[t]
        A[n + t, e.start + t] = -1.0
        A[n + t, e.start + t + 1] = 1.0
        A[n + t, c.start + t] = -q.ETA_C
        A[n + t, d.start + t] = 1.0 / q.ETA_D
    bounds = [(0.0, q.C_MAX_KWH)] * n + [(0.0, q.C_MAX_KWH)] * n + [(0.0, None)] * 2 * n
    bounds += [(e_start, e_start)] + [(q.E_MIN, q.E_MAX)] * (n - 1) + [(e_terminal, e_terminal)]
    res = linprog(obj, A_eq=A, b_eq=b, bounds=bounds, method="highs")
    if not res.success:
        raise RuntimeError(f"实时再调度 LP 求解失败: {res.message}")
    x = res.x.copy()
    x[np.abs(x) < 1e-9] = 0.0
    return {"c": x[c], "d": x[d], "emg": x[emg], "dump": x[dump], "e": x[e],
            "emg_cost": float(5 * np.dot(att.price, x[emg])),
            "emg_kwh": float(x[emg].sum()), "dump_kwh": float(x[dump].sum())}
