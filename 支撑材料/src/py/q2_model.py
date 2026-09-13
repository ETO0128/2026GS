"""问题二公共底座：数据层 + 日前计划 LP + 实时结算 + 因果预测。

时间口径（与问题一保持一致，必须显式记录）
----------------------------------------
附件1/2/4 的 10 分钟时间戳按行/列给出，顺序为 0:10, 0:20, ..., 23:50, 0:00+1。
本模块约定「时间戳 = 时段起点」，且 0:00+1 ≡ 0:00，因此

    时段 j = [10j, 10(j+1)) 分钟，对应原始数据第 (j-1) mod 144 列/行。

在代码里体现为 period_order = np.roll(sheet_order, +1)。
该口径与问题一 `src/py/question1.py` 的旋转处理一致，四个结果模板的列/行标签
（0:10-0:20 ... 0:00+1-0:10+1）也支持这一读法。

变量口径
--------
充电量 c 与放电量 d 均为**交流母线侧**电量，效率只出现在储能状态方程中：
    e[t+1] = e[t] + 0.9*c[t] - d[t]/0.9
储能约束：1200 <= e <= 10800 kWh；0 <= c, d <= 5000/6 = 833.3333 kWh；不允许反送电。
"""
from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np
from scipy.optimize import linprog

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RNS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
RID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"

N = 144                # 每天 144 个 10 分钟时段
DT_H = 1.0 / 6.0       # 时段长度（小时）
CAP_KWH = 12000.0      # 储能额定容量
E_MIN = 1200.0         # 储电量下限
E_MAX = 10800.0        # 储电量上限
E0_KWH = 6000.0        # 2025-01-01 0:00 初始储电量
P_MAX_KW = 5000.0      # 最大充放电功率
C_MAX_KWH = P_MAX_KW * DT_H      # 833.3333 kWh / 时段
ETA_C = 0.9            # 充电效率
ETA_D = 0.9            # 放电效率
EMG_MULTIPLIER = 5.0   # 紧急购电倍率
WINDOW_START = dt.date(2025, 2, 1)     # 结果文件覆盖区间起点
WINDOW_END = dt.date(2025, 12, 31)     # 结果文件覆盖区间终点


# --------------------------------------------------------------------------- 数据层
def project_root() -> Path:
    """仓库根目录（本文件位于 src/py/ 下）。"""
    return Path(__file__).resolve().parents[2]


def _col_letters(n: int) -> list[str]:
    out = []
    for i in range(2, n + 2):
        c, k = "", i
        while k:
            k, r = divmod(k - 1, 26)
            c = chr(65 + r) + c
        out.append(c)
    return out


COLS = _col_letters(N)


def read_workbook(path: Path) -> dict[str, dict[str, str]]:
    """读取 xlsx 为 {sheet 名: {单元格引用: 值}}，不依赖 openpyxl。

    支持 sharedStrings 与 inlineStr 两种字符串存储方式。
    """
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{NS}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{NS}t")))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        relmap = {r.get("Id"): r.get("Target") for r in rels.findall(f"{RNS}Relationship")}
        result: dict[str, dict[str, str]] = {}
        for sh in wb.find(f"{NS}sheets").findall(f"{NS}sheet"):
            target = relmap.get(sh.get(RID), "")
            sheet_path = "xl/" + target.lstrip("/")
            if sheet_path not in names:
                sheet_path = "xl/worksheets/" + target.split("/")[-1]
            root = ET.fromstring(z.read(sheet_path))
            grid: dict[str, str] = {}
            for row in root.iter(f"{NS}row"):
                for c in row.findall(f"{NS}c"):
                    ref = c.get("r")
                    t = c.get("t")
                    if t == "inlineStr":
                        v = "".join(x.text or "" for x in c.iter(f"{NS}t"))
                    else:
                        ve = c.find(f"{NS}v")
                        v = ve.text if ve is not None else None
                        if t == "s" and v and v.isdigit():
                            v = shared[int(v)]
                    if v is not None:
                        grid[ref] = v
            result[sh.get("name")] = grid
    return result


def period_order(values_in_sheet_order: np.ndarray) -> np.ndarray:
    """原始行列顺序（0:10 ... 0:00+1）-> 时段顺序（0:00-0:10 ... 23:50-24:00）。"""
    return np.roll(np.asarray(values_in_sheet_order, dtype=float), 1)


