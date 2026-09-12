import unittest

import numpy as np

import q3_model as q3


class RiskFeasibleRegionTests(unittest.TestCase):
    def test_high_demand_scenario_can_be_covered_by_advance_purchase(self):
        result = q3.seg_lp(
            price=np.array([1.0]),
            q_plan=None,
            l_fc=np.array([100.0]),
            v_fc=np.array([0.0]),
            e_start=q3.DEFAULT_PARAMS.e0,
            scen_net=[np.array([200.0])],
            weights=np.array([1.0]),
            mode="plan",
        )

        self.assertAlmostEqual(result["q"][0], 200.0, places=6)
        self.assertAlmostEqual(result["exp_emg_cost"], 0.0, places=6)
        self.assertAlmostEqual(result["fee"], 200.0, places=6)


if __name__ == "__main__":
    unittest.main()
