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

DEFAULT_SCENARIO_COUNT = 18
from question2_data import YearData
from question2_forecast import ForecastConfig, forecast_day as official_forecast_day

NODE_MIN = [0, 360, 720, 1080]
NODE_NAME = ["0:00", "6:00", "12:00", "18:00"]


class Params:
    """问题三的系统参数，用于敏感性分析。

    默认值全部取自 q2_model（E_MIN=1200、E_MAX=10800、单时段最大充放电量
    C_MAX_KWH=833.3333、往返效率 0.9、初始储电量 6000、紧急购电倍率 5），
    因此 ``Params()`` 即原模型。可在不改变代码结构的前提下扫描各参数的影响。
    """

    def __init__(self, e_min=None, e_max=None, c_max=None, eta=None, e0=None, emg=None):
        self.e_min = float(q2.E_MIN if e_min is None else e_min)
        self.e_max = float(q2.E_MAX if e_max is None else e_max)
        self.c_max = float(q2.C_MAX_KWH if c_max is None else c_max)
        self.eta = float(q2.ETA_C if eta is None else eta)
        self.e0 = float(q2.E0_KWH if e0 is None else e0)
        self.emg = float(q2.EMG_MULTIPLIER if emg is None else emg)

    def scaled_e(self, e_max_scale: float) -> "Params":
        """按比例缩放容量上下限（保持 E_MIN/E_MAX 比值），返回新参数。"""
        return Params(e_min=self.e_min * e_max_scale, e_max=self.e_max * e_max_scale,
                      c_max=self.c_max, eta=self.eta, e0=self.e0, emg=self.emg)


DEFAULT_PARAMS = Params()


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

    def pv_kwh(self, day: dt.date, tau: int, j0: int, j1: int,
               interpolation: str = "step") -> np.ndarray:
        """把整点功率预报映射到十分钟电量。

        ``linear`` 在相邻预报点间作非负线性插值；``step`` 保留原逐小时常值
        口径，专门用于消融实验。最后一个预报点之后采用末值外推。
        """
        arr = self.hourly(day, tau)
        minute = 10.0 * np.arange(j0, j1)
        horizon = minute - float(tau)
        if np.any(horizon < 0) or np.any(horizon >= 24 * 60):
            raise ValueError(f"时段 [{j0},{j1}) 超出 {tau} 时刻预报的 24 小时范围")
        if interpolation == "step":
            power = arr[np.floor(horizon / 60.0).astype(int)]
        elif interpolation == "linear":
            # 第 h 个数表示未来第 h 个整点附近的功率，首点锚定发布时刻。
            knots = np.arange(24, dtype=float) * 60.0
            power = np.interp(horizon, knots, arr, left=arr[0], right=arr[-1])
        else:
            raise ValueError("interpolation must be 'linear' or 'step'")
        return np.maximum(power, 0.0) * q2.DT_H


# --------------------------------------------------------------------------- 预测
def _official_year(att) -> YearData:
    """零拷贝适配正式问题二数据结构，统一 Q2/Q3 的因果预测底座。"""
    return YearData(tuple(att.dates), np.arange(0, 1440, 10), att.price,
                    att.load_kw, att.pv_kw)


def forecast_full(att, f3: PvForecast3, i: int, tau: int, load_lam: float = 1.0,
                  fc_kwargs: dict | None = None, pv_interpolation: str = "step",
                  forecast_source: str = "legacy"):
    """当天 144 段的负荷预测（因果）与 τ 时刻的光伏预报（kWh）。

    load_lam 为负荷预测的指数衰减系数（默认 1.0 = 纯均值）；问题二已表明
    load_lam=0.9 的“同月+同类型+指数加权”预测误差明显更小，问题三据此允许调参。
    fc_kwargs 可覆盖负荷预测口径（如七日均值 dict(use_month=False, use_type=False, k_max=7)）。
    """
    if forecast_source == "official":
        # 正式问题二采用七日均值作为点预测；条件残差只用于日前安全分位数，
        # 此处由滚动残差场景显式描述不确定性，不能再叠加一次分位数修正。
        cfg = ForecastConfig(method="seven_day", planning_method="historical_net")
        l_fc = official_forecast_day(_official_year(att), i, cfg).load_kw * q2.DT_H
    elif forecast_source == "legacy":
        l_fc = q2.forecast_day(att, i, lam=load_lam, **(fc_kwargs or {}))[0]
    else:
        raise ValueError("forecast_source must be 'official' or 'legacy'")
    v_fc = np.zeros(q2.N)
    j0 = tau // 10
    if j0 < q2.N:
        v_fc[j0:] = f3.pv_kwh(att.dates[i], tau, j0, q2.N, pv_interpolation)
    return l_fc, v_fc


