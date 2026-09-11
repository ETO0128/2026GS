"""Small integration tests for the annual Question 2 loop."""

from __future__ import annotations

import unittest
from datetime import date, timedelta

import numpy as np

from question2 import Question2Config, run_question2
from question2_data import ColdStartForecast, YearData
from question2_forecast import ForecastConfig


def make_data(days: int = 3) -> YearData:
    dates = tuple(date(2025, 1, 1) + timedelta(days=i) for i in range(days))
    load = np.full((days, 144), 600.0)
    pv = np.zeros((days, 144))
    return YearData(dates, np.arange(0, 1440, 10), np.ones(144), load, pv)


class Question2IntegrationTests(unittest.TestCase):
    def test_realized_soc_is_carried_across_days(self) -> None:
        result = run_question2(
            make_data(),
            Question2Config(forecast=ForecastConfig(method="previous_day")),
            ColdStartForecast(np.full(144, 600.0), np.zeros(144)),
        )
        for previous, current in zip(result.days, result.days[1:]):
            self.assertAlmostEqual(previous.execution.soc_kwh[-1], current.execution.soc_kwh[0], places=5)

    def test_information_cutoff_precedes_each_decision(self) -> None:
        result = run_question2(
            make_data(),
            Question2Config(forecast=ForecastConfig(method="seven_day")),
            ColdStartForecast(np.full(144, 600.0), np.zeros(144)),
        )
        self.assertIsNone(result.days[0].forecast.history_end)
        for record in result.days[1:]:
            self.assertLess(record.forecast.history_end, record.date)

    def test_stochastic_plan_carries_realized_soc(self) -> None:
        result = run_question2(
            make_data(4),
            Question2Config(
                forecast=ForecastConfig(method="seven_day"),
                planner="stochastic",
                scenario_count=2,
                scenario_decay=0.9,
            ),
            ColdStartForecast(np.full(144, 600.0), np.zeros(144)),
        )
        self.assertGreater(result.days[1].expected_emergency_cost_yuan, -1e-8)
        for previous, current in zip(result.days, result.days[1:]):
            self.assertAlmostEqual(previous.execution.soc_kwh[-1], current.execution.soc_kwh[0], places=5)


if __name__ == "__main__":
    unittest.main()
