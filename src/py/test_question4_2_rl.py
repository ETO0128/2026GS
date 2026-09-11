"""Small deterministic tests for the safe Question 4-2 RL layer."""
import unittest
from datetime import date

import numpy as np

from question4_2_data import Question42Data
from question4_2_rl import KnownDay, RESERVES, state_of, step


class Question42RLTests(unittest.TestCase):
    def test_state_uses_only_known_features(self):
        data = Question42Data((date(2025, 1, 1),), np.arange(0, 1440, 10),
                              np.ones((1, 144)), np.ones((1, 144)), np.zeros((1, 144)))
        day = KnownDay(0, np.ones(144), np.linspace(0.2, 1.2, 144),
                       np.full(144, 99.0), np.ones(144), np.zeros(144))
        before = state_of(data, day, 6000.0, 0.08)
        changed = KnownDay(0, day.net_kw, day.predicted_price, np.full(144, 1.0),
                           np.full(144, 9999.0), day.actual_pv)
        self.assertEqual(before, state_of(data, changed, 6000.0, 0.08))

    def test_action_is_safe_lp_parameter_not_power_vector(self):
        self.assertEqual(RESERVES.shape, (5,))
        self.assertTrue(np.all((RESERVES >= 1200.0) & (RESERVES <= 10800.0)))


if __name__ == "__main__":
    unittest.main()
