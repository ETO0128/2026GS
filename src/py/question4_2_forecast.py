"""Causal variable-price forecasts for Question 4-2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from question4_2_data import Question42Data


@dataclass(frozen=True)
class PriceForecastConfig:
    method: str = "seven_day"
    candidate_count: int = 14
    decay: float = 0.95
    window_days: int = 90


@dataclass(frozen=True)
class PriceForecastResult:
    decision_date: date
    history_end_date: date | None
    price_yuan_per_kwh: np.ndarray
    method: str
    source_dates: tuple[date, ...]
    source_weights: np.ndarray
    fallback_reason: str | None


def _is_weekend(value: date) -> bool:
    return value.weekday() >= 5


def _season(value: date) -> int:
    return (value.month % 12) // 3


def _validate_request(data: Question42Data, target_index: int, config: PriceForecastConfig) -> None:
    methods = {"previous_day", "seven_day", "week_type", "similar_day_decay", "expanding_mean"}
    if config.method not in methods:
        raise ValueError(f"Unknown price forecast method: {config.method}")
    if not 0 <= target_index < len(data.dates):
        raise IndexError("Price forecast target index is outside the data range")
    if target_index == 0:
        raise ValueError("The first day requires an explicit cold-start price")
    prices = np.asarray(data.price_yuan_per_kwh, dtype=float)
    if prices.shape != (len(data.dates), 144):
        raise ValueError("Price history must have shape (days, 144)")
    if not np.all(np.isfinite(prices)) or np.any(prices < 0.0):
        raise ValueError("Price history must be finite and nonnegative")
    if config.candidate_count < 1 or config.window_days < 1:
        raise ValueError("Candidate count and history window must be positive")
    if not 0.0 < config.decay <= 1.0:
        raise ValueError("Price history decay must lie in (0, 1]")


def _result(
    data: Question42Data,
    target_index: int,
    config: PriceForecastConfig,
    source_indices: np.ndarray,
    weights: np.ndarray,
    fallback_reason: str | None,
) -> PriceForecastResult:
    normalized = np.asarray(weights, dtype=float)
    normalized = normalized / normalized.sum()
    forecast = np.sum(data.price_yuan_per_kwh[source_indices] * normalized[:, None], axis=0)
    return PriceForecastResult(
        decision_date=data.dates[target_index],
        history_end_date=data.dates[target_index - 1],
        price_yuan_per_kwh=forecast,
        method=config.method,
        source_dates=tuple(data.dates[index] for index in source_indices),
        source_weights=normalized,
        fallback_reason=fallback_reason,
    )


def forecast_price(
    data: Question42Data,
    target_index: int,
    config: PriceForecastConfig = PriceForecastConfig(),
) -> PriceForecastResult:
    """Forecast a 144-point price curve using only earlier realized days."""

    _validate_request(data, target_index, config)
    if config.method == "previous_day":
        sources = np.asarray([target_index - 1], dtype=int)
        return _result(data, target_index, config, sources, np.ones(1), None)

    if config.method == "seven_day":
        sources = np.arange(max(0, target_index - 7), target_index, dtype=int)
        return _result(data, target_index, config, sources, np.ones(len(sources)), None)

    if config.method == "expanding_mean":
        # 截至决策日前的扩展窗口均值；与旧版“全年均值曲线”不同，不读取未来日期。
        sources = np.arange(target_index, dtype=int)
        return _result(data, target_index, config, sources, np.ones(len(sources)), None)

    ages = np.asarray(
        [(data.dates[target_index] - data.dates[index]).days for index in range(target_index)],
        dtype=int,
    )
    eligible = np.flatnonzero(ages <= config.window_days)
    if eligible.size == 0:
        eligible = np.arange(target_index, dtype=int)

    matching_week_type = eligible[np.asarray([
        _is_weekend(data.dates[index]) == _is_weekend(data.dates[target_index])
        for index in eligible
    ], dtype=bool)]
    if config.method == "week_type":
        fallback: str | None = None
        sources = matching_week_type
        if sources.size == 0:
            sources = np.arange(max(0, target_index - 7), target_index, dtype=int)
            fallback = "week_type_history_unavailable"
        return _result(data, target_index, config, sources, np.ones(len(sources)), fallback)

    season_and_week = matching_week_type[np.asarray([
        _season(data.dates[index]) == _season(data.dates[target_index])
        for index in matching_week_type
    ], dtype=bool)]
    fallback = None
    candidates = season_and_week
    if candidates.size < 2:
        candidates = matching_week_type
        fallback = "season_cluster_too_small"
    if candidates.size < 2:
        candidates = eligible
        fallback = "week_type_cluster_too_small"

    prototype_start = max(0, target_index - 7)
    prototype = np.mean(data.price_yuan_per_kwh[prototype_start:target_index], axis=0)
    scale = max(float(np.mean(prototype)), 1e-6)
    distance = np.sqrt(np.mean(
        ((data.price_yuan_per_kwh[candidates] - prototype) / scale) ** 2,
        axis=1,
    ))
    order = np.argsort(distance, kind="stable")[: config.candidate_count]
    sources = candidates[order]
    similarity = 1.0 / (1.0 + distance[order])
    raw_weights = similarity * np.power(config.decay, ages[sources])
    return _result(data, target_index, config, sources, raw_weights, fallback)


def price_forecast_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    """Calculate price forecast errors with prediction-minus-actual bias."""

    actual_values = np.asarray(actual, dtype=float)
    predicted_values = np.asarray(predicted, dtype=float)
    if actual_values.shape != predicted_values.shape or actual_values.size == 0:
        raise ValueError("Actual and predicted prices must have the same nonempty shape")
    if not np.all(np.isfinite(actual_values)) or not np.all(np.isfinite(predicted_values)):
        raise ValueError("Price metrics require finite values")
    error = predicted_values - actual_values
    return {
        "mae_yuan_per_kwh": float(np.mean(np.abs(error))),
        "rmse_yuan_per_kwh": float(np.sqrt(np.mean(error ** 2))),
        "bias_yuan_per_kwh": float(np.mean(error)),
    }


def calibrate_price_method(
    data: Question42Data,
    methods: tuple[str, ...] = (
        "previous_day", "seven_day", "week_type", "similar_day_decay", "expanding_mean"
    ),
    minimum_history_days: int = 7,
) -> tuple[str, dict[str, dict[str, float]]]:
    """Select one causal method using January only and lock it before February.

    RMSE is the primary score because large price errors can distort storage
    arbitrage more severely; MAE and bias are retained for audit.  Ties keep
    the caller-provided method order.
    """

    indices = tuple(
        index for index, value in enumerate(data.dates)
        if value.month == 1 and index >= minimum_history_days
    )
    if not indices:
        raise ValueError("Price calibration requires January observations after the warm-up window")
    scores: dict[str, dict[str, float]] = {}
    actual = data.price_yuan_per_kwh[list(indices)]
    for method in methods:
        predicted = np.stack([
            forecast_price(data, index, PriceForecastConfig(method=method)).price_yuan_per_kwh
            for index in indices
        ])
        scores[method] = price_forecast_metrics(actual, predicted)
    selected = min(methods, key=lambda method: scores[method]["rmse_yuan_per_kwh"])
    return selected, scores
