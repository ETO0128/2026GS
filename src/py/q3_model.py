"""问题三：滚动调整购电策略模型。

信息结构（题目原文）
--------------------
在每天 0:00、6:00、12:00、18:00 可获得未来 24 小时整点的光伏发电功率预报（附件3）。
0:00 制定当天计划购电策略，6:00/12:00/18:00 依据新预报制定剩余时段的调整购电策略。

费用口径（题目原文）
--------------------
总购电费用 = 计划购电费用 + 紧急购电费用 + 调整购电量的相关费用，其中
    计划购电量 > 调整购电量的部分：按交易时刻电价的 50% 计违约费；
    调整购电量 > 计划购电量的部分：按交易时刻电价的 1.5 倍计费。

    fee_t = p_t*min(q_plan,q_adj) + 0.5*p_t*(q_plan-q_adj)^+ + 1.5*p_t*(q_adj-q_plan)^+

注意：向下调整**不是免费的**（MODELING_PLAN 中"向下调整不收费"与题面不符）。
费用按"最终调整购电量"与"0:00 计划购电量"之差结算，与 result3.xlsx 只提供
"计划购电量"和"调整购电量"两张矩阵的结构一致。

执行口径（与问题二口径 A 一致）
------------------------------
已执行时段不可更改；节点决策覆盖 [节点, 24:00)；储能随调整一并重优化；
实际执行按最终计划严格执行，缺口按 5 倍价紧急购电；日周期 e_144 = e_0 = 6000 kWh。

预测
----
光伏：直接使用附件3 预报（整点值按小时取常值映射到 10 分钟时段）；
负荷：附件3 不含负荷预报，用与问题二相同的因果模型（同月 + 同负荷类型均值）。
场景：以"同一预报时刻 τ 的历史预报误差"构造剩余时段残差场景（与提前量对齐）。
"""
from __future__ import annotations

import datetime as dt

import numpy as np
from scipy.optimize import linprog

import q2_model as q2

NODE_MIN = [0, 360, 720, 1080]
NODE_NAME = ["0:00", "6:00", "12:00", "18:00"]


def date_of(value) -> dt.date:
    """兼容 datetime、Excel 序列号与 "2025-1-1" 字符串三种写法。"""
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    s = str(value).strip()
    try:
        return dt.date(1899, 12, 30) + dt.timedelta(days=int(float(s)))
    except ValueError:
        pass
    parts = [p for p in s.replace("/", "-").split("-") if p]
    if len(parts) == 3:
        y, m, d = (int(p) for p in parts)
        return dt.date(y, m, d)
    raise ValueError(f"无法解析日期：{value!r}")


def minutes_of(value) -> int:
    """把 "0:00"/"6:00"、datetime.time 或 Excel 小数时刻统一换算为分钟数。"""
    if isinstance(value, dt.time):
        return value.hour * 60 + value.minute
    if isinstance(value, dt.datetime):
        return value.hour * 60 + value.minute
    s = str(value).strip()
    if ":" in s:
        h, m = s.split(":")[:2]
        return int(float(h)) * 60 + int(float(m))
    f = float(s)
    return int(round(f * 1440)) if f <= 1.5 else int(round(f))


