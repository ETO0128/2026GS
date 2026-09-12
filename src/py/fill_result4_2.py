"""把问题四 4-2（波动电价下重做问题二）结果回填到官方模板 result4-2.xlsx。

三种数据源
----------
``official``（默认）：与问题二正式口径一致（七日均值+条件残差的源荷预测、因果电价预测、
    0:00 固定计划 + 储能严格执行），全年 17,256,638.87 元。
``B``：官方计划照付不议 + 储能日内因果滚动再调度，全年 16,681,808.91 元（第四问正式结果）。
``legacy``：本文自建源荷预测 + 价格信息口径对照（早期实现）。

模板与 result2.xlsx 完全同构，直接复用 `fill_result2.fill` 与 `verify`。

用法：
    python src/py/fill_result4_2.py --source B      # 第四问正式结果（口径 B）
    python src/py/fill_result4_2.py                 # 口径 A（严格执行的对照）
输出：src/附件5/result4-2.xlsx
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import q2_model as q2
from fill_result2 import fill, verify


def compute_days_official(root: Path, price_method: str, limit: int | None = None) -> list[dict]:
    """官方 4-2 因果基线：与问题二同源荷预测，电价用因果预测。"""
    from question1 import load_question1_data
    from question2_data import load_cold_start_forecast
    from question4_2 import Question42Config, run_question42_baseline
    from question4_2_data import load_question42_data
    from question4_2_forecast import PriceForecastConfig

    att_dir = root / "problems" / "C题" / "附件"
    q1 = load_question1_data(att_dir / "附件1.xlsx")
    data = load_question42_data(att_dir / "附件2.xlsx", att_dir / "附件4.xlsx")
    cold = load_cold_start_forecast(att_dir / "附件1.xlsx")
    cfg = Question42Config(price_forecast=PriceForecastConfig(method=price_method))
    res = run_question42_baseline(data, cold, cold_start_price_yuan_per_kwh=q1.price_yuan_per_kwh,
                                  config=cfg)
    records = res.official_days[:limit] if limit else res.official_days
    days = []
    for k, rec in enumerate(records):
        days.append({
            "date": rec.date, "index": k,
            "g": rec.plan.grid_kwh, "charge": rec.plan.charge_kwh, "discharge": rec.plan.discharge_kwh,
            "soc_start": float(rec.execution.soc_kwh[0]), "soc_end": float(rec.execution.soc_kwh[-1]),
            "shortfall": rec.execution.emergency_kwh,
            "plan_cost": rec.execution.normal_purchase_cost_yuan,
            "emg_cost": rec.execution.emergency_cost_yuan,
        })
    return days


def compute_days_legacy(root: Path, price_mode: str, limit: int | None = None) -> list[dict]:
    """旧口径对照：本文自建源荷预测 + 价格信息口径（oracle/prev_day/profile）。"""
    import q4_model as q4
    from run_q4_2 import simulate_day

    att = q2.Attachment(root)
    p4 = q4.Prices4(root, att)
    window = att.window[:limit] if limit else att.window
    days = []
    for i in window:
        r = simulate_day(att, p4, i, price_mode)
        days.append({"date": r["date"], "index": i, "g": r["g"], "charge": r["charge"],
                     "discharge": r["discharge"], "soc_start": r["soc_start"], "soc_end": r["soc_end"],
                     "shortfall": r["shortfall"], "plan_cost": r["plan_cost"], "emg_cost": r["emg_cost"]})
    return days


def compute_days_B(root: Path) -> list[dict]:
    """口径 B（官方计划 + 因果滚动再调度）：直接读 run_q4_2_B.py 的产物。"""
    import datetime as dt

    path = root / "src" / "outputs" / "q4_2_B.json"
    if not path.exists():
        raise SystemExit(f"缺少 {path}，请先运行 src/py/run_q4_2_B.py")
    rec = json.loads(path.read_text(encoding="utf-8"))
    days = []
    for k, d in enumerate(rec["detail"]):
        days.append({
            "date": dt.date.fromisoformat(d["date"]),
            "index": d.get("index", k),
            "g": np.asarray(d["g"], dtype=float),
            "charge": np.asarray(d["charge"], dtype=float),
            "discharge": np.asarray(d["discharge"], dtype=float),
            "soc_start": float(d["soc_start"]), "soc_end": float(d["soc_end"]),
            "shortfall": np.asarray(d.get("shortfall", d["emg"]), dtype=float),
            "plan_cost": float(d.get("plan_cost", d["normal"])),
            "emg_cost": float(d["emg_cost"]),
        })
    return days


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", choices=["official", "legacy", "B"], default="official")
    ap.add_argument("--price-method", default="seven_day",
                    choices=["previous_day", "seven_day", "week_type", "similar_day_decay"])
    ap.add_argument("--price-mode", default="oracle", choices=["oracle", "prev_day", "profile"])
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--data-root", type=Path, default=None)
    ap.add_argument("--template", type=Path, default=None)
    ap.add_argument("--output", type=Path, default=None)
    args = ap.parse_args()

    root = Path(args.data_root) if args.data_root else q2.project_root()
    template = Path(args.template) if args.template else \
        root / "problems" / "C题" / "附件" / "附件5" / "result4-2.xlsx"
    output = Path(args.output) if args.output else root / "src" / "附件5" / "result4-2.xlsx"

    if args.source == "official":
        days = compute_days_official(root, args.price_method, args.limit)
        tag = f"官方口径（源荷=问题二正式，电价={args.price_method}）"
    elif args.source == "B":
        days = compute_days_B(root)
        tag = "口径B（官方计划 + 储能日内滚动再调度）"
    else:
        days = compute_days_legacy(root, args.price_mode, args.limit)
        tag = f"旧自建口径（价格 {args.price_mode}）"

    fill(template, output, days, "A")
    print(f"已写入 {output}（{tag}，{len(days)} 天）")
    verify(output, days)


if __name__ == "__main__":
    main()