def residual_scenarios(att, f3: PvForecast3, i: int, tau: int,
                       s_max: int = DEFAULT_SCENARIO_COUNT,
                       load_lam: float = 1.0, scen_scale: float = 1.0,
                       fc_kwargs: dict | None = None,
                       scenario_decay: float = 0.95,
                       pv_interpolation: str = "step",
                       forecast_source: str = "legacy",
                       scenario_weighting: str = "legacy"):
    """剩余时段 [τ,24:00) 的净负荷场景（同一预报时刻的历史预报误差）。

    历史预报误差必须用与当天一致的预测口径（load_lam）重算，否则场景与决策不同源。
    scen_scale 用于按比例放大/缩小预报误差，做“预报质量”敏感性分析。
    """
    j0 = tau // 10
    l_fc, v_fc = forecast_full(att, f3, i, tau, load_lam, fc_kwargs,
                               pv_interpolation, forecast_source)
    l_fc, v_fc = l_fc[j0:], v_fc[j0:]
    have = set(f3.days)
    idx = [j for j in q2.history_index(att, i) if att.dates[j] in have]
    dl, dv, valid_idx = [], [], []
    for j in idx:
        try:
            pl = forecast_full(att, f3, j, tau, load_lam, fc_kwargs,
                               pv_interpolation, forecast_source)[0][j0:]
            pv = f3.pv_kwh(att.dates[j], tau, j0, q2.N, pv_interpolation)
        except (KeyError, ValueError):
            continue
        dl.append(att.load_kwh[j][j0:] - pl)
        dv.append(att.pv_kwh[j][j0:] - pv)
        valid_idx.append(j)
    if not dl:
        return [l_fc - v_fc], np.array([1.0])
    dl, dv = np.array(dl), np.array(dv)
    if scenario_weighting == "legacy":
        order = np.argsort(dl.sum(axis=1), kind="stable")
    elif scenario_weighting == "weighted":
        order = None
    else:
        raise ValueError("scenario_weighting must be 'weighted' or 'legacy'")
    # 用完整残差轨迹的标准化距离选相似场景，避免只按日误差总量排序。
    target_shape = l_fc - v_fc
    historical_shape = np.array([att.load_kwh[j][j0:] - att.pv_kwh[j][j0:] for j in valid_idx])
    scale = max(float(np.std(target_shape)), 1.0)
    distance = np.sqrt(np.mean(((historical_shape - target_shape) / scale) ** 2, axis=1))
    if order is None:
        order = np.argsort(distance, kind="stable")
    if len(order) > s_max:
        sel = order[np.rint(np.linspace(0, len(order) - 1, s_max)).astype(int)]
    else:
        sel = order
    scen = [np.maximum(0.0, l_fc + scen_scale * dl[s]) - np.maximum(0.0, v_fc + scen_scale * dv[s])
            for s in sel]
    ages = np.asarray([i - valid_idx[s] for s in sel], dtype=float)
    same_type = np.asarray([(att.dates[valid_idx[s]].weekday() >= 5) == (att.dates[i].weekday() >= 5)
                            for s in sel], dtype=float)
    if scenario_weighting == "weighted":
        raw = np.power(scenario_decay, ages) * np.exp(-distance[sel]) * (1.0 + 0.25 * same_type)
        weights = raw / raw.sum()
    else:
        weights = np.full(len(scen), 1.0 / len(scen))
    return scen, weights