# --------------------------------------------------------------------------- 附件3
class PvForecast3:
    """附件3：每天 0:00/6:00/12:00/18:00 发布的未来 24 小时整点光伏功率预报（kW）。"""

    def __init__(self, root):
        path = root / "problems" / "C题" / "附件" / "附件3.xlsx"
        grid = q2.read_workbook(path)
        sheet = list(grid.values())[0]
        # 列布局：A 日期（仅每天首行有值，需向下填充）、B 预报时刻、C..Z 预报 1~24 小时
        fcols = q2.COLS[1:25]
        self.data: dict[tuple[dt.date, int], np.ndarray] = {}
        current: dt.date | None = None
        for r in range(2, 1462):
            a, b = sheet.get(f"A{r}"), sheet.get(f"B{r}")
            if a not in (None, ""):
                current = date_of(a)
            if b is None or current is None:
                continue
            tau = minutes_of(b)
            self.data[(current, tau)] = np.array(
                [float(sheet.get(f"{c}{r}", 0.0) or 0.0) for c in fcols])
        if not self.data:
            raise ValueError("附件3 解析为空")
        self.days = sorted({d for d, _ in self.data})

    def hourly(self, day: dt.date, tau: int) -> np.ndarray:
        return self.data[(day, tau)]

    def pv_kwh(self, day: dt.date, tau: int, j0: int, j1: int) -> np.ndarray:
        """把 τ 时刻发布的预报映射到时段 [j0, j1) 的电量（kWh）。"""
        arr = self.hourly(day, tau)
        out = np.empty(j1 - j0)
        for k, j in enumerate(range(j0, j1)):
            offset = (10 * j - tau) // 60            # 落在第 (offset+1) 个预报小时
            if offset < 0 or offset >= 24:
                raise ValueError(f"时段 {j} 超出 {tau} 时刻预报的 24 小时范围")
            out[k] = arr[offset] * q2.DT_H
        return out


# --------------------------------------------------------------------------- 预测
def forecast_full(att, f3: PvForecast3, i: int, tau: int):
    """当天 144 段的负荷预测（因果）与 τ 时刻的光伏预报（kWh）。"""
    l_fc = q2.forecast_day(att, i)[0]
    v_fc = np.zeros(q2.N)
    j0 = tau // 10
    if j0 < q2.N:
        v_fc[j0:] = f3.pv_kwh(att.dates[i], tau, j0, q2.N)
    return l_fc, v_fc


def residual_scenarios(att, f3: PvForecast3, i: int, tau: int, s_max: int = 6):
    """剩余时段 [τ,24:00) 的净负荷场景（同一预报时刻的历史预报误差）。"""
    j0 = tau // 10
    l_fc, v_fc = forecast_full(att, f3, i, tau)
    l_fc, v_fc = l_fc[j0:], v_fc[j0:]
    have = set(f3.days)
    idx = [j for j in q2.history_index(att, i) if att.dates[j] in have]
    dl, dv = [], []
    for j in idx:
        try:
            pl = q2.forecast_day(att, j)[0][j0:]
            pv = f3.pv_kwh(att.dates[j], tau, j0, q2.N)
        except (KeyError, ValueError):
            continue
        dl.append(att.load_kwh[j][j0:] - pl)
        dv.append(att.pv_kwh[j][j0:] - pv)
    if not dl:
        return [l_fc - v_fc], np.array([1.0])
    dl, dv = np.array(dl), np.array(dv)
    order = np.argsort(dl.sum(axis=1))
    if len(order) > s_max:
        sel = order[np.rint(np.linspace(0, len(order) - 1, s_max)).astype(int)]
    else:
        sel = order
    scen = [np.maximum(0.0, l_fc + dl[s]) - np.maximum(0.0, v_fc + dv[s]) for s in sel]
    return scen, np.full(len(scen), 1.0 / len(scen))


# --------------------------------------------------------------------------- 费用
def fee_seg(price, q_plan, q_adj) -> float:
    up = np.maximum(0.0, q_adj - q_plan)
    dn = np.maximum(0.0, q_plan - q_adj)
    return float((price * np.minimum(q_plan, q_adj)).sum()
                 + (1.5 * price * up).sum() + (0.5 * price * dn).sum())


def expected_emergency(price, q, c, d, scen_net, weights) -> float:
    tot = 0.0
    for w, net in zip(weights, scen_net):
        gap = np.maximum(0.0, net + c - d - q)
        tot += w * 5.0 * float((price * gap).sum())
    return tot


