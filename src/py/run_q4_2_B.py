"""问题 4-2 口径 B：0:00 官方计划（照付不议） + 储能日内滚动再调度。

两个版本同时给出，便于论文交代：
  causal —— 严格因果：每 10 分钟重优化、只执行当前时段；未来时段用带安全余量的
            计划净负荷（与 4-2 官方计划的构造一致）。**正式结果**。
  oracle —— 日内完全信息：一次性解全天 LP，是日内再调度的**上界**（问题二 P2B 口径）。

运行：python src/py/run_q4_2_B.py [--limit 60] [--future planning|point] [--free-terminal]
输出：src/outputs/q4_2_B.json / q4_2_B.txt（含每日数组，供回填 result4-2.xlsx）
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import q2_model as q2
from q4_exec import redispatch_causal, redispatch_oracle
from question1 import load_question1_data
from question2_data import load_cold_start_forecast
from question4_2 import Question42Config, run_question42_baseline
from question4_2_data import load_question42_data
from question4_2_forecast import PriceForecastConfig

RESERVE = 6000.0


def compute_days(root: Path, limit: int | None = None, price_method: str = "seven_day",
                 future: str = "planning", free_terminal: bool = False) -> dict:
    """返回口径 B 的逐日结果（可直接喂给 fill_result2.fill）。"""
    att_dir = root / "problems" / "C题" / "附件"
    q1 = load_question1_data(att_dir / "附件1.xlsx")
    data = load_question42_data(att_dir / "附件2.xlsx", att_dir / "附件4.xlsx")
    cold = load_cold_start_forecast(att_dir / "附件1.xlsx")
    cfg = Question42Config(price_forecast=PriceForecastConfig(method=price_method),
                           reserve_kwh=RESERVE)
    res = run_question42_baseline(data, cold, cold_start_price_yuan_per_kwh=q1.price_yuan_per_kwh,
                                  config=cfg)
    records = res.official_days[:limit] if limit else res.official_days
    term = None if free_terminal else RESERVE

    e_causal = float(records[0].plan.soc_kwh[0])
    days: list[dict] = []
    tot_c = tot_o = emg_c = emg_o = 0.0
    for rec in records:
        idx = data.dates.index(rec.date)
        g = rec.plan.grid_kwh
        p_act = data.price_yuan_per_kwh[idx]
        p_fc = rec.price_forecast.price_yuan_per_kwh
        load_kwh, pv_kwh = data.load_kw[idx] / 6.0, data.pv_kw[idx] / 6.0
        net_fc_kw = (rec.source_forecast.planning_net_kw if future == "planning"
                     else rec.source_forecast.load_kw - rec.source_forecast.pv_kw)
        rc = redispatch_causal(p_act, p_fc, g, load_kwh, pv_kwh, net_fc_kw, e_causal, term)
        ro = redispatch_oracle(p_act, g, load_kwh, pv_kwh,
                               float(rec.plan.soc_kwh[0]), float(rec.plan.soc_kwh[-1]))
        e_causal = float(rc["e"][-1])
        normal = float(p_act @ g)
        tot_c += normal + rc["emg_cost"]
        tot_o += normal + ro["emg_cost"]
        emg_c += rc["emg_kwh"]
        emg_o += ro["emg_kwh"]
        days.append({
            "date": rec.date, "index": idx,
            "g": g, "charge": rc["c"], "discharge": rc["d"],
            "soc_start": float(rc["e"][0]), "soc_end": float(rc["e"][-1]),
            "shortfall": rc["emg"], "plan_cost": normal, "emg_cost": rc["emg_cost"],
            "emg_kwh": rc["emg_kwh"], "total": normal + rc["emg_cost"],
        })
    return {"days": days, "causal_total": tot_c, "causal_emg_kwh": emg_c,
            "oracle_total": tot_o, "oracle_emg_kwh": emg_o}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--price-method", default="seven_day")
    ap.add_argument("--future", choices=["planning", "point"], default="planning")
    ap.add_argument("--free-terminal", action="store_true")
    args = ap.parse_args()

    root = q2.project_root()
    out = compute_days(root, args.limit, args.price_method, args.future, args.free_terminal)
    lines = ["问题 4-2 口径 B：0:00 官方计划（照付不议） + 储能日内滚动再调度",
             f"天数 {len(out['days'])}（2025-02-01 起）",
             "  口径 A（严格执行，官方基线）：17,256,638.87 元",
             f"  口径 B · 因果滚动（正式）  ：{out['causal_total']:,.2f} 元"
             f"（紧急购电 {out['causal_emg_kwh']:,.1f} kWh）",
             f"  口径 B · 日内完全信息上界：{out['oracle_total']:,.2f} 元"
             f"（紧急购电 {out['oracle_emg_kwh']:,.1f} kWh）"]
    rec = {"days": len(out["days"]), "reserve": RESERVE, "future": args.future,
           "official_A": 17256638.87,
           "causal": {"total": out["causal_total"], "emg_kwh": out["causal_emg_kwh"]},
           "oracle": {"total": out["oracle_total"], "emg_kwh": out["oracle_emg_kwh"]},
           "detail": [{**d, "date": str(d["date"]), "g": np.asarray(d["g"]).tolist(),
                       "charge": d["charge"].tolist(), "discharge": d["discharge"].tolist(),
                       "shortfall": d["shortfall"].tolist()} for d in out["days"]]}
    (root / "src" / "outputs" / "q4_2_B.json").write_text(
        json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    (root / "src" / "outputs" / "q4_2_B.txt").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