def load_only_residual_scenarios(att, f3: PvForecast3, i: int, tau: int,
                                 known_pv: np.ndarray,
                                 s_max: int = DEFAULT_SCENARIO_COUNT,
                                 load_lam: float = 1.0,
                                 fc_kwargs: dict | None = None,
                                 forecast_source: str = "legacy"):
    """在光伏曲线已知时，仅保留因果负荷预测误差的场景。

    用于评估额外光伏信息的价值：负荷预测方法和历史误差保持不变，不能把
    当日真实负荷同时泄露给调整模型。
    """
    j0 = tau // 10
    if np.asarray(known_pv).shape != (q2.N - j0,):
        raise ValueError("known_pv must cover the complete remaining horizon")
    l_fc = forecast_full(att, f3, i, 0, load_lam, fc_kwargs,
                         forecast_source=forecast_source)[0][j0:]
    idx = q2.history_index(att, i)
    residuals = []
    for j in idx:
        hist_fc = forecast_full(att, f3, j, 0, load_lam, fc_kwargs,
                                forecast_source=forecast_source)[0][j0:]
        residuals.append(att.load_kwh[j][j0:] - hist_fc)
    if not residuals:
        return [l_fc - known_pv], np.array([1.0])
    residuals = np.asarray(residuals)
    order = np.argsort(residuals.sum(axis=1), kind="stable")
    if len(order) > s_max:
        selected = order[np.rint(np.linspace(0, len(order) - 1, s_max)).astype(int)]
    else:
        selected = order
    scenarios = [np.maximum(0.0, l_fc + residuals[s]) - known_pv for s in selected]
    return scenarios, np.full(len(scenarios), 1.0 / len(scenarios))


# --------------------------------------------------------------------------- 费用
def fee_seg(price, q_plan, q_adj) -> float:
    up = np.maximum(0.0, q_adj - q_plan)
    dn = np.maximum(0.0, q_plan - q_adj)
    return float((price * np.minimum(q_plan, q_adj)).sum()
                 + (1.5 * price * up).sum() + (0.5 * price * dn).sum())


def expected_emergency(price, q, c, d, scen_net, weights, P: "Params" = DEFAULT_PARAMS) -> float:
    tot = 0.0
    for w, net in zip(weights, scen_net):
        gap = np.maximum(0.0, net + c - d - q)
        tot += w * float((price * gap).sum())
    return P.emg * tot


