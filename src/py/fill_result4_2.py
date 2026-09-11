"""把问题四 4-2（波动电价下重做问题二）结果回填到官方模板 result4-2.xlsx。

模板与 result2.xlsx 完全同构（计划购电量 / 充放电量 / 紧急购电量 三张表），
因此直接复用 ``fill_result2.fill`` 与 ``fill_result2.verify``，只是把电价换成附件4。

价格信息口径（默认 oracle）
---------------------------
``oracle``   ：0:00 即知当天全部时段电价（与问题一~三、4-3 一致，正式提交口径）；
``prev_day`` ：只用前一日实际电价作预测（因果对照）；
``profile``  ：用附件4 逐时段均值作预测（因果对照）。

用法：
    python src/py/fill_result4_2.py                    # 已知当天电价（默认）
    python src/py/fill_result4_2.py --price-mode prev_day
    python src/py/fill_result4_2.py --limit 20         # 只填前 20 天，检查格式
输出：src/附件5/result4-2.xlsx
"""
from __future__ import annotations

import argparse
from pathlib import Path

import q2_model as q2
import q4_model as q4
from fill_result2 import fill, verify
from run_q4_2 import simulate_day


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--price-mode", choices=list(q4.PRICE_MODES), default="oracle")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--data-root", type=Path, default=None)
    ap.add_argument("--template", type=Path, default=None)
    ap.add_argument("--output", type=Path, default=None)
    args = ap.parse_args()

    root = Path(args.data_root) if args.data_root else q2.project_root()
    template = Path(args.template) if args.template else \
        root / "problems" / "C题" / "附件" / "附件5" / "result4-2.xlsx"
    output = Path(args.output) if args.output else root / "src" / "附件5" / "result4-2.xlsx"

    att = q2.Attachment(root)
    p4 = q4.Prices4(root, att)
    window = att.window[:args.limit] if args.limit else att.window
    days = [simulate_day(att, p4, i, args.price_mode) for i in window]

    fill(template, output, days, "A")
    print(f"已写入 {output}（价格口径 {q4.MODE_CN[args.price_mode]}，{len(days)} 天）")
    verify(output, days)


if __name__ == "__main__":
    main()
