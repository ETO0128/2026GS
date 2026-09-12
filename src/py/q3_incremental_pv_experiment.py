"""Evaluate the conditional value of an extra perfect-PV update.

The load forecast and load-residual scenarios remain causal.  Each candidate
update is inserted into the existing 06:00/12:00/18:00 sequence, so the result
measures incremental rather than stand-alone information value.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

import q2_model as q2
import q3_model as q3


STANDARD_NODES = {360, 720, 1080}
EXTRA_NODES = (180, 540, 900, 1260)


def simulate(att, f3, index: int, extra_minute: int | None) -> dict:
    price = att.price
    l_fc, v_fc = q3.forecast_full(att, f3, index, 0)
    scenarios, weights = q3.residual_scenarios(att, f3, index, 0)
    plan = q3.seg_lp(price, None, l_fc, v_fc, q2.E0_KWH, scenarios, weights, "plan")
    q_plan = plan["q"].copy()
    q_cur, c_cur, d_cur, e_cur = (plan[key].copy() for key in ("q", "c", "d", "e"))

    events = sorted(STANDARD_NODES | ({extra_minute} if extra_minute is not None else set()))
    accepted = []
    for minute in events:
        j0 = minute // 10
        if minute in STANDARD_NODES:
            l_fc, v_fc = q3.forecast_full(att, f3, index, minute)
            scenarios, weights = q3.residual_scenarios(att, f3, index, minute)
        else:
            l_fc = q3.forecast_full(att, f3, index, 0)[0]
            v_fc = att.pv_kwh[index]
            scenarios, weights = q3.load_only_residual_scenarios(
                att, f3, index, minute, v_fc[j0:])
        keep = q3.eval_seg(price[j0:], q_cur[j0:], c_cur[j0:], d_cur[j0:],
                           q_plan[j0:], scenarios, weights)
        adjusted = q3.seg_lp(price[j0:], q_plan[j0:], l_fc[j0:], v_fc[j0:],
                             e_cur[j0], scenarios, weights, "adjust")
        gain = keep["fee"] + keep["exp_emg_cost"] - (
            adjusted["fee"] + adjusted["exp_emg_cost"])
        if gain > 1e-6:
            q_cur[j0:], c_cur[j0:], d_cur[j0:], e_cur[j0:] = (
                adjusted["q"], adjusted["c"], adjusted["d"], adjusted["e"])
            accepted.append(minute)

    net_actual = att.load_kwh[index] - att.pv_kwh[index]
    emergency = np.maximum(0.0, net_actual - (q_cur + d_cur - c_cur))
    fee = q3.fee_seg(price, q_plan, q_cur)
    emergency_cost = 5.0 * float(np.dot(price, emergency))
    return {"total": fee + emergency_cost, "emergency_kwh": float(emergency.sum()),
            "accepted": accepted}


def main() -> None:
    root = q2.project_root()
    att, f3 = q2.Attachment(root), q3.PvForecast3(root)
    cases = {"existing": None, **{f"plus_{m // 60:02d}00": m for m in EXTRA_NODES}}
    result = {}
    for name, extra in cases.items():
        rows = [simulate(att, f3, i, extra) for i in att.window]
        result[name] = {
            "total_yuan": float(sum(row["total"] for row in rows)),
            "emergency_kwh": float(sum(row["emergency_kwh"] for row in rows)),
            "extra_accepted_days": int(sum(extra in row["accepted"] for row in rows))
                if extra is not None else 0,
        }
    baseline = result["existing"]["total_yuan"]
    for item in result.values():
        item["saving_vs_existing_yuan"] = baseline - item["total_yuan"]
    output = root / "src" / "outputs" / "q3_incremental_pv_experiment.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
