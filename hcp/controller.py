"""The control loop.

One thread owns all valve movements and all decisions.  API requests only
change requested state under a lock (mode, target, manual target, calibration
request); the loop picks them up on its next tick.  This removes the races of
the old design, where event handlers moved the valve from a second thread.

Modes:
  off     valve closed fully, nothing else happens
  auto    the original step controller keeps the main return in [target, target + band]
  manual  the valve stays where the user puts it; overheat protection still applies
"""

from __future__ import annotations

import logging
import math
import threading
import time
from typing import Callable, Dict, Optional, Tuple

from . import monitor as mon
from .config import (HEATING_INLET, MAIN_INLET, MAIN_RETURN, SENSOR_ROLES, Config, ControlConfig)
from .history import EventLog
from .monitor import Monitor
from .relay import RelayError
from .state_store import MODE_AUTO, MODE_MANUAL, MODE_OFF, MODES, StateStore
from .valve import Valve

log = logging.getLogger(__name__)

PHASE_IDLE = "idle"                    # off mode
PHASE_MANUAL = "manual"
PHASE_NORMAL = "normal"                # auto, regulating
PHASE_WATER_TANK = "water_tank"        # auto, paused while the hot water tank heats
PHASE_NO_CONSUMPTION = "no_consumption"
PHASE_OVERHEAT = "overheat"
PHASE_SENSOR_FAULT = "sensor_fault"
PHASE_RELAY_FAULT = "relay_fault"

REQUIRED_FOR_AUTO = (MAIN_INLET, MAIN_RETURN, HEATING_INLET)
MANUAL_PULSES_PER_TICK = 4
RELAY_FAULT_RETRY_SECONDS = 60.0

UP, DOWN, HOLD = "up", "down", "hold"


class CommandError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def decide(temps: Dict[str, Optional[float]], target: int, c: ControlConfig) -> Tuple[str, str, str]:
    """The original rule table. Later rules override earlier ones, so closing wins over opening.

    Returns (op, rule, reason); ``rule`` is a stable code the app translates.
    """
    hi, mr = temps[HEATING_INLET], temps[MAIN_RETURN]
    result = (HOLD, "in_range", "within target range")
    if hi < c.heating_inlet_min:
        result = (UP, "heating_inlet_low", f"heating inlet below {c.heating_inlet_min:g}")
    if hi + mr < c.inlet_plus_return_low:
        result = (UP, "sum_low", f"heating inlet + main return below {c.inlet_plus_return_low:g}")
    if mr < target:
        result = (UP, "below_target", f"main return below target {target}")
    if hi + mr >= c.inlet_plus_return_high:
        result = (DOWN, "sum_high", f"heating inlet + main return at or above {c.inlet_plus_return_high:g}")
    if mr > target + c.upper_band:
        result = (DOWN, "above_target", f"main return above {target + c.upper_band}")
    return result


