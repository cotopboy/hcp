"""A crude plant model so the controller and the phone app can be exercised without hardware.

Run with ``python3 -m hcp --simulate``.  The boiler supplies ~75 °C; the heating
inlet follows the valve opening with a first-order lag.
"""

from __future__ import annotations

import random
import threading
import time

from .config import HEATING_INLET, HEATING_RETURN, MAIN_INLET, MAIN_RETURN, WATER_INLET


class SimulatedPlant:
    def __init__(self, sensor_ids: dict, valve_getter, max_position: int):
        self._role_by_id = {sensor_id: role for role, sensor_id in sensor_ids.items()}
        self._valve = valve_getter
        self._max = max_position
        self._lock = threading.Lock()
        self._last = time.monotonic()
        self.t = {MAIN_INLET: 75.0, MAIN_RETURN: 55.0, HEATING_INLET: 35.0,
                  HEATING_RETURN: 30.0, WATER_INLET: 45.0}

    def _advance(self) -> None:
        now = time.monotonic()
        dt, self._last = now - self._last, now
        opening = self._valve() / self._max
        k = min(1.0, dt / 120.0)
        t = self.t
        t[HEATING_INLET] += (25 + 55 * opening - t[HEATING_INLET]) * k
        t[HEATING_RETURN] += (t[HEATING_INLET] - 8 - t[HEATING_RETURN]) * k
        t[MAIN_RETURN] += (t[MAIN_INLET] - 8 - 25 * opening - t[MAIN_RETURN]) * k
        t[WATER_INLET] += (45 - t[WATER_INLET]) * k

    def read(self, sensor_id: str) -> float:
        with self._lock:
            self._advance()
            role = self._role_by_id[sensor_id]
            return round(self.t[role] + random.uniform(-0.1, 0.1), 3)

