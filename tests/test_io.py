import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

from hcp.api import ApiServer
from hcp.config import Config, ConfigError, SensorConfig, ValveConfig, load_config
from hcp.history import EventLog, History
from hcp.relay import FakeRelay
from hcp.sensors import DS18B20Source, SensorError, SensorService, parse_w1_slave
from hcp.state_store import StateStore
from hcp.valve import Valve
from tests.helpers import make_controller

GOOD = ["72 01 4b 46 7f ff 0e 10 57 : crc=57 YES\n", "72 01 4b 46 7f ff 0e 10 57 t=23125\n"]


class SensorTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.cfg = SensorConfig(w1_dir=self.dir, crc_retries=2)

    def write(self, sensor_id, lines):
        os.makedirs(os.path.join(self.dir, sensor_id), exist_ok=True)
        with open(os.path.join(self.dir, sensor_id, "w1_slave"), "w") as f:
            f.writelines(lines)

    def test_parse(self):
        self.assertEqual(parse_w1_slave(GOOD), 23125)
        for bad in ([], [GOOD[0].replace("YES", "NO"), GOOD[1]], [GOOD[0], "no value\n"],
                    [GOOD[0], "t=abc\n"]):
            with self.assertRaises(SensorError):
                parse_w1_slave(bad)

    def test_source_errors_are_bounded(self):
        src = DS18B20Source(self.cfg)
        self.write("28-a", GOOD)
        self.assertAlmostEqual(src.read("28-a"), 23.125)
        self.write("28-b", [GOOD[0].replace("YES", "NO"), GOOD[1]])
        with self.assertRaises(SensorError):
            src.read("28-b")  # CRC failures give up instead of looping forever
        self.write("28-c", [GOOD[0], "x t=85000\n"])
        with self.assertRaises(SensorError):
            src.read("28-c")
        self.write("28-d", [GOOD[0], "x t=127000\n"])
        with self.assertRaises(SensorError):
            src.read("28-d")
        with self.assertRaises(SensorError):
            src.read("28-missing")

    def test_service_survives_a_dead_sensor(self):
        for i, role in enumerate(self.cfg.ids):
            self.cfg.ids[role] = f"28-{i}"
            if i:
                self.write(f"28-{i}", GOOD)
        service = SensorService(self.cfg, DS18B20Source(self.cfg))
        r = service.read_once()
        values = [r.get(role, r.taken_at, 60) for role in self.cfg.ids]
        self.assertIsNone(values[0])
        self.assertEqual(values[1:], [23.125] * 4)
        self.assertIsNone(r.get("mainReturn", r.taken_at + 61, 60))  # stale


class ValveTest(unittest.TestCase):
    def make(self, position=10, calibrated=True):
        self.saved = []
        cfg = ValveConfig(pulse_seconds=0, direction_change_pause_seconds=0)
        self.relay = FakeRelay()
        return Valve(self.relay, cfg, position, calibrated, 25,
                     persist=lambda p, c, o: self.saved.append((p, c)))

    def test_clamps_to_stroke(self):
        v = self.make()
        v.move_to(-500)
        self.assertEqual((v.absolute, v.position), (0, -25))
        v.move_to(1000)
        self.assertEqual((v.absolute, v.position), (120, 95))
        v.move_to(0)
        self.assertEqual(v.absolute, 25)
        self.assertEqual(self.relay.active, None)

    def test_close_fully_recalibrates(self):
        v = self.make(position=50, calibrated=False)
        v.close_fully()
        self.assertEqual((v.absolute, v.position, v.calibrated), (0, -25, True))
        self.assertEqual(self.relay.history, ["down", "off"])
        self.assertEqual(self.saved[-1], (0, True))

    def test_relay_released_on_abort(self):
        stop = threading.Event()
        cfg = ValveConfig(pulse_seconds=0, direction_change_pause_seconds=0)
        relay = FakeRelay()
        v = Valve(relay, cfg, 10, True, 0, persist=lambda p, c, o: None, stop_event=stop)
        stop.set()
        v.step(5)
        self.assertEqual(v.position, 10)
        self.assertIsNone(relay.active)


