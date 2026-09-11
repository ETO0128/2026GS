"""Tests for Question 4-2 causal dispatch and realized settlement."""

from __future__ import annotations

import unittest
from datetime import date

import numpy as np

from question4_2_dispatch import (
    dispatch_regret_yuan,
    plan_causal_day,
    settle_causal_plan,
    solve_perfect_information_day,
)


RUN_DATE = date(2025, 2, 1)


class Question42DispatchTests(unittest.TestCase):
    def test_causal_plan_uses_forecast_curves_and_respects_physics(self) -> None:
        plan = plan_causal_day(
            RUN_DATE,
            forecast_net_kw=np.full(144, 600.0),
            forecast_price_yuan_per_kwh=np.ones(144),
            initial_soc_kwh=6000.0,
            reserve_kwh=6000.0,
        )

        np.testing.assert_allclose(plan.grid_kwh, np.full(144, 100.0), atol=1e-6)
        np.testing.assert_allclose(plan.charge_kwh, 0.0, atol=1e-6)
        np.testing.assert_allclose(plan.discharge_kwh, 0.0, atol=1e-6)
        self.assertAlmostEqual(plan.soc_kwh[0], 6000.0)
        self.assertGreaterEqual(plan.soc_kwh[-1], 6000.0 - 1e-6)
        self.assertAlmostEqual(plan.predicted_cost_yuan, 14_400.0, places=4)

    def test_realized_shortfall_uses_five_times_actual_price(self) -> None:
        plan = plan_causal_day(
            RUN_DATE,
            forecast_net_kw=np.zeros(144),
            forecast_price_yuan_per_kwh=np.ones(144),
            initial_soc_kwh=6000.0,
        )
        actual_load_kw = np.zeros(144)
        actual_load_kw[8] = 6.0
        actual_price = np.full(144, 2.0)
        execution = settle_causal_plan(
            plan,
            actual_load_kw=actual_load_kw,
            actual_pv_kw=np.zeros(144),
            actual_price_yuan_per_kwh=actual_price,
        )

        self.assertAlmostEqual(execution.emergency_kwh[8], 1.0)
        self.assertAlmostEqual(execution.emergency_cost_yuan, 10.0)
        self.assertAlmostEqual(execution.normal_purchase_cost_yuan, 0.0)
        self.assertAlmostEqual(execution.total_cost_yuan, 10.0)

    def test_normal_purchase_is_settled_at_actual_not_forecast_price(self) -> None:
        plan = plan_causal_day(
            RUN_DATE,
            forecast_net_kw=np.full(144, 600.0),
            forecast_price_yuan_per_kwh=np.ones(144),
            initial_soc_kwh=6000.0,
        )
        execution = settle_causal_plan(
            plan,
            actual_load_kw=np.full(144, 600.0),
            actual_pv_kw=np.zeros(144),
            actual_price_yuan_per_kwh=np.full(144, 2.0),
        )

        self.assertAlmostEqual(execution.normal_purchase_cost_yuan, 28_800.0, places=4)
        self.assertAlmostEqual(execution.emergency_cost_yuan, 0.0, places=4)
        self.assertNotEqual(execution.normal_purchase_cost_yuan, plan.predicted_cost_yuan)

    def test_perfect_information_is_a_lower_bound_for_same_day_state(self) -> None:
        forecast_price = np.ones(144)
        actual_price = np.concatenate((np.full(72, 0.2), np.ones(72)))
        load_kw = np.full(144, 600.0)
        plan = plan_causal_day(
            RUN_DATE,
            forecast_net_kw=load_kw,
            forecast_price_yuan_per_kwh=forecast_price,
            initial_soc_kwh=6000.0,
        )
        execution = settle_causal_plan(
            plan,
            actual_load_kw=load_kw,
            actual_pv_kw=np.zeros(144),
            actual_price_yuan_per_kwh=actual_price,
        )
        perfect = solve_perfect_information_day(
            RUN_DATE,
            actual_load_kw=load_kw,
            actual_pv_kw=np.zeros(144),
            actual_price_yuan_per_kwh=actual_price,
            initial_soc_kwh=6000.0,
        )

        self.assertEqual(perfect.information_scope, "realized_day_oracle")
        self.assertLessEqual(perfect.total_cost_yuan, execution.total_cost_yuan + 1e-5)
        self.assertAlmostEqual(
            dispatch_regret_yuan(execution, perfect),
            execution.total_cost_yuan - perfect.total_cost_yuan,
        )


if __name__ == "__main__":
    unittest.main()
