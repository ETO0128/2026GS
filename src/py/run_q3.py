"""问题三评价期实验：三种调整策略对比与各调整节点的边际价值。"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import numpy as np

import q2_model as q2
import q3_model as q3

POLICIES = ["none", "fixed", "selective"]
NODE_SETS = {                    # 用于"增加节点是否有价值"的累积实验
    "0": [],
    "6": [1],
    "6+12": [1, 2],
    "6+12+18": [1, 2, 3],
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--days", type=int, default=0, help="只跑前 N 天（调试）")
    ap.add_argument("--s-max", type=int, default=6)
    ap.add_argument("--policies", type=str, default="none,fixed,selective")
    ap.add_argument("--node-sets", type=str, default="", help="例如 0,6,6+12,6+12+18")
    ap.add_argument("--pv-interpolation", choices=("step", "linear"), default="step")
    args = ap.parse_args()

    root = q2.project_root()
    att = q2.Attachment(root)
    f3 = q3.PvForecast3(root)
    win = att.window[:args.days] if args.days else att.window
    out = args.out or root / "src" / "outputs" / "q3_report.txt"
    lines: list[str] = []

    def emit(s=""):
        lines.append(str(s))
        print(s, flush=True)

    emit("问题三评价期实验（滚动调整购电策略）")
    emit(f"结果窗口 {att.dates[win[0]]} ~ {att.dates[win[-1]]}，共 {len(win)} 天")
    emit("")

    summary = {}
    json_out: dict = {"window": [str(att.dates[win[0]]), str(att.dates[win[-1]]), len(win)],
                      "policies": {}, "node_sets": {}}
    store: dict[str, dict[str, np.ndarray]] = {}
    for pol in [p for p in args.policies.split(",") if p]:
        tot = dict(plan=0.0, fee=0.0, emg=0.0, emg_kwh=0.0, adj_days=0, adj_nodes=0,
                   dq=0.0, nodes={n: dict(keep=0.0, adj=0.0, take=0, dq=0.0)
                                  for n in q3.NODE_NAME[1:]})
        q_plan = np.zeros((len(win), 144))
        q_adj = np.zeros((len(win), 144))
        c_adj = np.zeros((len(win), 144))
        d_adj = np.zeros((len(win), 144))
        per_day = []
        for k, i in enumerate(win):
            if k % 40 == 0:
                print(f"  [{pol}] {k}/{len(win)} ...", flush=True)
            r = q3.simulate_day(att, f3, att.price, i, s_max=args.s_max, policy=pol,
                                pv_interpolation=args.pv_interpolation)
            tot["plan"] += r["plan_cost"]
            tot["fee"] += r["fee"]
            tot["emg"] += r["emg_cost"]
            tot["emg_kwh"] += r["emg_kwh"]
            q_plan[k], q_adj[k] = r["q_plan"], r["q_adj"]
            c_adj[k], d_adj[k] = r["c_adj"], r["d_adj"]
            took = False
            per_day.append({"date": str(r["date"]), "plan_cost": r["plan_cost"], "fee": r["fee"],
                            "emg_kwh": r["emg_kwh"], "emg_cost": r["emg_cost"],
                            "total": r["total"],
                            "adjusted": [e["node"] for e in r["log"] if e["adjusted"]]})
            for e in r["log"]:
                if e["J_keep"] is None:
                    continue
                nd = tot["nodes"][e["node"]]
                nd["keep"] += e["J_keep"]
                nd["adj"] += e["J_adj"]
                nd["take"] += int(e["adjusted"])
                nd["dq"] += e["dq_kwh"]
                if e["adjusted"]:
                    took = True
                    tot["adj_nodes"] += 1
            tot["adj_days"] += int(took)
        tot["total"] = tot["fee"] + tot["emg"]
        tot["dq"] = float(np.abs(q_adj - q_plan)[-len(win):].sum())
        summary[pol] = tot
        store[pol] = dict(q_plan=q_plan, q_adj=q_adj, c_adj=c_adj, d_adj=d_adj)
        json_out["policies"][pol] = {
            "total": tot["total"], "plan_cost": tot["plan"], "fee": tot["fee"],
            "emg_cost": tot["emg"], "emg_kwh": tot["emg_kwh"],
            "adj_days": tot["adj_days"], "adj_nodes": tot["adj_nodes"], "dq_kwh": tot["dq"],
            "nodes": {n: {"take": tot["nodes"][n]["take"],
                          "J_keep": tot["nodes"][n]["keep"],
                          "J_adj": tot["nodes"][n]["adj"],
                          "gain": tot["nodes"][n]["keep"] - tot["nodes"][n]["adj"]}
                      for n in q3.NODE_NAME[1:]},
            "per_day": per_day,
        }

        emit(f"策略 {pol}")
        emit(f"  计划购电费 {tot['plan']:>15,.2f} 元")
        emit(f"  结算购电费（含调整） {tot['fee']:>15,.2f} 元")
        emit(f"  紧急购电费 {tot['emg']:>15,.2f} 元（{tot['emg_kwh']:>12,.2f} kWh）")
        emit(f"  合计 {tot['total']:>15,.2f} 元")
        emit(f"  发生调整的天数 {tot['adj_days']} / {len(win)}，调整次数 {tot['adj_nodes']}，"
             f"累计调整量 {tot['dq']:,.2f} kWh")
        for n in q3.NODE_NAME[1:]:
            nd = tot["nodes"][n]
            emit(f"    节点 {n:<6} 采用 {nd['take']:>3} 次 | 期望 J_keep {nd['keep']:>14,.2f} | "
                 f"J_adj {nd['adj']:>14,.2f} | 期望收益 {nd['keep']-nd['adj']:>13,.2f} 元")
        emit("")

    # ---- 节点累积实验：回答"是否需要其他时刻的预报"
    if args.node_sets:
        emit("节点累积实验（固定调整策略，逐步增加可用的预报时刻）")
        base = None
        for key in [k for k in args.node_sets.split(",") if k]:
            tot = 0.0
            emg = 0.0
            for i in win:
                r = q3.simulate_day(att, f3, att.price, i, s_max=args.s_max,
                                    policy="fixed", node_subset=NODE_SETS[key],
                                    pv_interpolation=args.pv_interpolation)
                tot += r["total"]
                emg += r["emg_kwh"]
            if base is None:
                base = tot
            json_out["node_sets"][key] = {"total": tot, "emg_kwh": emg,
                                          "gain": base - tot, "gain_pct": (base - tot) / base * 100}
            emit(f"  可用节点 {key:<8} 合计 {tot:>15,.2f} 元 | 紧急 {emg:>12,.2f} kWh | "
                 f"相对 0:00 降低 {base-tot:>12,.2f} 元（{(base-tot)/base*100:5.2f}%）")
        emit("")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    json_path = (root / "src" / "outputs" / "q3_summary.json"
                 if args.out is None else out.with_suffix(".json"))
    json_path.write_text(json.dumps(json_out, ensure_ascii=False, indent=1), encoding="utf-8")
    np.savez_compressed(root / "src" / "outputs" / "q3_arrays.npz",
                        **{f"{p}_{k}": v for p, d in store.items() for k, v in d.items()})
    print("done")


if __name__ == "__main__":
    main()
