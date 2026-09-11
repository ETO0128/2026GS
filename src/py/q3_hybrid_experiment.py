"""Validate a Q2 day-ahead contract followed by Q3 intraday rolling recourse."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import q2_model as legacy
import q3_model as q3
from question2 import Question2Config, run_question2
from question2_data import load_cold_start_forecast, load_year_data


def summarize(rows):
    return {
        "total_yuan": float(sum(r["total"] for r in rows)),
        "contract_fee_yuan": float(sum(r["fee"] for r in rows)),
        "emergency_cost_yuan": float(sum(r["emg_cost"] for r in rows)),
        "emergency_kwh": float(sum(r["emg_kwh"] for r in rows)),
        "adjustments": int(sum(item["adjusted"] for r in rows for item in r["log"])),
        "adjusted_days": int(sum(any(item["adjusted"] for item in r["log"]) for r in rows)),
    }


def paired_bootstrap_saving(reference, candidate, samples=5000, seed=2026):
    differences = np.asarray([a["total"] - b["total"] for a, b in zip(reference, candidate)])
    rng = np.random.default_rng(seed)
    means = np.empty(samples)
    for k in range(samples):
        means[k] = differences[rng.integers(0, len(differences), len(differences))].sum()
    return {
        "observed_saving_yuan": float(differences.sum()),
        "ci95_yuan": [float(x) for x in np.quantile(means, [0.025, 0.975])],
        "probability_saving_positive": float(np.mean(means > 0.0)),
        "improved_days": int(np.sum(differences > 0.0)),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=0)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    root = legacy.project_root()
    attachment_dir = root / "problems" / "C题" / "附件"
    data = load_year_data(attachment_dir / "附件1.xlsx", attachment_dir / "附件2.xlsx")
    cold = load_cold_start_forecast(attachment_dir / "附件1.xlsx")
    q2_result = run_question2(data, Question2Config(), cold)
    q2_by_date = {record.date: record for record in q2_result.days}

    att = legacy.Attachment(root)
    f3 = q3.PvForecast3(root)
    indices = att.window[: args.days or None]
    baseline, hybrid, q2_no_adjust = [], [], []
    for position, i in enumerate(indices):
        if position % 40 == 0:
            print(f"{position}/{len(indices)}", flush=True)
        record = q2_by_date[att.dates[i]]
        initial = {
            "q": record.plan.grid_kwh,
            "c": record.plan.charge_kwh,
            "d": record.plan.discharge_kwh,
            "e": record.plan.soc_kwh,
        }
        common = dict(initial_plan=initial, initial_soc=float(record.plan.soc_kwh[0]))
        q2_no_adjust.append(q3.simulate_day(att, f3, att.price, i, policy="none", **common))
        hybrid.append(q3.simulate_day(att, f3, att.price, i, policy="selective", **common))
        baseline.append(q3.simulate_day(att, f3, att.price, i, policy="selective"))

    result = {
        "days": len(indices),
        "q2_no_adjust": summarize(q2_no_adjust),
        "lcy_baseline": summarize(baseline),
        "q2_contract_plus_lcy_rolling": summarize(hybrid),
    }
    result["hybrid_saving_vs_q2_yuan"] = result["q2_no_adjust"]["total_yuan"] - result["q2_contract_plus_lcy_rolling"]["total_yuan"]
    result["hybrid_difference_vs_lcy_yuan"] = result["q2_contract_plus_lcy_rolling"]["total_yuan"] - result["lcy_baseline"]["total_yuan"]
    result["bootstrap_hybrid_vs_q2"] = paired_bootstrap_saving(q2_no_adjust, hybrid)
    result["bootstrap_lcy_vs_hybrid"] = paired_bootstrap_saving(hybrid, baseline)
    out = args.out or root / "src" / "outputs" / "q3_hybrid_experiment.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
