"""Tests for causal Question 4-2 price forecasts."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date, timedelta

import numpy as np

from question4_2_data import Question42Data
from question4_2_forecast import (
    PriceForecastConfig,
    forecast_price,
    price_forecast_metrics,
)


def synthetic_data(days: int = 21) -> Question42Data:
    dates = tuple(date(2025, 1, 1) + timedelta(days=index) for index in range(days))
    slots = np.arange(144, dtype=float) / 1000.0
    prices = np.stack([0.2 + 0.01 * index + slots for index in range(days)])
    zeros = np.zeros_like(prices)
    return Question42Data(
        dates=dates,
        minute_of_day=np.arange(0, 1440, 10, dtype=int),
        price_yuan_per_kwh=prices,
        load_kw=zeros,
        pv_kw=zeros,
    )


class Question42ForecastTests(unittest.TestCase):
    def test_previous_day_and_seven_day_use_only_past_curves(self) -> None:
        data = synthetic_data()
        previous = forecast_price(data, 10, PriceForecastConfig(method="previous_day"))
        seven = forecast_price(data, 10, PriceForecastConfig(method="seven_day"))

        np.testing.assert_allclose(previous.price_yuan_per_kwh, data.price_yuan_per_kwh[9])
        np.testing.assert_allclose(seven.price_yuan_per_kwh, data.price_yuan_per_kwh[3:10].mean(axis=0))
        self.assertEqual(previous.source_dates, (data.dates[9],))
        self.assertLess(previous.history_end_date, previous.decision_date)

    def test_week_type_uses_only_matching_past_day_type(self) -> None:
        data = synthetic_data()
        target_index = 17  # 2025-01-18, Saturday
        result = forecast_price(data, target_index, PriceForecastConfig(method="week_type"))
        expected_indices = (3, 4, 10, 11)

        np.testing.assert_allclose(
            result.price_yuan_per_kwh,
            data.price_yuan_per_kwh[list(expected_indices)].mean(axis=0),
        )
        self.assertEqual(result.source_dates, tuple(data.dates[index] for index in expected_indices))
        self.assertIsNone(result.fallback_reason)

    def test_similar_day_weights_decay_toward_recent_history(self) -> None:
        data = synthetic_data()
        constant_prices = np.full_like(data.price_yuan_per_kwh, 0.5)
        constant_data = replace(data, price_yuan_per_kwh=constant_prices)
        result = forecast_price(
            constant_data,
            17,
            PriceForecastConfig(
                method="similar_day_decay",
                candidate_count=4,
                decay=0.8,
                window_days=30,
            ),
        )

        self.assertEqual(result.source_dates, tuple(constant_data.dates[index] for index in (3, 4, 10, 11)))
        self.assertGreater(result.source_weights[-1], result.source_weights[0])
        self.assertAlmostEqual(float(np.sum(result.source_weights)), 1.0)
        np.testing.assert_allclose(result.price_yuan_per_kwh, np.full(144, 0.5))

    def test_future_mutation_does_not_change_current_forecast(self) -> None:
        data = synthetic_data()
        config = PriceForecastConfig(
            method="similar_day_decay",
            candidate_count=5,
            decay=0.95,
            window_days=30,
        )
        baseline = forecast_price(data, 15, config)
        mutated_prices = data.price_yuan_per_kwh.copy()
        mutated_prices[15:] = 99.0
        mutated = replace(data, price_yuan_per_kwh=mutated_prices)
        changed = forecast_price(mutated, 15, config)

        np.testing.assert_allclose(changed.price_yuan_per_kwh, baseline.price_yuan_per_kwh)
        np.testing.assert_allclose(changed.source_weights, baseline.source_weights)
        self.assertEqual(changed.source_dates, baseline.source_dates)
        self.assertEqual(changed.history_end_date, baseline.history_end_date)

    def test_similar_day_falls_back_before_first_matching_weekend(self) -> None:
        data = synthetic_data()
        result = forecast_price(
            data,
            3,  # 2025-01-04 is the first Saturday in the sample.
            PriceForecastConfig(method="similar_day_decay"),
        )

        self.assertEqual(set(result.source_dates), set(data.dates[:3]))
        self.assertEqual(result.fallback_reason, "week_type_cluster_too_small")
        self.assertTrue(np.all(np.isfinite(result.price_yuan_per_kwh)))

    def test_price_forecast_metrics_have_known_values(self) -> None:
        metrics = price_forecast_metrics(
            actual=np.asarray([1.0, 3.0]),
            predicted=np.asarray([2.0, 1.0]),
        )
        self.assertAlmostEqual(metrics["mae_yuan_per_kwh"], 1.5)
        self.assertAlmostEqual(metrics["rmse_yuan_per_kwh"], np.sqrt(2.5))
        self.assertAlmostEqual(metrics["bias_yuan_per_kwh"], -0.5)

    def test_first_day_requires_explicit_cold_start_price(self) -> None:
        with self.assertRaisesRegex(ValueError, "cold-start price"):
            forecast_price(synthetic_data(), 0, PriceForecastConfig())


if __name__ == "__main__":
    unittest.main()
