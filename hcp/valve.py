"""Open-loop mixing valve.

The valve has no position feedback.  Its position is the number of relay pulses
driven in the open direction minus those in the close direction, clamped to
``[0, full_stroke_pulses]``.  :meth:`Valve.close_fully` drives past the end stop
and re-zeroes the counter, which removes any accumulated drift.

Every movement switches the relay off in a ``finally`` block, so an exception
or a shutdown request never leaves the motor energised.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from .config import ValveConfig
from .relay import DOWN, UP, RelayError

log = logging.getLogger(__name__)


class Valve:
    def __init__(self, relay, cfg: ValveConfig, position: int, calibrated: bool,
                 persist: Callable[[int, bool], None],
                 stop_event: Optional[threading.Event] = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.relay = relay
        self.cfg = cfg
        self.position = self._clamp(position)
        self.calibrated = calibrated
        self.moving: Optional[str] = None
        self._persist = persist
        self._stop = stop_event or threading.Event()
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last_direction: Optional[str] = None

    def _clamp(self, position: int) -> int:
        return max(0, min(self.cfg.full_stroke_pulses, int(position)))

    def _drive(self, direction: str, pulses: int) -> int:
        """Energise one relay for ``pulses`` pulse lengths. Returns the pulses completed."""
        if pulses <= 0:
            return 0
        done = 0
        with self._lock:
            if self._last_direction not in (None, direction):
                self._sleep(self.cfg.direction_change_pause_seconds)
            self._last_direction = direction
            if self._stop.is_set():
                return 0
            try:
                self.moving = direction
                self.relay.energize(direction)
                for _ in range(pulses):
                    if self._stop.is_set():
                        log.warning("valve movement aborted by shutdown")
                        break
                    self._sleep(self.cfg.pulse_seconds)
                    done += 1
                    step = 1 if direction == UP else -1
                    self.position = self._clamp(self.position + step)
            finally:
                self.moving = None
                try:
                    self.relay.all_off()
                except RelayError:
                    log.critical("could not switch the valve relays off!", exc_info=True)
                    raise
                finally:
                    self._save()
        if done:
            log.info("valve %s %d pulse(s) -> position %d", direction, done, self.position)
        return done

    def move_to(self, target: int) -> int:
        """Move to an absolute position within the stroke. Returns pulses driven."""
        target = self._clamp(target)
        delta = target - self.position
        if delta > 0:
            return self._drive(UP, delta)
        if delta < 0:
            return self._drive(DOWN, -delta)
        return 0

    def step(self, delta: int) -> int:
        return self.move_to(self.position + delta)

    def close_fully(self) -> None:
        """Close against the end stop and re-zero the counter (calibration)."""
        pulses = self.position + self.cfg.close_overtravel_pulses
        if not self.calibrated:
            pulses = self.cfg.full_stroke_pulses + self.cfg.close_overtravel_pulses
        log.info("closing valve fully (%d pulses) to calibrate", pulses)
        done = self._drive(DOWN, pulses)
        if done == pulses:
            self.position = 0
            self.calibrated = True
            self._save()
            log.info("valve calibrated: position 0")

    def _save(self) -> None:
        """Persist the position; a disk error must never interrupt valve handling."""
        try:
            self._persist(self.position, self.calibrated)
        except Exception:
            log.exception("could not save valve position")

    def mark_uncalibrated(self) -> None:
        self.calibrated = False
        self._save()

    def emergency_off(self) -> None:
        """Best effort: release both relays (used at shutdown)."""
        self._stop.set()
        try:
            self.relay.all_off()
        except Exception:
            log.critical("emergency relay off failed", exc_info=True)
