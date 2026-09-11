"""Node-policy learning experiment for Question 4-3.

The learned layer selects an EVSI threshold; q3_model's rolling LP remains the
safe controller.  A ridge fitted-Q approximation is trained on Jan--Jun and
evaluated without updating on Sep--Dec.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

import q2_model as q2
import q3_model as q3
import q4_model as q4

THRESHOLDS = np.asarray([0.0, 100.0, 300.0, 600.0])


def features(att, p4, i):
    previous = p4.price[i - 1] if i else att.price
    return np.asarray([1.0, previous.mean(), previous.max() - previous.min(),
                       np.sin(2*np.pi*att.dates[i].timetuple().tm_yday/365),
                       np.cos(2*np.pi*att.dates[i].timetuple().tm_yday/365),
                       att.dates[i].weekday() >= 5], dtype=float)


def main():
    root = q2.project_root()
    att, f3 = q2.Attachment(root), q3.PvForecast3(root)
    p4 = q4.Prices4(root, att)
    indices = att.window
    costs = np.zeros((len(indices), len(THRESHOLDS)))
    adjustments = np.zeros_like(costs)
    for row, i in enumerate(indices):
        if row % 40 == 0:
            print(f"{row}/{len(indices)}", flush=True)
        for action, threshold in enumerate(THRESHOLDS):
            result = q3.simulate_day(att, f3, p4.day(i), i, policy="selective",
                                     tol=threshold, price_plan=p4.forecast(i, "prev_day"))
            costs[row, action] = result["total"]
            adjustments[row, action] = sum(item["adjusted"] for item in result["log"])
    x = np.stack([features(att, p4, i) for i in indices])
    dates = np.asarray([att.dates[i] for i in indices])
    train = dates <= __import__("datetime").date(2025, 6, 30)
    test = dates >= __import__("datetime").date(2025, 9, 1)
    predictions = np.zeros_like(costs)
    ridge = 1e-5 * np.eye(x.shape[1])
    for action in range(len(THRESHOLDS)):
        coef = np.linalg.solve(x[train].T @ x[train] + ridge, x[train].T @ costs[train, action])
        predictions[:, action] = x @ coef
    chosen = np.argmin(predictions, axis=1)
    learned = float(costs[np.arange(len(indices)), chosen][test].sum())
    fixed = {str(int(t)): float(costs[test, k].sum()) for k, t in enumerate(THRESHOLDS)}
    counts = np.bincount(chosen[test], minlength=len(THRESHOLDS))
    result = {"method": "ridge fitted-Q high-level EVSI threshold",
              "split": "train Feb-Jun; frozen test Sep-Dec",
              "fixed_threshold_cost_yuan": fixed, "learned_cost_yuan": learned,
              "learned_action_counts": counts.tolist(),
              "gain_vs_best_fixed_yuan": min(fixed.values()) - learned}
    out = root / "src" / "outputs" / "question4_3_rl.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
