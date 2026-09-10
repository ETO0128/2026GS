"""Small deterministic checks for the Question 1 optimizer."""

from __future__ import annotations

import unittest

import numpy as np

from question1 import (
    INITIAL_SOC_KWH,
    SLOT_MINUTES,
    Question1Data,
    solve_question1,
)


class Question1SolverTests(unittest.TestCase):
    def test_flat_price_without_pv_does_not_cycle_battery(self) -> None:
        minutes = np.arange(0, 1440, SLOT_MINUTES, dtype=int)
        data = Question1Data(
            minute_of_day=minutes,
            price_yuan_per_kwh=np.ones(144),
            load_kw=np.full(144, 1000.0),
            pv_kw=np.zeros(144),
        )

        solution = solve_question1(data)

        np.testing.assert_allclose(solution.grid_kwh, data.load_kwh, atol=1e-5)
        np.testing.assert_allclose(solution.charge_kwh, 0.0, atol=1e-5)
        np.testing.assert_allclose(solution.discharge_kwh, 0.0, atol=1e-5)
        self.assertAlmostEqual(solution.soc_kwh[0], INITIAL_SOC_KWH, places=5)
        self.assertAlmostEqual(solution.soc_kwh[-1], INITIAL_SOC_KWH, places=5)


if __name__ == "__main__":
    unittest.main()
