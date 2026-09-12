"""把问题三结果回填到官方模板 result3.xlsx。

用法（在仓库根目录执行）：
    python src/py/fill_result3.py                      # 默认策略 selective（择优调整，费用最低）
    python src/py/fill_result3.py --policy none        # 只提交 0:00 计划、不调整
    python src/py/fill_result3.py --policy fixed       # 每个预报节点都调整
    python src/py/fill_result3.py --limit 20           # 只填前 20 天，检查格式

输出：src/附件5/result3.xlsx（模板读自 problems/C题/附件/附件5/result3.xlsx）

四个工作表
----------
1) 计划购电量：334 天（2025-02-01 ~ 12-31）× 144 个 10 分钟时段的**0:00 计划**购电量（kWh）
2) 调整购电量：同一张矩阵，填**最终**（经 6:00/12:00/18:00 滚动调整后）的购电量
3) 充放电量：每天 6 个四小时时段的**最终**充/放电量，以及 0:00 与 24:00 的储电量
4) 紧急购电量：日期写在当天首行；同一段连续的紧急购电时段合并为一行

两张矩阵表在 144 个时段列后还有 ``全天购电量`` 与 ``全天购电费`` 两列，本脚本一并填写：
    - 全天购电量 = 该日 144 段购电量之和；
    - 计划购电量表的全天购电费 = Σ p_t·q_plan,t；
    - 调整购电量表的全天购电费 = 结算购电费（含向下 50%、向上 150% 的调整费）。
  这也是与 ``q3_report.txt`` 中"计划购电费/结算购电费（含调整）"逐日对账的桥梁。

口径
----
- 时间戳 = 时段起点，0:00+1 ≡ 0:00；模板列标签 "0:10-0:20" 对应时段 j=1、"0:00-0:10+1"
  对应 j=0，脚本按表头文本自动解析并校验（不硬编码）；
- 与问题二口径 A 一致：最终计划严格执行，实际净负荷超出"调整购电量 + 放电 - 充电"的部分
  按 5 倍价紧急购电；储能日周期 e_144 = e_0 = 6000 kWh；
- 所有结果直接复用 ``q3_model.simulate_day`` 重算（确定性、可复现），不依赖中间缓存。
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
from pathlib import Path

import numpy as np
from openpyxl import load_workbook

import q2_model as q2
import q3_model as q3
from fill_result2 import fmt_clock, label_to_period, merge_intervals, style_from

BLOCKS = [(0, 240), (240, 480), (480, 720), (720, 960), (960, 1200), (1200, 1440)]
DEC = 4


# --------------------------------------------------------------------------- 逐日结果
def compute_days(att: q2.Attachment, f3: q3.PvForecast3, policy: str,
                 s_max: int = 6, limit: int | None = None) -> list[dict]:
    window = att.window[:limit] if limit else att.window
    days = []
    for i in window:
        r = q3.simulate_day(att, f3, att.price, i, s_max=s_max, policy=policy)
        committed = r["q_adj"] + r["d_adj"] - r["c_adj"]
        shortfall = np.maximum(0.0, (att.load_kwh[i] - att.pv_kwh[i]) - committed)
        assert abs(shortfall.sum() - r["emg_kwh"]) < 1e-6, "紧急购电量与仿真不一致"
        days.append({
            "date": att.dates[i], "index": i,
            "q_plan": r["q_plan"], "q_adj": r["q_adj"],
            "charge": r["c_adj"], "discharge": r["d_adj"],
            "soc_start": float(r["e_adj"][0]), "soc_end": float(r["e_adj"][-1]),
            "shortfall": shortfall,
            "plan_cost": r["plan_cost"], "fee": r["fee"],
            "emg_kwh": r["emg_kwh"], "emg_cost": r["emg_cost"], "total": r["total"],
        })
    return days


# --------------------------------------------------------------------------- 写入
def fill_matrix(ws, days: list[dict], key: str, date_row: dict, col_period: dict,
                summary: dict[int, np.ndarray]) -> None:
    """填写一张 334×144 的购电量矩阵（含全天购电量/全天购电费两列）。"""
    for d in days:
        row = date_row[d["date"]]
        q = d[key]
        for c, j in col_period.items():
            cell = ws.cell(row, c)
            cell.value = round(float(q[j]), DEC)
            cell.number_format = "0.0000"
        ws.cell(row, 146).value = round(float(q.sum()), DEC)          # 全天购电量
        ws.cell(row, 147).value = round(float(summary[d["date"]]), DEC)  # 全天购电费
        ws.cell(row, 146).number_format = "0.0000"
        ws.cell(row, 147).number_format = "0.0000"


def fill(template: Path, output: Path, days: list[dict]) -> None:
    wb = load_workbook(template)
    need = ("计划购电量", "调整购电量", "充放电量", "紧急购电量")
    for name in need:
        if name not in wb.sheetnames:
            raise ValueError(f"模板缺少工作表 {name}：{wb.sheetnames}")

    def date_rows(ws) -> dict:
        out = {}
        for r in range(2, ws.max_row + 1):
            v = ws.cell(r, 1).value
            if isinstance(v, dt.datetime):
                out[v.date()] = r
            elif isinstance(v, dt.date):
                out[v] = r
        return out

    def col_periods(ws) -> dict:
        cp = {c: label_to_period(ws.cell(1, c).value) for c in range(2, 146)}
        if sorted(cp.values()) != list(range(q2.N)):
            raise ValueError("模板列标签与时段序号不是一一对应")
        if ws.cell(1, 146).value != "全天购电量" or ws.cell(1, 147).value != "全天购电费":
            raise ValueError(f"模板缺少全天汇总列：{ws.cell(1,146).value!r}, {ws.cell(1,147).value!r}")
        return cp

    # ---------------- 1) 计划购电量 / 2) 调整购电量
    ws = wb["计划购电量"]
    cp = col_periods(ws)
    rows = date_rows(ws)
    plan_fee = {d["date"]: d["plan_cost"] for d in days}
    fill_matrix(ws, days, "q_plan", rows, cp, plan_fee)

    ws = wb["调整购电量"]
    rows_adj = date_rows(ws)
    adj_fee = {d["date"]: d["fee"] for d in days}
    fill_matrix(ws, days, "q_adj", rows_adj, cp, adj_fee)

    # ---------------- 3) 充放电量
    ws = wb["充放电量"]
    block_labels = [ws.cell(r, 2).value for r in range(2, 2 + len(BLOCKS))]
    if any(v is None for v in block_labels):
        raise ValueError("模板充放电量工作表缺少四小时时段标签")
    r = 2
    for d in days:
        for k, (a, b) in enumerate(BLOCKS):
            row = r + k
            if row > ws.max_row:
                style_from(ws, 2, row, range(1, 7))
            ws.cell(row, 1).value = d["date"] if k == 0 else None
            ws.cell(row, 2).value = block_labels[k]
            ws.cell(row, 3).value = round(float(d["charge"][a // 10:b // 10].sum()), DEC)
            ws.cell(row, 4).value = round(float(d["discharge"][a // 10:b // 10].sum()), DEC)
            ws.cell(row, 3).number_format = "0.0000"
            ws.cell(row, 4).number_format = "0.0000"
        ws.cell(r, 5).value = dt.time(0, 0)
        ws.cell(r, 6).value = round(float(d["soc_start"]), DEC)
        ws.cell(r + 1, 5).value = "24:00"
        ws.cell(r + 1, 6).value = round(float(d["soc_end"]), DEC)
        ws.cell(r, 6).number_format = "0.0000"
        ws.cell(r + 1, 6).number_format = "0.0000"
        r += len(BLOCKS)
    for row in range(r, ws.max_row + 1):       # 清掉模板里的占位行
        for c in range(1, 7):
            ws.cell(row, c).value = None

    # ---------------- 4) 紧急购电量
    ws = wb["紧急购电量"]
    r = 2
    for d in days:
        items = merge_intervals(d["shortfall"])
        row = r
        if row > ws.max_row:
            style_from(ws, 2, row, range(1, 4))
        ws.cell(row, 1).value = d["date"]
        if items:
            t0, t1, energy = items[0]
            ws.cell(row, 2).value = f"{fmt_clock(10 * t0)}-{fmt_clock(10 * t1)}"
            ws.cell(row, 3).value = round(energy, DEC)
            ws.cell(row, 3).number_format = "0.0000"
        for t0, t1, energy in items[1:]:
            row += 1
            if row > ws.max_row:
                style_from(ws, 3, row, range(1, 4))
            ws.cell(row, 1).value = None
            ws.cell(row, 2).value = f"{fmt_clock(10 * t0)}-{fmt_clock(10 * t1)}"
            ws.cell(row, 3).value = round(energy, DEC)
            ws.cell(row, 3).number_format = "0.0000"
        r = row + 1
    for row in range(r, ws.max_row + 1):       # 清掉模板里的占位行
        for c in range(1, 4):
            ws.cell(row, c).value = None

    output.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output)


# --------------------------------------------------------------------------- 校验
def _split_ref(ref: str) -> tuple[str, int]:
    """单元格引用 -> (列字母, 行号)，例如 "AA12" -> ("AA", 12)。"""
    col = "".join(ch for ch in ref if ch.isalpha())
    row = int("".join(ch for ch in ref if ch.isdigit()))
    return col, row


def verify(output: Path, days: list[dict], policy: str) -> None:
    grid = q2.read_workbook(output)

    def is_num(v) -> bool:
        try:
            float(v)
            return True
        except (TypeError, ValueError):
            return False

    def cell_sum(sheet: dict, cols: set[str] | None = None, min_row: int = 2) -> tuple[float, int]:
        """求和并计数数值单元；cols 给定时只统计这些列。"""
        total, n = 0.0, 0
        for ref, v in sheet.items():
            col, row = _split_ref(ref)
            if row < min_row or not is_num(v):
                continue
            if cols is not None and col not in cols:
                continue
            total += float(v)
            n += 1
        return total, n

    from openpyxl.utils import get_column_letter
    period_cols = {get_column_letter(c) for c in range(2, 146)}
    for name, key in (("计划购电量", "q_plan"), ("调整购电量", "q_adj")):
        total, n = cell_sum(grid[name], cols=period_cols)
        ref = sum(float(d[key].sum()) for d in days)
        print(f"  工作表 {name}：时段单元 {n} 个（应 = {len(days) * 144}），"
              f"合计 {total:,.1f} kWh（内部 {ref:,.1f}）")
        day_qty, _ = cell_sum(grid[name], cols={"EP"})
        day_fee, _ = cell_sum(grid[name], cols={"EQ"})
        print(f"    全天购电量列合计 {day_qty:,.1f} kWh，全天购电费列合计 {day_fee:,.2f} 元")

    c_sheet = grid["充放电量"]
    ch, _ = cell_sum(c_sheet, {"C"})
    dis, _ = cell_sum(c_sheet, {"D"})
    print(f"  工作表 充放电量：充电 {ch:,.1f} / 放电 {dis:,.1f} kWh（内部 "
          f"{sum(d['charge'].sum() for d in days):,.1f} / {sum(d['discharge'].sum() for d in days):,.1f}）")

    emg, rows = cell_sum(grid["紧急购电量"], {"C"})
    print(f"  工作表 紧急购电量：行数 {rows}，合计 {emg:,.1f} kWh"
          f"（内部 {sum(d['emg_kwh'] for d in days):,.1f}）")

    print(f"  总计 {len(days)} 天：计划购电费 {sum(d['plan_cost'] for d in days):,.2f} 元，"
          f"结算购电费（含调整） {sum(d['fee'] for d in days):,.2f} 元，"
          f"紧急购电费 {sum(d['emg_cost'] for d in days):,.2f} 元，"
          f"合计 {sum(d['total'] for d in days):,.2f} 元")
    print(f"  策略 = {policy}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--policy", choices=["none", "fixed", "selective"], default="selective")
    ap.add_argument("--s-max", type=int, default=6)
    ap.add_argument("--limit", type=int, default=None, help="只填前 N 天（检查格式用）")
    ap.add_argument("--from-q4opt", default=None,
                    help="从 src/outputs/q4_3_opt.json 的某个 run 读取逐日结果回填")
    ap.add_argument("--exec-mode", default="A", help="A / B / B_causal（直接计算时生效）")
    ap.add_argument("--plan-hedge", type=float, default=None, help="安全分位对冲（直接计算时生效）")
    ap.add_argument("--data-root", type=Path, default=None)
    ap.add_argument("--template", type=Path, default=None)
    ap.add_argument("--output", type=Path, default=None)
    args = ap.parse_args()

    root = Path(args.data_root) if args.data_root else q2.project_root()
    template = Path(args.template) if args.template else \
        root / "problems" / "C题" / "附件" / "附件5" / "result3.xlsx"
    output = Path(args.output) if args.output else root / "src" / "附件5" / "result3.xlsx"

    att = q2.Attachment(root)
    f3 = q3.PvForecast3(root)
    if args.from_q4opt:
        import datetime as _dt
        import json as _json
        opt = _json.loads((outs := root / "src" / "outputs" / "q4_3_opt.json").read_text(
            encoding="utf-8"))
        run = opt["runs"][args.from_q4opt]
        days = [{"date": _dt.date.fromisoformat(d["date"]), "index": d["index"],
                 "q_plan": np.asarray(d["q_plan"]), "q_adj": np.asarray(d["q_adj"]),
                 "charge": np.asarray(d["charge"]), "discharge": np.asarray(d["discharge"]),
                 "soc_start": float(d["soc_start"]), "soc_end": float(d["soc_end"]),
                 "shortfall": np.asarray(d["shortfall"]), "plan_cost": float(d["plan_cost"]),
                 "fee": float(d["fee"]), "emg_kwh": float(d["emg_kwh"]),
                 "emg_cost": float(d["emg_cost"]), "total": float(d["total"])}
                for d in run["detail"]]
    else:
        days = compute_days(att, f3, args.policy, args.s_max, args.limit)
    fill(template, output, days)
    print(f"已写入 {output}（策略 {args.policy}，{len(days)} 天）")
    verify(output, days, args.policy)


if __name__ == "__main__":
    main()
