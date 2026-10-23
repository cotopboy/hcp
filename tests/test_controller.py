import unittest
from datetime import datetime

from hcp.config import ControlConfig
from hcp.controller import (DOWN, HOLD, PHASE_NIGHT_SAVER, PHASE_NORMAL, PHASE_OVERHEAT, PHASE_RELAY_FAULT,
                            PHASE_SENSOR_FAULT, PHASE_WATER_TANK, PHASE_ZERO_CALIBRATION, UP,
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
        ctl, sensors, clock, relay, store = make_controller(position=25, calibrated=False)
        ctl.tick()
        self.assertEqual(ctl.valve.position, ctl.cfg.valve.ready_position)
        self.assertTrue(ctl.valve.calibrated)
        self.assertEqual(store.snapshot().valve_position, ctl.cfg.valve.ready_position + 25)
        self.assertEqual(relay.history[-1], "off")

    def test_auto_steps_up_then_waits(self):
        ctl, sensors, clock, relay, _ = make_controller(position=15, temps=temps(mainReturn=45, heatingInlet=40))
        ctl.tick()
        self.assertEqual(ctl.valve.position, 16)
        clock.advance(30)
        ctl.tick()
        self.assertEqual(ctl.valve.position, 16)  # waits 15 + 60 s after opening
        clock.advance(46)
        ctl.tick()
        self.assertEqual(ctl.valve.position, 17)

    def test_auto_respects_limits(self):
        ctl, sensors, clock, _, _ = make_controller(position=10, temps=temps(mainReturn=65, heatingInlet=40))
        ctl.tick()
        self.assertEqual(ctl.valve.position, 10)
        self.assertTrue(ctl.status()["last_decision"]["at_limit"])

    def test_target_change_applies_immediately(self):
        ctl, sensors, clock, _, store = make_controller(position=15, temps=temps(mainReturn=55, heatingInlet=35))
        ctl.tick()
        self.assertEqual(ctl.valve.position, 15)
        ctl.set_target(60)
        ctl.tick()
        self.assertEqual(ctl.valve.position, 16)
        self.assertEqual(store.snapshot().target_temperature, 60)

    def test_target_validation(self):
        ctl, *_ = make_controller()
        for bad in (None, "50", 50.5, True, 10, 99, float("nan"), float("inf")):
            with self.assertRaises(CommandError):
                ctl.set_target(bad)

    def test_off_closes_fully(self):
        ctl, sensors, clock, relay, store = make_controller(position=15)
        ctl.set_mode("off")
        ctl.tick()
        self.assertEqual(ctl.valve.position, 0)  # closed to the zero point, not the end stop
        self.assertEqual(store.snapshot().valve_position, 25)
        self.assertEqual(store.snapshot().mode, "off")
        clock.advance(100)
        ctl.tick()
        self.assertEqual(ctl.valve.position, 0)

    def test_manual_move_only_in_manual_mode(self):
        ctl, sensors, clock, *_ = make_controller(position=15)
        with self.assertRaises(CommandError):
            ctl.manual_move(steps=5)
        ctl.set_mode("manual")
        ctl.manual_move(steps=10)
        for _ in range(5):
            ctl.tick()
        self.assertEqual(ctl.valve.position, 25)
        ctl.manual_move(position=500)
        for _ in range(30):
            ctl.tick()
        self.assertEqual(ctl.valve.position, ctl.valve.max_position)

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
        ctl, sensors, clock, *_ = make_controller(mode="manual", position=55)
        self._heat_up(ctl, sensors, clock)
        self.assertEqual(ctl.phase(), PHASE_OVERHEAT)
        self.assertEqual(ctl.valve.position, ctl.cfg.valve.reduced_position)
        with self.assertRaises(CommandError):
            ctl.manual_move(steps=1)
        ctl.manual_move(steps=-1)

    def test_overheat_clamps_existing_manual_target(self):
        ctl, sensors, clock, relay, _ = make_controller(mode="manual", position=15)
        ctl.manual_move(position=35)
        for _ in range(10):
            ctl.tick()
        self.assertEqual(ctl.valve.position, 35)
        self._heat_up(ctl, sensors, clock)
        relay.history.clear()
        for _ in range(5):
            ctl.tick()
        self.assertEqual(ctl.valve.position, 0)
        self.assertEqual(relay.history, [])  # no chatter back up toward the old target

    def test_overheat_in_auto_pauses_then_resumes(self):
        ctl, sensors, clock, *_ = make_controller(position=35)
        self._heat_up(ctl, sensors, clock)
        self.assertEqual(ctl.valve.position, 0)
        clock.advance(200)
        ctl.tick()
        self.assertEqual(ctl.valve.position, 0)  # held while overheat is latched
        sensors.set(heatingInlet=40, mainReturn=45)
        clock.advance(16)
        ctl.tick()
        self.assertGreater(ctl.valve.position, 0)  # resumed: opened to ready and stepped up

    def test_missing_sensor_holds_valve(self):
        ctl, sensors, clock, *_ = make_controller(position=15, temps=temps(mainReturn=None))
        ctl.tick()
        self.assertEqual(ctl.phase(), PHASE_SENSOR_FAULT)
        self.assertEqual(ctl.valve.position, 15)
        self.assertTrue(any(a["code"] == "sensor_fault" for a in ctl.status()["alarms"]))

    def test_relay_fault_is_reported_and_retried(self):
        relay = FailingRelay()
        ctl, sensors, clock, *_ = make_controller(position=15, relay=relay,
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


class WaterTankTest(unittest.TestCase):
    """The hot water controller opens our valve fully while the tank heats."""

    def start(self, ctl, sensors, clock):
        for w in (61, 62, 63, 64, 65):
            sensors.set(mainInlet=75, mainReturn=55, waterInlet=w)
            clock.advance(16)
            ctl.step()
        self.assertEqual(ctl.phase(), PHASE_WATER_TANK)

    def end(self, ctl, sensors, clock):
        clock.advance(5 * 60)
        sensors.set(mainInlet=75, mainReturn=72, waterInlet=66)  # tank hot: delta below 5
        ctl.step()
        self.assertNotEqual(ctl.phase(), PHASE_WATER_TANK)

    def test_hands_off_while_heating_then_recalibrates(self):
        ctl, sensors, clock, relay, _ = make_controller(position=15)
        self.start(ctl, sensors, clock)
        self.assertFalse(ctl.valve.calibrated)
        status = ctl.status()
        self.assertIsNotNone(status["water_tank"])
        self.assertNotIn("uncalibrated", [a["code"] for a in status["alarms"]])
        relay.history.clear()
        for _ in range(20):
            clock.advance(16)
            ctl.step()
        self.assertEqual(relay.history, [])  # never fights the other controller
        for command in (lambda: ctl.request_calibration(), lambda: ctl.start_zero_calibration()):
            with self.assertRaises(CommandError):
                command()

        self.end(ctl, sensors, clock)
        v = ctl.cfg.valve
        self.assertTrue(ctl.valve.calibrated)
        self.assertEqual(relay.history[0], DOWN)  # full close first: from fully open to the end stop
        self.assertEqual(ctl.phase(), PHASE_NORMAL)
        self.assertEqual(ctl.valve.position, v.ready_position)
        self.assertIsNone(ctl.status()["water_tank"])

    def test_mode_change_during_heating_waits(self):
        ctl, sensors, clock, relay, _ = make_controller(position=15)
        self.start(ctl, sensors, clock)
        ctl.set_mode("off")
        relay.history.clear()
        ctl.step()
        self.assertEqual(relay.history, [])
        self.end(ctl, sensors, clock)
        self.assertTrue(ctl.valve.calibrated)
        self.assertEqual(ctl.valve.position, 0)  # off: back to the zero point

    def test_manual_position_is_restored(self):
        ctl, sensors, clock, *_ = make_controller(mode="manual", position=30)
        self.start(ctl, sensors, clock)
        with self.assertRaises(CommandError):
            ctl.manual_move(steps=1)
        self.end(ctl, sensors, clock)
        for _ in range(20):
            ctl.step()
        self.assertTrue(ctl.valve.calibrated)
        self.assertEqual(ctl.valve.position, 30)

    def test_no_consumption_end_does_not_trust_old_count(self):
        ctl, sensors, clock, relay, _ = make_controller(position=15)
        self.start(ctl, sensors, clock)
        relay.history.clear()
        clock.advance(16)
        sensors.set(mainInlet=70, mainReturn=68, waterInlet=66)  # no consumption ends heating
        ctl.step()
        self.assertTrue(ctl.valve.calibrated)
        self.assertLessEqual(ctl.valve.position, ctl.cfg.valve.reduced_position)
        self.assertEqual(relay.history[:2], [DOWN, "off"])  # one full close, no partial move first


class ZeroCalibrationTest(unittest.TestCase):
    def run_ticks(self, ctl, n=3):
        for _ in range(n):
            ctl.step()

    def test_set_new_zero_point(self):
        ctl, sensors, clock, relay, store = make_controller(mode="off", position=0)
        ctl.start_zero_calibration()
        self.assertEqual(ctl.phase(), PHASE_ZERO_CALIBRATION)
        with self.assertRaises(CommandError):
            ctl.zero_jog(5)  # not closed yet
        ctl.step()
        self.assertEqual(ctl.valve.absolute, 0)
        self.assertEqual(ctl.status()["zero_calibration"]["stage"], "ready")
        ctl.zero_jog(5)
        ctl.zero_jog(5)
        ctl.zero_jog(-1)
        self.assertEqual(ctl.status()["zero_calibration"]["target"], 9)  # before the controller moves
        ctl.finish_zero_calibration()
        self.run_ticks(ctl)
        self.assertIsNone(ctl.status()["zero_calibration"])
        self.assertEqual(ctl.valve.zero_offset, 9)
        self.assertEqual(store.snapshot().valve_zero_offset, 9)
        self.assertEqual((ctl.valve.position, ctl.valve.absolute), (0, 9))  # off: back at the zero point

    def test_auto_positions_follow_zero_point(self):
        ctl, sensors, clock, *_ = make_controller(position=0, zero_offset=40)
        ctl.tick()
        self.assertEqual(ctl.valve.absolute, 40 + ctl.cfg.valve.ready_position)

    def test_cancel_keeps_offset_and_restores_mode(self):
        ctl, sensors, clock, *_ = make_controller(mode="auto", position=15)
        ctl.start_zero_calibration()
        ctl.step()
        ctl.zero_jog(3)
        ctl.cancel_zero_calibration()
        self.run_ticks(ctl)
        self.assertEqual(ctl.valve.zero_offset, 25)
        self.assertEqual(ctl.valve.position, ctl.cfg.valve.ready_position)  # auto re-entered

    def test_blocks_other_commands_and_times_out(self):
        ctl, sensors, clock, *_ = make_controller(mode="manual")
        ctl.start_zero_calibration()
        with self.assertRaises(CommandError):
            ctl.manual_move(steps=1)
        with self.assertRaises(CommandError):
            ctl.request_calibration()
        for bad in (0, 21, -21, "5", True, 2.5):
            with self.assertRaises(CommandError):
                ctl.zero_jog(bad)
        ctl.step()
        clock.advance(31 * 60)
        ctl.step()
        self.assertIsNone(ctl.status()["zero_calibration"])
        self.assertEqual(ctl.valve.zero_offset, 25)

    def test_offset_is_capped_so_auto_range_fits(self):
        ctl, *_ = make_controller(mode="off", position=0)
        ctl.start_zero_calibration()
        ctl.step()
        for _ in range(10):
            ctl.zero_jog(20)
        ctl.finish_zero_calibration()
        self.run_ticks(ctl)
        self.assertEqual(ctl.valve.zero_offset, ctl.max_zero_offset)
        self.assertLessEqual(ctl.valve.zero_offset + ctl.cfg.valve.auto_max, ctl.cfg.valve.full_stroke_pulses)


if __name__ == "__main__":
    unittest.main()


class NightSaverTest(unittest.TestCase):
    def setUp(self):
        self.ctl, self.sensors, self.clock, _, self.store = make_controller(
            position=15, temps=temps(mainReturn=55, heatingInlet=35))
        self.clock.wall = datetime(2026, 1, 15, 0, 29)

    def test_off_in_window_then_resumes_auto(self):
        ctl, clock = self.ctl, self.clock
        ctl.set_night_saver(True)
        self.assertTrue(self.store.snapshot().night_saver)
        ctl.tick()
        self.assertEqual(ctl.valve.position, 15)  # 00:29: still heating
        clock.advance(60)
        ctl.tick()
        self.assertEqual(ctl.valve.position, 0)
        self.assertEqual(ctl.phase(), PHASE_NIGHT_SAVER)
        self.assertEqual(ctl.mode, "auto")  # the stored mode is untouched
        self.assertTrue(ctl.status()["night_saver"]["active"])
        clock.advance(6 * 3600)  # 06:30
        ctl.tick()
        self.assertEqual(ctl.phase(), PHASE_NORMAL)
        self.assertGreaterEqual(ctl.valve.position, ctl.cfg.valve.ready_position)

    def test_disabled_does_nothing(self):
        self.clock.wall = datetime(2026, 1, 15, 3, 0)
        self.ctl.tick()
        self.assertEqual(self.ctl.valve.position, 15)
        self.assertFalse(self.ctl.status()["night_saver"]["active"])

    def test_disabling_at_night_resumes_now(self):
        ctl = self.ctl
        self.clock.wall = datetime(2026, 1, 15, 3, 0)
        ctl.set_night_saver(True)
        ctl.tick()
        self.assertEqual(ctl.valve.position, 0)
        ctl.set_night_saver(False)
        ctl.tick()
        self.assertEqual(ctl.phase(), PHASE_NORMAL)
        self.assertGreater(ctl.valve.position, 0)

    def test_manual_position_restored_and_moves_blocked(self):
        ctl, sensors, clock, _, store = make_controller(mode="manual", position=20)
        clock.wall = datetime(2026, 1, 15, 3, 0)
        ctl.set_night_saver(True)
        ctl.tick()
        self.assertEqual(ctl.valve.position, 0)
        with self.assertRaises(CommandError):
            ctl.manual_move(steps=1)
        clock.wall = datetime(2026, 1, 15, 6, 30)
        for _ in range(10):
            ctl.tick()
        self.assertEqual(ctl.valve.position, 20)

    def test_window_across_midnight(self):
        ctl, sensors, clock, _, _ = make_controller(position=15, night_saver__start="22:00",
                                                    night_saver__end="06:00")
        ctl.set_night_saver(True)
        for hour, active in ((21, False), (23, True), (2, True), (6, False)):
            clock.wall = datetime(2026, 1, 15, hour, 0)
            ctl.tick()
            self.assertEqual(ctl.status()["night_saver"]["active"], active, hour)

    def test_validation(self):
        with self.assertRaises(CommandError):
            self.ctl.set_night_saver("yes")