class Attachment:
    """附件1（电价）与附件2（全年实际负荷/光伏）。"""

    def __init__(self, root: Path | None = None):
        root = Path(root) if root is not None else project_root()
        att_dir = root / "problems" / "C题" / "附件"

        a1 = read_workbook(att_dir / "附件1.xlsx")
        g1 = list(a1.values())[0]
        self.price = period_order(np.array([float(g1[f"B{r}"]) for r in range(2, 2 + N)]))
        self.q1_load = period_order(np.array([float(g1[f"C{r}"]) for r in range(2, 2 + N)]))
        self.q1_pv = period_order(np.array([float(g1[f"D{r}"]) for r in range(2, 2 + N)]))

        a2 = read_workbook(att_dir / "附件2.xlsx")
        load_g, pv_g = a2["小区负载"], a2["光伏发电实际功率"]
        self.dates: list[dt.date] = []
        rows_load, rows_pv = [], []
        for r in range(2, 367):
            self.dates.append(dt.date(1899, 12, 30) + dt.timedelta(days=int(float(load_g[f"A{r}"]))))
            rows_load.append(period_order(np.array([float(load_g[f"{c}{r}"]) for c in COLS])))
            rows_pv.append(period_order(np.array([float(pv_g[f"{c}{r}"]) for c in COLS])))
        self.load_kw = np.array(rows_load)
        self.pv_kw = np.array(rows_pv)
        self.load_kwh = self.load_kw * DT_H
        self.pv_kwh = self.pv_kw * DT_H

    def day_index(self, d: dt.date) -> int:
        return self.dates.index(d)

    @property
    def window(self) -> list[int]:
        """结果文件覆盖区间：2025-02-01 ~ 2025-12-31（1 月仅作预热历史）。"""
        return [i for i, d in enumerate(self.dates) if WINDOW_START <= d <= WINDOW_END]


# --------------------------------------------------------------------------- 日前计划 LP
def plan_lp(price: np.ndarray, load_kwh: np.ndarray, pv_kwh: np.ndarray,
            e_start: float, terminal: str = "cycle") -> dict:
    """日前确定性 LP：给定负荷/光伏序列，最小化计划购电费。

    变量 [g, c, d, w, e]，其中 g 购电量、c/d 母线侧充放电量、w 弃光量、e 储电量。
    terminal = "cycle": e_144 = e_start（日周期平衡，与问题一口径一致）
    terminal = "free" : e_144 自由（用于演示日末放空的问题）
    """
    n = N
    nv = 4 * n + (n + 1)
    g, c, d, w = slice(0, n), slice(n, 2 * n), slice(2 * n, 3 * n), slice(3 * n, 4 * n)
    e = slice(4 * n, 4 * n + n + 1)

    obj = np.zeros(nv)
    obj[g] = price

    A = np.zeros((2 * n, nv))
    b = np.zeros(2 * n)
    for t in range(n):
        A[t, g.start + t] = 1.0          # 母线平衡：g + v + d = l + c + w
        A[t, c.start + t] = -1.0
        A[t, d.start + t] = 1.0
        A[t, w.start + t] = -1.0
        b[t] = load_kwh[t] - pv_kwh[t]

        A[n + t, e.start + t] = -1.0     # 状态转移：e[t+1] = e[t] + 0.9c - d/0.9
        A[n + t, e.start + t + 1] = 1.0
        A[n + t, c.start + t] = -ETA_C
        A[n + t, d.start + t] = 1.0 / ETA_D

    bounds = [(0.0, None)] * n
    bounds += [(0.0, C_MAX_KWH)] * n
    bounds += [(0.0, C_MAX_KWH)] * n
    bounds += [(0.0, float(pv_kwh[t])) for t in range(n)]
    bounds += [(e_start, e_start)]
    bounds += [(E_MIN, E_MAX)] * (n - 1)
    bounds += [(e_start, e_start) if terminal == "cycle" else (E_MIN, E_MAX)]

    res = linprog(obj, A_eq=A, b_eq=b, bounds=bounds, method="highs")
    if not res.success:
        raise RuntimeError(f"日前 LP 求解失败: {res.message}")
    x = res.x.copy()
    x[np.abs(x) < 1e-9] = 0.0
    out = {"g": x[g], "c": x[c], "d": x[d], "w": x[w], "e": x[e],
           "plan_cost": float(np.dot(price, x[g]))}
    check_plan(load_kwh, pv_kwh, out)
    return out


