"""Tests for Question 2 planning and settlement."""

from __future__ import annotations

import unittest
from datetime import date

import numpy as np

from question2_dispatch import (
    DayAheadPlan,
    RealizedDay,
    compress_emergency_events,
    plan_day_ahead,
    plan_two_stage_stochastic,
    simulate_fixed_plan,
)
from question2_forecast import ForecastResult
from question2_scenarios import ResidualScenario, ScenarioSet


def make_plan(grid: float = 100.0) -> DayAheadPlan:
    zeros = np.zeros(144)
    return DayAheadPlan(
        date(2025, 2, 1), np.ones(144), np.full(144, grid), zeros.copy(), zeros.copy(), zeros.copy(),
        np.full(145, 6000.0), 144.0 * grid,
    )


class Question2DispatchTests(unittest.TestCase):
    def test_one_slot_shortfall_uses_five_times_price(self) -> None:
        plan = make_plan()
        load = np.full(144, 100.0)
        load[12] = 130.0
        result = simulate_fixed_plan(plan, RealizedDay(plan.date, load, np.zeros(144)), 6000.0)
        self.assertAlmostEqual(result.emergency_kwh[12], 30.0)
        self.assertAlmostEqual(result.emergency_cost_yuan, 150.0)

    def test_adjacent_emergency_slots_are_compressed(self) -> None:
        values = np.zeros(144)
        values[0:2] = [2.0, 3.0]
        values[4] = 7.0
        events = compress_emergency_events(values)
        self.assertEqual([(e.start_minute, e.end_minute, e.energy_kwh) for e in events], [(0, 20, 5.0), (40, 50, 7.0)])

    def test_single_zero_error_scenario_matches_deterministic_plan(self) -> None:
        load = np.full(144, 600.0)
        pv = np.zeros(144)
        forecast = ForecastResult(load, pv, load - pv, date(2025, 1, 31), "seven_day", {}, (), None)
        deterministic = plan_day_ahead(date(2025, 2, 1), forecast, np.ones(144), 6000.0, 6000.0)
        scenario = ResidualScenario(date(2025, 1, 31), load, pv, 1.0, 1.0, 1, 0.0, 0.0)
        stochastic = plan_two_stage_stochastic(
            date(2025, 2, 1),
            ScenarioSet(date(2025, 2, 1), (scenario,), 0.95, None),
            np.ones(144),
            6000.0,
            6000.0,
        )
        np.testing.assert_allclose(stochastic.plan.grid_kwh, deterministic.grid_kwh, atol=1e-5)
        np.testing.assert_allclose(stochastic.plan.charge_kwh, deterministic.charge_kwh, atol=1e-5)


if __name__ == "__main__":
    unittest.main()