class Controller:
    def __init__(self, cfg: Config, sensors, valve: Valve, store: StateStore, events: EventLog,
                 clock: Callable[[], float] = time.monotonic):
        self.cfg = cfg
        self.sensors = sensors
        self.valve = valve
        self.store = store
        self.events = events
        self.monitor = Monitor(cfg.monitor)
        self._clock = clock
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="controller", daemon=True)
        self._started_at = time.time()

        state = store.snapshot()
        self._mode = state.mode
        self._target = self._clamp_target(state.target_temperature)
        self._manual_target: Optional[int] = None
        self._pending_mode_entry = True
        self._pending_calibration = cfg.valve.calibrate_on_startup or not valve.calibrated
        self._busy: Optional[str] = None
        self._last_seq = -1
        self._last_monitor_at = float("-inf")
        self._next_auto_at = float("-inf")
        self._last_decision: Optional[dict] = None
        self._missing_sensors: Tuple[str, ...] = ()
        self._relay_fault: Optional[str] = None
        self._relay_fault_at = 0.0
        self._temps: Dict[str, Optional[float]] = {r: None for r in SENSOR_ROLES}

    # ---------------------------------------------------------------- commands (any thread)

    def _clamp_target(self, value) -> int:
        c = self.cfg.control
        try:
            value = int(value)
        except (TypeError, ValueError):
            return c.default_target
        return max(c.target_min, min(c.target_max, value))

    def set_mode(self, mode: str) -> None:
        if mode not in MODES:
            raise CommandError(400, f"mode must be one of {', '.join(MODES)}")
        with self._lock:
            if mode == self._mode:
                return
            self.store.update(mode=mode)  # persist first: a failed write leaves the mode unchanged
            old, self._mode = self._mode, mode
            self._pending_mode_entry = True
            self._manual_target = None
        self.events.add("mode", f"mode changed: {old} -> {mode}")
        log.info("mode changed: %s -> %s", old, mode)

    def set_target(self, value) -> None:
        c = self.cfg.control
        if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 1000:
            raise CommandError(400, f"temperature must be between {c.target_min} and {c.target_max}")
        if isinstance(value, bool) or not isinstance(value, (int, float)) \
                or not math.isfinite(value) or value != int(value):
            raise CommandError(400, "temperature must be a whole number")
        value = int(value)
        if not c.target_min <= value <= c.target_max:
            raise CommandError(400, f"temperature must be between {c.target_min} and {c.target_max}")
        with self._lock:
            if value == self._target:
                return
            self.store.update(target_temperature=value)
            self._target = value
            self._next_auto_at = float("-inf")  # react right away
        self.events.add("target", f"target temperature set to {value} °C")
        log.info("target temperature set to %d", value)

    def manual_move(self, steps=None, position=None) -> None:
        if (steps is None) == (position is None):
            raise CommandError(400, "give exactly one of 'steps' or 'position'")
        for v in (steps, position):
            if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
                raise CommandError(400, "steps / position must be integers")
        with self._lock:
            if self._mode != MODE_MANUAL:
                raise CommandError(409, "switch to manual mode before moving the valve")
            base = self._manual_target if self._manual_target is not None else self.valve.position
            target = base + steps if steps is not None else position
            target = max(0, min(self.cfg.valve.full_stroke_pulses, target))
            if self.monitor.overheat and target > min(base, self.cfg.valve.reduced_position):
                raise CommandError(409, "overheat protection active: the valve cannot be opened")
            self._manual_target = target

    def request_calibration(self) -> None:
        with self._lock:
            self._pending_calibration = True
        self.events.add("calibration", "valve calibration requested")

    # ---------------------------------------------------------------- status (any thread)

    def phase(self) -> str:
        if self._relay_fault:
            return PHASE_RELAY_FAULT
        if self._mode == MODE_OFF:
            return PHASE_IDLE
        if self.monitor.overheat:
            return PHASE_OVERHEAT
        if self._mode == MODE_MANUAL:
            return PHASE_MANUAL
        if self._missing_sensors:
            return PHASE_SENSOR_FAULT
        if self.monitor.no_consumption:
            return PHASE_NO_CONSUMPTION
        if self.monitor.water_tank:
            return PHASE_WATER_TANK
        return PHASE_NORMAL

    @property
    def mode(self) -> str:
        return self._mode

    def status(self) -> dict:
        readings = self.sensors.latest()
        v, c = self.cfg.valve, self.cfg.control
        temps = {}
        for role in SENSOR_ROLES:
            sv = readings.values.get(role)
            value = readings.get(role, time.time(), self.cfg.sensors.stale_after_seconds)
            temps[role] = {
                "value": None if value is None else round(value, 2),
                "ok": value is not None and (sv is None or sv.error is None),
                "updated_at": sv.updated_at if sv else None,
                "error": sv.error if sv else None,
            }
        with self._lock:
            alarms = []
            if self._relay_fault:
                alarms.append({"code": "relay_fault", "level": "critical", "message": self._relay_fault})
            if self.monitor.overheat:
                alarms.append({"code": "overheat", "level": "critical",
                               "message": "heating inlet too hot, valve held at reduced position"})
            if self.monitor.no_consumption:
                alarms.append({"code": "no_consumption", "level": "warning",
                               "message": "no heat consumption on the main circuit"})
            if self.monitor.water_tank:
                alarms.append({"code": "water_tank", "level": "info",
                               "message": "hot water tank is heating, auto control paused"})
            for role in SENSOR_ROLES:
                if not temps[role]["ok"]:
                    alarms.append({"code": "sensor_fault", "level": "warning", "sensor": role,
                                   "message": f"{role}: {temps[role]['error'] or 'no reading'}"})
            if not self.valve.calibrated:
                alarms.append({"code": "uncalibrated", "level": "warning",
                               "message": "valve position unknown until the next calibration"})
            return {
                "time": time.time(),
                "uptime_seconds": round(time.time() - self._started_at),
                "mode": self._mode,
                "phase": self.phase(),
                "busy": self._busy,
                "target_temperature": self._target,
                "target_range": {"min": c.target_min, "max": c.target_max, "upper_band": c.upper_band},
                "temperatures": temps,
                "valve": {
                    "position": self.valve.position,
                    "max": v.full_stroke_pulses,
                    "percent": round(100 * self.valve.position / v.full_stroke_pulses),
                    "auto_min": v.auto_min,
                    "auto_max": v.auto_max,
                    "reduced": v.reduced_position,
                    "manual_target": self._manual_target,
                    "moving": self.valve.moving,
                    "calibrated": self.valve.calibrated,
                },
                "last_decision": self._last_decision,
                "alarms": alarms,
            }

    # ---------------------------------------------------------------- loop (controller thread)

    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self.valve.emergency_off()
        if self._thread.is_alive():
            self._thread.join(timeout)

    def _run(self) -> None:
        log.info("controller started in %s mode, target %d °C", self._mode, self._target)
        while not self._stop.is_set():
            try:
                self.step()
            except Exception:
                log.exception("controller tick failed")
                self._stop.wait(5)
            self._stop.wait(0.5)

    def step(self) -> None:
        """One tick; a relay failure becomes a reported fault instead of an exception."""
        try:
            self.tick()
        except RelayError as e:
            self._on_relay_fault(str(e))

    def _on_relay_fault(self, message: str) -> None:
        with self._lock:
            first = self._relay_fault is None
            self._relay_fault = message
            self._relay_fault_at = self._clock()
        if first:
            log.critical("relay fault: %s", message)
            self.events.add("relay_fault", f"relay fault: {message}", "critical")
        self.valve.mark_uncalibrated()

    def _set_busy(self, what: Optional[str]) -> None:
        with self._lock:
            self._busy = what

    def tick(self) -> None:
        now = self._clock()
        if self._relay_fault:
            if now - self._relay_fault_at < RELAY_FAULT_RETRY_SECONDS:
                try:  # keep trying to release the relays: one may still be energised
                    self.valve.relay.all_off()
                except RelayError:
                    pass
                return
            # Retry: a successful calibration clears the fault.
            with self._lock:
                self._pending_calibration = True

        self._process_sensors(now)

        with self._lock:
            mode = self._mode
            calibrate, self._pending_calibration = self._pending_calibration, False
            entry, self._pending_mode_entry = self._pending_mode_entry, False
            manual_target = self._manual_target

        if calibrate:
            self._calibrate()
            entry = True  # re-apply the mode, e.g. reopen to the ready position in auto
        if entry:
            self._enter_mode(mode, now)

        if mode == MODE_OFF:
            return
        if self.monitor.overheat:
            with self._lock:
                if self._manual_target is not None and self._manual_target > self.cfg.valve.reduced_position:
                    self._manual_target = self.cfg.valve.reduced_position
                manual_target = self._manual_target
        if self.monitor.overheat and self.valve.position > self.cfg.valve.reduced_position:
            self._set_busy("overheat protection")
            try:
                self.valve.move_to(self.cfg.valve.reduced_position)
            finally:
                self._set_busy(None)
        if mode == MODE_MANUAL:
            self._manual_tick(manual_target)
        else:
            self._auto_tick(now)

    def _calibrate(self) -> None:
        self._set_busy("calibrating")
        try:
            self.valve.close_fully()
        finally:
            self._set_busy(None)
        with self._lock:
            if self._relay_fault and self.valve.calibrated:
                self.events.add("relay_fault", "relay working again")
                self._relay_fault = None
        self.events.add("calibration", "valve closed fully and recalibrated")

    def _enter_mode(self, mode: str, now: float) -> None:
        if mode == MODE_OFF:
            if not (self.valve.calibrated and self.valve.position == 0):
                self._set_busy("closing")
                try:
                    self.valve.close_fully()
                finally:
                    self._set_busy(None)
        elif mode == MODE_AUTO:
            if self.phase() == PHASE_NORMAL and self.valve.position < self.cfg.valve.ready_position:
                self._set_busy("opening to ready position")
                try:
                    self.valve.move_to(self.cfg.valve.ready_position)
                finally:
                    self._set_busy(None)
            self._next_auto_at = now

    def _process_sensors(self, now: float) -> None:
        readings = self.sensors.latest()
        temps = {r: readings.get(r, time.time(), self.cfg.sensors.stale_after_seconds) for r in SENSOR_ROLES}
        missing = tuple(r for r in REQUIRED_FOR_AUTO if temps[r] is None)
        with self._lock:
            self._temps = temps
            if missing != self._missing_sensors and readings.seq > 0:
                if missing:
                    log.error("sensor(s) missing: %s — auto control holds the valve", ", ".join(missing))
                    self.events.add("sensor_fault", f"sensor(s) missing: {', '.join(missing)}", "warning")
                else:
                    self.events.add("sensor_fault", "all required sensors are reporting again")
                self._missing_sensors = missing
        if readings.seq == self._last_seq or now - self._last_monitor_at < self.cfg.monitor.interval_seconds:
            return
        self._last_seq = readings.seq
        self._last_monitor_at = now
        with self._lock:
            events = self.monitor.update(temps, now)
        for ev in events:
            self._handle_event(ev, now)

    def _handle_event(self, ev: mon.Event, now: float) -> None:
        critical = ev.name in (mon.OVERHEAT_START, mon.NO_CONSUMPTION_START)
        (log.critical if critical else log.info)(ev.message)
        if ev.name != mon.HEATING_GETTING_HOT:
            self.events.add(ev.name, ev.message, "critical" if critical else "info")
        if self._mode != MODE_AUTO:
            return  # overheat protection for manual mode is handled in tick()
        v = self.cfg.valve
        if ev.name == mon.NO_CONSUMPTION_START and self.valve.position > v.reduced_position:
            self.valve.move_to(v.reduced_position)
        elif ev.name == mon.HEATING_GETTING_HOT and self.phase() == PHASE_NORMAL \
                and self.valve.position > v.auto_min:
            self.valve.step(-1)
        elif ev.name in (mon.OVERHEAT_END, mon.NO_CONSUMPTION_END, mon.WATER_TANK_END):
            self._next_auto_at = now

    def _manual_tick(self, manual_target: Optional[int]) -> None:
        if manual_target is None or manual_target == self.valve.position:
            return
        delta = manual_target - self.valve.position
        chunk = max(-MANUAL_PULSES_PER_TICK, min(MANUAL_PULSES_PER_TICK, delta))
        self.valve.step(chunk)  # in small chunks so a new command takes effect quickly

    def _auto_tick(self, now: float) -> None:
        c, v = self.cfg.control, self.cfg.valve
        if now < self._next_auto_at:
            return
        self._next_auto_at = now + c.interval_seconds
        if self.phase() != PHASE_NORMAL:
            return
        with self._lock:
            temps, target = dict(self._temps), self._target
        op, rule, reason = decide(temps, target, c)
        moved = False
        if op == UP:
            if self.valve.position < v.ready_position:
                self._set_busy("opening to ready position")
                try:
                    self.valve.move_to(v.ready_position)
                finally:
                    self._set_busy(None)
            if self.valve.position < v.auto_max:
                moved = self.valve.step(1) > 0
            if moved:
                self._next_auto_at += c.wait_after_up_seconds
        elif op == DOWN and self.valve.position > v.auto_min:
            moved = self.valve.step(-1) > 0
            if moved:
                self._next_auto_at += c.wait_after_down_seconds
        at_limit = op != HOLD and not moved
        if at_limit:
            reason += " (valve at its auto limit)"
        if op != HOLD:
            log.info("auto: %s — %s", op, reason)
        with self._lock:
            self._last_decision = {"op": op, "rule": rule, "reason": reason, "moved": moved,
                                   "at_limit": at_limit, "at": time.time()}
