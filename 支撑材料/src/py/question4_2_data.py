"""Validated annual source, load and variable-price data for Question 4-2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from question2_data import (
    SLOTS_PER_DAY,
    ActualYearData,
    load_actual_year_data,
    read_daily_matrix,
)


@dataclass(frozen=True)
class Question42Data:
    dates: tuple[date, ...]
    minute_of_day: np.ndarray
    price_yuan_per_kwh: np.ndarray
    load_kw: np.ndarray
    pv_kw: np.ndarray

    @property
    def load_kwh(self) -> np.ndarray:
        return self.load_kw / 6.0

    @property
    def pv_kwh(self) -> np.ndarray:
        return self.pv_kw / 6.0


def load_question42_data(attachment2: Path, attachment4: Path) -> Question42Data:
    """Load actual source/load curves and align the realized variable prices."""

    actual: ActualYearData = load_actual_year_data(attachment2)
    price_dates, _, source_price = read_daily_matrix(attachment4, "Sheet1")
    if price_dates != actual.dates:
        raise ValueError("Attachment 4 dates must match Attachment 2")
    price = np.concatenate((source_price[:, -1:], source_price[:, :-1]), axis=1)
    if price.shape != (len(actual.dates), SLOTS_PER_DAY):
        raise ValueError(f"Attachment 4 must contain {len(actual.dates)} days and {SLOTS_PER_DAY} slots")
    return Question42Data(
        dates=actual.dates,
        minute_of_day=actual.minute_of_day.copy(),
        price_yuan_per_kwh=price,
        load_kw=actual.load_kw.copy(),
        pv_kw=actual.pv_kw.copy(),
    )


def _mean_lagged_curve_correlation(values: np.ndarray, lag: int) -> float:
    earlier = values[:-lag]
    later = values[lag:]
    earlier_centered = earlier - earlier.mean(axis=1, keepdims=True)
    later_centered = later - later.mean(axis=1, keepdims=True)
    denominator = np.linalg.norm(earlier_centered, axis=1) * np.linalg.norm(later_centered, axis=1)
    valid = denominator > 0.0
    if not np.any(valid):
        raise ValueError(f"Cannot calculate lag-{lag} correlation from constant price curves")
    correlations = np.sum(earlier_centered[valid] * later_centered[valid], axis=1) / denominator[valid]
    return float(np.mean(correlations))


def summarize_prices(data: Question42Data) -> dict[str, float]:
    """Return stable source controls used by the first Question 4-2 audit."""

    prices = np.asarray(data.price_yuan_per_kwh, dtype=float)
    if prices.ndim != 2 or prices.shape[1] != SLOTS_PER_DAY or prices.shape[0] <= 7:
        raise ValueError("Price summary requires more than seven complete 144-slot days")
    if not np.all(np.isfinite(prices)) or np.any(prices < 0.0):
        raise ValueError("Prices must be finite and nonnegative")
    return {
        "minimum_yuan_per_kwh": float(np.min(prices)),
        "maximum_yuan_per_kwh": float(np.max(prices)),
        "mean_yuan_per_kwh": float(np.mean(prices)),
        "lag1_curve_correlation": _mean_lagged_curve_correlation(prices, 1),
        "lag7_curve_correlation": _mean_lagged_curve_correlation(prices, 7),
    }