# --------------------------------------------------------------------------- 节点 LP
def seg_lp(price, q_plan, l_fc, v_fc, e_start, scen_net, weights, mode="adjust"):
    """剩余时段最优 (q,c,d,w,e)。

    mode="plan"  : 0:00 制定计划（无调整费，q 自由）
    mode="adjust": 调整，与 q_plan 的差额按 50%/150% 计费
    返回 q,c,d,w,e,fee,exp_emg_cost
    """
    m = len(l_fc)
    idx_q, idx_c, idx_d, idx_w = 0, m, 2 * m, 3 * m
    idx_up, idx_dn, idx_e = 4 * m, 5 * m, 6 * m
    base = 7 * m + 1
    S = len(scen_net)
    nv = base + S * m

    obj = np.zeros(nv)
    if mode == "plan":
        obj[idx_q:idx_q + m] = price
    else:
        obj[idx_up:idx_up + m] = 1.5 * price
        obj[idx_dn:idx_dn + m] = -0.5 * price
    obj[idx_c:idx_c + m] += 1e-7
    obj[idx_d:idx_d + m] += 1e-7
    for k, w in enumerate(weights):
        obj[base + k * m: base + (k + 1) * m] = w * 5.0 * price

    A_eq = np.zeros((3 * m, nv))
    b_eq = np.zeros(3 * m)
    for t in range(m):
        A_eq[t, idx_q + t] = 1.0                  # q + v + d = l + c + w
        A_eq[t, idx_c + t] = -1.0
        A_eq[t, idx_d + t] = 1.0
        A_eq[t, idx_w + t] = -1.0
        b_eq[t] = l_fc[t] - v_fc[t]

        A_eq[m + t, idx_e + t] = -1.0             # e[t+1] = e[t] + ηc c - d/ηd
        A_eq[m + t, idx_e + t + 1] = 1.0
        A_eq[m + t, idx_c + t] = -q2.ETA_C
        A_eq[m + t, idx_d + t] = 1.0 / q2.ETA_D

        if mode != "plan":
            A_eq[2 * m + t, idx_q + t] = 1.0      # q - up + dn = q_plan
            A_eq[2 * m + t, idx_up + t] = -1.0
            A_eq[2 * m + t, idx_dn + t] = 1.0
            b_eq[2 * m + t] = q_plan[t]

    A_ub = np.zeros((S * m, nv))
    b_ub = np.zeros(S * m)
    for k in range(S):
        for t in range(m):
            r = k * m + t
            A_ub[r, base + r] = -1.0              # q - c + d + emg >= net
            A_ub[r, idx_q + t] = -1.0
            A_ub[r, idx_c + t] = 1.0              # 充电消耗电能
            A_ub[r, idx_d + t] = -1.0             # 放电提供电能
            b_ub[r] = -scen_net[k][t]

    zero = (0.0, 0.0)
    bounds = ([(0, None)] * m + [(0, q2.C_MAX_KWH)] * m + [(0, q2.C_MAX_KWH)] * m
              + [(0.0, float(v)) for v in v_fc] + [(0, None)] * m + [(0, None)] * m
              + [(q2.E_MIN, q2.E_MAX)] * (m + 1) + [(0, None)] * (S * m))
    if mode == "plan":
        for t in range(m):                        # 计划模式下禁用 up/dn
            bounds[idx_up + t] = zero
            bounds[idx_dn + t] = zero
    bounds[idx_e] = (e_start, e_start)
    bounds[idx_e + m] = (q2.E0_KWH, q2.E0_KWH)    # 日周期终值

    res = linprog(obj, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq, bounds=bounds,
                  method="highs")
    if not res.success:
        raise RuntimeError("节点 LP 求解失败：" + str(res.message))
    x = res.x
    q, c, d = x[idx_q:idx_q + m], x[idx_c:idx_c + m], x[idx_d:idx_d + m]
    w, e = x[idx_w:idx_w + m], x[idx_e:idx_e + m + 1]
    qp = np.zeros(m) if mode == "plan" else np.asarray(q_plan, dtype=float)
    fee = fee_seg(price, qp, q) if mode == "adjust" else float((price * q).sum())
    return {"q": q, "c": c, "d": d, "w": w, "e": e, "fee": fee,
            "exp_emg_cost": expected_emergency(price, q, c, d, scen_net, weights)}


