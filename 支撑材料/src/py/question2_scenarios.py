"""Causal whole-day paired residual scenarios for Question 2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from question2_forecast import ForecastResult


@dataclass(frozen=True)
class ResidualScenario:
    source_date: date
    load_kw: np.ndarray
    pv_kw: np.ndarray
    probability: float
    similarity: float
    age_days: int
    clipped_load_kwh: float
    clipped_pv_kwh: float


@dataclass(frozen=True)
class ScenarioSet:
    decision_date: date
    items: tuple[ResidualScenario, ...]
    decay: float
    fallback_reason: str | None

    @property
    def probabilities(self) -> np.ndarray:
        return np.asarray([item.probability for item in self.items], dtype=float)


def _is_weekend(value: date) -> bool:
    return value.weekday() >= 5


def _season(value: date) -> int:
    return (value.month % 12) // 3


def build_joint_residual_scenarios(
    history_dates: tuple[date, ...],
    actual_load_kw: np.ndarray,
    actual_pv_kw: np.ndarray,
    load_residual_kw: np.ndarray,
    pv_residual_kw: np.ndarray,
    target_forecast: ForecastResult,
    decision_date: date,
    max_scenarios: int = 14,
    decay: float = 0.95,
    window_days: int = 90,
) -> ScenarioSet:
    """Select paired daily residuals and assign similarity-decay probabilities.

    Every scenario keeps all 144 load residuals and PV residuals from the same
    historical day. Candidate selection uses only the target forecast and past
    actual curves. The time-decay factor therefore participates directly in the
    stochastic objective rather than being a display-only forecast variant.
    """

    if not history_dates:
        raise ValueError("At least one historical residual day is required")
    if max_scenarios < 1 or window_days < 1:
        raise ValueError("Scenario count and history window must be positive")
    if not 0.0 < decay <= 1.0:
        raise ValueError("Scenario decay must lie in (0, 1]")
    matrices = tuple(np.asarray(values, dtype=float) for values in (
        actual_load_kw,
        actual_pv_kw,
        load_residual_kw,
        pv_residual_kw,
    ))
    expected_shape = (len(history_dates), 144)
    if any(values.shape != expected_shape or not np.all(np.isfinite(values)) for values in matrices):
        raise ValueError(f"Scenario histories must be finite arrays with shape {expected_shape}")
    if any(item >= decision_date for item in history_dates):
        raise ValueError("Residual scenarios cannot use the decision date or future dates")
    if len(set(history_dates)) != len(history_dates):
        raise ValueError("Residual source dates must be unique")

    actual_load, actual_pv, residual_load, residual_pv = matrices
    ages = np.asarray([(decision_date - item).days for item in history_dates], dtype=int)
    eligible = np.flatnonzero(ages <= window_days)
    if eligible.size == 0:
        eligible = np.arange(len(history_dates), dtype=int)
    calendar = np.asarray([
        _is_weekend(history_dates[index]) == _is_weekend(decision_date)
        and _season(history_dates[index]) == _season(decision_date)
        for index in eligible
    ])
    candidates = eligible[calendar]
    fallback: str | None = None
    if candidates.size < 2:
        candidates = eligible[np.asarray([
            _is_weekend(history_dates[index]) == _is_weekend(decision_date) for index in eligible
        ])]
        fallback = "season_cluster_too_small"
    if candidates.size < 2:
        candidates = eligible
        fallback = "calendar_cluster_too_small"

    load_scale = max(float(np.mean(target_forecast.load_kw)), 1.0)
    pv_scale = max(float(np.max(target_forecast.pv_kw)), 1.0)
    distance = (
        np.sqrt(np.mean(((actual_load[candidates] - target_forecast.load_kw) / load_scale) ** 2, axis=1))
        + np.sqrt(np.mean(((actual_pv[candidates] - target_forecast.pv_kw) / pv_scale) ** 2, axis=1))
    )
    order = np.argsort(distance, kind="stable")[:max_scenarios]
    selected = candidates[order]
    similarity = 1.0 / (1.0 + distance[order])
    raw_weights = similarity * np.power(decay, ages[selected])
    probabilities = raw_weights / raw_weights.sum()

    items: list[ResidualScenario] = []
    for source, probability, source_similarity in zip(selected, probabilities, similarity, strict=True):
        raw_load = target_forecast.load_kw + residual_load[source]
        raw_pv = target_forecast.pv_kw + residual_pv[source]
        scenario_load = np.maximum(raw_load, 0.0)
        scenario_pv = np.maximum(raw_pv, 0.0)
        items.append(ResidualScenario(
            source_date=history_dates[source],
            load_kw=scenario_load,
            pv_kw=scenario_pv,
            probability=float(probability),
            similarity=float(source_similarity),
            age_days=int(ages[source]),
            clipped_load_kwh=float(np.sum(np.maximum(-raw_load, 0.0)) / 6.0),
            clipped_pv_kwh=float(np.sum(np.maximum(-raw_pv, 0.0)) / 6.0),
        ))
    return ScenarioSet(decision_date, tuple(items), decay, fallback)


def empirical_net_demand_quantile(history: np.ndarray, quantile: float = 0.80) -> np.ndarray:
    values = np.asarray(history, dtype=float)
    if values.ndim != 2 or values.shape[0] == 0 or not np.all(np.isfinite(values)):
        raise ValueError("Quantile history must be a nonempty finite matrix")
    return np.quantile(values, quantile, axis=0, method="higher")
