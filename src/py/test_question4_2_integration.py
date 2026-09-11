"""Integration tests for the Question 4-2 causal baseline loop."""

from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import date, timedelta

import numpy as np

from question2_data import ColdStartForecast
from question2_forecast import ForecastConfig
from question4_2 import Question42Config, run_question42_baseline
from question4_2_data import Question42Data
from question4_2_forecast import PriceForecastConfig


def three_day_data() -> Question42Data:
    dates = tuple(date(2025, 1, 1) + timedelta(days=index) for index in range(3))
    prices = np.stack((
        np.ones(144),
        np.full(144, 1.2),
        np.full(144, 0.8),
    ))
    load = np.stack((
        np.full(144, 600.0),
        np.full(144, 660.0),
        np.full(144, 540.0),
    ))
    return Question42Data(
        dates=dates,
        minute_of_day=np.arange(0, 1440, 10, dtype=int),
        price_yuan_per_kwh=prices,
        load_kw=load,
        pv_kw=np.zeros_like(load),
    )


def baseline_config() -> Question42Config:
    return Question42Config(
        source_forecast=ForecastConfig(method="seven_day", planning_method="historical_net"),
        price_forecast=PriceForecastConfig(method="seven_day"),
    )


class Question42IntegrationTests(unittest.TestCase):
    def test_three_day_loop_carries_soc_and_uses_past_price_only(self) -> None:
        data = three_day_data()
        cold_start = ColdStartForecast(load_kw=data.load_kw[0], pv_kw=data.pv_kw[0])
        result = run_question42_baseline(
            data,
            cold_start,
            cold_start_price_yuan_per_kwh=np.full(144, 0.9),
            config=baseline_config(),
        )

        self.assertEqual(len(result.days), 3)
        self.assertIsNone(result.days[0].price_forecast.history_end_date)
        self.assertLess(result.days[1].price_forecast.history_end_date, result.days[1].date)
        self.assertLess(result.days[2].price_forecast.history_end_date, result.days[2].date)
        self.assertAlmostEqual(result.days[1].plan.soc_kwh[0], result.days[0].execution.soc_kwh[-1])
        self.assertAlmostEqual(result.days[2].plan.soc_kwh[0], result.days[1].execution.soc_kwh[-1])
        self.assertTrue(all(day.dispatch_regret_yuan >= -1e-5 for day in result.days))
        self.assertEqual(result.metrics["evaluated_days"], 3)
        self.assertEqual(result.metrics["price_evaluated_days"], 2)
        self.assertEqual(result.metrics["constraint_violations"], 0)

    def test_future_mutation_does_not_change_second_day_plan(self) -> None:
        data = three_day_data()
        cold_start = ColdStartForecast(load_kw=data.load_kw[0], pv_kw=data.pv_kw[0])
        baseline = run_question42_baseline(
            data,
            cold_start,
            cold_start_price_yuan_per_kwh=np.full(144, 0.9),
            config=baseline_config(),
        )
        changed_prices = data.price_yuan_per_kwh.copy()
        changed_load = data.load_kw.copy()
        changed_prices[2] = 50.0
        changed_load[2] = 9000.0
        changed = run_question42_baseline(
            replace(data, price_yuan_per_kwh=changed_prices, load_kw=changed_load),
            cold_start,
            cold_start_price_yuan_per_kwh=np.full(144, 0.9),
            config=baseline_config(),
        )

        np.testing.assert_allclose(changed.days[1].price_forecast.price_yuan_per_kwh, baseline.days[1].price_forecast.price_yuan_per_kwh)
        np.testing.assert_allclose(changed.days[1].plan.grid_kwh, baseline.days[1].plan.grid_kwh)
        np.testing.assert_allclose(changed.days[1].plan.soc_kwh, baseline.days[1].plan.soc_kwh)


if __name__ == "__main__":
    unittest.main()