def check_plan(load_kwh: np.ndarray, pv_kwh: np.ndarray, plan: dict, tol: float = 1e-5) -> None:
    """校验计划方案的能量平衡、SOC 递推、边界与充放电互斥。"""
    bal = plan["g"] + pv_kwh + plan["d"] - load_kwh - plan["c"] - plan["w"]
    soc = plan["e"][:-1] + ETA_C * plan["c"] - plan["d"] / ETA_D
    assert np.abs(bal).max() < tol, f"能量平衡残差 {np.abs(bal).max()}"
    assert np.abs(plan["e"][1:] - soc).max() < tol, "SOC 递推残差超限"
    assert plan["g"].min() > -tol, "购电量为负"
    assert plan["c"].max() < C_MAX_KWH + tol and plan["d"].max() < C_MAX_KWH + tol, "超出功率上限"
    assert plan["e"].min() > E_MIN - tol and plan["e"].max() < E_MAX + tol, "储电量越界"
    assert np.minimum(plan["c"], plan["d"]).max() < tol, "出现同时充放电"


def settle(price: np.ndarray, plan: dict, net_actual_kwh: np.ndarray) -> dict:
    """实时结算（变体 A：严格按计划执行）。

    计划购电量照付不议；实际净负荷高于"计划购电量 + 计划放电 - 计划充电"的部分，
    按 5 倍价紧急购电。返回值同时给出与计划相比的过剩电量。
    """
    committed = plan["g"] + plan["d"] - plan["c"]     # = 预测净负荷 + 计划弃光
    shortfall = np.maximum(0.0, net_actual_kwh - committed)
    surplus = np.maximum(0.0, committed - net_actual_kwh)
    cost_plan = float(np.dot(price, plan["g"]))
    cost_emg = float(EMG_MULTIPLIER * np.dot(price, shortfall))
    return {"cost_plan": cost_plan, "cost_emg": cost_emg, "total": cost_plan + cost_emg,
            "emg_kwh": float(shortfall.sum()), "emg_slots": int((shortfall > 1e-9).sum()),
            "surplus_kwh": float(surplus.sum()),
            "plan_curtail_kwh": float(plan["w"].sum())}


# --------------------------------------------------------------------------- 预测层（因果）
def is_low_day(d: dt.date) -> bool:
    """低负荷日判定。

    由附件2 数据决定：日均负荷约 7.8 万 kWh 的日子恰好是**周五与周六**（各 52 天），
    其余约 12.4 万 kWh。该判定只依赖日期，不依赖当日数据，因此不构成未来信息泄漏。
    注意不能用"周六周日为周末"的常识假设，否则周日会被误判（周日其实是高负荷日）。
    """
    return d.weekday() in (4, 5)


def history_index(att: Attachment, i: int, min_month_days: int = 3) -> list[int]:
    """因果历史子集：同类型（周五六 / 其余）+ 同月；同月样本不足时回退到同类型。

    预测与分位数计划必须使用完全相同的子集规则，否则策略对比会出现假象。
    """
    d = att.dates[i]
    idx = [j for j in range(i) if is_low_day(att.dates[j]) == is_low_day(d)]
    sub = [j for j in idx if att.dates[j].month == d.month]
    if len(sub) >= min_month_days:
        idx = sub
    if not idx:
        idx = list(range(i)) or [i]
    return idx


def forecast_day(att: Attachment, i: int, lam: float = 1.0, use_month: bool = True,
                 use_type: bool = True, k_max: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """只用第 i 天之前的历史构造负荷/光伏预测（相似日 + 指数衰减，默认退化为均值）。

    返回 (负荷预测 kWh/时段, 光伏预测 kWh/时段)。
    """
    if use_month and use_type and k_max is None:
        idx = history_index(att, i)
    else:
        d = att.dates[i]
        idx = list(range(i))
        if k_max is not None:
            idx = idx[-k_max:]
        if use_type:
            idx = [j for j in idx if is_low_day(att.dates[j]) == is_low_day(d)]
        if use_month:
            sub = [j for j in idx if att.dates[j].month == d.month]
            if len(sub) >= 3:
                idx = sub
        if not idx:
            idx = list(range(i)) or [i]
    d = att.dates[i]
    w = np.array([lam ** (d - att.dates[j]).days for j in idx], dtype=float)
    w = w / w.sum()
    load = (att.load_kwh[idx] * w[:, None]).sum(0)
    pv = (att.pv_kwh[idx] * w[:, None]).sum(0)
    return load, pv


def quantile_plan(att: Attachment, i: int, tau: float) -> np.ndarray:
    """无储能时：计划购电量 = 净需求的因果 tau 分位数（下界 0）。"""
    idx = history_index(att, i)
    net = att.load_kwh[idx] - att.pv_kwh[idx]
    return np.maximum(0.0, np.quantile(net, tau, axis=0))