# --------------------------------------------------------------------------- 节点 LP
def seg_lp(price, q_plan, l_fc, v_fc, e_start, scen_net, weights, mode="adjust",
           plan_pen=None, P: "Params" = DEFAULT_PARAMS,
           terminal_min=None, terminal_max=None, terminal_value: float = 0.0):
    """剩余时段的场景风险线性规划。

    mode="plan"  : 0:00 制定计划（无调整费，q 自由）
    mode="adjust": 调整，与 q_plan 的差额按 50%/150% 计费
    plan_pen     : 仅 mode="plan" 生效，各时段缺口的计价倍率（默认 5 倍紧急电价）。
                   对后续节点可调整的时段，用较低的倍率即可反映“稍后可按 1.5 倍调整”
                   的期权价值，避免 0:00 过度囤电。
    每个场景分别以紧急购电 ``h`` 和剩余能量 ``r`` 满足
    ``q + d - c + h - r = net``。这样计划购电量不会再被点预测平衡式
    额外钉住，历史残差显示高需求风险时可以提前备购。

    返回 q,c,d,w,e,fee,exp_emg_cost；其中 w 为场景剩余能量的加权均值，
    仅用于诊断，不进入储能状态方程。
    """
    m = len(l_fc)
    idx_q, idx_c, idx_d = 0, m, 2 * m
    idx_up, idx_dn, idx_e = 3 * m, 4 * m, 5 * m
    base = 6 * m + 1
    S = len(scen_net)
    idx_h, idx_r = base, base + S * m
    nv = base + 2 * S * m

    obj = np.zeros(nv)
    if mode == "plan":
        obj[idx_q:idx_q + m] = price
    else:
        obj[idx_up:idx_up + m] = 1.5 * price
        obj[idx_dn:idx_dn + m] = -0.5 * price
    obj[idx_c:idx_c + m] += 1e-7
    obj[idx_d:idx_d + m] += 1e-7
    pen = np.full(m, P.emg)
    if mode == "plan" and plan_pen is not None:
        pen = np.asarray(plan_pen, dtype=float)[:m]
    for k, w in enumerate(weights):
        obj[idx_h + k * m: idx_h + (k + 1) * m] = w * pen * price
    obj[idx_e + m] -= float(terminal_value)

    n_adjust = 0 if mode == "plan" else m
    scenario_row0 = m + n_adjust
    A_eq = np.zeros((scenario_row0 + S * m, nv))
    b_eq = np.zeros(scenario_row0 + S * m)
    for t in range(m):
        A_eq[t, idx_e + t] = -1.0                 # e[t+1] = e[t] + ηc c - d/ηd
        A_eq[t, idx_e + t + 1] = 1.0
        A_eq[t, idx_c + t] = -P.eta
        A_eq[t, idx_d + t] = 1.0 / P.eta

        if mode != "plan":
            A_eq[m + t, idx_q + t] = 1.0          # q - up + dn = q_plan
            A_eq[m + t, idx_up + t] = -1.0
            A_eq[m + t, idx_dn + t] = 1.0
            b_eq[m + t] = q_plan[t]

    for k in range(S):
        for t in range(m):
            row = scenario_row0 + k * m + t
            A_eq[row, idx_q + t] = 1.0
            A_eq[row, idx_c + t] = -1.0
            A_eq[row, idx_d + t] = 1.0
            A_eq[row, idx_h + k * m + t] = 1.0
            A_eq[row, idx_r + k * m + t] = -1.0
            b_eq[row] = scen_net[k][t]

    zero = (0.0, 0.0)
    bounds = ([(0, None)] * m + [(0, P.c_max)] * m + [(0, P.c_max)] * m
              + [(0, None)] * m + [(0, None)] * m
              + [(P.e_min, P.e_max)] * (m + 1)
              + [(0, None)] * (2 * S * m))
    if mode == "plan":
        for t in range(m):                        # 计划模式下禁用 up/dn
            bounds[idx_up + t] = zero
            bounds[idx_dn + t] = zero
    bounds[idx_e] = (e_start, e_start)
    lo = P.e0 if terminal_min is None else float(terminal_min)
    hi = lo if terminal_max is None else float(terminal_max)
    bounds[idx_e + m] = (lo, hi)

    res = linprog(obj, A_eq=A_eq, b_eq=b_eq, bounds=bounds, method="highs")
    if not res.success:
        raise RuntimeError("节点 LP 求解失败：" + str(res.message))
    x = res.x
    q, c, d = x[idx_q:idx_q + m], x[idx_c:idx_c + m], x[idx_d:idx_d + m]
    e = x[idx_e:idx_e + m + 1]
    spill = x[idx_r:idx_r + S * m].reshape(S, m)
    w = np.average(spill, axis=0, weights=np.asarray(weights, dtype=float))
    qp = np.zeros(m) if mode == "plan" else np.asarray(q_plan, dtype=float)
    fee = fee_seg(price, qp, q) if mode == "adjust" else float((price * q).sum())
    return {"q": q, "c": c, "d": d, "w": w, "e": e, "fee": fee,
            "exp_emg_cost": expected_emergency(price, q, c, d, scen_net, weights, P)}


def eval_seg(price, q, c, d, q_plan, scen_net, weights, P: "Params" = DEFAULT_PARAMS):
    """评估"保持现有计划"的费用（调整费 + 期望紧急购电费）。"""
    return {"fee": fee_seg(price, q_plan, q),
            "exp_emg_cost": expected_emergency(price, q, c, d, scen_net, weights, P)}


