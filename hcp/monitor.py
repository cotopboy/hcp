"""Detection of special operating conditions.

Each condition is a latch with separate set / clear thresholds (hysteresis), so
it fires once on entry and once on exit instead of on every sample.  The monitor
is pure logic — it does not touch the valve — which keeps it unit-testable.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional

from .config import HEATING_INLET, MAIN_INLET, MAIN_RETURN, WATER_INLET, MonitorConfig

HEATING_GETTING_HOT = "heating_getting_hot"
OVERHEAT_START = "overheat_start"
OVERHEAT_END = "overheat_end"
NO_CONSUMPTION_START = "no_consumption_start"
NO_CONSUMPTION_END = "no_consumption_end"
WATER_TANK_START = "water_tank_start"
WATER_TANK_END = "water_tank_end"


@dataclass
class Event:
    name: str
    message: str


class Monitor:
    def __init__(self, cfg: MonitorConfig):
        self.cfg = cfg
        self.overheat = False
        self.no_consumption = False
        self.water_tank = False
        self.water_tank_since: Optional[float] = None
        self._trends: Dict[str, Deque[float]] = {
            HEATING_INLET: deque(maxlen=cfg.trend_samples),
            WATER_INLET: deque(maxlen=cfg.trend_samples),
        }

    def _push(self, role: str, value: Optional[float]) -> None:
        window = self._trends[role]
        if value is None:
            window.clear()  # a gap breaks the "continuously rising" chain
        else:
            window.append(value)

    def _rising(self, role: str) -> bool:
        w = list(self._trends[role])
        return len(w) == self.cfg.trend_samples and all(b > a for a, b in zip(w, w[1:]))

    def _end_water_tank(self, reason: str, events: List[Event]) -> None:
        if self.water_tank:
            self.water_tank = False
            self.water_tank_since = None
            events.append(Event(WATER_TANK_END, f"water tank heating ended ({reason})"))

    def update(self, t: Dict[str, Optional[float]], now: float) -> List[Event]:
        """Feed one new sample (role -> °C or None). ``now`` is a monotonic time in seconds."""
        c = self.cfg
        events: List[Event] = []
        mi, mr, hi, wi = t.get(MAIN_INLET), t.get(MAIN_RETURN), t.get(HEATING_INLET), t.get(WATER_INLET)
        self._push(HEATING_INLET, hi)
        self._push(WATER_INLET, wi)
        delta = mi - mr if mi is not None and mr is not None else None

        if delta is not None:
            if not self.no_consumption and mr > c.no_consumption_main_return_above \
                    and delta < c.no_consumption_delta_below:
                self.no_consumption = True
                events.append(Event(NO_CONSUMPTION_START,
                                    f"no heat consumption (main return {mr:.1f}, delta {delta:.1f})"))
                self._end_water_tank("no consumption", events)
            elif self.no_consumption and (mr < c.no_consumption_clear_main_return_below
                                          or delta > c.no_consumption_clear_delta_above):
                self.no_consumption = False
                events.append(Event(NO_CONSUMPTION_END,
                                    f"heat consumption resumed (main return {mr:.1f}, delta {delta:.1f})"))

        if hi is not None:
            if not self.overheat and hi > c.heating_too_hot_above and self._rising(HEATING_INLET):
                self.overheat = True
                events.append(Event(OVERHEAT_START, f"heating inlet too hot ({hi:.1f})"))
                self._end_water_tank("overheat", events)
            elif self.overheat and hi < c.heating_ok_below:
                self.overheat = False
                events.append(Event(OVERHEAT_END, f"heating inlet back to normal ({hi:.1f})"))
            elif not self.overheat and hi > c.heating_getting_hot_above and self._rising(HEATING_INLET):
                events.append(Event(HEATING_GETTING_HOT, f"heating inlet {hi:.1f} and rising"))

        if self.water_tank:
            if now - self.water_tank_since > c.water_tank_timeout_minutes * 60:
                self._end_water_tank("timeout", events)
        elif (delta is not None and wi is not None and not self.overheat and not self.no_consumption
              and delta > c.water_tank_delta_above and mi > c.water_tank_main_inlet_above
              and wi > c.water_tank_water_inlet_above and self._rising(WATER_INLET)):
            self.water_tank = True
            self.water_tank_since = now
            events.append(Event(WATER_TANK_START, f"water tank heating detected (water inlet {wi:.1f})"))

        return events
