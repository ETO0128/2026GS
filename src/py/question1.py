"""Solve Question 1 of the 2026 CUMCM problem C.

The model is a deterministic linear program with 10-minute resolution.  Power
data from attachment 1 are converted from kW to kWh before optimization.  The
result is written into a copy of the official ``result1.xlsx`` template.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path
from typing import Iterable

import numpy as np
from openpyxl import load_workbook

from microgrid_core import (
    DispatchInput,
    DispatchSolution,
    StorageParameters,
    solve_dispatch,
    validate_dispatch,
)


SLOTS_PER_DAY = 144
SLOT_MINUTES = 10
DELTA_HOURS = SLOT_MINUTES / 60

CAPACITY_KWH = 12_000.0
MIN_SOC_KWH = 1_200.0
MAX_SOC_KWH = 10_800.0
INITIAL_SOC_KWH = 6_000.0
MAX_POWER_KW = 5_000.0
MAX_SLOT_ENERGY_KWH = MAX_POWER_KW * DELTA_HOURS
CHARGE_EFFICIENCY = 0.90
DISCHARGE_EFFICIENCY = 0.90

PURCHASE_SHEET = "计划购电量"
STORAGE_SHEET = "充放电量"

SPECIFIED_START_MINUTES = (600, 720, 840, 960, 1080, 1200)
FOUR_HOUR_GROUPS = tuple((start, start + 240) for start in range(0, 1440, 240))


@dataclass(frozen=True)
class Question1Data:
    """Chronological inputs for 00:00--24:00."""

    minute_of_day: np.ndarray
    price_yuan_per_kwh: np.ndarray
    load_kw: np.ndarray
    pv_kw: np.ndarray

    @property
    def load_kwh(self) -> np.ndarray:
        return self.load_kw * DELTA_HOURS

    @property
    def pv_kwh(self) -> np.ndarray:
        return self.pv_kw * DELTA_HOURS


@dataclass(frozen=True)
class ScheduleSolution:
    """Optimal bus-side energy flows and internal battery state."""

    grid_kwh: np.ndarray
    charge_kwh: np.ndarray
    discharge_kwh: np.ndarray
    curtailment_kwh: np.ndarray
    soc_kwh: np.ndarray
    total_cost_yuan: float


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _normalize_header(value: object) -> str:
    return "".join(str(value).split())


def _parse_clock(value: object) -> int:
    """Return absolute minutes; ``0:00+1`` is returned as 1440."""

    if isinstance(value, datetime):
        value = value.time()
    if isinstance(value, time):
        return value.hour * 60 + value.minute
    if isinstance(value, (int, float)):
        # Excel stores times as fractions of one day.
        return int(round(float(value) * 24 * 60))

    text = str(value).strip()
    day_offset = 1440 if text.endswith("+1") else 0
    if day_offset:
        text = text[:-2]
    hour_text, minute_text = text.split(":", maxsplit=1)
    hour = int(hour_text)
    minute = int(minute_text)
    if hour == 24:
        return 1440 + minute
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid time value: {value!r}")
    return day_offset + hour * 60 + minute


def _format_clock(minute: int) -> str:
    day, minute_of_day = divmod(minute, 1440)
    hour, minute_part = divmod(minute_of_day, 60)
    suffix = f"+{day}" if day else ""
    return f"{hour}:{minute_part:02d}{suffix}"


def _format_interval(start_minute: int) -> str:
    return f"{_format_clock(start_minute)}-{_format_clock(start_minute + SLOT_MINUTES)}"


def _column_by_header(headers: Iterable[object], expected: str) -> int:
    normalized = [_normalize_header(value) for value in headers]
    try:
        return normalized.index(_normalize_header(expected)) + 1
    except ValueError as exc:
        raise ValueError(f"Missing column {expected!r}; found {normalized}") from exc


def load_question1_data(path: Path) -> Question1Data:
    """Load attachment 1 and rotate ``0:00+1`` to the start of the day.

    The official input and result template list timestamps from 00:10 through
    00:00+1.  For the state equation, the row marked 00:00+1 is treated as the
    periodic 00:00--00:10 slot and rotated to the beginning.  Results are later
    mapped back to the untouched template order.
    """

    workbook = load_workbook(path, data_only=True, read_only=True)
    sheet = workbook.active
    headers = [cell.value for cell in sheet[1]]
    time_col = _column_by_header(headers, "时间")
    price_col = _column_by_header(headers, "电价")
    load_col = _column_by_header(headers, "小区负载")
    pv_col = _column_by_header(headers, "光伏发电预测功率")

    records: list[tuple[int, float, float, float]] = []
    for row in range(2, sheet.max_row + 1):
        values = [
            sheet.cell(row, time_col).value,
            sheet.cell(row, price_col).value,
            sheet.cell(row, load_col).value,
            sheet.cell(row, pv_col).value,
        ]
        if all(value is None for value in values):
            continue
        if any(value is None for value in values):
            raise ValueError(f"Attachment 1 has an incomplete record on row {row}")
        absolute_minute = _parse_clock(values[0])
        records.append(
            (
                absolute_minute % 1440,
                float(values[1]),
                float(values[2]),
                float(values[3]),
            )
        )

    if len(records) != SLOTS_PER_DAY:
        raise ValueError(f"Expected {SLOTS_PER_DAY} records, found {len(records)}")

    records.sort(key=lambda item: item[0])
    minute_of_day = np.asarray([item[0] for item in records], dtype=int)
    expected_minutes = np.arange(0, 1440, SLOT_MINUTES, dtype=int)
    if not np.array_equal(minute_of_day, expected_minutes):
        raise ValueError("Attachment 1 must contain every 10-minute timestamp exactly once")

    price = np.asarray([item[1] for item in records], dtype=float)
    load = np.asarray([item[2] for item in records], dtype=float)
    pv = np.asarray([item[3] for item in records], dtype=float)
    if np.any(price < 0) or np.any(load < 0) or np.any(pv < 0):
        raise ValueError("Price, load and PV values must be nonnegative")

    return Question1Data(minute_of_day, price, load, pv)


def solve_question1(data: Question1Data) -> ScheduleSolution:
    """Solve the deterministic daily scheduling LP.

    ``charge_kwh`` and ``discharge_kwh`` are measured at the AC bus.  Therefore
    the battery transition is

        soc[t+1] = soc[t] + eta_c * charge[t] - discharge[t] / eta_d.

    A second LP minimizes battery throughput while retaining the minimum
    purchase cost.  This lexicographic tie-break removes degenerate simultaneous
    charging and discharging without changing the economic objective.
    """

    if len(data.minute_of_day) != SLOTS_PER_DAY:
        raise ValueError(f"Expected {SLOTS_PER_DAY} time slots")
    shared_solution = solve_dispatch(
        DispatchInput(
            price_yuan_per_kwh=data.price_yuan_per_kwh,
            load_kwh=data.load_kwh,
            pv_kwh=data.pv_kwh,
        ),
        StorageParameters(),
        initial_soc_kwh=INITIAL_SOC_KWH,
        terminal_soc_min_kwh=INITIAL_SOC_KWH,
        terminal_soc_max_kwh=INITIAL_SOC_KWH,
    )
    solution = ScheduleSolution(
        grid_kwh=shared_solution.grid_kwh,
        charge_kwh=shared_solution.charge_kwh,
        discharge_kwh=shared_solution.discharge_kwh,
        curtailment_kwh=shared_solution.curtailment_kwh,
        soc_kwh=shared_solution.soc_kwh,
        total_cost_yuan=shared_solution.total_cost_yuan,
    )
    validate_solution(data, solution)
    return solution


def validate_solution(
    data: Question1Data,
    solution: ScheduleSolution,
    tolerance: float = 1e-5,
) -> None:
    """Raise an error if an optimization result violates a physical constraint."""

    validate_dispatch(
        DispatchInput(
            price_yuan_per_kwh=data.price_yuan_per_kwh,
            load_kwh=data.load_kwh,
            pv_kwh=data.pv_kwh,
        ),
        StorageParameters(),
        DispatchSolution(
            grid_kwh=solution.grid_kwh,
            charge_kwh=solution.charge_kwh,
            discharge_kwh=solution.discharge_kwh,
            curtailment_kwh=solution.curtailment_kwh,
            soc_kwh=solution.soc_kwh,
            total_cost_yuan=solution.total_cost_yuan,
        ),
        initial_soc_kwh=INITIAL_SOC_KWH,
        terminal_soc_min_kwh=INITIAL_SOC_KWH,
        terminal_soc_max_kwh=INITIAL_SOC_KWH,
        tolerance=tolerance,
    )


def _value_by_start_minute(values: np.ndarray) -> dict[int, float]:
    return {minute: float(values[minute // SLOT_MINUTES]) for minute in range(0, 1440, SLOT_MINUTES)}


def write_result_workbook(
    template_path: Path,
    output_path: Path,
    solution: ScheduleSolution,
) -> None:
    """Fill a copy of the official ``result1.xlsx`` template."""

    workbook = load_workbook(template_path)
    if PURCHASE_SHEET not in workbook.sheetnames or STORAGE_SHEET not in workbook.sheetnames:
        raise ValueError(f"Unexpected result template sheets: {workbook.sheetnames}")

    purchase_sheet = workbook[PURCHASE_SHEET]
    purchase_by_minute = _value_by_start_minute(solution.grid_kwh)
    expected_labels = {
        _format_interval(minute): minute % 1440
        for minute in range(SLOT_MINUTES, 1440 + SLOT_MINUTES, SLOT_MINUTES)
    }
    if purchase_sheet.max_row - 1 != SLOTS_PER_DAY:
        raise ValueError("The purchase sheet must contain 144 output rows")

    seen_labels: set[str] = set()
    for row in range(2, purchase_sheet.max_row + 1):
        label = str(purchase_sheet.cell(row, 1).value).strip()
        if label not in expected_labels:
            raise ValueError(f"Unexpected time interval in result template: {label!r}")
        seen_labels.add(label)
        minute = expected_labels[label]
        cell = purchase_sheet.cell(row, 2)
        cell.value = purchase_by_minute[minute]
        cell.number_format = "0.0000"
    if len(seen_labels) != SLOTS_PER_DAY:
        raise ValueError("The purchase sheet has duplicate or missing interval labels")

    storage_sheet = workbook[STORAGE_SHEET]
    for row, (start, end) in enumerate(FOUR_HOUR_GROUPS, start=2):
        mask = (np.arange(0, 1440, SLOT_MINUTES) >= start) & (
            np.arange(0, 1440, SLOT_MINUTES) < end
        )
        charge_cell = storage_sheet.cell(row, 2)
        discharge_cell = storage_sheet.cell(row, 3)
        charge_cell.value = float(np.sum(solution.charge_kwh[mask]))
        discharge_cell.value = float(np.sum(solution.discharge_kwh[mask]))
        charge_cell.number_format = "0.0000"
        discharge_cell.number_format = "0.0000"

    storage_sheet["E2"] = float(solution.soc_kwh[0])
    storage_sheet["E3"] = float(solution.soc_kwh[-1])
    storage_sheet["E2"].number_format = "0.0000"
    storage_sheet["E3"].number_format = "0.0000"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_path)


def plot_question1(
    data: Question1Data,
    solution: ScheduleSolution,
    figure_dir: Path,
) -> tuple[Path, Path, Path]:
    """Create three publication-ready figures with Matplotlib."""

    matplotlib_cache = Path(tempfile.gettempdir()) / "cumcm-matplotlib"
    matplotlib_cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(matplotlib_cache))

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "font.sans-serif": [
                "Microsoft YaHei",
                "SimHei",
                "Noto Sans CJK SC",
                "DejaVu Sans",
            ],
            "axes.unicode_minus": False,
            "font.size": 10,
            "axes.labelsize": 10,
            "legend.fontsize": 9,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "figure.dpi": 120,
            "savefig.dpi": 300,
        }
    )

    figure_dir.mkdir(parents=True, exist_ok=True)
    hour = data.minute_of_day / 60.0
    hour_step = np.append(hour, 24.0)
    ticks = np.arange(0, 25, 4)

    blue = "#2F5597"
    orange = "#C65911"
    green = "#548235"
    red = "#C00000"
    gray = "#7F7F7F"

    input_path = figure_dir / "q1_input_profile.pdf"
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 5.0), sharex=True, constrained_layout=True)
    axes[0].plot(hour, data.load_kw, color=blue, linewidth=1.8, label="小区负荷")
    axes[0].plot(hour, data.pv_kw, color=orange, linewidth=1.8, label="光伏预测功率")
    axes[0].set_ylabel("功率/kW")
    axes[0].legend(frameon=False, ncol=2, loc="upper left")
    axes[0].grid(axis="y", color="#D9D9D9", linewidth=0.6)
    axes[1].step(
        hour_step,
        np.append(data.price_yuan_per_kwh, data.price_yuan_per_kwh[-1]),
        where="post",
        color=green,
        linewidth=1.6,
    )
    axes[1].set_ylabel("电价/(元·kWh$^{-1}$)")
    axes[1].set_xlabel("时刻/h")
    axes[1].set_xticks(ticks)
    axes[1].set_xlim(0, 24)
    axes[1].grid(axis="y", color="#D9D9D9", linewidth=0.6)
    fig.savefig(input_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    schedule_path = figure_dir / "q1_optimal_schedule.pdf"
    fig, axes = plt.subplots(2, 1, figsize=(7.2, 5.2), sharex=True, constrained_layout=True)
    net_load_kwh = data.load_kwh - data.pv_kwh
    axes[0].step(
        hour_step,
        np.append(solution.grid_kwh, solution.grid_kwh[-1]),
        where="post",
        color=blue,
        linewidth=1.6,
        label="计划购电量",
    )
    axes[0].plot(hour, net_load_kwh, color=gray, linewidth=1.0, label="净负荷电量")
    axes[0].set_ylabel("电量/(kWh/时段)")
    axes[0].legend(frameon=False, ncol=2, loc="upper left")
    axes[0].grid(axis="y", color="#D9D9D9", linewidth=0.6)

    axes[1].bar(
        hour,
        solution.charge_kwh,
        width=DELTA_HOURS * 0.9,
        color=orange,
        label="充电",
    )
    axes[1].bar(
        hour,
        -solution.discharge_kwh,
        width=DELTA_HOURS * 0.9,
        color=green,
        label="放电",
    )
    axes[1].axhline(0, color="#666666", linewidth=0.7)
    axes[1].set_ylabel("储能动作/(kWh/时段)")
    axes[1].set_xlabel("时刻/h")
    axes[1].set_xticks(ticks)
    axes[1].set_xlim(0, 24)
    axes[1].legend(frameon=False, ncol=2, loc="upper left")
    axes[1].grid(axis="y", color="#D9D9D9", linewidth=0.6)
    fig.savefig(schedule_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    soc_path = figure_dir / "q1_soc.pdf"
    fig, ax = plt.subplots(figsize=(7.2, 3.6), constrained_layout=True)
    soc_hour = np.arange(SLOTS_PER_DAY + 1) * DELTA_HOURS
    ax.plot(soc_hour, solution.soc_kwh, color=blue, linewidth=1.9, label="储电量")
    ax.axhline(MIN_SOC_KWH, color=red, linestyle="--", linewidth=1.0, label="储电下限")
    ax.axhline(MAX_SOC_KWH, color=green, linestyle="--", linewidth=1.0, label="储电上限")
    ax.scatter(
        [0, 24],
        [solution.soc_kwh[0], solution.soc_kwh[-1]],
        color=orange,
        s=28,
        zorder=3,
        label="首末状态",
    )
    ax.set_xlabel("时刻/h")
    ax.set_ylabel("储电量/kWh")
    ax.set_xticks(ticks)
    ax.set_xlim(0, 24)
    ax.set_ylim(0, CAPACITY_KWH)
    ax.grid(axis="y", color="#D9D9D9", linewidth=0.6)
    ax.legend(frameon=False, ncol=4, loc="upper center")
    fig.savefig(soc_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    return input_path, schedule_path, soc_path


def print_summary(data: Question1Data, solution: ScheduleSolution) -> None:
    purchase_by_minute = _value_by_start_minute(solution.grid_kwh)
    print("Question 1 optimal schedule")
    for minute in SPECIFIED_START_MINUTES:
        print(f"  {_format_interval(minute):>13}: {purchase_by_minute[minute]:12.4f} kWh")
    print(f"  Total purchase: {np.sum(solution.grid_kwh):12.4f} kWh")
    print(f"  Total cost:     {solution.total_cost_yuan:12.4f} yuan")
    print(f"  PV curtailment: {np.sum(solution.curtailment_kwh):12.4f} kWh")
    print(f"  Charge total:   {np.sum(solution.charge_kwh):12.4f} kWh")
    print(f"  Discharge total:{np.sum(solution.discharge_kwh):12.4f} kWh")
    print(f"  SOC range:      {np.min(solution.soc_kwh):.4f}--{np.max(solution.soc_kwh):.4f} kWh")
    print(f"  SOC 00:00/24:00:{solution.soc_kwh[0]:.4f}/{solution.soc_kwh[-1]:.4f} kWh")


def parse_args() -> argparse.Namespace:
    root = _project_root()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        type=Path,
        default=root / "problems" / "C题" / "附件" / "附件1.xlsx",
        help="Path to attachment 1",
    )
    parser.add_argument(
        "--template",
        type=Path,
        default=root / "src" / "附件5" / "result1.xlsx",
        help="Path to the official result1.xlsx template",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=root / "src" / "附件5" / "result1.xlsx",
        help="Path for the filled result workbook",
    )
    parser.add_argument(
        "--figure-dir",
        type=Path,
        default=root / "src" / "tex" / "figure",
        help="Directory for Matplotlib figures",
    )
    parser.add_argument(
        "--no-plots",
        action="store_true",
        help="Do not generate figures",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data = load_question1_data(args.input.resolve())
    solution = solve_question1(data)
    write_result_workbook(args.template.resolve(), args.output.resolve(), solution)
    figure_paths: tuple[Path, ...] = ()
    if not args.no_plots:
        figure_paths = plot_question1(data, solution, args.figure_dir.resolve())
    print_summary(data, solution)
    print(f"  Saved workbook: {args.output.resolve()}")
    for path in figure_paths:
        print(f"  Saved figure:   {path}")


if __name__ == "__main__":
    main()
