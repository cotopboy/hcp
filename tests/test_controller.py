import unittest

from hcp.config import ControlConfig
from hcp.controller import (DOWN, HOLD, PHASE_OVERHEAT, PHASE_RELAY_FAULT, PHASE_SENSOR_FAULT, UP,
                            CommandError, decide)
from tests.helpers import NORMAL, FailingRelay, make_controller


def temps(**kw):
    return {**NORMAL, **kw}


class DecideTest(unittest.TestCase):
    c = ControlConfig()

    def test_rule_table(self):
        self.assertEqual(decide(temps(mainReturn=55, heatingInlet=35), 50, self.c)[0], HOLD)
        self.assertEqual(decide(temps(mainReturn=49, heatingInlet=35), 50, self.c)[0], UP)
        self.assertEqual(decide(temps(mainReturn=55, heatingInlet=25), 50, self.c)[0], UP)
        self.assertEqual(decide(temps(mainReturn=61, heatingInlet=30), 50, self.c)[0], DOWN)
        self.assertEqual(decide(temps(mainReturn=55, heatingInlet=40), 50, self.c)[0], DOWN)  # sum 95

    def test_down_overrides_up(self):
        # heating inlet below 30 says up, main return above target + 10 says down
        self.assertEqual(decide(temps(mainReturn=65, heatingInlet=20), 50, self.c)[0], DOWN)


class ControllerTest(unittest.TestCase):
    def test_startup_calibrates_then_opens_to_ready(self):
        ctl, sensors, clock, relay, store = make_controller(position=50, calibrated=False)
        ctl.tick()
        self.assertEqual(ctl.valve.position, ctl.cfg.valve.ready_position)
        self.assertTrue(ctl.valve.calibrated)
        self.assertEqual(store.snapshot().valve_position, ctl.cfg.valve.ready_position)
        self.assertEqual(relay.history[-1], "off")

    def test_auto_steps_up_then_waits(self):
        ctl, sensors, clock, relay, _ = make_controller(position=40, temps=temps(mainReturn=45, heatingInlet=40))
        ctl.tick()
        self.assertEqual(ctl.valve.position, 41)
        clock.advance(30)
        ctl.tick()
        self.assertEqual(ctl.valve.position, 41)  # waits 15 + 60 s after opening
        clock.advance(46)
        ctl.tick()
        self.assertEqual(ctl.valve.position, 42)

    def test_auto_respects_limits(self):
        ctl, sensors, clock, _, _ = make_controller(position=35, temps=temps(mainReturn=65, heatingInlet=40))
        ctl.tick()
        self.assertEqual(ctl.valve.position, 35)
        self.assertTrue(ctl.status()["last_decision"]["at_limit"])

    def test_target_change_applies_immediately(self):
        ctl, sensors, clock, _, store = make_controller(position=40, temps=temps(mainReturn=55, heatingInlet=35))
        ctl.tick()
        self.assertEqual(ctl.valve.position, 40)
        ctl.set_target(60)
        ctl.tick()
        self.assertEqual(ctl.valve.position, 41)
        self.assertEqual(store.snapshot().target_temperature, 60)

    def test_target_validation(self):
        ctl, *_ = make_controller()
        for bad in (None, "50", 50.5, True, 10, 99, float("nan"), float("inf")):
            with self.assertRaises(CommandError):
                ctl.set_target(bad)

    def test_off_closes_fully(self):
        ctl, sensors, clock, relay, store = make_controller(position=40)
        ctl.set_mode("off")
        ctl.tick()
        self.assertEqual(ctl.valve.position, 0)
        self.assertEqual(store.snapshot().mode, "off")
        clock.advance(100)
        ctl.tick()
        self.assertEqual(ctl.valve.position, 0)

    def test_manual_move_only_in_manual_mode(self):
        ctl, sensors, clock, *_ = make_controller(position=40)
        with self.assertRaises(CommandError):
            ctl.manual_move(steps=5)
        ctl.set_mode("manual")
        ctl.manual_move(steps=10)
        for _ in range(5):
            ctl.tick()
        self.assertEqual(ctl.valve.position, 50)
        ctl.manual_move(position=500)
        for _ in range(30):
            ctl.tick()
        self.assertEqual(ctl.valve.position, ctl.cfg.valve.full_stroke_pulses)

    def test_manual_rejects_bad_input(self):
        ctl, *_ = make_controller(mode="manual")
        for kwargs in ({}, {"steps": 1, "position": 2}, {"steps": "1"}, {"position": 1.5}):
            with self.assertRaises(CommandError):
                ctl.manual_move(**kwargs)

    def _heat_up(self, ctl, sensors, clock):
        for t in (66, 67, 68, 69, 70):
            sensors.set(heatingInlet=t)
            clock.advance(16)
            ctl.tick()

    def test_overheat_protects_in_manual_mode(self):
        ctl, sensors, clock, *_ = make_controller(mode="manual", position=80)
        self._heat_up(ctl, sensors, clock)
        self.assertEqual(ctl.phase(), PHASE_OVERHEAT)
        self.assertEqual(ctl.valve.position, ctl.cfg.valve.reduced_position)
        with self.assertRaises(CommandError):
            ctl.manual_move(steps=1)
        ctl.manual_move(steps=-1)

    def test_overheat_clamps_existing_manual_target(self):
        ctl, sensors, clock, relay, _ = make_controller(mode="manual", position=40)
        ctl.manual_move(position=60)
        for _ in range(10):
            ctl.tick()
        self.assertEqual(ctl.valve.position, 60)
        self._heat_up(ctl, sensors, clock)
        relay.history.clear()
        for _ in range(5):
            ctl.tick()
        self.assertEqual(ctl.valve.position, 25)
        self.assertEqual(relay.history, [])  # no chatter back up toward the old target

    def test_overheat_in_auto_pauses_then_resumes(self):
        ctl, sensors, clock, *_ = make_controller(position=60)
        self._heat_up(ctl, sensors, clock)
        self.assertEqual(ctl.valve.position, 25)
        clock.advance(200)
        ctl.tick()
        self.assertEqual(ctl.valve.position, 25)  # held while overheat is latched
        sensors.set(heatingInlet=40, mainReturn=45)
        clock.advance(16)
        ctl.tick()
        self.assertGreater(ctl.valve.position, 25)  # resumed: opened to ready and stepped up

    def test_missing_sensor_holds_valve(self):
        ctl, sensors, clock, *_ = make_controller(position=40, temps=temps(mainReturn=None))
        ctl.tick()
        self.assertEqual(ctl.phase(), PHASE_SENSOR_FAULT)
        self.assertEqual(ctl.valve.position, 40)
        self.assertTrue(any(a["code"] == "sensor_fault" for a in ctl.status()["alarms"]))

    def test_relay_fault_is_reported_and_retried(self):
        relay = FailingRelay()
        ctl, sensors, clock, *_ = make_controller(position=40, relay=relay,
                                                  temps=temps(mainReturn=45, heatingInlet=40))
        relay.fail = True
        ctl.step()
        self.assertEqual(ctl.phase(), PHASE_RELAY_FAULT)
        self.assertFalse(ctl.valve.calibrated)
        self.assertIsNone(relay.active)
        relay.fail = False
        clock.advance(61)
        ctl.step()
        self.assertNotEqual(ctl.phase(), PHASE_RELAY_FAULT)
        self.assertTrue(ctl.valve.calibrated)


if __name__ == "__main__":
    unittest.main()
