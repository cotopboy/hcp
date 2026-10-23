"""DS18B20 temperature sensors.

A background thread reads every configured sensor periodically.  Failures are
contained per sensor: a broken, missing or implausible sensor yields ``None`` for
that role instead of crashing the thread, and readings older than
``stale_after_seconds`` are reported as missing.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from .config import SENSOR_ROLES, SensorConfig

log = logging.getLogger(__name__)

# 85.000 °C is the DS18B20 power-on reset value, not a measurement.
_POWER_ON_RESET_RAW = 85000


@dataclass
class SensorValue:
    value: Optional[float] = None
    updated_at: Optional[float] = None   # wall clock (time.time()) of the last good read
    error: Optional[str] = None


@dataclass
class Readings:
    """A snapshot of all sensors. ``seq`` increases with every completed read cycle."""
    seq: int = 0
    taken_at: float = 0.0
    values: Dict[str, SensorValue] = field(default_factory=dict)

    def get(self, role: str, now: float, stale_after: float) -> Optional[float]:
        sv = self.values.get(role)
        if sv is None or sv.value is None or sv.updated_at is None:
            return None
        if now - sv.updated_at > stale_after:
            return None
        return sv.value


class SensorError(Exception):
    pass


def parse_w1_slave(lines: List[str]) -> int:
    """Parse the w1_slave file of a DS18B20 and return milli-degrees Celsius."""
    if len(lines) < 2:
        raise SensorError("short read")
    if not lines[0].strip().endswith("YES"):
        raise SensorError("CRC check failed")
    pos = lines[1].find("t=")
    if pos == -1:
        raise SensorError("no temperature in output")
    try:
        return int(lines[1][pos + 2:].strip())
    except ValueError as e:
        raise SensorError(f"bad temperature value: {lines[1].strip()!r}") from e


class DS18B20Source:
    """Reads one sensor value from sysfs."""

    def __init__(self, cfg: SensorConfig):
        self.cfg = cfg

    def read(self, sensor_id: str) -> float:
        path = os.path.join(self.cfg.w1_dir, sensor_id, "w1_slave")
        last_error: Exception = SensorError("not read")
        for attempt in range(max(1, self.cfg.crc_retries)):
            try:
                with open(path, encoding="ascii", errors="replace") as f:
                    raw = parse_w1_slave(f.readlines())
            except FileNotFoundError:
                raise SensorError("sensor not found on 1-Wire bus")
            except (OSError, SensorError) as e:
                last_error = e
                time.sleep(0.2)
                continue
            if raw == _POWER_ON_RESET_RAW:
                last_error = SensorError("power-on reset value (85 °C)")
                time.sleep(0.2)
                continue
            value = raw / 1000.0
            if not self.cfg.min_valid <= value <= self.cfg.max_valid:
                raise SensorError(f"implausible value {value:.1f} °C")
            return value
        raise SensorError(str(last_error))


class SensorService:
    """Owns the read thread and the latest :class:`Readings` snapshot."""

    def __init__(self, cfg: SensorConfig, source, listeners: Optional[List[Callable[[Readings], None]]] = None):
        self.cfg = cfg
        self.source = source
        self.listeners = listeners or []
        self._lock = threading.Lock()
        self._readings = Readings(values={role: SensorValue() for role in SENSOR_ROLES})
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="sensors", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout)

    def latest(self) -> Readings:
        with self._lock:
            return self._readings

    def read_once(self) -> Readings:
        now = time.time()
        with self._lock:
            previous = self._readings
        values: Dict[str, SensorValue] = {}
        for role in SENSOR_ROLES:
            sensor_id = self.cfg.ids[role]
            old = previous.values.get(role, SensorValue())
            try:
                values[role] = SensorValue(self.source.read(sensor_id), now, None)
            except Exception as e:  # keep the last good value; it goes stale on its own
                if old.error != str(e):
                    log.warning("sensor %s (%s): %s", role, sensor_id, e)
                values[role] = SensorValue(old.value, old.updated_at, str(e))
        readings = Readings(previous.seq + 1, now, values)
        with self._lock:
            self._readings = readings
        for listener in self.listeners:
            try:
                listener(readings)
            except Exception:
                log.exception("sensor listener failed")
        return readings

    def _run(self) -> None:
        # read_once() is called synchronously at startup, so wait one interval first.
        started = time.monotonic()
        while not self._stop.wait(max(0.0, self.cfg.read_interval_seconds - (time.monotonic() - started))):
            started = time.monotonic()
            try:
                self.read_once()
            except Exception:
                log.exception("sensor read cycle failed")
