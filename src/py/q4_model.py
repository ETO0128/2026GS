"""问题四：波动电价的读取与 4-3（波动电价下的滚动调整）公共层。

附件4 的结构
------------
``Sheet1``：A1 = ``日期\\时间``，B1..EO1 = 144 个时刻标签（0:10 ... ``0:00+1``），
A2..A366 = 2025-01-01 ~ 12-31 的日期，B..EO 为对应时段的电价（元/kWh）。
读入后按问题一~三的统一口径做 ``period_order`` 旋转（时间戳 = 时段起点）。

价格信息口径
------------
题目没有说明制定计划时是否已知当天的波动电价，因此提供三种：

``oracle``   ：0:00 即知当天全部时段电价（仅作不可实施的信息基准）；
``prev_day`` ：只用前一日实际电价曲线作为预测（因果）；
``profile``  ：用决策日前历史价格的逐时段扩展均值预测（因果）。
"""
from __future__ import annotations

import datetime as dt

import numpy as np

import q2_model as q2
import q3_model as q3

PRICE_MODES = ("oracle", "prev_day", "seven_day", "profile")
MODE_CN = {"oracle": "已知当天电价", "prev_day": "前一日电价预测",
           "seven_day": "近七日均值预测", "profile": "历史扩展均值曲线"}


class Prices4:
    """附件4 的逐日波动电价，行序与附件2/3 的日期严格对齐。"""

    def __init__(self, root, att: q2.Attachment | None = None):
        att = att if att is not None else q2.Attachment(root)
        self.att = att
        path = root / "problems" / "C题" / "附件" / "附件4.xlsx"
        grid = q2.read_workbook(path)
        sheet = list(grid.values())[0]
        rows, dates = [], []
        for r in range(2, 367):
            d = dt.date(1899, 12, 30) + dt.timedelta(days=int(float(sheet[f"A{r}"])))
            dates.append(d)
            rows.append(q2.period_order(np.array([float(sheet[f"{c}{r}"]) for c in q2.COLS])))
        self.price = np.array(rows)
        self.dates = dates
        if dates != att.dates:
            raise ValueError("附件4 的日期与附件2 不一致")
        self.index = {d: k for k, d in enumerate(dates)}
        self.profile = self.price.mean(axis=0)      # 逐时段均值 ≈ 附件1 曲线
        self.a1 = att.price

    def day(self, i: int) -> np.ndarray:
        return self.price[i]

    def forecast(self, i: int, mode: str) -> np.ndarray:
        if mode == "oracle":
            return self.price[i]
        if mode == "prev_day":
            return self.price[i - 1] if i > 0 else self.a1
        if mode == "seven_day":
            return self.price[max(0, i - 7):i].mean(axis=0) if i > 0 else self.a1
        if mode == "profile":
            # 扩展窗口只含决策日前已经实现的价格；首日使用附件1冷启动曲线。
            return self.price[:i].mean(axis=0) if i > 0 else self.a1
        raise ValueError(f"未知的价格信息口径：{mode!r}")

    def stats(self) -> dict:
        lo, hi = float(self.price.min()), float(self.price.max())
        rng = self.price.max(axis=1) - self.price.min(axis=1)
        corr = np.array([np.corrcoef(self.price[k], self.a1)[0, 1] for k in range(len(self.price))])
        return {"min": lo, "max": hi, "mean": float(self.price.mean()),
                "daily_range_mean": float(rng.mean()),
                "a1_range": float(self.a1.max() - self.a1.min()),
                "corr_with_a1_mean": float(corr.mean()),
                "profile_vs_a1_maxdiff": float(np.abs(self.profile - self.a1).max())}


def simulate_day4(att: q2.Attachment, f3: q3.PvForecast3, price_act: np.ndarray,
                  i: int, price_mode: str, p4: Prices4,
                  s_max: int = q3.DEFAULT_SCENARIO_COUNT,
                  policy: str = "selective") -> dict:
    """4-3 的单日仿真：决策用价格预测，结算用实际波动电价。"""
    return q3.simulate_day(att, f3, price_act, i, s_max=s_max, policy=policy,
                           price_plan=p4.forecast(i, price_mode))


def perfect_bound(p4: Prices4, att: q2.Attachment) -> dict:
    """完全信息下界：0:00 即知当天电价与当天真实负荷/光伏的确定性最优费用。

    不做滚动调整（信息已经完全），也不产生紧急购电与调整费，因此是 4-3 的费用下界。
    """
    total = 0.0
    for i in range(len(att.dates)):
        if att.dates[i] < q2.WINDOW_START or att.dates[i] > q2.WINDOW_END:
            continue
        plan = q2.plan_lp(p4.price[i], att.load_kwh[i], att.pv_kwh[i], q2.E0_KWH, "cycle")
        total += plan["plan_cost"]
    return {"total": total, "name": "perfect_bound"}
