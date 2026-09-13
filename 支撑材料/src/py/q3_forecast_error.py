"""附件3 光伏预报精度统计（问题三“预测更新频率”论证的数据来源）。

统计口径（与论文问题三“多时刻光伏预测更新”一节一致）
------------------------------------------------------
1. 逐时段误差：把附件3 的整点预报按小时取常值映射到 10 分钟时段（见
   ``q3_model.PvForecast3.pv_kwh``），与实际光伏功率（附件2，kW）比较，取绝对误差。
2. **全天 MAE**：起报时刻 τ 的预报覆盖 [τ, 24:00)，对该区间全部时段取平均（全年 365 天）。
   用于与本文自建因果模型对比（0:00 起报 445.00 kW，自建模型 229.12 kW）。
3. **共同目标时段 MAE**：三种起报时刻（0:00/6:00/12:00）都能覆盖的共同区间
   [12:00, 24:00)，在同一目标时段上比较不同起报时刻的误差，得到“越晚起报越准”的结论
   （455.94 / 414.13 / 383.38 kW）。这是滚动调整能压缩紧急购电的物理依据。

运行：python src/py/q3_forecast_error.py
输出：src/outputs/q3_forecast_error_report.txt
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

import q2_model as q2
import q3_model as q3

NL = 6.0                      # kW = kWh / (1/6 h)
ISSUES = ((0, "0:00"), (360, "6:00"), (720, "12:00"), (1080, "18:00"))
COMMON = (72, 144)            # [12:00, 24:00)：0:00/6:00/12:00 起报的共同覆盖区间


def abs_errors(f3: q3.PvForecast3, att: q2.Attachment, tau: int, j0: int, j1: int) -> np.ndarray:
    """返回起报时刻 tau 在目标时段 [j0,j1) 上的逐时段绝对误差（kW，全年拼接）。"""
    a0 = max(j0, tau // 10)
    out = []
    for d in f3.days:
        if d not in att.dates:
            continue
        try:
            fc = f3.pv_kwh(d, tau, a0, j1) * NL
        except (KeyError, ValueError):
            continue
        out.append(np.abs(fc - att.pv_kw[att.day_index(d)][a0:j1]))
    return np.concatenate(out) if out else np.array([np.nan])


def main() -> None:
    root = q2.project_root()
    att = q2.Attachment(root)
    f3 = q3.PvForecast3(root)
    lines: list[str] = []

    def emit(s: str = "") -> None:
        lines.append(str(s))
        print(s, flush=True)

    emit("附件3 光伏预报精度统计")
    emit(f"附件3 覆盖 {len(f3.days)} 天、每天 4 个发布时刻（0:00/6:00/12:00/18:00）")
    emit("")
    emit("1) 各起报时刻在其覆盖时段 [τ,24:00) 内的全天 MAE（全年 365 天，kW）")
    for tau, name in ISSUES:
        e = abs_errors(f3, att, tau, 0, q2.N)
        emit(f"   {name} 起报：{e.mean():8.2f} kW（{e.size} 个时段）")
    emit("")
    emit("2) 共同目标时段 [12:00,24:00) 上，不同起报时刻的 MAE（kW）")
    base = None
    for tau, name in ISSUES:
        if tau // 10 > COMMON[0]:
            continue
        e = abs_errors(f3, att, tau, *COMMON)
        if base is None:
            base = e.mean()
        emit(f"   {name} 起报：{e.mean():8.2f} kW"
             + (f"（相对 0:00 起报改善 {(base - e.mean()) / base * 100:4.1f}%）" if tau else ""))
    emit("")
    emit("3) 本文自建因果模型（同月 + 同类型均值）的全年 MAE")
    for tag, win in (("2-12 月（334 天）", att.window), ("全年（365 天）", range(len(att.dates)))):
        ep, el = [], []
        for i in win:
            lf, vf = q2.forecast_day(att, i)
            ep.append(np.abs(vf - att.pv_kwh[i]))
            el.append(np.abs(lf - att.load_kwh[i]))
        emit(f"   {tag}：光伏 {np.concatenate(ep).mean() * NL:7.2f} kW，"
             f"负荷 {np.concatenate(el).mean() * NL:7.2f} kW")
    emit("")
    emit("结论：附件3 在 0:00 起报的预报（445.00 kW）差于本文自建因果模型（229.12 kW，全年）；")
    emit("但在共同目标时段 [12:00,24:00) 上，误差随起报时刻下降（455.94 → 414.13 → 383.38 kW），")
    emit("即“越晚发布、对越近的时段越准”，这正是滚动调整压缩紧急购电的物理依据。")

    out = root / "src" / "outputs" / "q3_forecast_error_report.txt"
    out.write_text("\n".join(lines), encoding="utf-8")
    print("done ->", out)


if __name__ == "__main__":
    main()
