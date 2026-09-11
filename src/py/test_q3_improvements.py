import datetime as dt
import unittest

import numpy as np

import q3_model as q3


def fake_forecast(values):
    item = q3.PvForecast3.__new__(q3.PvForecast3)
    day = dt.date(2025, 1, 1)
    item.data = {(day, 0): np.asarray(values, dtype=float)}
    item.days = [day]
    return item, day


class Question3ImprovementTests(unittest.TestCase):
    def test_pv_mapping_keeps_legacy_step_default(self):
        forecast, day = fake_forecast(np.arange(24, dtype=float) * 60.0)
        mapped = forecast.pv_kwh(day, 0, 0, 12)
        self.assertTrue(np.allclose(mapped[:6], 0.0))
        self.assertTrue(np.allclose(mapped[6:], 10.0))

    def test_pv_linear_interpolation_is_nonnegative_and_aligned(self):
        forecast, day = fake_forecast(np.arange(24, dtype=float) * 60.0)
        mapped = forecast.pv_kwh(day, 0, 0, 7, interpolation="linear")
        self.assertTrue(np.allclose(mapped, np.arange(7, dtype=float) / 6.0 * 10.0))
        forecast, day = fake_forecast([-10.0] * 24)
        self.assertTrue(np.all(forecast.pv_kwh(day, 0, 0, 7, interpolation="linear") == 0.0))

    def test_pv_mapping_rejects_unknown_interpolation(self):
        forecast, day = fake_forecast(np.ones(24))
        with self.assertRaisesRegex(ValueError, "interpolation"):
            forecast.pv_kwh(day, 0, 0, 1, interpolation="spline")

    def test_segment_lp_supports_terminal_value(self):
        price = np.ones(2)
        load = np.zeros(2)
        pv = np.zeros(2)
        scenario = [np.zeros(2)]
        fixed = q3.seg_lp(price, None, load, pv, 6000.0, scenario, np.ones(1), mode="plan",
                          terminal_min=6000.0, terminal_max=6000.0)
        self.assertAlmostEqual(fixed["e"][-1], 6000.0)
        valued = q3.seg_lp(price, None, load, pv, 6000.0, scenario, np.ones(1), mode="plan",
                           terminal_min=1200.0, terminal_max=10800.0, terminal_value=2.0)
        self.assertAlmostEqual(valued["e"][-1], 7500.0)


if __name__ == "__main__":
    unittest.main()
