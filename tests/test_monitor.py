import unittest

from hcp import monitor as mon
from hcp.config import MonitorConfig
from tests.helpers import NORMAL


def names(events):
    return [e.name for e in events]


class MonitorTest(unittest.TestCase):
    def setUp(self):
        self.m = mon.Monitor(MonitorConfig())
        self.now = 0.0

    def feed(self, **temps):
        self.now += 15
        return names(self.m.update({**NORMAL, **temps}, self.now))

    def test_overheat_needs_a_rising_trend_and_latches_with_hysteresis(self):
        self.assertEqual(self.feed(heatingInlet=66), [])  # not a full trend window yet
        for t in (67, 68, 69, 70):
            events = self.feed(heatingInlet=t)
        self.assertIn(mon.OVERHEAT_START, events)
        self.assertTrue(self.m.overheat)
        self.assertEqual(self.feed(heatingInlet=50), [])  # still latched above 45
        self.assertEqual(self.feed(heatingInlet=44), [mon.OVERHEAT_END])
        self.assertFalse(self.m.overheat)

    def test_flat_samples_are_not_rising(self):
        for t in (66, 67, 67, 68, 69):
            events = self.feed(heatingInlet=t)
        self.assertNotIn(mon.OVERHEAT_START, events)

    def test_missing_sample_breaks_trend(self):
        for t in (66, 67):
            self.feed(heatingInlet=t)
        self.feed(heatingInlet=None)
        for t in (68, 69, 70):
            events = self.feed(heatingInlet=t)
        self.assertNotIn(mon.OVERHEAT_START, events)

    def test_getting_hot_fires_only_below_overheat(self):
        for t in (52, 53, 54, 55, 56):
            events = self.feed(heatingInlet=t)
        self.assertEqual(events, [mon.HEATING_GETTING_HOT])

    def test_no_consumption_latches_once(self):
        self.assertEqual(self.feed(mainInlet=70, mainReturn=68), [mon.NO_CONSUMPTION_START])
        self.assertEqual(self.feed(mainInlet=70, mainReturn=68), [])
        self.assertEqual(self.feed(mainInlet=70, mainReturn=63), [mon.NO_CONSUMPTION_END])  # delta 7 > 5
        self.assertFalse(self.m.no_consumption)

    def test_water_tank_detect_and_timeout(self):
        for w in (61, 62, 63, 64, 65):
            events = self.feed(mainInlet=75, mainReturn=60, waterInlet=w)
        self.assertEqual(events, [mon.WATER_TANK_START])
        self.assertTrue(self.m.water_tank)
        self.now += 91 * 60
        self.assertEqual(self.feed(mainInlet=75, mainReturn=60, waterInlet=66), [mon.WATER_TANK_END])

    def test_no_consumption_ends_water_tank(self):
        for w in (61, 62, 63, 64, 65):
            self.feed(mainInlet=75, mainReturn=60, waterInlet=w)
        events = self.feed(mainInlet=70, mainReturn=68, waterInlet=66)
        self.assertEqual(events, [mon.NO_CONSUMPTION_START, mon.WATER_TANK_END])

    def _start_water_tank(self):
        for w in (61, 62, 63, 64, 65):
            self.feed(mainInlet=75, mainReturn=60, waterInlet=w)
        self.assertTrue(self.m.water_tank)

    def test_water_tank_ends_when_tank_is_hot(self):
        self._start_water_tank()
        self.assertEqual(self.feed(mainInlet=75, mainReturn=72, waterInlet=66), [])  # too soon
        self.now += 5 * 60
        self.assertEqual(self.feed(mainInlet=75, mainReturn=72, waterInlet=66), [mon.WATER_TANK_END])

    def test_water_tank_ends_when_water_inlet_falls(self):
        self._start_water_tank()
        self.now += 5 * 60
        for w in (66, 65.5, 65, 64.5):
            self.assertEqual(self.feed(mainInlet=75, mainReturn=60, waterInlet=w), [])
        self.assertEqual(self.feed(mainInlet=75, mainReturn=60, waterInlet=63.9), [mon.WATER_TANK_END])

    def test_small_water_inlet_wobble_keeps_water_tank(self):
        self._start_water_tank()
        self.now += 5 * 60
        for w in (66, 65.9, 65.8, 65.7, 65.6, 65.7):
            self.assertEqual(self.feed(mainInlet=75, mainReturn=60, waterInlet=w), [])
        self.assertTrue(self.m.water_tank)

    def test_missing_main_sensors_skip_checks(self):
        self.assertEqual(self.feed(mainInlet=None, mainReturn=None), [])


if __name__ == "__main__":
    unittest.main()
