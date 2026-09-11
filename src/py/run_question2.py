"""问题二完整实验：确定性基线阶梯 + 两阶段随机规划 + 安全余量分析。

运行（在仓库任意位置执行）：
    python src/py/run_question2.py            # 全年 334 天，约 4~6 分钟
    python src/py/run_question2.py --quick    # 冒烟测试，只跑前 12 天

输出：
    src/outputs/q2_report.txt        结果报告
    src/outputs/q2_margin_slots.npy  每个(日,时段)的安全余量样本，供绘图使用
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import numpy as np

import q2_model as q
import q2_stochastic as qs


# --------------------------------------------------------------------------- 轮次
KEYS = ("plan", "emg", "total", "emg_kwh", "emg_slots", "surplus",
        "curtail", "charge", "discharge", "cover")


def rollup(att: q.Attachment, kind: str, tau: float = 0.8, terminal: str = "cycle"):
    """全年逐日滚动。kind: point_nostor / quantile / lp(A) / lp_B / perfect / perfect_nostor"""
    e = q.E0_KWH
    agg = {k: 0.0 for k in KEYS}
    daily = {}
    for i in att.window:
        L, V = att.load_kwh[i], att.pv_kwh[i]
        net_act = L - V
        if kind == "perfect":
            plan = q.plan_lp(att.price, L, V, e, terminal)
        elif kind in ("lp", "lp_B"):
            lh, vh = q.forecast_day(att, i)
            plan = q.plan_lp(att.price, lh, vh, e, terminal)
        elif kind == "point_nostor":
            lh, vh = q.forecast_day(att, i)
            plan = {"g": np.maximum(0.0, lh - vh), "c": np.zeros(q.N), "d": np.zeros(q.N),
                    "w": np.zeros(q.N), "e": np.full(q.N + 1, e)}
        elif kind == "quantile":
            plan = {"g": q.quantile_plan(att, i, tau), "c": np.zeros(q.N), "d": np.zeros(q.N),
                    "w": np.zeros(q.N), "e": np.full(q.N + 1, e)}
        elif kind == "perfect_nostor":
            plan = {"g": np.maximum(0.0, net_act), "c": np.zeros(q.N), "d": np.zeros(q.N),
                    "w": np.zeros(q.N), "e": np.full(q.N + 1, e)}
        else:
            raise ValueError(kind)

        if kind == "lp_B":
            rt = qs.realtime_dispatch(att, plan["g"], L, V, e, float(plan["e"][-1]))
            committed = plan["g"] + rt["d"] - rt["c"]
            st = {"plan": float(np.dot(att.price, plan["g"])), "emg": rt["emg_cost"],
                  "emg_kwh": rt["emg_kwh"], "emg_slots": int((rt["emg"] > 1e-9).sum()),
                  "surplus": rt["dump_kwh"], "curtail": rt["dump_kwh"],
                  "charge": float(rt["c"].sum()), "discharge": float(rt["d"].sum()),
                  "cover": float((net_act <= committed + 1e-9).mean())}
            e = float(rt["e"][-1])
        else:
            st0 = q.settle(att.price, plan, net_act)
            st = {"plan": st0["cost_plan"], "emg": st0["cost_emg"], "emg_kwh": st0["emg_kwh"],
                  "emg_slots": st0["emg_slots"], "surplus": st0["surplus_kwh"],
                  "curtail": st0["plan_curtail_kwh"], "charge": float(plan["c"].sum()),
                  "discharge": float(plan["d"].sum()),
                  "cover": float((net_act <= (plan["g"] + plan["d"] - plan["c"]) + 1e-9).mean())}
            e = float(plan["e"][-1])
        st["total"] = st["plan"] + st["emg"]
        for k in KEYS:
            agg[k] += st[k]
        daily[i] = st
    agg["end_soc"] = e
    agg["cover"] /= max(1, len(att.window))
    return agg, daily


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--quick", action="store_true",
                    help="冒烟测试：限制随机规划部分的天数（确定性阶梯仍跑全年，因其很快）")
    ap.add_argument("--days", type=int, default=None, help="限制天数")
    ap.add_argument("--s-max", type=int, default=6, help="场景数上限")
    ap.add_argument("--skip-stochastic", action="store_true")
    ap.add_argument("--data-root", type=Path, default=None)
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()

    root = Path(args.data_root) if args.data_root else q.project_root()
    out_dir = Path(args.out_dir) if args.out_dir else root / "src" / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []

    def emit(s: str = "") -> None:
        lines.append(str(s))
        print(s, flush=True)

    att = q.Attachment(root)
    if args.quick:
        args.days = args.days or 12
    if args.days:
        keep = set(att.window[:args.days])
        att.window_limit = args.days
        att_window = [i for i in att.window if i in keep]
    else:
        att_window = att.window
    n_days = len(att_window)

    emit("问题二实验报告")
    emit(f"数据：附件1 电价 + 附件2 实际负荷/光伏；结果窗口 {att.dates[att_window[0]]} ~ "
         f"{att.dates[att_window[-1]]}，共 {n_days} 天")
    emit(f"时间口径：时间戳=时段起点，0:00+1 ≡ 0:00（详见 q2_model.py 模块说明）")

    # ---------------- 0) 自检：复现问题一
    emit("")
    emit("=" * 88)
    emit("0) 自检：用本模块 LP 重解问题一，应复现 result1.xlsx")
    pq1 = q.plan_lp(att.price, att.q1_load * q.DT_H, att.q1_pv * q.DT_H, q.E0_KWH, "cycle")
    emit(f"   购电费 {pq1['plan_cost']:.4f} 元（仓库 35126.8486，差 {pq1['plan_cost']-35126.8486:+.6f}）")
    emit(f"   购电量 {pq1['g'].sum():.4f} kWh（仓库 59482.6990）；"
         f"充电 {pq1['c'].sum():.4f}（20740.6661）；放电 {pq1['d'].sum():.4f}（16799.9396）；"
         f"弃光 {pq1['w'].sum():.4f}（0）")
    emit("   注：仓库版另有第二级目标 min Σ(c+d)，因此个别时段的最优顶点可能不同，"
         "但费用与充放电总量完全一致。")

    # ---------------- 1) 预测质量
    emit("")
    emit("=" * 88)
    emit("1) 因果预测质量（只用当日之前的历史）")
    emit(f"   {'方法':<26}{'负荷MAE/kW':>12}{'光伏MAE/kW':>12}{'净负荷MAE/(kWh/时段)':>22}")
    for name, kw in [("前一日同刻", dict(use_month=False, use_type=False, k_max=1)),
                     ("同类型日（周五六/其余）", dict(use_month=False, use_type=True)),
                     ("同月+同类型均值", dict(use_month=True, use_type=True)),
                     ("同月+同类型，λ=0.9", dict(use_month=True, use_type=True, lam=0.9))]:
        el, ev, en = [], [], []
        for i in att_window:
            lh, vh = q.forecast_day(att, i, **kw)
            el.append(np.abs(att.load_kw[i] - lh * 6))
            ev.append(np.abs(att.pv_kw[i] - vh * 6))
            en.append(np.abs((att.load_kwh[i] - att.pv_kwh[i]) - (lh - vh)))
        emit(f"   {name:<26}{np.concatenate(el).mean():>12.1f}{np.concatenate(ev).mean():>12.1f}"
             f"{np.concatenate(en).mean():>22.2f}")

    # ---------------- 2) 策略阶梯
    emit("")
    emit("=" * 88)
    emit("2) 全年策略对比")
    res = {}
    res["P0 点预测·无储能"], _ = rollup(att, "point_nostor")
    res["P1 τ=0.80分位·无储能"], _ = rollup(att, "quantile", tau=0.80)
    res["P2A 储能LP·严格执行"], daily_a = rollup(att, "lp")
    res["P2B 储能LP·日内再调度"], _ = rollup(att, "lp_B")
    res["P3 完美信息·储能"], _ = rollup(att, "perfect")
    res["P3' 完美预测·无储能"], _ = rollup(att, "perfect_nostor")
    emit(f"   {'策略':<24}{'计划购电费':>12}{'紧急购电费':>12}{'总费用':>12}"
         f"{'紧急电量kWh':>12}{'覆盖率':>8}")
    for k, v in res.items():
        emit(f"   {k:<24}{v['plan']:>12.0f}{v['emg']:>12.0f}{v['total']:>12.0f}"
             f"{v['emg_kwh']:>12.0f}{v['cover']:>8.3f}")
    d0 = res["P0 点预测·无储能"]["total"]
    for k in ("P1 τ=0.80分位·无储能", "P2A 储能LP·严格执行", "P2B 储能LP·日内再调度"):
        emit(f"   {k} 相对 P0：{res[k]['total']-d0:+,.0f} 元（{(res[k]['total']-d0)/d0*100:+.2f}%）")
    a, b, c, d = (res["P0 点预测·无储能"]["total"], res["P3' 完美预测·无储能"]["total"],
                  res["P3 完美信息·储能"]["total"], res["P2B 储能LP·日内再调度"]["total"])
    emit(f"   优化空间分解：P0 − P3 = {a-c:,.0f} = 预测误差 {a-b:,.0f}"
         f"（{100*(a-b)/(a-c):.1f}%）+ 储能调度 {b-c:,.0f}（{100*(b-c)/(a-c):.1f}%）")
    emit(f"   P2B 的调度遗憾（相对完美信息）= {d-c:,.0f} 元")

    # ---------------- 3) 临界分位
    emit("")
    emit("=" * 88)
    emit("3) 临界分位验证（无储能；计划购电量 = 净需求的因果 τ 分位数）")
    emit(f"   {'τ':>6}{'计划购电费':>13}{'紧急购电费':>13}{'总费用':>13}{'覆盖率':>9}")
    sweep = []
    for tau in [0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]:
        a2, _ = rollup(att, "quantile", tau=tau)
        sweep.append((tau, a2["plan"], a2["emg"], a2["total"], a2["cover"]))
    best = min(sweep, key=lambda x: x[3])
    for tau, pc, ec, tc, cv in sweep:
        emit(f"   {tau:>6.2f}{pc:>13.0f}{ec:>13.0f}{tc:>13.0f}{cv:>9.3f}"
             + ("   ← 最小" if tau == best[0] else ""))
    emit(f"   理论值 0.80（由 5 倍罚价推出），建议作为基线与正确性校验")

    # ---------------- 4) 两阶段随机规划
    margin_slots = []
    if not args.skip_stochastic:
        emit("")
        emit("=" * 88)
        emit(f"4) 两阶段随机规划（整日残差场景 + CVaR，场景数上限 {args.s_max}）")
        cache = qs.precompute_forecasts(att)
        betas = [0.0, 0.25, 0.5]
        rec = {b: {k: 0.0 for k in ("plan", "emg", "total", "emg_kwh", "exp")} for b in betas}
        det_rec = {k: 0.0 for k in ("plan", "emg", "total", "emg_kwh")}
        eev = 0.0
        for cnt, i in enumerate(att_window):
            if cnt % 25 == 0:
                print(f"   ... {att.dates[i]} ({cnt+1}/{n_days})", flush=True)
            L, V = att.load_kwh[i], att.pv_kwh[i]
            fl, fv = cache[i]
            scen, w = qs.make_scenarios(att, i, cache, s_max=args.s_max)
            det = q.plan_lp(att.price, fl, fv, q.E0_KWH, "cycle")
            rt_det = qs.realtime_dispatch(att, det["g"], L, V, q.E0_KWH, float(det["e"][-1]))
            det_rec["plan"] += float((att.price * det["g"]).sum())
            det_rec["emg"] += rt_det["emg_cost"]
            det_rec["emg_kwh"] += rt_det["emg_kwh"]
            e_eev = 0.0
            for k, (Lk, Vk) in enumerate(scen):
                r = qs.realtime_dispatch(att, det["g"], Lk, Vk, q.E0_KWH, float(det["e"][-1]))
                e_eev += w[k] * (float((att.price * det["g"]).sum()) + r["emg_cost"])
            eev += e_eev
            sto0 = None
            for beta in betas:
                st = qs.stochastic_plan(att, (fl, fv), scen, w, q.E0_KWH, beta=beta)
                rt = qs.realtime_dispatch(att, st["g"], L, V, q.E0_KWH, float(st["e1"][-1]))
                rec[beta]["plan"] += float((att.price * st["g"]).sum())
                rec[beta]["emg"] += rt["emg_cost"]
                rec[beta]["emg_kwh"] += rt["emg_kwh"]
                rec[beta]["exp"] += st["exp_cost"]
                if beta == 0.0:
                    sto0 = st
            sig = np.std(np.array([Lk - Vk for Lk, Vk in scen]), axis=0)
            mg = sto0["g"] - det["g"]
            for t in range(q.N):
                margin_slots.append((float(sig[t]), float(mg[t]), float(att.price[t])))
        det_rec["total"] = det_rec["plan"] + det_rec["emg"]
        for b in betas:
            rec[b]["total"] = rec[b]["plan"] + rec[b]["emg"]
        emit(f"   {'策略':<22}{'计划购电费':>12}{'紧急购电费':>12}{'总费用':>12}{'紧急电量kWh':>13}")
        emit(f"   {'确定性（点预测）':<22}{det_rec['plan']:>12.0f}{det_rec['emg']:>12.0f}"
             f"{det_rec['total']:>12.0f}{det_rec['emg_kwh']:>13.0f}")
        for b in betas:
            r = rec[b]
            emit(f"   {'两阶段随机 β=' + str(b):<22}{r['plan']:>12.0f}{r['emg']:>12.0f}"
                 f"{r['total']:>12.0f}{r['emg_kwh']:>13.0f}")
        for b in betas:
            r = rec[b]
            emit(f"   β={b} 相对确定性：{r['total']-det_rec['total']:+,.0f} 元"
                 f"（{(r['total']-det_rec['total'])/det_rec['total']*100:+.2f}%），"
                 f"多买计划电量 {r['plan']-det_rec['plan']:+,.0f} 元，"
                 f"紧急电量 {r['emg_kwh']-det_rec['emg_kwh']:+,.0f} kWh")
        rp = rec[0.0]["exp"]
        emit(f"   同场景测度下的期望费用：随机最优 RP = {rp:,.0f} 元，"
             f"确定性方案 EEV = {eev:,.0f} 元")
        emit(f"   VSS = EEV − RP = {eev-rp:,.0f} 元（{100*(eev-rp)/rp:.2f}% 的 RP）")

        emit("")
        emit("   安全余量分析（随机计划 − 确定性计划）")
        ms = np.array(margin_slots)
        emit(f"   样本 {len(ms):,} 个(日,时段)：多买 {int((ms[:,1]>1e-9).sum())}，"
             f"少买 {int((ms[:,1]<-1e-9).sum())}，不变 {int((np.abs(ms[:,1])<=1e-9).sum())}")
        emit(f"   corr(场景波动σ, 安全余量) = {np.corrcoef(ms[:,0], ms[:,1])[0,1]:+.3f}")
        emit("   按场景波动四分位：")
        for x, y in zip(np.quantile(ms[:, 0], [0, .25, .5, .75]),
                        np.quantile(ms[:, 0], [.25, .5, .75, 1.0])):
            sel = (ms[:, 0] >= x) & (ms[:, 0] <= y)
            if sel.sum():
                emit(f"     σ∈[{x:7.1f},{y:7.1f}] → 平均余量 {ms[sel,1].mean():+7.1f} kWh/时段")
        emit("   按电价四分位：")
        for x, y in zip(np.quantile(ms[:, 2], [0, .25, .5, .75]),
                        np.quantile(ms[:, 2], [.25, .5, .75, 1.0])):
            sel = (ms[:, 2] >= x) & (ms[:, 2] <= y)
            if sel.sum():
                emit(f"     p∈[{x:.4f},{y:.4f}] → 平均余量 {ms[sel,1].mean():+7.1f} kWh/时段")
        np.save(out_dir / "q2_margin_slots.npy", ms)

    # ---------------- 5) 指定日期
    emit("")
    emit("=" * 88)
    emit("5) 题目指定日期明细（P2A 严格执行口径）")
    named = {dt.date(2025, 3, 20): "3/20", dt.date(2025, 6, 21): "6/21",
             dt.date(2025, 9, 23): "9/23", dt.date(2025, 12, 21): "12/21"}
    wk = "一二三四五六日"
    emit(f"   {'日期':<7}{'周':<3}{'实际净负荷':>11}{'计划购电费':>12}{'紧急购电费':>12}"
         f"{'紧急电量kWh':>12}{'紧急次数':>8}")
    for d, nm in named.items():
        i = att.day_index(d)
        if i not in daily_a:
            continue
        st = daily_a[i]
        emit(f"   {nm:<7}{wk[d.weekday()]:<3}{(att.load_kwh[i]-att.pv_kwh[i]).sum():>11.0f}"
             f"{st['plan']:>12.0f}{st['emg']:>12.0f}{st['emg_kwh']:>12.0f}{st['emg_slots']:>8}")

    # ---------------- 6) 终端诊断
    emit("")
    emit("=" * 88)
    emit("6) 终端条件诊断")
    cyc, _ = rollup(att, "lp", terminal="cycle")
    fr, _ = rollup(att, "lp", terminal="free")
    emit(f"   e144 = e0（日周期）：总费用 {cyc['total']:,.0f} 元，年末储电量 {cyc['end_soc']:.1f} kWh")
    emit(f"   e144 自由           ：总费用 {fr['total']:,.0f} 元，年末储电量 {fr['end_soc']:.1f} kWh")
    emit(f"   自由终端反而贵 {fr['total']-cyc['total']:,.0f} 元：无终端约束时每日计划都把储电量"
         f"压到下限、全年在低位运行，因此必须用日周期约束或跨日终端价值函数处理。")

    (out_dir / "q2_report.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已写入 {out_dir / 'q2_report.txt'}")


if __name__ == "__main__":
    sys.exit(main())
