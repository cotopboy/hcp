"""The control loop.

One thread owns all valve movements and all decisions.  API requests only
change requested state under a lock (mode, target, manual target, calibration
request); the loop picks them up on its next tick.  This removes the races of
the old design, where event handlers moved the valve from a second thread.

Modes:
  off     valve closed to the zero point (flow start), nothing else happens
  auto    the original step controller keeps the main return in [target, target + band]
  manual  the valve stays where the user puts it; overheat protection still applies

While the hot water tank heats, another controller drives the same valve fully
open.  We never touch the relays then, mark the position as unknown, and close
fully to recalibrate once heating ends before resuming the current mode.

Night saver: when enabled, auto and manual behave like off inside the configured
night window (local time) without changing the stored mode; the mode resumes
when the window ends (a manual position is restored).
"""

from __future__ import annotations

import logging
import math
import threading
import time
from datetime import datetime
from typing import Callable, Dict, Optional, Tuple

from . import monitor as mon
from .config import (HEATING_INLET, MAIN_INLET, MAIN_RETURN, SENSOR_ROLES, Config, ControlConfig,
                     parse_hhmm)
from .history import EventLog
from .monitor import Monitor
from .relay import RelayError
from .state_store import MODE_AUTO, MODE_MANUAL, MODE_OFF, MODES, StateStore
from .valve import Valve

log = logging.getLogger(__name__)

PHASE_IDLE = "idle"                    # off mode
PHASE_MANUAL = "manual"
PHASE_NORMAL = "normal"                # auto, regulating
PHASE_WATER_TANK = "water_tank"        # the hot water controller owns the valve; we pause
PHASE_NO_CONSUMPTION = "no_consumption"
PHASE_OVERHEAT = "overheat"
PHASE_SENSOR_FAULT = "sensor_fault"
PHASE_RELAY_FAULT = "relay_fault"
PHASE_ZERO_CALIBRATION = "zero_calibration"  # user is setting the flow-start point; control paused
PHASE_NIGHT_SAVER = "night_saver"      # inside the night window: heating off until it ends

