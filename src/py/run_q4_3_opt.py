"""问题四 4-3 优化：安全分位对冲（plan_hedge）+ 储能日内滚动再调度（口径 B）。

对照（全年 334 天，附件4 实际电价结算，价格信息口径 oracle）：
  A         —— 现行口径：点预测计划 + 储能严格执行
  A_hedge   —— 计划/节点需求抬到历史净负荷残差 q 分位（口径 A 下唯一有效的对冲手段）
  B_hedge   —— 上述对冲 + 购电量照付不议、储能日内因果滚动再调度（正式候选）

同时给出问题三（附件1 固定电价）在同样对冲下的全年费用，用于校验基线是否同步更新。

运行：python src/py/run_q4_3_opt.py [--hedge 0.8] [--limit 40]
输出：src/outputs/q4_3_opt.json / q4_3_opt.txt
"""
from __future__ import annotations

import argparse
import json

import numpy as np

import q2_model as q2
import q3_model as q3
import q4_model as q4


def run(att, f3, p4, win, policy, mode, hedge, price_mode="oracle"):
    fee = emg = kwh = 0.0
    detail = []
    for i in win:
        if price_mode is None:
            r = q3.simulate_day(att, f3, att.price, i, policy=policy, exec_mode=mode,
                                plan_hedge=hedge)
        else:
            r = q3.simulate_day(att, f3, p4.day(i), i, policy=policy, exec_mode=mode,
                                price_plan=p4.forecast(i, price_mode), plan_hedge=hedge)
        fee += r["fee"]
        emg += r["emg_cost"]
        kwh += r["emg_kwh"]
        detail.append({"date": str(r["date"]), "index": i,
                       "q_plan": r["q_plan"].tolist(), "q_adj": r["q_adj"].tolist(),
                       "charge": r["c_adj"].tolist(), "discharge": r["d_adj"].tolist(),
                       "soc_start": float(r["e_adj"][0]), "soc_end": float(r["e_adj"][-1]),
                       "shortfall": np.asarray(np.maximum(
                           0.0, (att.load_kwh[i] - att.pv_kwh[i])
                           - (r["q_adj"] + r["d_adj"] - r["c_adj"]))).tolist(),
                       "plan_cost": r["plan_cost"], "fee": r["fee"],
                       "emg_kwh": r["emg_kwh"], "emg_cost": r["emg_cost"], "total": r["total"]})
    return {"fee": fee, "emg_cost": emg, "emg_kwh": kwh, "total": fee + emg, "detail": detail}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hedge", type=float, default=0.8)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    root = q2.project_root()
    att = q2.Attachment(root)
    f3 = q3.PvForecast3(root)
    p4 = q4.Prices4(root, att)
    win = att.window[:args.limit] if args.limit else att.window

    out: dict = {"hedge": args.hedge, "days": len(win), "runs": {}}
    lines = [f"问题四 4-3 优化实验（{len(win)} 天，plan_hedge={args.hedge}）", ""]

    cases = [
        ("q3_fixed_A_hedge", None, "selective", "A", "问题三（附件1 固定电价）+ 对冲"),
        ("q43_A_hedge", "oracle", "selective", "A", "4-3 口径A + 对冲"),
        ("q43_B_hedge_sel", "oracle", "selective", "B_causal", "4-3 口径B + 对冲（择优调整）"),
        ("q43_B_hedge_none", "oracle", "none", "B_causal", "4-3 口径B + 对冲（不调整）"),
    ]
    for key, pmode, pol, mode, cn in cases:
        print(f"[{key}] running ...", flush=True)
        r = run(att, f3, p4, win, pol, mode, args.hedge, pmode)
        out["runs"][key] = {k: v for k, v in r.items() if k != "detail"}
        out["runs"][key]["detail"] = r["detail"]
        lines.append(f"  {cn:<36} 结算 {r['fee']:>15,.2f}  紧急 {r['emg_cost']:>13,.2f}  "
                     f"合计 {r['total']:>15,.2f}  紧急量 {r['emg_kwh']:>10,.1f} kWh")
        print(lines[-1], flush=True)

    (root / "src" / "outputs" / "q4_3_opt.json").write_text(
        json.dumps(out, ensure_ascii=False), encoding="utf-8")
    (root / "src" / "outputs" / "q4_3_opt.txt").write_text("\n".join(lines), encoding="utf-8")
    print("done")


if __name__ == "__main__":
    main()
