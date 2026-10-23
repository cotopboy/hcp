"""Open-loop mixing valve.

The valve has no position feedback.  It counts relay pulses in two ways:

* ``absolute``: pulses above the mechanical end stop, clamped to
  ``[0, full_stroke_pulses]``.  :meth:`Valve.close_fully` drives past the end
  stop and re-zeroes it, which removes accumulated drift.
* ``position``: ``absolute - zero_offset``.  The zero point is where water
  just starts to flow (set with the zero-point calibration), so position 0 is
  "barely open" and negative positions are closed without flow.  All
  positions in the config and the API use this scale.

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
    def __init__(self, relay, cfg: ValveConfig, absolute: int, calibrated: bool, zero_offset: int,
                 persist: Callable[[int, bool, int], None],
                 stop_event: Optional[threading.Event] = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.relay = relay
        self.cfg = cfg
        self.absolute = self._clamp(absolute)
        self.calibrated = calibrated
        self.zero_offset = self._clamp(zero_offset)
        self.moving: Optional[str] = None
        self._persist = persist
        self._stop = stop_event or threading.Event()
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last_direction: Optional[str] = None

    @property
    def position(self) -> int:
        """Pulses above the zero (flow start) point; negative when closed below it."""
        return self.absolute - self.zero_offset

    @property
    def min_position(self) -> int:
        return -self.zero_offset

    @property
    def max_position(self) -> int:
        return self.cfg.full_stroke_pulses - self.zero_offset

    def _clamp(self, absolute: int) -> int:
        return max(0, min(self.cfg.full_stroke_pulses, int(absolute)))

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
                    self.absolute = self._clamp(self.absolute + step)
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
            log.info("valve %s %d pulse(s) -> position %d (absolute %d)",
                     direction, done, self.position, self.absolute)
        return done

    def move_to_absolute(self, target: int) -> int:
        """Move to a position counted from the end stop. Returns pulses driven."""
        target = self._clamp(target)
        delta = target - self.absolute
        if delta > 0:
            return self._drive(UP, delta)
        if delta < 0:
            return self._drive(DOWN, -delta)
        return 0

    def move_to(self, position: int) -> int:
        """Move to a position relative to the zero point. Returns pulses driven."""
        return self.move_to_absolute(position + self.zero_offset)

    def step(self, delta: int) -> int:
        return self.move_to_absolute(self.absolute + delta)

    def close_fully(self) -> None:
        """Close against the end stop and re-zero the counter (calibration)."""
        pulses = self.absolute + self.cfg.close_overtravel_pulses
        if not self.calibrated:
            pulses = self.cfg.full_stroke_pulses + self.cfg.close_overtravel_pulses
        log.info("closing valve fully (%d pulses) to calibrate", pulses)
        done = self._drive(DOWN, pulses)
        if done == pulses:
            self.absolute = 0
            self.calibrated = True
            self._save()
            log.info("valve calibrated: at end stop, position %d", self.position)

    def set_zero_offset(self, offset: int) -> None:
        self.zero_offset = self._clamp(offset)
        self._save()
        log.info("valve zero point set %d pulses above the end stop", self.zero_offset)

    def _save(self) -> None:
        """Persist the position; a disk error must never interrupt valve handling."""
        try:
            self._persist(self.absolute, self.calibrated, self.zero_offset)
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