REQUIRED_FOR_AUTO = (MAIN_INLET, MAIN_RETURN, HEATING_INLET)
MANUAL_PULSES_PER_TICK = 4
MAX_JOG_PULSES = 20
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
                 clock: Callable[[], float] = time.monotonic, wall_clock: Callable[[], datetime] = datetime.now):
        self.cfg = cfg
        self.sensors = sensors
        self.valve = valve
        self.store = store
        self.events = events
        self.monitor = Monitor(cfg.monitor)
        self._clock = clock
        self._wall_clock = wall_clock
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
        # Zero-point calibration: {"stage": "closing"|"ready", "started_at", "jog", "finish"}
        self._zero_cal: Optional[dict] = None
        # Manual position to restore after the hot water controller gives the valve back.
        self._water_tank_manual: Optional[int] = None
        self._night_saver = state.night_saver
        self._night_active = False
        self._night_start = parse_hhmm(cfg.night_saver.start)
        self._night_end = parse_hhmm(cfg.night_saver.end)
        # Manual position to restore when the night window ends.
        self._night_manual: Optional[int] = None

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
            self._night_manual = None
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

    def set_night_saver(self, enabled) -> None:
        if not isinstance(enabled, bool):
            raise CommandError(400, "enabled must be true or false")
        with self._lock:
            if enabled == self._night_saver:
                return
            self.store.update(night_saver=enabled)
            self._night_saver = enabled
        n = self.cfg.night_saver
        self.events.add("night_saver", f"night saver {'enabled' if enabled else 'disabled'} "
                                       f"({n.start}–{n.end})")
        log.info("night saver %s", "enabled" if enabled else "disabled")

    def _in_night_window(self) -> bool:
        now = self._wall_clock()
        t = now.hour * 60 + now.minute
        if self._night_start < self._night_end:
            return self._night_start <= t < self._night_end
        return t >= self._night_start or t < self._night_end  # crosses midnight

    def _effective_mode(self) -> str:
        return MODE_OFF if self._night_active else self._mode

    def manual_move(self, steps=None, position=None) -> None:
        if (steps is None) == (position is None):
            raise CommandError(400, "give exactly one of 'steps' or 'position'")
        for v in (steps, position):
            if v is not None and (isinstance(v, bool) or not isinstance(v, int)):
                raise CommandError(400, "steps / position must be integers")
        with self._lock:
            if self._zero_cal is not None:
                raise CommandError(409, "zero-point calibration in progress")
            if self._mode != MODE_MANUAL:
                raise CommandError(409, "switch to manual mode before moving the valve")
            if self._night_active:
                raise CommandError(409, "night saver active: heating is off until the night window ends")
            self._check_not_water_tank()
            base = self._manual_target if self._manual_target is not None else self.valve.position
            target = base + steps if steps is not None else position
            target = max(self.valve.min_position, min(self.valve.max_position, target))
            if self.monitor.overheat and target > min(base, self.cfg.valve.reduced_position):
                raise CommandError(409, "overheat protection active: the valve cannot be opened")
            self._manual_target = target

    def _check_not_water_tank(self) -> None:
        if self.monitor.water_tank:
            raise CommandError(409, "the hot water controller is using the valve")

    def request_calibration(self) -> None:
        with self._lock:
            if self._zero_cal is not None:
                raise CommandError(409, "zero-point calibration in progress")
            self._check_not_water_tank()
            self._pending_calibration = True
        self.events.add("calibration", "valve calibration requested")

    # Zero-point calibration: close to the end stop, the user opens step by step until water
    # starts to flow, and that absolute position becomes the new zero point.

    def start_zero_calibration(self) -> None:
        with self._lock:
            if self._relay_fault:
                raise CommandError(409, "relay fault: fix the relay board first")
            if self._zero_cal is not None:
                return
            self._check_not_water_tank()
            self._zero_cal = {"stage": "closing", "started_at": self._clock(), "jog": 0, "finish": None}
        self.events.add("zero_calibration", "zero-point calibration started")
        log.info("zero-point calibration started")

    def _ready_zero_cal(self) -> dict:
        if self._zero_cal is None:
            raise CommandError(409, "no zero-point calibration in progress")
        if self._zero_cal["stage"] != "ready" or self._zero_cal["finish"]:
            raise CommandError(409, "the valve is still closing to the end stop")
        return self._zero_cal

    def zero_jog(self, steps) -> None:
        if isinstance(steps, bool) or not isinstance(steps, int) or not 0 < abs(steps) <= MAX_JOG_PULSES:
            raise CommandError(400, f"steps must be a non-zero integer between -{MAX_JOG_PULSES} "
                                    f"and {MAX_JOG_PULSES}")
        with self._lock:
            self._ready_zero_cal()["jog"] += steps

    def finish_zero_calibration(self) -> None:
        with self._lock:
            self._ready_zero_cal()["finish"] = "set"

    def cancel_zero_calibration(self) -> None:
        with self._lock:
            if self._zero_cal is not None:
                self._zero_cal["finish"] = "cancel"

    @property
    def max_zero_offset(self) -> int:
        """The auto range must still fit inside the stroke above the zero point."""
        return self.cfg.valve.full_stroke_pulses - self.cfg.valve.auto_max

    # ---------------------------------------------------------------- status (any thread)

    def phase(self) -> str:
        if self._relay_fault:
            return PHASE_RELAY_FAULT
        if self._zero_cal is not None:
            return PHASE_ZERO_CALIBRATION
        if self.monitor.water_tank:
            return PHASE_WATER_TANK
        if self._mode == MODE_OFF:
            return PHASE_IDLE
        if self._night_active:
            return PHASE_NIGHT_SAVER
        if self.monitor.overheat:
            return PHASE_OVERHEAT
        if self._mode == MODE_MANUAL:
            return PHASE_MANUAL
        if self._missing_sensors:
            return PHASE_SENSOR_FAULT
        if self.monitor.no_consumption:
            return PHASE_NO_CONSUMPTION
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
                               "message": "hot water tank is heating: the hot water controller has opened "
                                          "the valve, control paused"})
            for role in SENSOR_ROLES:
                if not temps[role]["ok"]:
                    alarms.append({"code": "sensor_fault", "level": "warning", "sensor": role,
                                   "message": f"{role}: {temps[role]['error'] or 'no reading'}"})
            if not self.valve.calibrated and not self.monitor.water_tank:
                alarms.append({"code": "uncalibrated", "level": "warning",
                               "message": "valve position unknown until the next calibration"})
            zero_cal = None
            if self._zero_cal is not None:
                target = max(0, min(self.max_zero_offset, self.valve.absolute + self._zero_cal["jog"]))
                zero_cal = {"stage": self._zero_cal["stage"], "absolute": self.valve.absolute,
                            "target": target, "max_offset": self.max_zero_offset, "max_jog": MAX_JOG_PULSES}
            water_tank = None
            if self.monitor.water_tank:
                m = self.cfg.monitor
                water_tank = {"started_at": time.time() - (self._clock() - self.monitor.water_tank_since),
                              "min_minutes": m.water_tank_min_minutes,
                              "timeout_minutes": m.water_tank_timeout_minutes}
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
                    "min": self.valve.min_position,
                    "max": self.valve.max_position,
                    "percent": round(100 * max(0, self.valve.position) / self.valve.max_position),
                    "absolute": self.valve.absolute,
                    "zero_offset": self.valve.zero_offset,
                    "full_stroke": v.full_stroke_pulses,
                    "auto_min": v.auto_min,
                    "auto_max": v.auto_max,
                    "reduced": v.reduced_position,
                    "manual_target": self._manual_target,
                    "moving": self.valve.moving,
                    "calibrated": self.valve.calibrated,
                },
                "last_decision": self._last_decision,
                "zero_calibration": zero_cal,
                "water_tank": water_tank,
                "night_saver": {"enabled": self._night_saver, "active": self._night_active,
                                "start": self.cfg.night_saver.start, "end": self.cfg.night_saver.end},
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
            if self._zero_cal is not None:
                self._zero_cal = None
                self._pending_mode_entry = True
                self.events.add("zero_calibration", "zero-point calibration cancelled: relay fault", "warning")
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
        if self.monitor.water_tank:
            return  # hands off: the hot water controller is driving the valve

        with self._lock:
            zero_cal = self._zero_cal
        if zero_cal is not None:
            self._zero_tick(zero_cal, now)  # all other control waits until the user finishes
            return

        self._update_night()
        with self._lock:
            mode = self._effective_mode()
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

    def _update_night(self) -> None:
        """Enter or leave the night window; the mode is re-entered on the change."""
        with self._lock:
            active = self._night_saver and self._in_night_window()
            if active == self._night_active:
                return
            self._night_active = active
            self._pending_mode_entry = True
            if self._mode == MODE_MANUAL:
                if active:
                    self._night_manual = self._manual_target if self._manual_target is not None \
                        else self.valve.position
                    self._manual_target = None
                else:
                    self._manual_target = self._night_manual
            if not active:
                self._night_manual = None
            self._next_auto_at = float("-inf")
        if self._mode == MODE_OFF:
            return  # nothing changes for the valve
        message = "night saver: heating off until " + self.cfg.night_saver.end if active \
            else f"night saver: night over, resuming {self._mode} mode"
        log.info(message)
        self.events.add("night_saver", message)

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

    def _zero_tick(self, zc: dict, now: float) -> None:
        timeout = self.cfg.valve.zero_calibration_timeout_minutes * 60
        with self._lock:
            if zc["finish"] is None and now - zc["started_at"] > timeout:
                zc["finish"] = "timeout"
            closing = zc["stage"] == "closing" and zc["finish"] is None
        if closing:
            self._set_busy("closing to end stop")
            try:
                self.valve.close_fully()
            finally:
                self._set_busy(None)
            with self._lock:
                if self.valve.calibrated and self.valve.absolute == 0:
                    zc["stage"] = "ready"
            return
        with self._lock:
            jog, zc["jog"] = zc["jog"], 0
            finish = zc["finish"]
        if jog:
            target = max(0, min(self.max_zero_offset, self.valve.absolute + jog))
            self.valve.move_to_absolute(target)
        if finish is None:
            return
        if finish == "set":
            old = self.valve.zero_offset
            self.valve.set_zero_offset(self.valve.absolute)
            message = f"zero point set: water starts to flow {self.valve.zero_offset} pulses above " \
                      f"the end stop (was {old})"
        elif finish == "timeout":
            message = "zero-point calibration cancelled after timeout, zero point unchanged"
        else:
            message = "zero-point calibration cancelled, zero point unchanged"
        log.info(message)
        self.events.add("zero_calibration", message, "warning" if finish == "timeout" else "info")
        with self._lock:
            self._zero_cal = None
            self._pending_mode_entry = True  # e.g. back to the zero point (off) or ready position (auto)

    def _enter_mode(self, mode: str, now: float) -> None:
        if mode == MODE_OFF:
            self._set_busy("closing")
            try:
                if not self.valve.calibrated:
                    self.valve.close_fully()
                self.valve.move_to(0)  # the zero point: closed just to where flow starts
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
        if ev.name == mon.WATER_TANK_START:
            self._water_tank_started()
        elif ev.name == mon.WATER_TANK_END:
            self._water_tank_ended()
        if self._effective_mode() != MODE_AUTO:
            return  # overheat protection for manual mode is handled in tick()
        v = self.cfg.valve
        if ev.name == mon.NO_CONSUMPTION_START and self.valve.calibrated \
                and self.valve.position > v.reduced_position:
            self.valve.move_to(v.reduced_position)
        elif ev.name == mon.HEATING_GETTING_HOT and self.phase() == PHASE_NORMAL \
                and self.valve.position > v.auto_min:
            self.valve.step(-1)
        elif ev.name in (mon.OVERHEAT_END, mon.NO_CONSUMPTION_END, mon.WATER_TANK_END):
            self._next_auto_at = now

    def _water_tank_started(self) -> None:
        """The other controller opens the valve fully: our pulse count no longer means anything."""
        with self._lock:
            self._water_tank_manual = self._manual_target if self._manual_target is not None \
                else self.valve.position
            if self._zero_cal is not None:
                self._zero_cal = None
                self.events.add("zero_calibration",
                                "zero-point calibration cancelled: hot water tank heating", "warning")
        self.valve.mark_uncalibrated()
        log.info("hot water controller took over the valve, position unknown")

    def _water_tank_ended(self) -> None:
        """Close fully to find the end stop again, then re-enter the current mode."""
        with self._lock:
            self._pending_calibration = True
            self._pending_mode_entry = True
            if self._mode == MODE_MANUAL:
                self._manual_target = self._water_tank_manual
            self._water_tank_manual = None
        self.events.add("calibration", "recalibrating the valve after hot water tank heating")

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
