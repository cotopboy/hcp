import os
import tempfile
import time

from hcp.config import SENSOR_ROLES, Config
from hcp.controller import Controller
from hcp.history import EventLog
from hcp.relay import FakeRelay, RelayError
from hcp.sensors import Readings, SensorValue
from hcp.state_store import StateStore
from hcp.valve import Valve


class FakeSensors:
    def __init__(self, **temps):
        self.seq = 0
        self.set(**temps)

    def set(self, **temps):
        """Publish a new sample. Roles not given keep their value; pass None for a dead sensor."""
        now = time.time()
        old = getattr(self, "_readings", None)
        values = {}
        for role in SENSOR_ROLES:
            if role in temps:
                v = temps[role]
                values[role] = SensorValue(v, now if v is not None else None, None if v is not None else "dead")
            else:
                values[role] = old.values[role] if old else SensorValue(40.0, now, None)
        self.seq += 1
        self._readings = Readings(self.seq, now, values)

    def latest(self):
        return self._readings


class FailingRelay(FakeRelay):
    def __init__(self):
        super().__init__()
        self.fail = False

    def energize(self, direction):
        if self.fail:
            raise RelayError("bus error")
        super().energize(direction)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


NORMAL = dict(mainInlet=75.0, mainReturn=55.0, heatingInlet=45.0, heatingReturn=38.0, waterInlet=45.0)


def make_controller(mode="auto", position=40, calibrated=True, temps=None, relay=None, **cfg_overrides):
    tmp = tempfile.mkdtemp()
    cfg = Config(data_dir=tmp)
    cfg.valve.pulse_seconds = 0
    cfg.valve.direction_change_pause_seconds = 0
    cfg.valve.calibrate_on_startup = False
    for key, value in cfg_overrides.items():
        section, name = key.split("__")
        setattr(getattr(cfg, section), name, value)
    store = StateStore(os.path.join(tmp, "state.json"), cfg.control.default_target)
    store.update(mode=mode, valve_position=position, valve_calibrated=calibrated)
    relay = relay or FakeRelay()
    valve = Valve(relay, cfg.valve, position, calibrated,
                  persist=lambda p, c: store.update(valve_position=p, valve_calibrated=c))
    sensors = FakeSensors(**(temps or NORMAL))
    clock = Clock()
    ctl = Controller(cfg, sensors, valve, store, EventLog(), clock=clock)
    return ctl, sensors, clock, relay, store
