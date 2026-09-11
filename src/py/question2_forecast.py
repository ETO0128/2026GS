"""Causal baseline and similar-day forecasts for Question 2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

import numpy as np

from question2_data import YearData


ForecastMethod = Literal["previous_day", "seven_day", "week_type", "similar_day"]


@dataclass(frozen=True)
class ForecastConfig:
    method: ForecastMethod = "seven_day"
    window_days: int = 90
    candidate_count: int = 14
    lambda_load: float = 0.95
    lambda_pv: float = 0.95
    planning_quantile: float = 0.80


@dataclass(frozen=True)
class ForecastResult:
    load_kw: np.ndarray
    pv_kw: np.ndarray
    planning_net_kw: np.ndarray
    history_end: date | None
    method: str
    parameters: dict[str, float | int | str]
    candidate_dates: tuple[date, ...]
    fallback_reason: str | None


def _is_weekend(value: date) -> bool:
    return value.weekday() >= 5


def _season(value: date) -> int:
    return ((value.month % 12) // 3)


def _weighted_curve(curves: np.ndarray, weights: np.ndarray) -> np.ndarray:
    weights = np.asarray(weights, dtype=float)
    weights /= weights.sum()
    return np.sum(curves * weights[:, None], axis=0)


def _higher_weighted_quantile(values: np.ndarray, weights: np.ndarray, quantile: float) -> np.ndarray:
    if not 0.0 < quantile < 1.0:
        raise ValueError("planning_quantile must lie strictly between zero and one")
    order = np.argsort(values, axis=0)
    sorted_values = np.take_along_axis(values, order, axis=0)
    sorted_weights = np.take_along_axis(np.broadcast_to(weights[:, None], values.shape), order, axis=0)
    cumulative = np.cumsum(sorted_weights, axis=0)
    indices = np.argmax(cumulative >= quantile * weights.sum(), axis=0)
    return sorted_values[indices, np.arange(values.shape[1])]


def _recent_indices(day_index: int, window_days: int) -> np.ndarray:
    return np.arange(max(0, day_index - window_days), day_index, dtype=int)


def _similar_candidates(data: YearData, day_index: int, config: ForecastConfig) -> tuple[np.ndarray, np.ndarray, str | None]:
    target = data.dates[day_index]
    eligible = _recent_indices(day_index, config.window_days)
    calendar = np.asarray(
        [(_is_weekend(data.dates[i]) == _is_weekend(target)) and (_season(data.dates[i]) == _season(target)) for i in eligible]
    )
    candidates = eligible[calendar]
    fallback: str | None = None
    if candidates.size < 2:
        candidates = eligible[np.asarray([_is_weekend(data.dates[i]) == _is_weekend(target) for i in eligible])]
        fallback = "season_cluster_too_small"
    if candidates.size < 2:
        candidates = eligible
        fallback = "calendar_cluster_too_small"
    if candidates.size == 0:
        raise ValueError("At least one historical day is required")

    # Yesterday is the only fully observed curve immediately before the 0:00
    # decision and serves as the target-shape proxy for both series.
    query_load = data.load_kw[day_index - 1]
    query_pv = data.pv_kw[day_index - 1]
    load_scale = max(float(np.mean(query_load)), 1.0)
    pv_scale = max(float(np.max(query_pv)), 1.0)
    distance = (
        np.sqrt(np.mean(((data.load_kw[candidates] - query_load) / load_scale) ** 2, axis=1))
        + np.sqrt(np.mean(((data.pv_kw[candidates] - query_pv) / pv_scale) ** 2, axis=1))
    )
    order = np.argsort(distance, kind="stable")[: config.candidate_count]
    selected = candidates[order]
    similarity = 1.0 / (1.0 + distance[order])
    return selected, similarity, fallback


def forecast_day(
    data: YearData,
    day_index: int,
    config: ForecastConfig,
    cold_start_load_kw: np.ndarray | None = None,
    cold_start_pv_kw: np.ndarray | None = None,
) -> ForecastResult:
    """Forecast a day using rows strictly before ``day_index``."""

    if not 0 <= day_index < len(data.dates):
        raise IndexError("day_index is outside the annual data")
    if day_index == 0:
        if cold_start_load_kw is None or cold_start_pv_kw is None:
            raise ValueError("January 1 requires the attachment-1 cold-start forecast")
        load = np.asarray(cold_start_load_kw, dtype=float).copy()
        pv = np.asarray(cold_start_pv_kw, dtype=float).copy()
        return ForecastResult(load, pv, load - pv, None, "cold_start", {}, (), "no_history")

    fallback: str | None = None
    if config.method == "previous_day":
        indices = np.asarray([day_index - 1])
        weights = np.ones(1)
    elif config.method == "seven_day":
        indices = _recent_indices(day_index, 7)
        weights = np.ones(indices.size)
    elif config.method == "week_type":
        eligible = _recent_indices(day_index, config.window_days)
        target_weekend = _is_weekend(data.dates[day_index])
        indices = eligible[np.asarray([_is_weekend(data.dates[i]) == target_weekend for i in eligible])]
        if indices.size < 2:
            indices = _recent_indices(day_index, 7)
            fallback = "no_matching_week_type"
        weights = np.ones(indices.size)
    elif config.method == "similar_day":
        indices, similarity, fallback = _similar_candidates(data, day_index, config)
        age = day_index - indices
        load_weights = similarity * np.power(config.lambda_load, age)
        pv_weights = similarity * np.power(config.lambda_pv, age)
        load = _weighted_curve(data.load_kw[indices], load_weights)
        pv = _weighted_curve(data.pv_kw[indices], pv_weights)
        joint_weights = np.sqrt(load_weights * pv_weights)
        planning_net = _higher_weighted_quantile(data.load_kw[indices] - data.pv_kw[indices], joint_weights, config.planning_quantile)
        return _result(data, day_index, config, indices, load, pv, planning_net, fallback)
    else:
        raise ValueError(f"Unknown forecast method: {config.method}")

    load = _weighted_curve(data.load_kw[indices], weights)
    pv = _weighted_curve(data.pv_kw[indices], weights)
    planning_net = np.quantile(data.load_kw[indices] - data.pv_kw[indices], config.planning_quantile, axis=0, method="higher")
    return _result(data, day_index, config, indices, load, pv, planning_net, fallback)


def _result(
    data: YearData,
    day_index: int,
    config: ForecastConfig,
    indices: np.ndarray,
    load: np.ndarray,
    pv: np.ndarray,
    planning_net: np.ndarray,
    fallback: str | None,
) -> ForecastResult:
    arrays = (load, pv, planning_net)
    if any(array.shape != (144,) or not np.all(np.isfinite(array)) for array in arrays):
        raise RuntimeError("Forecast produced an invalid curve")
    return ForecastResult(
        load_kw=np.maximum(load, 0.0),
        pv_kw=np.maximum(pv, 0.0),
        planning_net_kw=np.asarray(planning_net, dtype=float),
        history_end=data.dates[day_index - 1],
        method=config.method,
        parameters={
            "window_days": config.window_days,
            "candidate_count": config.candidate_count,
            "lambda_load": config.lambda_load,
            "lambda_pv": config.lambda_pv,
            "planning_quantile": config.planning_quantile,
        },
        candidate_dates=tuple(data.dates[i] for i in indices),
        fallback_reason=fallback,
    )


def forecast_metrics(actual: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
    actual = np.asarray(actual, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    if actual.shape != predicted.shape or actual.size == 0:
        raise ValueError("Actual and predicted arrays must have the same nonempty shape")
    error = predicted - actual
    return {
        "mae": float(np.mean(np.abs(error))),
        "rmse": float(np.sqrt(np.mean(error**2))),
        "bias": float(np.mean(error)),
    }
