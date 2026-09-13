"""Print the four specified-day Q3 details from the formal model."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np

import q2_model as q2
import q3_model as q3
from fill_result2 import fmt_clock, merge_intervals


def main() -> None:
    att = q2.Attachment()
    forecast = q3.PvForecast3(q2.project_root())
    out = {}
    for day in (dt.date(2025, 3, 20), dt.date(2025, 6, 21),
                dt.date(2025, 9, 23), dt.date(2025, 12, 21)):
        i = att.day_index(day)
        result = q3.simulate_day(att, forecast, att.price, i, policy="selective")
        shortfall = np.maximum(
            0.0,
            att.load_kwh[i] - att.pv_kwh[i]
            - (result["q_adj"] + result["d_adj"] - result["c_adj"]),
        )
        out[str(day)] = {
            "purchase_plan_adjusted": [
                [float(result["q_plan"][j]), float(result["q_adj"][j])]
                for j in (60, 72, 84, 96, 108, 120)
            ],
            "storage_charge_discharge": [
                [float(result["c_adj"][a:b].sum()), float(result["d_adj"][a:b].sum())]
                for a, b in ((0, 24), (24, 48), (48, 72), (72, 96), (96, 120), (120, 144))
            ],
            "emergency": [
                [fmt_clock(10 * a), fmt_clock(10 * b), float(energy)]
                for a, b, energy in merge_intervals(shortfall)
            ],
        }
    text = json.dumps(out, ensure_ascii=False, indent=2)
    output = Path(__file__).resolve().parents[1] / "outputs" / "q3_specified_details.json"
    output.write_text(text, encoding="utf-8")
    print(text)
    print(f"written: {output}")


if __name__ == "__main__":
    main()
