"""问题三鲁棒性/敏感性分析：储能容量、功率、往返效率、初始储电量、紧急购电倍率、预报误差水平。

按“一次一个因素”方式扫描（口径 A、selective 策略、全年 334 天），结果写入
``src/outputs/q3_sens.json`` 缓存，便于分批运行；每次运行都会重新生成
``src/outputs/q3_sensitivity_report.txt``、``src/tex/q3_sensitivity.tex``
与插图 ``src/tex/figure/q3_sensitivity.pdf``。

用法：
    python src/py/q3_sensitivity.py --factor cap --levels 0.6,0.8,1.2,1.5
    python src/py/q3_sensitivity.py                      # 仅根据缓存重生成报告/表/图
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

import q2_model as q2
import q3_model as q3

FACTORS = {
    "cap": ("储能容量", lambda v: q3.Params().scaled_e(v), "{:.0%}"),
    "pow": ("储能功率", lambda v: q3.Params(c_max=q2.C_MAX_KWH * v), "{:.0%}"),
    "eta": ("往返效率", lambda v: q3.Params(eta=v), "{:.2f}"),
    "e0": ("初始储电量", lambda v: q3.Params(e0=v), "{:,.0f} kWh"),
    "emg": ("紧急购电倍率", lambda v: q3.Params(emg=v), "{:.0f} 倍"),
    "fcst": ("预报误差标定倍率", None, "{:.0%}"),
}
BASE_LEVEL = {"cap": 1.0, "pow": 1.0, "eta": q2.ETA_C, "e0": q2.E0_KWH,
              "emg": q2.EMG_MULTIPLIER, "fcst": 1.0}


def run_year(att, f3, params=None, scen_scale=1.0) -> dict:
    fee = emg = tot = emg_kwh = 0.0
    for i in att.window:
        r = q3.simulate_day(att, f3, att.price, i, policy="selective",
                            params=params or q3.DEFAULT_PARAMS, scen_scale=scen_scale)
        fee += r["fee"]
        emg += r["emg_cost"]
        tot += r["total"]
        emg_kwh += r["emg_kwh"]
    return {"fee": fee, "emg": emg, "total": tot, "emg_kwh": emg_kwh}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--factor", default=None)
    ap.add_argument("--levels", default="")
    args = ap.parse_args()

    root = q2.project_root()
    att = q2.Attachment(root)
    f3 = q3.PvForecast3(root)
    cache_path = root / "src" / "outputs" / "q3_sens.json"
    res: dict = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}

    if "base" not in res:
        print("[base] 计算中 ...", flush=True)
        res["base"] = run_year(att, f3)
        cache_path.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    if args.factor:
        fac = args.factor
        res.setdefault(fac, {})
        for s in [float(x) for x in args.levels.split(",") if x]:
            key = f"{s:g}"
            if key in res[fac]:
                continue
            print(f"[{fac}={key}] 计算中 ...", flush=True)
            if fac == "fcst":
                r = run_year(att, f3, scen_scale=s)
            else:
                r = run_year(att, f3, params=FACTORS[fac][1](s))
            res[fac][key] = r
            cache_path.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")

    base = res["base"]["total"]
    lines = ["问题三鲁棒性/敏感性分析（口径 A，selective 策略，全年 334 天）",
             f"基准：全参数取题面值，全年合计 {base:,.2f} 元（紧急购电费 {res['base']['emg']:,.2f} 元）",
             ""]
    tex = ["% 由 src/py/q3_sensitivity.py 自动生成，请勿手工修改",
           r"\begin{table}[H]", r"  \centering",
           r"  \caption{问题三关键参数的灵敏度（口径 A、择优调整策略、全年 334 天）}",
           r"  \label{tab:q3-sens}", r"  \small",
           r"  \begin{tabular}{llrrr}", r"    \toprule",
           r"    参数 & 水平 & 全年费用/元 & 紧急购电费/元 & 相对基准 \\",
           r"    \midrule"]
    for fac, (cn, _, fmt) in FACTORS.items():
        if fac not in res:
            continue
        base_lv = f"{BASE_LEVEL[fac]:g}"
        rows = {**{base_lv: res["base"]}, **res[fac]}
        keys = sorted(rows.keys(), key=float)
        for i, k in enumerate(keys):
            d = rows[k]
            rel = "--" if k == base_lv else f"{(d['total']-base)/base*100:+.2f}\\%"
            name = cn if i == 0 else ""
            tex.append(f"    {name} & {fmt.format(float(k))} & {d['total']:,.0f} & "
                       f"{d['emg']:,.0f} & {rel} \\\\")
        tex.append(r"    \addlinespace")
    tex += [r"    \bottomrule", r"  \end{tabular}", r"\end{table}"]
    tex.append(f"% 完整数据见 src/outputs/q3_sensitivity_report.txt（基准 {base:,.2f} 元）")

    for fac, (cn, _, fmt) in FACTORS.items():
        if fac not in res:
            continue
        base_lv = f"{BASE_LEVEL[fac]:g}"
        rows = {**{base_lv: res["base"]}, **res[fac]}
        lines.append(f"—— {cn} ——")
        lines.append(f"  {'水平':<14}{'全年合计/元':>16}{'相对基准':>12}{'紧急购电费/元':>16}")
        for k in sorted(rows.keys(), key=float):
            d = rows[k]
            rel = "（基准）" if k == base_lv else f"{(d['total']-base)/base*100:+.2f}%"
            lines.append(f"  {fmt.format(float(k)):<14}{d['total']:>16,.2f}{rel:>12}{d['emg']:>16,.2f}")
        lines.append("")

    out = root / "src" / "outputs" / "q3_sensitivity_report.txt"
    out.write_text("\n".join(lines), encoding="utf-8")
    (root / "src" / "tex" / "q3_sensitivity.tex").write_text("\n".join(tex), encoding="utf-8")
    print("\n".join(lines))
    print("done ->", out)


if __name__ == "__main__":
    main()
