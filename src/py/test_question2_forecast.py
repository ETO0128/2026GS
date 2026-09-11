"""Tests for causal Question 2 forecasts."""

from __future__ import annotations

import dataclasses
import unittest
from datetime import date, timedelta

import numpy as np

from question2_data import YearData
from question2_forecast import (
    ForecastConfig,
    apply_conditional_residual_quantile,
    forecast_day,
    forecast_metrics,
)


def make_data(days: int = 40) -> YearData:
    dates = tuple(date(2025, 1, 1) + timedelta(days=i) for i in range(days))
    slots = np.arange(144, dtype=float)
    load = np.stack([1000.0 + 10.0 * day + slots for day in range(days)])
    pv_curve = np.maximum(0.0, 500.0 - np.abs(slots - 72.0) * 20.0)
    pv = np.stack([pv_curve * (1.0 + day / 1000.0) for day in range(days)])
    return YearData(dates, np.arange(0, 1440, 10), np.ones(144), load, pv)


class Question2ForecastTests(unittest.TestCase):
    def test_future_mutation_does_not_change_forecast(self) -> None:
        base = make_data()
        config = ForecastConfig(method="similar_day", window_days=28, candidate_count=7)
        first = forecast_day(base, 31, config)
        changed_load = base.load_kw.copy()
        changed_pv = base.pv_kw.copy()
        changed_load[31:] += 99999.0
        changed_pv[31:] += 99999.0
        changed = dataclasses.replace(base, load_kw=changed_load, pv_kw=changed_pv)
        second = forecast_day(changed, 31, config)
        np.testing.assert_allclose(first.load_kw, second.load_kw)
        np.testing.assert_allclose(first.pv_kw, second.pv_kw)
        np.testing.assert_allclose(first.planning_net_kw, second.planning_net_kw)
        self.assertTrue(all(candidate < base.dates[31] for candidate in first.candidate_dates))

    def test_week_type_falls_back_with_too_little_history(self) -> None:
        result = forecast_day(make_data(2), 1, ForecastConfig(method="week_type"))
        self.assertEqual(result.fallback_reason, "no_matching_week_type")

    def test_forecast_metrics_have_known_values(self) -> None:
        metrics = forecast_metrics(np.array([1.0, 2.0]), np.array([2.0, 0.0]))
        self.assertAlmostEqual(metrics["mae"], 1.5)
        self.assertAlmostEqual(metrics["rmse"], np.sqrt(2.5))
        self.assertAlmostEqual(metrics["bias"], -0.5)

    def test_conditional_residual_quantile_adds_residual_to_point_forecast(self) -> None:
        data = make_data(5)
        target = forecast_day(data, 4, ForecastConfig(method="seven_day"))
        history_dates = data.dates[:4]
        point_history = np.stack([target.load_kw - target.pv_kw] * 4)
        residuals = np.stack([np.full(144, value) for value in (10.0, 20.0, 30.0, 40.0)])
        config = ForecastConfig(
            method="seven_day",
            planning_quantile=0.80,
            residual_candidate_count=4,
            residual_decay=1.0,
        )
        result = apply_conditional_residual_quantile(
            target,
            data.dates[4],
            history_dates,
            point_history,
            residuals,
            config,
        )
        np.testing.assert_allclose(
            result.planning_net_kw,
            target.load_kw - target.pv_kw + 40.0,
        )

    def test_conditional_residual_quantile_rejects_future_history(self) -> None:
        data = make_data(5)
        target = forecast_day(data, 4, ForecastConfig(method="seven_day"))
        with self.assertRaises(ValueError):
            apply_conditional_residual_quantile(
                target,
                data.dates[4],
                (data.dates[4],),
                np.zeros((1, 144)),
                np.zeros((1, 144)),
                ForecastConfig(),
            )

    def test_conditional_residual_quantile_applies_time_decay(self) -> None:
        data = make_data(3)
        target = forecast_day(data, 2, ForecastConfig(method="seven_day"))
        target_net = target.load_kw - target.pv_kw
        result = apply_conditional_residual_quantile(
            target,
            data.dates[2],
            data.dates[:2],
            np.stack([target_net, target_net]),
            np.stack([np.full(144, 100.0), np.zeros(144)]),
            ForecastConfig(
                planning_quantile=0.60,
                residual_candidate_count=2,
                residual_decay=0.50,
            ),
        )
        np.testing.assert_allclose(result.planning_net_kw, target_net)


if __name__ == "__main__":
    unittest.main()