def eval_seg(price, q, c, d, q_plan, scen_net, weights):
    """评估"保持现有计划"的费用（调整费 + 期望紧急购电费）。"""
    return {"fee": fee_seg(price, q_plan, q),
            "exp_emg_cost": expected_emergency(price, q, c, d, scen_net, weights)}


# --------------------------------------------------------------------------- 单日仿真
def simulate_day(att, f3: PvForecast3, price, i: int, s_max: int = 6,
                 policy: str = "selective", tol: float = 1e-6, node_subset=None,
                 price_plan=None) -> dict:
    """执行一天：0:00 计划 + 6:00/12:00/18:00 调整 + 实际结算。

    policy: "none" 不调整；"fixed" 固定调整；"selective" 仅当预期收益为正才调整
    node_subset: 允许使用的调整节点索引（默认 [1,2,3]），用于分析增减节点的影响
    price_plan: 制定计划/调整时使用的电价（默认为实际电价 price）。问题四中若电价逐日波动
        且建模时并未预先得知，可传入"因果价格预测"，此时决策按 price_plan 优化、
        结算仍按实际价格 price 执行。
    """
    price_plan = price if price_plan is None else price_plan
    l_act, v_act = att.load_kwh[i], att.pv_kwh[i]
    net_act = l_act - v_act
    nodes = [1, 2, 3] if node_subset is None else list(node_subset)

    l_fc, v_fc = forecast_full(att, f3, i, 0)
    scen, w = residual_scenarios(att, f3, i, 0, s_max)
    plan = seg_lp(price_plan, None, l_fc, v_fc, q2.E0_KWH, scen, w, "plan")
    q_plan = plan["q"].copy()
    q_cur, c_cur, d_cur = plan["q"].copy(), plan["c"].copy(), plan["d"].copy()
    e_cur = plan["e"].copy()

    log = []
    for k in (1, 2, 3):
        if k not in nodes:
            log.append({"node": NODE_NAME[k], "J_keep": None, "J_adj": None,
                        "adjusted": False, "fee": 0.0, "dq_kwh": 0.0})
            continue
        j0 = NODE_MIN[k] // 10
        l_fc, v_fc = forecast_full(att, f3, i, NODE_MIN[k])
        scen, w = residual_scenarios(att, f3, i, NODE_MIN[k], s_max)
        qp_seg = q_plan[j0:]
        keep = eval_seg(price_plan[j0:], q_cur[j0:], c_cur[j0:], d_cur[j0:], qp_seg, scen, w)
        J_keep = keep["fee"] + keep["exp_emg_cost"]
        adj = seg_lp(price_plan[j0:], qp_seg, l_fc[j0:], v_fc[j0:], e_cur[j0], scen, w, "adjust")
        J_adj = adj["fee"] + adj["exp_emg_cost"]
        take = (policy == "fixed") or (policy == "selective" and J_adj < J_keep - tol)
        if take:
            dq = float(np.abs(adj["q"] - q_cur[j0:]).sum())
            q_cur[j0:], c_cur[j0:], d_cur[j0:] = adj["q"], adj["c"], adj["d"]
            e_cur[j0:] = adj["e"]
        else:
            dq = 0.0
        log.append({"node": NODE_NAME[k], "J_keep": float(J_keep), "J_adj": float(J_adj),
                    "adjusted": bool(take), "fee": float(adj["fee"]), "dq_kwh": dq})

    committed = q_cur + d_cur - c_cur
    shortfall = np.maximum(0.0, net_act - committed)
    cost_emg = float(5.0 * (price * shortfall).sum())
    return {
        "date": att.dates[i],
        "q_plan": q_plan, "q_adj": q_cur, "c_adj": c_cur, "d_adj": d_cur,
        "e_plan": plan["e"], "e_adj": e_cur,
        "plan_cost": float((price * q_plan).sum()),
        "fee": fee_seg(price, q_plan, q_cur),
        "emg_kwh": float(shortfall.sum()), "emg_cost": cost_emg,
        "total": float(cost_emg + fee_seg(price, q_plan, q_cur)),
        "log": log,
    }
