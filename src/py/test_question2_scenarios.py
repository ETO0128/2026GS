"""Tests for paired whole-day residual scenarios."""

from __future__ import annotations

import unittest
from datetime import date

import numpy as np

from question2_forecast import ForecastResult
from question2_scenarios import build_joint_residual_scenarios, empirical_net_demand_quantile


def flat_forecast(run_date: date) -> ForecastResult:
    load = np.full(144, 1000.0)
    pv = np.full(144, 200.0)
    return ForecastResult(load, pv, load - pv, run_date, "seven_day", {}, (), None)


class Question2ScenarioTests(unittest.TestCase):
    def test_whole_day_pairing_and_decay_probability(self) -> None:
        dates = (date(2024, 12, 28), date(2025, 1, 4))
        actual_load = np.full((2, 144), 1000.0)
        actual_pv = np.full((2, 144), 200.0)
        load_residual = np.stack((np.full(144, 10.0), np.full(144, 20.0)))
        pv_residual = np.stack((np.full(144, -1.0), np.full(144, -2.0)))
        scenarios = build_joint_residual_scenarios(
            dates,
            actual_load,
            actual_pv,
            load_residual,
            pv_residual,
            flat_forecast(date(2025, 1, 4)),
            date(2025, 1, 5),
            max_scenarios=2,
            decay=0.9,
        )
        by_source = {item.source_date: item for item in scenarios.items}
        np.testing.assert_allclose(by_source[dates[0]].load_kw, 1010.0)
        np.testing.assert_allclose(by_source[dates[0]].pv_kw, 199.0)
        ratio = by_source[dates[1]].probability / by_source[dates[0]].probability
        self.assertAlmostEqual(ratio, 0.9 ** 1 / 0.9 ** 8)
        self.assertTrue(all(item.source_date < scenarios.decision_date for item in scenarios.items))

    def test_quantile_uses_conservative_higher_order_statistic(self) -> None:
        values = np.array([[10.0], [20.0], [30.0], [40.0], [50.0]])
        np.testing.assert_allclose(empirical_net_demand_quantile(values, 0.8), np.array([50.0]))


if __name__ == "__main__":
    unittest.main()