# --------------------------------------------------------------------------- 单日仿真
def simulate_day(att, f3: PvForecast3, price, i: int,
                 s_max: int = DEFAULT_SCENARIO_COUNT,
                 policy: str = "selective", tol: float = 1e-6, node_subset=None,
                 price_plan=None, load_lam: float = 1.0,
                 load_bias: bool = False, bias_clip: float = 0.4,
                 lookahead_alpha: float = 5.0, exec_mode: str = "A",
                 params: "Params" = DEFAULT_PARAMS, scen_scale: float = 1.0,
                 fc_kwargs: dict | None = None,
                 scenario_decay: float = 0.95, pv_interpolation: str = "step",
                 initial_soc=None, terminal_mode: str = "cycle",
                 terminal_value: float = 0.0, forecast_source: str = "legacy",
                 scenario_weighting: str = "legacy", initial_plan=None) -> dict:
    """执行一天：0:00 计划 + 6:00/12:00/18:00 调整 + 实际结算。

    policy: "none" 不调整；"fixed" 固定调整；"selective" 仅当预期收益为正才调整
    node_subset: 允许使用的调整节点索引（默认 [1,2,3]），用于分析增减节点的影响
    price_plan: 制定计划/调整时使用的电价（默认为实际电价 price）。问题四中若电价逐日波动
        且建模时并未预先得知，可传入"因果价格预测"，此时决策按 price_plan 优化、
        结算仍按实际价格 price 执行。
    load_lam: 负荷预测的指数衰减系数（默认 1.0，与既有结果一致）。
    load_bias: 是否用当日已实现负荷对剩余时段负荷预测做日级倍率校正（因果，默认关）。
    lookahead_alpha: 0:00 计划中对“后续节点可调整时段”的缺口计价倍率（默认 5.0 = 只看
        紧急购电）。取较小值（如 2.0）即反映“稍后可按 1.5 倍调整购电量补足”的期权价值，
        使计划不再过度囤电。仅影响 0:00 计划，不影响调整与结算口径。
    exec_mode: "A" 严格按（调整后）计划执行储能；"B" 购电量照付不误、储能内部根据
        实际负荷/光伏日内再调度（与问题二 P2B 同口径），“充放电量”取再调度后的最终值。
    params: 系统参数（储能容量/功率/效率/初始储电量/紧急购电倍率），默认等于原模型。
    scen_scale: 预报误差水平缩放（1.0 = 实际历史误差），用于“预报质量”敏感性分析。
    fc_kwargs: 负荷预测口径覆盖项（默认 None = 同月 $+$ 同类型均值）。
    """
    P = params
    start_soc = P.e0 if initial_soc is None else float(initial_soc)
    if terminal_mode == "cycle":
        terminal_min = terminal_max = start_soc
    elif terminal_mode == "carry":
        terminal_min, terminal_max = P.e_min, P.e_max
    else:
        raise ValueError("terminal_mode must be 'cycle' or 'carry'")
    price_plan = price if price_plan is None else price_plan
    l_act, v_act = att.load_kwh[i], att.pv_kwh[i]
    net_act = l_act - v_act
    nodes = [1, 2, 3] if node_subset is None else list(node_subset)

    if initial_plan is None:
        l_fc, v_fc = forecast_full(att, f3, i, 0, load_lam, fc_kwargs,
                                   pv_interpolation, forecast_source)
        scen, w = residual_scenarios(att, f3, i, 0, s_max, load_lam, scen_scale,
                                     fc_kwargs, scenario_decay, pv_interpolation, forecast_source,
                                     scenario_weighting)
        plan_pen = np.full(q2.N, P.emg)
        if lookahead_alpha != P.emg:              # 可调整时段（6:00 之后）按更低倍率对冲
            plan_pen[NODE_MIN[1] // 10:] = lookahead_alpha
        plan = seg_lp(price_plan, None, l_fc, v_fc, start_soc, scen, w, "plan",
                      plan_pen=plan_pen, P=P, terminal_min=terminal_min,
                      terminal_max=terminal_max, terminal_value=terminal_value)
    else:
        required = ("q", "c", "d", "e")
        if any(key not in initial_plan for key in required):
            raise ValueError("initial_plan must contain q, c, d and e")
        plan = {key: np.asarray(initial_plan[key], dtype=float).copy() for key in required}
        if any(plan[key].shape != (q2.N,) for key in ("q", "c", "d")) or plan["e"].shape != (q2.N + 1,):
            raise ValueError("initial_plan arrays must contain one complete day")
        if abs(float(plan["e"][0]) - start_soc) > 1e-5:
            raise ValueError("initial_plan SOC does not match initial_soc")
        plan["fee"] = float(np.dot(price_plan, plan["q"]))
        plan["exp_emg_cost"] = 0.0
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
        l_fc, v_fc = forecast_full(att, f3, i, NODE_MIN[k], load_lam, fc_kwargs, pv_interpolation,
                                   forecast_source)
        if load_bias and j0 > 0:                      # 用已实现的上午负荷校正全天水平
            obs, fc = att.load_kwh[i][:j0].sum(), l_fc[:j0].sum()
            if fc > 1e-9:
                ratio = float(np.clip(obs / fc, 1.0 - bias_clip, 1.0 + bias_clip))
                l_fc = l_fc.copy()
                l_fc[j0:] *= ratio
        scen, w = residual_scenarios(att, f3, i, NODE_MIN[k], s_max, load_lam, scen_scale,
                                     fc_kwargs, scenario_decay, pv_interpolation, forecast_source,
                                     scenario_weighting)
        qp_seg = q_plan[j0:]
        keep = eval_seg(price_plan[j0:], q_cur[j0:], c_cur[j0:], d_cur[j0:], qp_seg, scen, w, P)
        J_keep = keep["fee"] + keep["exp_emg_cost"]
        adj = seg_lp(price_plan[j0:], qp_seg, l_fc[j0:], v_fc[j0:], e_cur[j0], scen, w, "adjust",
                     P=P, terminal_min=terminal_min, terminal_max=terminal_max,
                     terminal_value=terminal_value)
        J_adj = adj["fee"] + adj["exp_emg_cost"]
        gain = J_keep - J_adj
        take = (policy == "fixed") or (policy == "selective" and gain > tol)
        if take:
            dq = float(np.abs(adj["q"] - q_cur[j0:]).sum())
            q_cur[j0:], c_cur[j0:], d_cur[j0:] = adj["q"], adj["c"], adj["d"]
            e_cur[j0:] = adj["e"]
        else:
            dq = 0.0
        log.append({"node": NODE_NAME[k], "J_keep": float(J_keep), "J_adj": float(J_adj),
                    "adjusted": bool(take), "fee": float(adj["fee"]), "dq_kwh": dq,
                    "expected_gain": float(gain), "threshold": float(tol)})

    committed = q_cur + d_cur - c_cur
    shortfall = np.maximum(0.0, net_act - committed)
    cost_emg = float(P.emg * (price * shortfall).sum())
    c_final, d_final, e_final = c_cur, d_cur, e_cur
    if exec_mode == "B":
        from q2_stochastic import realtime_dispatch
        rt = realtime_dispatch(att, q_cur, att.load_kwh[i], att.pv_kwh[i],
                               float(e_cur[0]), float(e_cur[-1]))
        c_final, d_final, e_final = rt["c"], rt["d"], rt["e"]
        shortfall = rt["emg"]
        cost_emg = rt["emg_cost"]
    return {
        "date": att.dates[i],
        "q_plan": q_plan, "q_adj": q_cur, "c_adj": c_final, "d_adj": d_final,
        "e_plan": plan["e"], "e_adj": e_final,
        "plan_cost": float((price * q_plan).sum()),
        "fee": fee_seg(price, q_plan, q_cur),
        "emg_kwh": float(shortfall.sum()), "emg_cost": cost_emg,
        "total": float(cost_emg + fee_seg(price, q_plan, q_cur)),
        "log": log,
    }