class StateAndConfigTest(unittest.TestCase):
    def test_atomic_roundtrip_and_corrupt_file(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "state.json")
        StateStore(path, 50).update(mode="manual", target_temperature=55)
        self.assertEqual(StateStore(path, 50).snapshot().mode, "manual")
        with open(path, "w") as f:
            f.write("{broken")
        s = StateStore(path, 50).snapshot()
        self.assertEqual((s.mode, s.target_temperature, s.valve_calibrated), ("auto", 50, False))
        for bad in ("null", '{"valve_position": "x", "valve_calibrated": true, "mode": "manual"}'):
            with open(path, "w") as f:
                f.write(bad)
            s = StateStore(path, 50).snapshot()
            self.assertEqual((s.valve_position, s.valve_calibrated), (0, False))

    def test_legacy_migration(self):
        d = tempfile.mkdtemp()
        legacy = os.path.join(d, "settings")
        os.makedirs(legacy)
        with open(os.path.join(legacy, "target_temperature.txt"), "w") as f:
            f.write("48\n")
        s = StateStore(os.path.join(d, "state.json"), 50, legacy).snapshot()
        self.assertEqual((s.mode, s.target_temperature), ("off", 48))

    def test_config_overrides_and_rejects_typos(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "config.json")
        with open(path, "w") as f:
            json.dump({"http": {"port": 9000}, "sensors": {"ids": {"mainInlet": "28-x"}}, "data_dir": "data"}, f)
        cfg = load_config(path)
        self.assertEqual(cfg.http.port, 9000)
        self.assertEqual(cfg.sensors.ids["mainInlet"], "28-x")
        self.assertEqual(cfg.sensors.ids["mainReturn"], Config().sensors.ids["mainReturn"])
        self.assertEqual(cfg.data_dir, os.path.join(d, "data"))
        with open(path, "w") as f:
            json.dump({"http": {"prot": 1}}, f)
        with self.assertRaises(ConfigError):
            load_config(path)
        for bad in ({"valve": {"auto_min": 80}}, {"valve": {"full_stroke_pulses": 120.5}},
                    {"valve": {"direction_change_pause_seconds": -1}}, {"sensors": {"ids": "x"}},
                    {"sensors": {"stale_after_seconds": float("nan")}}, {"mqtt": {"enabled": 1}},
                    {"http": {"host": 5}}):
            with open(path, "w") as f:
                json.dump(bad, f)
            with self.assertRaises(ConfigError, msg=bad):
                load_config(path)
        with open(path, "w") as f:
            json.dump({"valve": {"full_stroke_pulses": 120.0}}, f)
        self.assertIsInstance(load_config(path).valve.full_stroke_pulses, int)


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.ctl, *_ = make_controller()
        self.server = ApiServer("127.0.0.1", 0, self.ctl, History(1, 10), EventLog())
        self.server.start()
        self.base = f"http://127.0.0.1:{self.server.port}"

    def tearDown(self):
        self.server.stop()

    def call(self, method, path, body=None, raw=None):
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method=method)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_status_and_commands(self):
        status, body = self.call("GET", "/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(body["mode"], "auto")
        self.assertEqual(set(body["temperatures"]), set(Config().sensors.ids))
        self.assertEqual(self.call("PUT", "/api/target", {"temperature": 55})[1]["target_temperature"], 55)
        self.assertEqual(self.call("PUT", "/api/mode", {"mode": "manual"})[1]["mode"], "manual")
        status, body = self.call("POST", "/api/valve/move", {"steps": 3})
        self.assertEqual((status, body["valve"]["manual_target"]), (202, 18))
        self.assertEqual(self.call("POST", "/api/valve/calibrate", {})[0], 202)
        self.assertEqual(self.call("POST", "/api/valve/zero/jog", {"steps": 1})[0], 409)
        status, body = self.call("POST", "/api/valve/zero/start", {})
        self.assertEqual((status, body["phase"]), (202, "zero_calibration"))
        self.assertEqual(self.call("POST", "/api/valve/zero/set", {})[0], 409)  # still closing
        self.assertEqual(self.call("POST", "/api/valve/zero/cancel", {})[0], 202)
        self.assertEqual(self.call("GET", "/api/history?hours=1")[0], 200)
        self.assertEqual(self.call("GET", "/api/events")[0], 200)

    def test_errors(self):
        self.assertEqual(self.call("GET", "/nope")[0], 404)
        self.assertEqual(self.call("POST", "/api/status")[0], 405)
        self.assertEqual(self.call("PUT", "/api/mode", {"mode": "turbo"})[0], 400)
        self.assertEqual(self.call("PUT", "/api/target", raw=b"not json")[0], 400)
        self.assertEqual(self.call("PUT", "/api/target", {"temperature": 200})[0], 400)
        self.assertEqual(self.call("POST", "/api/valve/move", {"steps": 1})[0], 409)  # not manual
        self.assertEqual(self.call("GET", "/api/history?hours=abc")[0], 400)
        self.assertEqual(self.call("PUT", "/api/target", {"temperature": 10 ** 400})[0], 400)


if __name__ == "__main__":
    unittest.main()
