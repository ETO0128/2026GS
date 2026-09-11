"""Question 3 ablation study for the Issue #17 improvements.

The script deliberately writes research outputs only.  It never overwrites the
official result workbook; promotion is a separate, evidence-based step.
"""
from __future__ import annotations

import argparse
import json
from itertools import combinations
from pathlib import Path

import numpy as np

import q2_model as q2
import q3_model as q3


def node_subsets():
    return [list(c) for n in range(4) for c in combinations((1, 2, 3), n)]


def run_variant(att, f3, indices, *, threshold=0.0, nodes=(1, 2, 3), carry=False, **kwargs):
    totals = []
    emergency = []
    adjusted = []
    gains = []
    soc = q3.DEFAULT_PARAMS.e0
    for i in indices:
        terminal_value = float(np.min(att.price) * 0.9) if carry else 0.0
        result = q3.simulate_day(
            att, f3, att.price, i, policy="selective", tol=threshold,
            node_subset=nodes, initial_soc=soc,
            terminal_mode="carry" if carry else "cycle",
            terminal_value=terminal_value, **kwargs,
        )
        soc = float(result["e_adj"][-1]) if carry else q3.DEFAULT_PARAMS.e0
        totals.append(result["total"])
        emergency.append(result["emg_kwh"])
        adjusted.append(sum(item["adjusted"] for item in result["log"]))
        gains.extend(item["expected_gain"] for item in result["log"] if item["J_keep"] is not None)
    return {
        "total_yuan": float(np.sum(totals)),
        "emergency_kwh": float(np.sum(emergency)),
        "adjustments": int(np.sum(adjusted)),
        "mean_expected_gain_yuan": float(np.mean(gains)) if gains else 0.0,
        "terminal_soc_kwh": float(soc),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=0, help="evaluation days from Feb 1; 0 means all")
    parser.add_argument("--all-subsets", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    root = q2.project_root()
    att = q2.Attachment(root)
    f3 = q3.PvForecast3(root)
    evaluation = att.window[: args.days or None]

    variants = {
        "legacy_reproduction": dict(load_lam=1.0, pv_interpolation="step",
                                    forecast_source="legacy", scenario_weighting="legacy"),
        "official_forecast_only": dict(load_lam=0.95, pv_interpolation="step",
                                       forecast_source="official", scenario_weighting="legacy"),
        "plus_pv_interpolation": dict(load_lam=0.95, pv_interpolation="linear",
                                      forecast_source="official", scenario_weighting="legacy"),
        "plus_weighted_scenarios": dict(load_lam=0.95, pv_interpolation="linear",
                                        forecast_source="official", scenario_weighting="weighted"),
        "legacy_plus_interpolation": dict(load_lam=1.0, pv_interpolation="linear",
                                          forecast_source="legacy", scenario_weighting="legacy"),
        "legacy_plus_weighted_scenarios": dict(load_lam=1.0, pv_interpolation="step",
                                                forecast_source="legacy", scenario_weighting="weighted"),
        "legacy_plus_both": dict(load_lam=1.0, pv_interpolation="linear",
                                 forecast_source="legacy", scenario_weighting="weighted"),
    }
    result = {"days": len(evaluation), "variants": {}, "thresholds": {}, "node_subsets": {}}
    for name, config in variants.items():
        print(f"running {name}", flush=True)
        result["variants"][name] = run_variant(att, f3, evaluation, **config)

    # January is outside the official result interval and is used only to lock EVSI threshold.
    calibration = [i for i, d in enumerate(att.dates) if d.month == 1 and d.day >= 15]
    calibration_scores = {}
    for name, config in variants.items():
        calibration_scores[name] = run_variant(att, f3, calibration, **config)["total_yuan"]
    result["calibration_variant_cost_yuan"] = calibration_scores
    selected_name = min(calibration_scores, key=calibration_scores.get)
    result["selected_variant"] = selected_name
    final_config = variants[selected_name]
    candidates = (0.0, 25.0, 50.0, 100.0, 200.0)
    for value in candidates:
        print(f"calibrating threshold {value:g}", flush=True)
        result["thresholds"][str(value)] = run_variant(
            att, f3, calibration, threshold=value, **final_config)
    locked = min(candidates, key=lambda x: (result["thresholds"][str(x)]["total_yuan"], x))
    result["locked_threshold_yuan"] = locked
    result["final"] = run_variant(att, f3, evaluation, threshold=locked, **final_config)
    result["carry_terminal_value"] = run_variant(
        att, f3, evaluation, threshold=locked, carry=True, **final_config)

    if args.all_subsets:
        for nodes in node_subsets():
            label = "+".join(q3.NODE_NAME[k] for k in nodes) or "0:00 only"
            print(f"running nodes {label}", flush=True)
            result["node_subsets"][label] = run_variant(
                att, f3, evaluation, threshold=locked, nodes=nodes, **final_config)

    out = args.out or root / "src" / "outputs" / "q3_improvement_experiment.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
