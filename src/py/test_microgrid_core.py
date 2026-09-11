"""Deterministic checks for the shared microgrid dispatch solver."""

from __future__ import annotations

import unittest

import numpy as np

from microgrid_core import DispatchInput, StorageParameters, solve_dispatch


class DispatchSolverTests(unittest.TestCase):
    def test_solver_accepts_carried_initial_soc_and_terminal_floor(self) -> None:
        """A carried state and terminal reserve define physical boundary states."""

        inputs = DispatchInput(
            price_yuan_per_kwh=np.ones(144),
            load_kwh=np.full(144, 100.0),
            pv_kwh=np.zeros(144),
        )

        result = solve_dispatch(
            inputs,
            StorageParameters(),
            initial_soc_kwh=7200.0,
            terminal_soc_min_kwh=6000.0,
        )

        self.assertAlmostEqual(result.soc_kwh[0], 7200.0, places=6)
        self.assertGreaterEqual(result.soc_kwh[-1], 6000.0 - 1e-6)


if __name__ == "__main__":
    unittest.main()
